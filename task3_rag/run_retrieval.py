"""Build R1–R5, evaluate them on the dev questions, write everything to results/.

    uv run python task3_rag/run_retrieval.py

Tuning is done honestly: the dev questions are split by id into a TUNE half (odd numbers) and a HOLDOUT half
(even numbers). The R3 chunk size and the hybrid weight are chosen on TUNE only. Tables are reported on all
dev questions AND on HOLDOUT alone, so you can see the choices did not just fit the questions we report.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chunking import chunk_corpus, load_corpus, n_tokens  # noqa: E402
from evaluate import evaluate, load_jsonl  # noqa: E402
from retrievers import (QUERY_INSTRUCTION, BM25Retriever, DenseRetriever, Embedder, HybridRetriever,  # noqa: E402
                        RerankRetriever, LLMClient, doc_ids)

RESULTS = HERE / "results"
DEV = load_jsonl(HERE / "data" / "questions_dev.jsonl")
TEST = load_jsonl(HERE / "data" / "questions_test.jsonl")
K = 5
CATEGORIES = ["identifier", "paraphrase", "multi-hop", "version"]

CHUNKINGS = {  # name: (method, size, overlap)
    "fixed128": ("fixed", 128, 32),
    "rec64": ("recursive", 64, 0),
    "rec128": ("recursive", 128, 0),
    "rec256": ("recursive", 256, 0),
}
WEIGHTS = [round(w * 0.1, 1) for w in range(11)]
ALPHAS = [0.25, 0.5, 0.75, 1.0]  # cross-encoder share in R5 (1.0 = pure re-ranking)


def is_tune(q: dict) -> bool:
    return int(q["id"][-3:]) % 2 == 1


TUNE = [q for q in DEV if is_tune(q)]
HOLDOUT = [q for q in DEV if not is_tune(q)]


def run(retriever, questions: list[dict], n: int = 30) -> tuple[list[dict], float]:
    """Retrieve for every question; returns (results, mean search seconds per query)."""
    results, seconds = [], []
    for q in questions:
        start = time.perf_counter()
        ranking = retriever.search(q["question"], n)
        seconds.append(time.perf_counter() - start)
        results.append({"id": q["id"], "retrieved_doc_ids": doc_ids(retriever.chunks, ranking)[:20]})
    return results, float(np.mean(seconds))


def score(results: list[dict], questions: list[dict]) -> dict:
    return evaluate(results, questions, K)["summary"]


def pick(summary: dict) -> tuple[float, float]:
    o = summary["overall"]
    return o["context_recall"], o["context_precision"]


def save(name: str, results: list[dict]) -> None:
    path = RESULTS / f"retrieval_{name}_dev.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in results), encoding="utf-8")
    report = evaluate(results, DEV, K)
    (RESULTS / f"metrics_{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def measure_query_embedding_latency(llm: LLMClient, n: int = 20) -> dict:
    """Single, first-time (uncached) query embedding calls, as one query would cost in a live system."""
    path = RESULTS / "latency_query_embedding.json"
    if path.exists():
        return json.loads(path.read_text())
    seconds = []
    for q in DEV[:n]:
        start = time.perf_counter()
        llm.embed([QUERY_INSTRUCTION + q["question"] + " "])  # trailing space: not identical to the cached batch call
        seconds.append(time.perf_counter() - start)
    data = {"n": n, "mean_s": float(np.mean(seconds)), "median_s": float(np.median(seconds))}
    path.write_text(json.dumps(data, indent=2))
    return data


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    llm = LLMClient(log_path=HERE / "logs" / "retrieval.jsonl")
    embedder = Embedder(llm)
    docs = load_corpus()
    embedder.embed_queries([q["question"] for q in DEV + TEST])  # one batch, cached

    # ---- chunk + index every chunking
    chunks, dense, index_info = {}, {}, {}
    for name, (method, size, overlap) in CHUNKINGS.items():
        start = time.perf_counter()
        chunks[name] = chunk_corpus(docs, method, size, overlap)
        chunk_s = time.perf_counter() - start
        dense[name] = DenseRetriever(chunks[name], embedder)
        index_info[name] = {"chunks": len(chunks[name]), "chunk_s": chunk_s, "embed_s": dense[name].embed_seconds,
                            "avg_tokens": float(np.mean([n_tokens(c.text) for c in chunks[name]]))}
        print(f"{name}: {len(chunks[name])} chunks, embedded in {dense[name].embed_seconds:.1f}s (first time)")

    systems, latency, report = {}, {}, {"tune_ids": [q["id"] for q in TUNE]}

    # ---- R2 and the R3 chunk size comparison
    results, latency["R2"] = run(dense["fixed128"], DEV)
    systems["R2"] = ("fixed128", results)
    size_table = {}
    for name in ["rec64", "rec128", "rec256"]:
        results, secs = run(dense[name], DEV)
        size_table[name] = {"tune": score(results, TUNE), "all": score(results, DEV), "holdout": score(results, HOLDOUT),
                            "search_s": secs}
        save(f"R3_{name}", results)
    best_size = max(size_table, key=lambda n: pick(size_table[n]["tune"]))
    print("R3 chunk size chosen on TUNE:", best_size)
    results, latency["R3"] = run(dense[best_size], DEV)
    systems["R3"] = (best_size, results)
    report["chunk_sizes"] = size_table
    report["r3_chunking"] = best_size

    # ---- R1 on the same chunks as R3
    start = time.perf_counter()
    bm25 = BM25Retriever(chunks[best_size])
    index_info["bm25"] = {"build_s": time.perf_counter() - start}
    results, latency["R1"] = run(bm25, DEV)
    systems["R1"] = (best_size, results)

    # ---- R4: hybrid weight chosen on TUNE
    grid = {}
    for w in WEIGHTS:
        results, _ = run(HybridRetriever(bm25, dense[best_size], w), TUNE)
        grid[w] = score(results, TUNE)
    best_w = max(WEIGHTS, key=lambda w: pick(grid[w]))
    print("Hybrid BM25 weight chosen on TUNE:", best_w)
    hybrid = HybridRetriever(bm25, dense[best_size], best_w)
    results, latency["R4"] = run(hybrid, DEV)
    systems["R4"] = (best_size, results)
    report["weight_grid_tune"] = {str(w): grid[w]["overall"] for w in WEIGHTS}
    report["hybrid_weight"] = best_w

    # ---- R5: cross-encoder re-ranking of the hybrid top 30, blend weight alpha chosen on TUNE
    start = time.perf_counter()
    rerank = RerankRetriever(hybrid, pool=30, alpha=1.0)
    index_info["cross_encoder_load_s"] = time.perf_counter() - start
    results, latency["R5_pure"] = run(rerank, DEV)  # first pass computes (and times) the cross-encoder
    systems["R5_pure"] = (best_size, results)
    alpha_grid = {}
    for alpha in ALPHAS:
        rerank.alpha = alpha
        alpha_grid[alpha] = score(run(rerank, TUNE)[0], TUNE)
    best_alpha = max(ALPHAS, key=lambda a: pick(alpha_grid[a]))
    print("Re-ranking blend alpha chosen on TUNE:", best_alpha)
    rerank.alpha = best_alpha
    results, _ = run(rerank, DEV)
    latency["R5"] = latency["R5_pure"]  # same work per query, only the final sort differs
    systems["R5"] = (best_size, results)
    report["alpha_grid_tune"] = {str(a): alpha_grid[a]["overall"] for a in ALPHAS}
    report["rerank_alpha"] = best_alpha

    # ---- save + summary
    for name, (_, results) in systems.items():
        save(name, results)
    report["systems"] = {name: {"chunking": ch, "all": score(r, DEV), "holdout": score(r, HOLDOUT),
                                "search_s": latency[name]} for name, (ch, r) in systems.items()}
    report["index"] = index_info
    report["query_embedding_latency"] = measure_query_embedding_latency(llm)
    report["query_tokens_avg"] = float(np.mean([n_tokens(QUERY_INSTRUCTION + q["question"]) for q in DEV]))
    report["embedding_usage"] = llm.usage_summary()
    (RESULTS / "retrieval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (RESULTS / "config.json").write_text(json.dumps({"chunking": best_size, "hybrid_weight": best_w,
                                                     "rerank_pool": 30, "rerank_alpha": best_alpha}, indent=2))
    print_tables(report)


def format_row(name: str, s: dict) -> str:
    """One markdown table row: recall / precision per category and overall."""
    cells = [f"{s['per_category'][c]['context_recall']:.2f} / {s['per_category'][c]['context_precision']:.2f}"
             for c in CATEGORIES]
    o = s["overall"]
    return f"| {name} | " + " | ".join(cells) + f" | **{o['context_recall']:.3f} / {o['context_precision']:.3f}** |"


def print_tables(report: dict) -> None:
    row = format_row

    head = "| config | " + " | ".join(CATEGORIES) + " | overall |\n|---" * 1 + "|---" * (len(CATEGORIES) + 1) + "|"
    lines = ["## Retrieval, all 120 answerable dev questions (recall@5 / precision@5)", head]
    lines += [row(n, v["all"]) for n, v in report["systems"].items()]
    lines += ["", "## Same, HOLDOUT half only (60 answerable questions not used for any choice)", head]
    lines += [row(n, v["holdout"]) for n, v in report["systems"].items()]
    lines += ["", f"## R3 chunk size (chosen on TUNE: {report['r3_chunking']})", head]
    lines += [row(n, v["all"]) for n, v in report["chunk_sizes"].items()]
    lines += ["", f"## Hybrid weight on TUNE (chosen: {report['hybrid_weight']})", "| BM25 weight | recall | precision |",
              "|---|---|---|"]
    lines += [f"| {w} | {o['context_recall']:.3f} | {o['context_precision']:.3f} |"
              for w, o in report["weight_grid_tune"].items()]
    lines += ["", f"## Re-ranking blend on TUNE (chosen alpha: {report['rerank_alpha']}; 1.0 = pure re-ranking)",
              "| cross-encoder share | recall | precision |", "|---|---|---|"]
    lines += [f"| {a} | {o['context_recall']:.3f} | {o['context_precision']:.3f} |"
              for a, o in report["alpha_grid_tune"].items()]
    text = "\n".join(lines)
    (RESULTS / "retrieval_tables.md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
