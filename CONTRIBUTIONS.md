# Contributions

Short list per person. Everyone checks their own entry before submission.

## Krish Viradiya
- Setup: Python environment, gateway key, OpenCode configuration (`task1_opencode/opencode.json`, `AGENTS.md`)
- Hello world with OpenCode (`task1_opencode/screenshots/hello_krish.png`)
- Task 1: ran all three OpenCode sessions (build, tagline + hover effects, new photos + study background),
  exported them and kept the session log in `task1_opencode/PROMPTS.md`
- Task 2: ran the agent (run_01–run_03) and gave the human feedback; README and results
- TODO: video part

## Nirav
- Task 1: profile `content/nirav.md` and picture
- TODO

## Harsh
- Task 1: profile `content/harsh.md` and picture
- TODO

## Keval
- Task 1: profile `content/keval.md` and picture
- TODO

## Nevil
- Task 1: profile `content/nevil.md` and picture
- TODO

## Whole group
- Shared view on AI and the future of software engineering (`content/_team.md`)
- TODO: Task 3, Task 4, video

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
