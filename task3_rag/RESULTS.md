# Task 3 – RAG under the microscope: our results

The task description and data formats are in [README.md](README.md) (given). This file is our report.
All numbers come from the files in `results/` and can be reproduced with the commands at the end.

## What we built

| | Retrieval | Code |
|---|---|---|
| R1 | BM25 (`rank_bm25`) on the R3 chunks; tokenizer keeps identifiers whole **and** splits them (`pq-e4663` → `pq-e4663`, `pq`, `e4663`) | `retrievers.py: BM25Retriever` |
| R2 | fixed-size chunks (128 tokens, 32 overlap) + embeddings | `chunking.py: fixed_chunks` |
| R3 | recursive chunks (headings → paragraphs → lines → sentences, merged up to 128 tokens) + embeddings | `chunking.py: recursive_chunks` |
| R4 | hybrid: `0.3 · BM25 + 0.7 · cosine`, both min-max normalised | `retrievers.py: HybridRetriever` |
| R5 | R4 + **re-ranking** of the top 30 with `cross-encoder/ms-marco-MiniLM-L-6-v2`, blended `0.5 · cross-encoder + 0.5 · hybrid` | `retrievers.py: RerankRetriever` |
| **deployed** | R5 + a **second retrieval round** for multi-hop questions (extension, see below) | `generate.py: two_hop_search` |

Shared choices:
- Every chunk starts with a metadata header `[type | title | version]`, e.g. `[config | ingress.interval_s (PaderQueue 2.x) | version 2.x]`.
  This makes the version and the document type searchable and visible to the generator.
- Embeddings: `kiconnect.qwen3-embedding-8b` from the gateway (4,096 dimensions); queries get the qwen3 instruction prefix.
  Vectors are cached in `.cache/` (140 MB, not submitted).
- Generator: `openai.gpt-6-luna`, top 8 chunks (~900 tokens), instructed to use only the excerpts, to trust official
  pages over forum posts, to respect versions, and otherwise to answer exactly
  *"The documentation does not contain this information."*

**No tuning on the reported questions without saying so.** The 150 dev questions are split by id into TUNE
(odd ids) and HOLDOUT (even ids). The chunk size, the hybrid weight and the re-ranking blend were chosen on TUNE only.
We report all 150 *and* HOLDOUT alone.

## 1. Retrieval: configurations × categories

recall@5 / precision@5 from `evaluate.py`, 120 answerable dev questions (`unanswerable` has no relevant documents).

| config | identifier | paraphrase | multi-hop | version | **overall** |
|---|---|---|---|---|---|
| R1 BM25 | **1.00** / 0.78 | 0.37 / 0.25 | **0.48** / 0.78 | 0.73 / 0.65 | 0.646 / 0.614 |
| R2 fixed + dense | 0.73 / 0.62 | 0.83 / 0.74 | 0.02 / 0.01 | 0.80 / 0.64 | 0.596 / 0.505 |
| R3 recursive + dense | 0.73 / 0.64 | **0.87** / 0.76 | 0.02 / 0.02 | 0.73 / 0.63 | 0.588 / 0.512 |
| R4 hybrid | **1.00** / 0.76 | 0.70 / 0.64 | 0.45 / 0.79 | 0.67 / 0.61 | 0.704 / **0.701** |
| R5 pure re-ranking (blend 1.0) | 0.77 / 0.64 | 0.67 / 0.51 | 0.28 / 0.36 | **1.00** / 0.93 | 0.679 / 0.611 |
| **R5** (blend 0.5) | 0.97 / 0.76 | 0.73 / 0.64 | 0.43 / 0.73 | 0.93 / 0.65 | **0.767** / 0.697 |

HOLDOUT only (60 questions never used for a choice): R1 0.595, R2 0.586, R3 0.586, R4 0.672, R5 pure 0.647,
**R5 0.716** recall@5 – same order, so the choices did not just fit the tuning questions.
Full tables: `results/retrieval_tables.md`.

**Which approach wins where, and why**
- **identifier → BM25.** Exact strings like `PQ-E3441` or `retention.batch_size` are rare tokens with a high IDF.
  An embedding sees `PQ-E3441` and `PQ-E4934` as almost the same thing (0.73 vs 1.00).
- **paraphrase → dense.** "the part that holds back messages until a later point in time" shares no words with
  "scheduler", but has the same meaning (0.87 vs 0.37).
- **multi-hop → nobody.** The question names only the first document ("the error that caused INC-2024-183"); the
  second one is named only *inside* the first. One search can't find it. Dense search can't even find the first one:
  all 120 postmortems read alike, only the number differs – BM25 matches the number.
- **version → the cross-encoder.** It reads question and chunk together and notices "2.x" in both (1.00). Bi-encoders
  and BM25 often return the 4.x page, which is almost identical.
- **The hybrid gets the best of both** for identifier and paraphrase. **Pure re-ranking hurts**: the ms-marco
  cross-encoder was trained on web search, can't tell `PQ-E3441` from `PQ-E4934`, and ranks forum threads above the
  right error page. Blending it 50/50 with the hybrid score keeps the exact match and keeps most of the version gain.

### Hybrid weight (TUNE)

| BM25 weight | 0.0 | 0.1 | 0.2 | **0.3** | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 | 1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| recall@5 | 0.589 | 0.613 | 0.677 | **0.734** | 0.710 | 0.710 | 0.726 | 0.710 | 0.694 | 0.694 | 0.694 |

0.3 is the best recall and precision on TUNE. A small BM25 weight is enough because after min-max normalisation the
top BM25 hit gets 1.0 when an identifier matches exactly, while the cosine scores of the top chunks are close together.

### Re-ranking blend (TUNE)

| cross-encoder share | 0.25 | **0.5** | 0.75 | 1.0 (pure) |
|---|---|---|---|---|
| recall@5 | 0.766 | **0.815** | 0.766 | 0.710 |

## 2. Chunk size (R3)

| chunk size (overlap 0) | chunks | avg tokens | identifier | paraphrase | multi-hop | version | overall |
|---|---|---|---|---|---|---|---|
| 64 | 2,803 | 60 | 0.70 | 0.87 | 0.00 | **0.83** | **0.600** / 0.493 |
| **128** (chosen on TUNE) | 1,315 | 109 | 0.73 | 0.87 | 0.02 | 0.73 | 0.588 / **0.512** |
| 256 | 957 | 144 | 0.73 | 0.87 | 0.02 | 0.73 | 0.588 / 0.502 |

Chunk size changes little here, because most documents are short (100–190 tokens; only the 14 release notes are long).
64-token chunks cut a config page into description / property table / "when to change it", so the
"Default" row becomes its own chunk – good for version questions, worse for precision (more fragments of one page in the top 5).
128 had the best TUNE score; on all dev questions 64 is 0.012 higher in recall – within noise for 120 questions.

## 3. End-to-end: 50 dev questions, judged by `judge.py --sample 50`

| system | identifier | paraphrase | multi-hop | version | unanswerable | **correct** | faithful | relevance | abstained |
|---|---|---|---|---|---|---|---|---|---|
| R4 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 0.80 | 0.983 | 0.608 | 40% |
| R5 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 0.80 | 1.000 | 0.582 | 40% |
| R5 + second round, v1 (chunk-level) | 1.00 | 1.00 | 0.25 | 1.00 | 1.00 | 0.85 | 1.000 | 0.603 | 34% |
| **R5 + second round (deployed)** | 1.00 | 1.00 | **0.40** | 1.00 | 1.00 | **0.88** | 1.000 | 0.600 | 32% |

(correctness per category; files `results/judge_*.jsonl`, `results/judge_summary_*.txt`)

**The second retrieval round (extension).** R4 and R5 failed *every* multi-hop question – the model correctly said
"not in the documentation", because the second document never reached it. So after the first search we take the
identifiers (error codes, incident ids, config keys) from the **whole documents** of the top 5 hits – documents that
contain an identifier from the question first – and search for each of them (max 4 follow-ups, 2 chunks each).
These chunks are added to the context only; the ranked document list (recall@5, test predictions) stays plain R5,
because mixing the follow-ups into the top 5 raised multi-hop recall (0.43 → 0.55) but lowered overall recall
(0.767 → 0.688).

We designed this on the 10 multi-hop questions of the judge sample, so we checked it on the **20 multi-hop dev
questions we never looked at** (`results/two_hop_context_check.json`): both needed documents are in the context for
0/20 with R5 and **7/20 with the second round** (4/10 on the seen ones) – it generalises.

## 4. Do we trust the judge? 10 decisions checked by hand

| id | category | answer (short) | judge | we agree? |
|---|---|---|---|---|
| dev004 | paraphrase | `dlq.max_retries` | correct | yes |
| dev011 | paraphrase | `broker.timeout_ms` | correct | yes |
| dev008 | identifier | defaults to `10` seconds | correct | yes (unit added, but it is in the doc) |
| dev061 | identifier | name of the tenant the command applies to | correct | yes |
| dev009 | version | `none` in 2.x | correct | yes |
| dev033 | version | `60` seconds in 3.x | correct | yes |
| dev013 | unanswerable | abstained | correct | yes |
| dev054 | unanswerable | abstained | correct | yes |
| dev025 | multi-hop | abstained | wrong | yes – the fix is in the documentation |
| dev030 | multi-hop | abstained | wrong | yes |

We agree with all 10 **correctness** verdicts. Two weaknesses of the other metrics:
- **Answer relevance punishes correct abstentions** (0.32–0.40): for the abstention sentence the judge always writes the same
  three generic questions ("What does the documentation say about the product's release schedule?") – it is the
  identical prompt, so the gateway cache even returns the identical reply.
- **Relevance rewards repeating the question**: dev061 is correct but scores 0.65; answers that restate the question score ~0.95.

So we trust correctness and faithfulness for short factual answers, and treat relevance as a weak signal.

## 5. Cost and latency

| | index build (first time) | search per query | tokens per query |
|---|---|---|---|
| R1 BM25 | 0.1 s chunking + 0.06 s index | 1.3 ms | 0 (local) |
| R2 fixed + dense | 65 s embedding (1,327 chunks) | 0.4 ms + 0.26 s query embedding | ~42 embedding tokens |
| R3 recursive + dense | 100 s embedding (1,315 chunks) | 0.5 ms + 0.26 s | ~42 |
| R4 hybrid | both of the above | 3.3 ms + 0.26 s | ~42 |
| R5 re-ranking | + 27 s to load the cross-encoder | **620 ms** (30 pairs on a laptop CPU) + 0.26 s | ~42 + 30 local cross-encoder pairs |
| R5 + second round | same | ~1.5 s (up to 4 more searches) | ~200 embedding tokens |

Generation (gpt-6-luna): ~1,150 prompt + ~36 output tokens and ~2.3 s per answer for R4/R5; ~1,490 prompt tokens and
~2.6 s with the second round (more context). Embeddings are free; generating 50 answers cost ~$0.008, judging 50
answers ~$0.01, the 100 test predictions $0.021. The query embedding latency (mean 0.26 s, median 0.15 s) was measured
with 20 single uncached calls. None of the 300 generation calls was a gateway cache hit (`cache_hit` in `logs/generate_*.jsonl`),
so the generation times are real first-time latencies. Index embedding times vary with the gateway load (R3 has fewer chunks than R2 but took longer).

## 6. Failure analysis: 5 questions our best system gets wrong

All wrong answers of the deployed system are **retrieval failures**. The generator never made something up
(faithfulness 1.0): whenever the fact was missing, it abstained.

| id | question (short) | what was in the context | failure | why |
|---|---|---|---|---|
| dev025 | fix for the error behind INC-2024-171 | the incident (names PQ-E1915), two chunks of the forum thread "PQ-E1915 after upgrade?" | retrieval (2nd hop) | the follow-up search for `PQ-E1915` returns the forum thread first; it fills both slots, the error page never gets in |
| dev030 | fix for the error behind INC-2025-175 | the incident (names PQ-E2617), forum "PQ-E2617 after upgrade?" | retrieval (2nd hop) | same pattern: forum threads titled with the code outrank the official error page |
| dev042 | current default of the setting PQ-E2051 tells you to change | six forum threads about various error codes, no error page | retrieval (1st hop) | the official page `PQ-E2051 COMPACTOR_CODEC_MISMATCH` is not even in the first round – forum threads with the code in the title win |
| dev069 | current default of the setting PQ-E4020 tells you to change | error page (says: change `spool.compression`) **and** the page of `spool.compression` – but the **2.x** version | retrieval (version) | the follow-up query `spool.compression` has no version, so the 2.x page ranked above the 4.x page; the model rightly refused to give a "current" default from a 2.x page |
| dev083 | fix for the error behind INC-2024-147 | the incident (names PQ-E2051), forum thread on PQ-E2051 | retrieval (2nd hop) | same as dev025 |

**What would fix it:** prefer official documents over forum threads when they match equally (a small type prior, or
re-rank follow-up results with the doc type), take more follow-up chunks per identifier, and add "4.x" to follow-up
queries for config keys when the question asks for the *current* value.

## 7. Recommendation

**Deploy R5 + the second retrieval round** (BM25 0.3 + dense on 128-token recursive chunks, cross-encoder blended 50/50,
plus follow-up searches for identifiers). It has the best recall@5 (0.767, HOLDOUT 0.716) and the best answers
(0.88 correct, faithfulness 1.0, never invents an answer).

If latency matters more than the last few percent, **R4** is the pragmatic choice: same answer correctness as R5
without the second round (0.80), 3 ms instead of 620 ms of search, and no 27 s model load. The cross-encoder is what
makes R5 slow; on a GPU or with a smaller pool it would be cheap.

Next steps, in order of value: (1) official-over-forum preference in the follow-up search; (2) version-aware follow-ups;
(3) a re-ranker that handles identifiers (or skip re-ranking when the query contains an exact code).

## Test predictions

`predictions_test.jsonl`: 100 lines `{id, answer, retrieved_doc_ids}` (5 documents each) with the deployed system.
36 of 100 answers are abstentions (dev sample: 32%).

## How to run

From the repository root (gateway key in `.env`, university network or VPN; R5 needs `uv sync --extra local`):

```bash
uv run python task3_rag/chunking.py                                   # chunk statistics
uv run python task3_rag/run_retrieval.py                              # R1–R5, chunk sizes, weights -> results/
uv run python task3_rag/evaluate.py task3_rag/results/retrieval_R5_dev.jsonl --k 5
uv run python task3_rag/generate.py --system R5 --two-hop --split dev --sample 50   # results/answers_R5_2hop.jsonl
uv run python task3_rag/judge.py task3_rag/results/answers_R5_2hop.jsonl --sample 50 --out task3_rag/results/judge_R5_2hop.jsonl
uv run python task3_rag/generate.py --system R5 --two-hop --split test           # predictions_test.jsonl
```

The first run embeds the corpus four times (~5 minutes); later runs use the cache.

## Files

| file | content |
|---|---|
| `chunking.py` | fixed-size and recursive chunking, metadata header |
| `retrievers.py` | BM25 tokenizer, BM25 / dense / hybrid / re-ranking retrievers, embedding cache |
| `run_retrieval.py` | builds and evaluates everything, TUNE/HOLDOUT split, writes `results/` |
| `generate.py` | answers (with or without the second round) and the test predictions |
| `results/retrieval_*_dev.jsonl`, `metrics_*.json` | retrieval results and `evaluate.py` output per config |
| `results/retrieval_report.json`, `retrieval_tables.md` | all tables, weight grids, timings |
| `results/answers_*.jsonl`, `judge_*.jsonl`, `judge_summary_*.txt` | generated answers and judge results |
| `results/two_hop_context_check.json` | the check on unseen multi-hop questions |
| `logs/` | every gateway call (generation, judge) |

## A bug we found on the way

The first results said 256-token chunks were terrible (recall 0.19). The cause was not chunking: when an embedding
batch mixes texts the gateway has cached with new ones, the gateway returns the vectors **in the wrong order and with
wrong `index` fields**. Our four chunkings share many identical chunks, so this happened a lot. We fixed it in
`common/llm_client.py` (embedding requests now bypass the gateway cache) and checked that Task 2's index was not affected.
