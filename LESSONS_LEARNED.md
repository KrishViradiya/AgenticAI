# Lessons learned (for the wrap-up)

Short version for the video's wrap-up part. Every point is backed by a log, result file or trace in this repository.

## About agents
1. **The model proposes, the program decides.** OpenCode asked before every edit and command (Task 1); our own loops
   validate every action before running it (Tasks 2 and 4). All safety lives in the program, not in the prompt.
2. **Agents have no memory between sessions.** OpenCode hit the same encoding error in all three sessions (Task 1).
   Knowledge only survives where it is written down: `AGENTS.md`, the system prompt, the code.
3. **The model decides what to look up – that is what makes it an agent.** At 24/25 checks our agent searched for the
   missing rule on its own and fixed it (Task 2, run_02 step 18, `task2_own_agent/docs/annotated_step.md`).
4. **Prompt injections were read, not followed – and not reported.** The real Task 4 model ignored both planted
   instructions but did not mention them, although we asked. Don't rely on the model to report attacks; make the
   harmful action impossible instead.

## About context and tokens
5. **Whatever enters the context is paid for again in every step.** Placeholders kept 18.6K tokens of image data out of
   the model's context (Task 1); retrieval with a 1,000-token budget replaced a 5.7K-token style guide (Task 2);
   compaction kept old pages out (Task 2); bounded tool outputs kept Task 4 at ~10K prompt tokens.
6. **Hidden reasoning is unpredictable.** One 113-character answer cost 11,456 output tokens (Task 2, run_01).

## About retrieval
7. **Embeddings measure similarity, not validity or exactness.** Deprecated rules ranked above active ones (Task 2);
   error codes like PQ-E3441 and PQ-E4934 look alike to embeddings and to the re-ranker (Task 3). Keyword search and
   metadata (status, version) in every chunk fix what embeddings miss.
8. **A stronger component can make the system worse.** Pure cross-encoder re-ranking lowered recall (0.704 → 0.679);
   blending it with the hybrid score raised it to 0.767 (Task 3).
9. **One search can't answer a two-step question.** All multi-hop questions failed until we added a second search for
   the identifiers found in the first results (0/10 → 4/10; 7/20 on unseen questions).

## About engineering
10. **Distrust numbers that make no sense.** A recall of 0.19 for 256-token chunks led us to a gateway bug that returned
    embedding vectors in the wrong order (Task 3, fixed in `common/llm_client.py`).
11. **Validate even when the format is guaranteed.** With native function calling the real model still sent a previous
    tool result as arguments; schema validation rejected it and the model recovered (Task 4).
12. **Tune on one half, report on the other.** All Task 3 choices were made on TUNE and checked on HOLDOUT; the second
    search was checked on 20 questions we never looked at.
13. **Windows matters.** Encoding (cp1252), read-only git objects, no symlinks for normal users, `nul` as the null
    device – each one broke something and each fix is documented.

## AI usage statement
See [CONTRIBUTIONS.md](CONTRIBUTIONS.md#ai-usage).
