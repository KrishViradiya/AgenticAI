"""A small coding agent that builds the team website and follows the style guide.

The loop (no frameworks, no native function calling):
    1. send the conversation to the model
    2. the model answers with ONE JSON object: {"thought": ..., "action": ..., "args": {...}}
       (for write_site the HTML follows the JSON in a ```html code block)
    3. our code validates the answer, runs the action and appends the result ("observation")
    4. repeat until an accepted `finish` or the step limit
    5. human in the loop: after finish, the user can type feedback and the loop continues

Run from the repository root:
    uv run python task2_own_agent/agent.py --content task1_opencode/content --out task2_own_agent/site/index.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.embed_images import embed_images  # noqa: E402
from common.llm_client import LLMClient, count_tokens  # noqa: E402
from common.site_checker import check_site, member_names_from_content  # noqa: E402
from rag import StyleGuideIndex  # noqa: E402

LOG_DIR = Path(__file__).resolve().parent / "logs"

# ---------------------------------------------------------------------------- prompts
# Neither prompt contains style guide text (lab rule). The model has to search for every rule.

SYSTEM_PROMPT = """You are a coding agent that builds a single-file team website.

You work in steps. In every step you answer with exactly ONE JSON object and nothing else:
{"thought": "<one short sentence>", "action": "<action name>", "args": {...}}

Actions:
- search_style_guide  args: {"query": "<question>"}
  Searches the team's web style guide. Returns the most relevant excerpts with their document ids.
- read_profiles       args: {}
  Returns the profiles of all team members, the team text and the available image file names.
- write_site          args: {}
  Put the COMPLETE HTML page in a ```html code block directly after the JSON object.
  The page is saved and checked; you get the checker report back.
- finish              args: {"summary": "<what you built>"}
  Only accepted when the last checker report passed all checks.

Rules:
- The page must follow the style guide. You do not know it: search it before you write, one specific
  question per search, for every aspect of the page (structure, metadata, colors, theming, components,
  typography, responsive layout, motion, footer, ...).
- Style guide documents have a status. Only ACTIVE rules count; a DEPRECATED document has been replaced.
  MUST rules are mandatory.
- Never write image data or base64. Use <img src="{{image:<file name>}}" alt="..."> with the exact
  file names from read_profiles. Our code inserts the images.
- write_site always replaces the whole page, so always send the complete page.
- If a check fails, search the style guide for that topic before you fix it.
"""

TASK_PROMPT = """Build our team website as one standalone HTML file:
- HTML + CSS + JavaScript only, everything inline, nothing loaded from the internet
- introduces the team and every member (name, picture, study background, interests, fun fact,
  views on AI today and in 5-10 years, hot take)
- responsive (phone and desktop) with a day/night mode toggle
- a section with the team's shared view on AI and the future of software engineering
- funny and creative, but it must follow the style guide

Start by reading the profiles and searching the style guide. You have at most {max_steps} steps."""


# ---------------------------------------------------------------------------- protocol

# Expected arguments per action: name -> type. write_site may carry the HTML in args (optional).
ACTIONS: dict[str, dict[str, type]] = {
    "search_style_guide": {"query": str},
    "read_profiles": {},
    "write_site": {},
    "finish": {"summary": str},
}
OPTIONAL_ARGS = {"write_site": {"html": str}}


class ProtocolError(Exception):
    """The model's answer does not follow the protocol. The message is sent back to the model."""


@dataclass
class Action:
    name: str
    args: dict
    thought: str = ""
    html: str | None = None


HTML_BLOCK_RE = re.compile(r"```html[^\n]*\n(.*?)```", re.S | re.I)


def parse_response(text: str) -> Action:
    """Parse one model answer into an Action, or raise ProtocolError with a helpful message."""
    text = (text or "").strip()
    if not text:
        raise ProtocolError("Your answer was empty. Answer with one JSON object.")

    # Find the first JSON object. Tolerate a ```json fence or a sentence before it.
    start = text.find("{")
    if start == -1:
        raise ProtocolError("No JSON object found. Answer with exactly one JSON object.")
    try:
        obj, end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"Invalid JSON ({exc.msg} at position {exc.pos}). Answer with exactly one valid JSON object.")

    name = obj.get("action")
    if name not in ACTIONS:
        raise ProtocolError(f"Unknown action {name!r}. Valid actions: {', '.join(ACTIONS)}.")
    args = obj.get("args", {})
    if not isinstance(args, dict):
        raise ProtocolError('"args" must be a JSON object, e.g. {}.')

    expected, optional = ACTIONS[name], OPTIONAL_ARGS.get(name, {})
    for key, typ in expected.items():
        if not isinstance(args.get(key), typ) or (typ is str and not args[key].strip()):
            raise ProtocolError(f'{name} needs the argument "{key}" (a non-empty {typ.__name__}).')
    unknown = set(args) - set(expected) - set(optional)
    if unknown:
        raise ProtocolError(f"{name} does not take the argument(s) {sorted(unknown)}. Expected: {list(expected) or '{}'}.")

    html = None
    if name == "write_site":
        rest = text[start + end:]
        match = HTML_BLOCK_RE.search(rest)
        if match:
            html = match.group(1)
        elif isinstance(args.get("html"), str):
            html = args["html"]
        elif "```html" in rest:
            raise ProtocolError("The ```html code block was not closed. Your answer was probably cut off. "
                                "Send the complete page again, a bit shorter if needed.")
        else:
            raise ProtocolError("write_site needs the complete page in a ```html code block directly after the JSON.")
        if not html.strip():
            raise ProtocolError("The ```html code block is empty.")
    return Action(name, args, str(obj.get("thought", "")), html)


# ---------------------------------------------------------------------------- agent

@dataclass
class Agent:
    llm: LLMClient
    index: StyleGuideIndex
    content_dir: Path
    out_path: Path
    max_steps: int = 25
    k: int = 4
    max_tokens: int | None = None
    input_fn: Callable[[str], str] = input
    print_fn: Callable[..., None] = print

    messages: list[dict] = field(default_factory=list)
    step: int = 0                      # steps in the current round (reset after human feedback)
    total_steps: int = 0
    last_report_passed: bool = False
    last_failures: str = "No site has been written yet."
    previous_calls: dict = field(default_factory=dict)  # (action, args) -> step, to detect repetition

    # ----------------------------------------------------------------- main loop

    def run(self) -> bool:
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": TASK_PROMPT.format(max_steps=self.max_steps)},
        ]
        self.llm.log_event({"event": "run_start", "max_steps": self.max_steps, "k": self.k,
                            "content": str(self.content_dir), "out": str(self.out_path)})
        while True:
            finished = self._run_round()
            if not finished:
                self.print_fn(f"\nStopped: step limit of {self.max_steps} reached without an accepted finish.")
                self.llm.log_event({"event": "step_limit_reached", "total_steps": self.total_steps})
                return False
            try:
                feedback = self.input_fn("\nFeedback for the agent (empty = done): ").strip()
            except EOFError:
                feedback = ""
            self.llm.log_event({"event": "human_feedback", "feedback": feedback})
            if not feedback:
                return True
            self.messages.append({"role": "user", "content": f"Feedback from the user: {feedback}\n"
                                  f"Change the page accordingly, check it, then finish again. "
                                  f"You have {self.max_steps} more steps."})
            self.step = 0
            self.last_report_passed = False
            self.last_failures = "You have not written the site again since the feedback."

    def _run_round(self) -> bool:
        while self.step < self.max_steps:
            self.step += 1
            self.total_steps += 1
            reply = self.llm.chat(self.messages, max_tokens=self.max_tokens)
            self.messages.append({"role": "assistant", "content": reply})

            try:
                action = parse_response(reply)
                observation, finished = self._execute(action)
                status = "ok"
            except ProtocolError as exc:
                action, observation, finished, status = None, f"ERROR: {exc}", False, "protocol_error"

            name = action.name if action else "invalid"
            self.print_fn(f"[step {self.step:>2}/{self.max_steps}] {name:<19} {_first_line(observation)}")
            self.llm.log_event({
                "event": "step", "step": self.step, "total_step": self.total_steps, "status": status,
                "thought": action.thought if action else None, "action": name,
                "args": action.args if action else None, "observation": observation,
            })
            if finished:
                return True

            left = self.max_steps - self.step
            note = f"\n\n(Step {self.step}/{self.max_steps} used, {left} left.)"
            if 0 < left <= 3:
                note += " You are running out of steps: fix the remaining failures and finish."
            self.messages.append({"role": "user", "content": f"Observation:\n{observation}{note}"})
            if action and action.name == "write_site":
                self._compact_old_pages()
        return False

    # ----------------------------------------------------------------- actions

    def _execute(self, action: Action) -> tuple[str, bool]:
        key = (action.name, json.dumps(action.args, sort_keys=True))
        if action.name != "write_site" and key in self.previous_calls:
            # Repetition: answer anyway, but tell the model so it can move on.
            prefix = f"(You already did exactly this in step {self.previous_calls[key]}. The result is the same.)\n"
        else:
            prefix = ""
        self.previous_calls[key] = self.step

        if action.name == "search_style_guide":
            return prefix + self._search(action.args["query"]), False
        if action.name == "read_profiles":
            return prefix + self._read_profiles(), False
        if action.name == "write_site":
            return self._write_site(action.html), False
        return self._finish(action.args["summary"])

    def _search(self, query: str) -> str:
        chunks = self.index.search(query, self.k)
        return self.index.format_results(chunks)   # ≤ 1,000 tokens of style guide text

    def _read_profiles(self) -> str:
        parts = []
        for path in sorted(self.content_dir.glob("*.md")):
            if path.name == "_template.md":
                continue
            parts.append(f"=== {path.name} ===\n{_strip_comments(path.read_text(encoding='utf-8')).strip()}")
        images_dir = self.content_dir / "images"
        images = sorted(p.name for p in images_dir.iterdir()) if images_dir.is_dir() else []
        parts.append("=== available image files ===\n" + ("\n".join(images) or "(none)"))
        return "\n\n".join(parts)

    def _write_site(self, html: str) -> str:
        if re.search(r"data:image/[^;]+;base64,", html):
            self.last_report_passed = False
            return "ERROR: the page contains base64 image data. Never write image data; use {{image:<file name>}} placeholders."
        try:
            final = embed_images(html, self.content_dir / "images")
        except (FileNotFoundError, ValueError) as exc:
            self.last_report_passed = False
            return f"ERROR while inserting images: {exc}"

        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.out_path.write_text(final, encoding="utf-8")
        report = check_site(final, mode="full", member_names=member_names_from_content(self.content_dir),
                            file_size=self.out_path.stat().st_size)
        self.last_report_passed = report.passed
        self.last_failures = report.summary(only_failures=True)
        n_pass = sum(r.passed for r in report.results)
        self.llm.log_event({"event": "checker", "step": self.step, "passed": report.passed,
                            "n_passed": n_pass, "n_checks": len(report.results), "report": report.to_dict()})
        head = f"Saved {self.out_path.name} ({self.out_path.stat().st_size // 1024} KB). Checker report:\n"
        return head + report.summary(only_failures=True)

    def _finish(self, summary: str) -> tuple[str, bool]:
        if not self.last_report_passed:
            return ("finish REJECTED: the last checker report did not pass.\n" + self.last_failures), False
        self.print_fn(f"\nAgent finished: {summary}")
        return f"finish accepted: {summary}", True

    # ----------------------------------------------------------------- context management

    def _compact_old_pages(self) -> None:
        """Keep only the newest page in the context. Older pages are replaced by a short note.

        Every step re-sends the whole conversation; without this, each write_site would add
        several thousand tokens to every later request. The full pages stay in the log.
        """
        page_messages = [m for m in self.messages if m["role"] == "assistant" and HTML_BLOCK_RE.search(m["content"] or "")]
        for m in page_messages[:-1]:
            m["content"] = HTML_BLOCK_RE.sub(
                lambda match: f"```html\n[older version omitted, {count_tokens(match.group(1))} tokens]\n```", m["content"])


def _first_line(text: str, width: int = 90) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= width else line[: width - 3] + "..."


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def next_log_path() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    n = 1
    while (LOG_DIR / f"run_{n:02d}.jsonl").exists():
        n += 1
    return LOG_DIR / f"run_{n:02d}.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the team website with our own agent.")
    parser.add_argument("--content", type=Path, default=REPO_ROOT / "task1_opencode" / "content")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "site" / "index.html")
    parser.add_argument("--model", help="chat model (default: $LAB_CHAT_MODEL)")
    parser.add_argument("--max-steps", type=int, default=25, help="step limit per round (default 25)")
    parser.add_argument("-k", type=int, default=4, help="chunks per style guide search (default 4)")
    parser.add_argument("--max-tokens", type=int, default=None, help="max output tokens per answer (default: no limit)")
    parser.add_argument("--log", type=Path, help="log file (default: logs/run_XX.jsonl)")
    args = parser.parse_args()

    log_path = args.log or next_log_path()
    llm = LLMClient(model=args.model, log_path=log_path)
    index = StyleGuideIndex.build(llm)
    agent = Agent(llm, index, args.content, args.out, args.max_steps, args.k, args.max_tokens)
    print(f"Model {llm.model} · {len(index.chunks)} style guide chunks · log {log_path}")
    ok = agent.run()
    print(f"\n{'Done' if ok else 'Not finished'} after {agent.total_steps} steps. Usage: {llm.usage_summary()}")
    llm.log_event({"event": "run_end", "finished": ok, "total_steps": agent.total_steps, "usage": llm.usage_summary()})
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
