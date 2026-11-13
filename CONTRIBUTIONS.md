# Contributions – Group 07

Short list per person. Everyone has checked their own entry and can explain every part of the submission.

## Krish Viradiya (4109611)
- Setup: Python environment, gateway key, OpenCode configuration (`task1_opencode/opencode.json`, `AGENTS.md`)
- Task 1: hello world (`screenshots/hello_krish.png`); profile and picture; ran all three OpenCode sessions
  (build, tagline + hover effects, new photos + study background), exported them, kept the session log in `PROMPTS.md`
- Task 2: built the agent with Claude Code (`rag.py`, `agent.py`, tests); ran run_01–run_03 and gave the human feedback; README
- Task 3: ran the retrieval experiments, the answer generation and the judge; `RESULTS.md`
- Task 4: tool layer, sandbox and agent with Claude Code; mock and real agent runs; `RESULTS.md`
- Repository, final checks and the submission ZIP
- Video: presents Task 2

## Keval (4108929)
- Task 1: hello world (`screenshots/hello_keval.png`); profile `content/keval.md` and picture
- Reviewed the Task 1 website and the team's shared view
- Video: presents the intro and Task 1 (using an agent: screenshots, session statistics, where the agent went wrong)

## Harsh (4108643)
- Task 1: hello world (`screenshots/hello_harsh.png`); profile `content/harsh.md` and picture
- Reviewed the Task 3 results: the per-category table, the failure analysis and the hand check of the judge decisions
- Video: presents Task 3 (RAG comparison, failures, recommendation)

## Nevil (4110898)
- Task 1: hello world (`screenshots/hello_nevil.png`); profile `content/nevil.md` and picture
- Reviewed the Task 4 results: the tool list, the threat → control table, the agent trace and the prompt injections
- Video: presents Task 4 (tools, containment, the real run and the untrusted content)

## Nirav (4090427)
- Task 1: hello world (`screenshots/hello_nirav.png`); profile `content/nirav.md` and picture
- Reviewed the Task 2 diagram and the lessons learned (`LESSONS_LEARNED.md`)
- Video: presents the wrap-up (lessons learned, AI usage, who did what); merged the video parts

## Whole group
- Shared view on AI and the future of software engineering (`task1_opencode/content/_team.md`)
- Prompt ideas and feedback for the website (Task 1) and for the agent's human-feedback rounds (Task 2)
- Video script and recording – every member presents one part

## AI usage
- Task 1: OpenCode (`openai.gpt-6-luna`) wrote all HTML/CSS/JS. Claude Code helped with setup, `AGENTS.md`,
  prompt drafts and first drafts of the profile texts; no site code.
- Task 2: Claude Code helped write `rag.py`, `agent.py`, the tests and the README. The agent itself uses
  `openai.gpt-6-luna` and `kiconnect.qwen3-embedding-8b` through the UPB AI Gateway.
- Task 3: Claude Code helped write the chunking, the five retrievers, the experiment and generation scripts and
  `RESULTS.md`, and found and fixed the gateway embedding-order bug in `common/llm_client.py`. Answers and judging use
  `openai.gpt-6-luna`; re-ranking uses the local `cross-encoder/ms-marco-MiniLM-L-6-v2`.
- Task 4: Claude Code helped write `tools.py`, `sandbox_runner.py`, `agent.py`, our attack tests and `RESULTS.md`.
  The debugging agent itself is `openai.gpt-6-luna` with native function calling.
- Documentation and video preparation: Claude Code drafted explanations and video scripts; screenshots of the
  websites were taken automatically with headless Edge (no site code was changed for that).
- Everything was reviewed by us; every member must be able to explain every part.
