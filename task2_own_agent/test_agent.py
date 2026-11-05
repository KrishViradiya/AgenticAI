"""Offline tests for the agent loop: a fake model replays scripted answers (no gateway needed).

    uv run pytest task2_own_agent/test_agent.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

import agent as agent_module
from agent import Agent, ProtocolError, parse_response
from common.site_checker import CheckReport, CheckResult

CONTENT = Path(__file__).resolve().parent.parent / "task1_opencode" / "content"


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.events = []
        self.requests = []

    def chat(self, messages, max_tokens=None):
        self.requests.append([dict(m) for m in messages])
        return self.replies.pop(0)

    def log_event(self, event):
        self.events.append(event)


class FakeIndex:
    def search(self, query, k):
        return [query]

    def format_results(self, chunks):
        return f"[SG-99] Fake rule for: {chunks[0]}"


def make_agent(replies, tmp_path, feedback=("",), max_steps=25):
    answers = iter(feedback)
    llm = FakeLLM(replies)
    a = Agent(llm, FakeIndex(), CONTENT, tmp_path / "index.html", max_steps=max_steps,
              input_fn=lambda prompt: next(answers), print_fn=lambda *a, **k: None)
    return a, llm


def steps(llm):
    return [e for e in llm.events if e.get("event") == "step"]


PAGE = '{"thought": "write", "action": "write_site", "args": {}}\n```html\n<html><body><img src="{{image:Krish.png}}" alt="Krish"></body></html>\n```'


# ------------------------------------------------------------------ parser

def test_parse_plain_and_fenced_json():
    assert parse_response('{"thought": "t", "action": "read_profiles", "args": {}}').name == "read_profiles"
    fenced = 'Sure!\n```json\n{"thought": "t", "action": "search_style_guide", "args": {"query": "footer"}}\n```'
    assert parse_response(fenced).args == {"query": "footer"}


def test_parse_write_site_html_block_and_args_variant():
    assert "<img" in parse_response(PAGE).html
    assert parse_response('{"action": "write_site", "args": {"html": "<p>x</p>"}}').html == "<p>x</p>"


@pytest.mark.parametrize("text, message", [
    ("", "empty"),
    ("I will now search.", "No JSON"),
    ('{"action": "search_style_guide", "args": {"query": "x"', "Invalid JSON"),
    ('{"action": "delete_everything", "args": {}}', "Unknown action"),
    ('{"action": "search_style_guide", "args": {}}', '"query"'),
    ('{"action": "search_style_guide", "args": {"query": 5}}', '"query"'),
    ('{"action": "read_profiles", "args": {"path": "/etc"}}', "does not take"),
    ('{"action": "write_site", "args": {}}\n```html\n<html>cut off', "not closed"),
    ('{"action": "write_site", "args": {}}', "code block"),
    ('[1, 2]', "No JSON object"),
])
def test_parse_errors(text, message):
    with pytest.raises(ProtocolError, match=message):
        parse_response(text)


# ------------------------------------------------------------------ loop

def test_invalid_output_does_not_crash_and_counts_as_step(tmp_path):
    a, llm = make_agent(["not json", "{bad", '{"action": "read_profiles", "args": {}}'], tmp_path, max_steps=3)
    assert a.run() is False                      # step limit reached, no crash
    s = steps(llm)
    assert [x["status"] for x in s] == ["protocol_error", "protocol_error", "ok"]
    assert "ERROR" in llm.requests[1][-1]["content"]   # the error went back to the model


def test_read_profiles_lists_profiles_and_images(tmp_path):
    a, llm = make_agent(['{"action": "read_profiles", "args": {}}'], tmp_path, max_steps=1)
    a.run()
    obs = steps(llm)[0]["observation"]
    assert "krish.md" in obs and "_team.md" in obs and "Krish.png" in obs and "_template.md" not in obs


def test_finish_rejected_before_passing_checks(tmp_path):
    a, llm = make_agent(['{"action": "finish", "args": {"summary": "done"}}', PAGE,
                         '{"action": "finish", "args": {"summary": "done"}}'], tmp_path, max_steps=3)
    assert a.run() is False
    obs = [x["observation"] for x in steps(llm)]
    assert obs[0].startswith("finish REJECTED") and "Checker report" in obs[1] and obs[2].startswith("finish REJECTED")
    assert (tmp_path / "index.html").exists()
    assert "data:image/png;base64," in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_unknown_image_and_base64_are_rejected(tmp_path):
    bad_image = PAGE.replace("Krish.png", "nobody.jpg")
    base64 = PAGE.replace("{{image:Krish.png}}", "data:image/png;base64,AAAA")
    a, llm = make_agent([bad_image, base64], tmp_path, max_steps=2)
    a.run()
    obs = [x["observation"] for x in steps(llm)]
    assert "not found" in obs[0] and "base64" in obs[1]


def test_repetition_is_pointed_out(tmp_path):
    q = '{"action": "search_style_guide", "args": {"query": "footer"}}'
    a, llm = make_agent([q, q], tmp_path, max_steps=2)
    a.run()
    assert "already did exactly this in step 1" in steps(llm)[1]["observation"]


def test_finish_accepted_then_human_feedback_continues(tmp_path, monkeypatch):
    passing = CheckReport([CheckResult("all", True, "ok")])
    monkeypatch.setattr(agent_module, "check_site", lambda *a, **k: passing)
    finish = '{"action": "finish", "args": {"summary": "done"}}'
    a, llm = make_agent([PAGE, finish, finish, PAGE, finish], tmp_path, feedback=("make it pink", ""))
    assert a.run() is True
    feedback = [e["feedback"] for e in llm.events if e.get("event") == "human_feedback"]
    assert feedback == ["make it pink", ""]
    obs = [x["observation"] for x in steps(llm)]
    # after the feedback, finish is rejected until the site has been written again
    assert obs[1].startswith("finish accepted") and obs[2].startswith("finish REJECTED") and obs[4].startswith("finish accepted")


def test_old_pages_are_compacted(tmp_path):
    a, llm = make_agent([PAGE, PAGE, '{"action": "read_profiles", "args": {}}'], tmp_path, max_steps=3)
    a.run()
    last_request = llm.requests[-1]
    pages = [m["content"] for m in last_request if m["role"] == "assistant" and "```html" in m["content"]]
    assert "older version omitted" in pages[0] and "<img" in pages[1]
