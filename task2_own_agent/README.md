# Task 2 – Our own coding agent

A small Python agent that builds the team website and follows the (fictional) UPB Agentic SE Web Style Guide.
It finds the style guide rules with retrieval (RAG), works in a loop with a JSON action protocol we designed,
and accepts feedback from a human after it finishes. No frameworks, no native function calling.

The task specification we were given is in [SPECIFICATION.md](SPECIFICATION.md).

## How to run

Requirements: the Python environment from the repository root (`uv sync`), a gateway key in `.env`,
and the university network or VPN.

From the repository root:

```bash
uv run python task2_own_agent/agent.py --content task1_opencode/content --out task2_own_agent/site/index.html
```

The agent prints one line per step. After an accepted `finish` it asks for feedback on the terminal:
type a change request to let it continue, or press Enter to end the run.
On Windows, set `PYTHONIOENCODING=utf-8` if the console shows encoding errors.

| Option | Default | Meaning |
|---|---|---|
| `--content` | `task1_opencode/content` | profiles (`*.md`) and `images/` |
| `--out` | `task2_own_agent/site/index.html` | where the site is written |
| `--model` | `$LAB_CHAT_MODEL` (gpt-6-luna) | chat model, e.g. the free fallback `kiconnect.qwen3.8-27b` |
| `--max-steps` | 25 | step limit per round (a feedback round gets a new budget) |
| `-k` | 4 | chunks per style guide search |
| `--max-tokens` | none | output limit per answer; leave unset, a page plus hidden reasoning is long |
| `--log` | `logs/run_XX.jsonl` | log file (next free number) |

Other commands:

```bash
uv run python task2_own_agent/rag.py "What text goes into the footer?" -k 4   # try the retrieval
uv run python task2_own_agent/test_rag.py                                    # retrieval check, 18 questions
uv run pytest task2_own_agent/test_agent.py -q                               # loop tests with a fake model
uv run python task2_own_agent/check_site.py task2_own_agent/site/index.html --content task1_opencode/content
```

## Files

| File | Content |
|---|---|
| `rag.py` | loading, chunking, embedding, `search(query, k)`, 1,000-token observation budget |
| `agent.py` | prompts, protocol parser, actions, loop, human feedback, context compaction, CLI |
| `test_rag.py` | 18 retrieval questions with the expected style guide document |
| `test_agent.py` | 19 offline tests of the loop (fake model, no gateway needed) |
| `logs/run_02.jsonl` | **the submitted run** that produced `site/index.html` (incl. human feedback) |
| `logs/run_01.jsonl` | first complete run (no feedback given) |
| `site/index.html` | the website from run_02, 25/25 checks |

## Design decisions

### Chunking
The style guide has 55 documents of 40–188 tokens (about 5,700 tokens in total), each about one topic.
We split a document only at its `##` sections (5 documents have them) and split a section further at blank
lines only if it would exceed 250 tokens (never happens with this guide). Result: **66 chunks**.
Splitting smaller would separate a rule from its context; merging documents would mix topics.

Every chunk starts with a header such as `[SG-13] Night mode palette (version 2) | Status: ACTIVE (version 2)`.
The header is embedded together with the text and shown to the model, so the source and the status of a rule
are never lost. This matters because the guide contains old and new versions of the same rule
(SG-10/11, SG-12/13, SG-19/21, SG-39/40, SG-49/50) whose texts – and therefore vectors – are almost identical.

### Embeddings and search
- Model: `kiconnect.qwen3-embedding-8b` from the gateway (free, 4,096 dimensions).
- Queries get the instruction prefix that qwen3-embedding was trained with (`Instruct: ... Query: ...`);
  documents don't.
- Vectors are L2-normalised and kept in a numpy matrix, so cosine similarity is one matrix-vector product.
- The vectors are cached in `.cache/` (key = hash of all chunk texts + model name), so a run needs only
  one embedding call per query. Building the index takes about 8 s.

### k and the 1,000-token budget
`k = 4`. `format_results()` adds chunks best first and **skips** a chunk that would push the observation over
1,000 tokens (measured with `count_tokens`); it never cuts a rule in half. In practice one search observation is
236–553 tokens (average ~385 over 33 searches in run_01 and run_02), so the limit is never close.
`test_rag.py` shows k = 4 is enough: the right document is in the top 4 for **18/18** questions (MRR 0.97).
Neither the system prompt nor the task contains style guide text (470 tokens together); every rule must be searched.

### Protocol and prompt design
One JSON object per step: `{"thought": "...", "action": "...", "args": {...}}`.
For `write_site` the HTML follows the JSON in a ```` ```html ```` block, because a whole page as an escaped JSON
string is error-prone; `{"html": "..."}` in `args` is accepted too.

The system prompt contains the protocol, the four actions with their arguments, and general working rules:
search before writing (one specific question per search), only ACTIVE rules count, never write image data,
always send the complete page, search again when a check fails. The task prompt lists the website requirements
from Task 1 and the step budget.

### Handling invalid output
`parse_response()` accepts a ```` ```json ```` fence or text before the JSON (it decodes the first `{...}`).
Everything else raises a `ProtocolError`, whose message goes back to the model as the observation
(`ERROR: ...`) and **counts as a step**. Nothing crashes. Covered cases:

| Model output | Observation |
|---|---|
| empty / no JSON / invalid JSON | what is wrong + "answer with exactly one JSON object" |
| unknown action | list of valid actions |
| missing, wrong-typed or extra arguments | which argument is expected |
| `write_site` without HTML, or the `html` block not closed (cut off) | send the complete page again |
| base64 image data in the page | rejected, use `{{image:...}}` placeholders |
| unknown image file | `embed_images` error with the available file names |
| exactly the same action again | executed, plus "you already did this in step N" |
| `finish` before a passing check | `finish REJECTED` + the failing checks |
| no `finish` at all | stops after `--max-steps`, with a warning from 3 steps left |

In run_02 the model once sent `write_site` without the HTML block (step 16); it got the error and sent the page
in the next step.

### Finish and human feedback
`finish` is accepted only if the **last** `write_site` passed all 25 checks of `check_site(mode="full")`.
After that the user is asked for feedback. Non-empty feedback is appended as a user message, the step counter
starts again, and the agent must write and pass the checks again before it may finish. Empty input ends the run.

### Context management
Every step re-sends the whole conversation. Pages are by far the largest messages (4–5K tokens each), so after
each `write_site` all **older** pages in the history are replaced by `[older version omitted, N tokens]`.
The model always sees its latest page; the log keeps every page. In run_02 the prompt grew from 479 tokens
(step 1) to 14,735 tokens (step 24); without compaction each extra page would add another ~4.5K tokens to every
later request.

### Logging
`LLMClient(log_path=logs/run_XX.jsonl)` logs every request and response (with tokens, cost, finish reason).
We add our own events with `log_event`: `run_start`, one `step` per step (step number, thought, action, args,
observation, ok/protocol_error), `checker` (full report), `human_feedback`, `step_limit_reached`, `run_end`.

## Results

| | run_01 | run_02 (submitted) |
|---|---|---|
| steps | 19 | 24 (20 + 4 after feedback) |
| style guide searches | 16 | 17 |
| invalid answers | 0 | 1 |
| first `write_site` | 25/25 | 24/25 (theme mechanism) → searched SG-20 → 25/25 |
| human feedback | none | "random hot take button + funny nicknames" → 25/25 |
| cost | $0.0115 | $0.0153 |

## Known limitations

- **Retrieval can rank a deprecated rule first.** Embeddings measure text similarity, not validity:
  for "day mode colors" SG-10 (deprecated) ranks above SG-11. We rely on the model reading the status in the
  chunk header. A stronger fix would be to filter or down-weight deprecated chunks.
- **Several chunks of one document can fill the top k** (e.g. 4 × SG-02 for a metadata query), which leaves no
  room for other documents. No de-duplication by document.
- **Search results are never removed from the context.** Only pages are compacted. With many more steps the
  prompt would keep growing by ~400 tokens per search; a long run would need summarising old observations.
- **The checker is the only definition of "done".** It tests 25 things; SHOULD rules and anything it doesn't test
  (e.g. spacing, card shadows) can be wrong without the agent noticing.
- **Every change rewrites the whole page** (~4–5K output tokens). Small edits would be cheaper with a diff/patch action.
- **Hidden reasoning is unpredictable.** In run_01 the first answer (`read_profiles`, 113 visible characters)
  cost 11,456 output tokens, half of the run's cost.
- **Repetition detection is exact-match only.** A slightly reworded search is not detected as a repeat.
- **The gateway caches identical requests.** Retrying the same conversation returns the same answer;
  our observations always change, so this doesn't block the loop, but latency numbers can look too good.
- **Feedback always forces a rewrite.** Even feedback like "looks good" makes the agent write and check again
  before it may finish.
- `count_tokens` uses tiktoken's `cl100k_base`; the gateway models tokenize differently, so all budgets are estimates.
- Needs the university network or VPN for every run (chat and query embeddings).
