"""Retrieve + generate answers with one of the systems R1–R5.

    # 50 dev questions (the same stratified sample judge.py --sample 50 uses) -> results/answers_R5.jsonl
    uv run python task3_rag/generate.py --system R5 --split dev --sample 50
    # all 100 test questions -> task3_rag/predictions_test.jsonl
    uv run python task3_rag/generate.py --system R5 --split test

The chunking and the hybrid weight come from results/config.json (written by run_retrieval.py).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chunking import chunk_corpus, load_corpus, n_tokens  # noqa: E402
from evaluate import load_jsonl  # noqa: E402
from judge import ABSTENTION, is_abstention, stratified_sample  # noqa: E402
from retrievers import (BM25Retriever, DenseRetriever, Embedder, HybridRetriever, LLMClient,  # noqa: E402
                        RerankRetriever, doc_ids)
from run_retrieval import CHUNKINGS  # noqa: E402

RESULTS = HERE / "results"
CONTEXT_CHUNKS = 8  # chunks given to the generator (~1,000 tokens with 128-token chunks)

SYSTEM_PROMPT = f"""You answer questions about PaderQueue, a message queue, using ONLY the documentation excerpts given to you.

Rules:
- Use only facts that are in the excerpts, not your own knowledge. Each excerpt starts with [type | title | version].
- Official documentation (config, error, cli, runbook, changelog, incident) is reliable. Forum posts can be wrong or outdated:
  never prefer a forum post over official documentation.
- Versions matter. If the question names a version (e.g. 2.x), use the excerpt for that version. Otherwise answer for the
  current version, 4.x.
- Some questions need two excerpts combined, e.g. an incident names an error code and the error page names the fix.
- If the excerpts do not contain the answer, reply with exactly this sentence and nothing else:
  {ABSTENTION}
- Answer in one to three sentences. Give exact values, names and codes as written in the documentation."""


def build_system(name: str, llm: LLMClient):
    config = json.loads((RESULTS / "config.json").read_text())
    embedder = Embedder(llm)
    docs = load_corpus()
    chunking = "fixed128" if name == "R2" else config["chunking"]
    chunks = chunk_corpus(docs, *CHUNKINGS[chunking])
    if name == "R1":
        return BM25Retriever(chunks)
    dense = DenseRetriever(chunks, embedder)
    if name in ("R2", "R3"):
        return dense
    hybrid = HybridRetriever(BM25Retriever(chunks), dense, config["hybrid_weight"])
    return hybrid if name == "R4" else RerankRetriever(hybrid, pool=config["rerank_pool"], alpha=config["rerank_alpha"])


IDENTIFIER_RE = re.compile(r"PQ-E\d{4}|INC-\d{4}-\d{3}|\b[a-z]+\.[a-z_]+\b")


def two_hop_search(retriever, question: str, first_hop: int = 5, max_follow: int = 4, per_follow: int = 2):
    """Second retrieval round for multi-hop questions (extension on top of R5).

    Multi-hop questions name only the first document ("the error that caused INC-2024-183"); the second one
    (the page of that error) is only named INSIDE the first. So: take identifiers (error codes, incident ids,
    config keys) that appear in the top chunks but not in the question, and search for each of them.
    Returns (ranking for the context, ranked doc ids).
    """
    first = retriever.search(question, 30)
    asked = set(IDENTIFIER_RE.findall(question))
    # Read identifiers from the WHOLE document of the top hits, not only the retrieved chunk: an incident report
    # is split into two chunks, and "caused by PQ-E1915" is often in the chunk that was not retrieved.
    # Documents that contain an identifier from the question (e.g. the incident INC-2024-171 itself) go first.
    top_docs = list(dict.fromkeys(retriever.chunks[i].doc_id for i, _ in first[:first_hop]))
    texts = {d: "\n".join(c.text for c in retriever.chunks if c.doc_id == d) for d in top_docs}
    top_docs.sort(key=lambda d: not any(a in texts[d] for a in asked))
    follow_ups = []
    for d in top_docs:
        for ident in IDENTIFIER_RE.findall(texts[d]):
            if ident not in asked and ident not in follow_ups:
                follow_ups.append(ident)
    extra = []
    for ident in follow_ups[:max_follow]:
        extra.extend(retriever.search(ident, per_follow))
    # context: best 6 chunks of the first round + the follow-up chunks, without duplicates
    ranking = list(dict.fromkeys(i for i, _ in first[:6] + extra))
    # Ranked documents (what recall@5 and the test predictions use): the first round only. We measured the
    # alternative "best 3 of the first round, then the follow-ups": multi-hop recall@5 rose 0.43 -> 0.55, but
    # overall recall@5 fell 0.767 -> 0.688, because follow-ups push correct first-round documents out of the top 5.
    # So the second round only feeds the generator's context.
    docs = list(dict.fromkeys(retriever.chunks[i].doc_id for i, _ in first))
    return [(i, 0.0) for i in ranking], docs


def prompt_for(question: str, contexts: list[str]) -> list[dict]:
    excerpts = "\n\n".join(f"Excerpt {i}:\n{text}" for i, text in enumerate(contexts, start=1))
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{excerpts}\n\nQuestion: {question}"}]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", required=True, choices=["R1", "R2", "R3", "R4", "R5"])
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--sample", type=int, help="dev only: the stratified sample judge.py uses")
    parser.add_argument("--two-hop", action="store_true", help="add the second retrieval round (extension)")
    parser.add_argument("--retrieval-only", action="store_true",
                        help="no answers: write retrieval results for all questions and print recall/precision")
    args = parser.parse_args()
    name = args.system + ("_2hop" if args.two_hop else "")

    questions = load_jsonl(HERE / "data" / f"questions_{args.split}.jsonl")
    if args.sample:
        questions = stratified_sample(questions, args.sample)
    llm = LLMClient(log_path=HERE / "logs" / f"generate_{name}_{args.split}.jsonl")
    retriever = build_system(args.system, llm)
    embedder = Embedder(llm)
    embedder.embed_queries([q["question"] for q in questions])  # already cached by run_retrieval.py

    if args.retrieval_only:
        from evaluate import evaluate
        from run_retrieval import format_row
        results = []
        for q in questions:
            docs = (two_hop_search(retriever, q["question"])[1] if args.two_hop
                    else doc_ids(retriever.chunks, retriever.search(q["question"], 30)))
            results.append({"id": q["id"], "retrieved_doc_ids": docs[:20]})
        (RESULTS / f"retrieval_{name}_{args.split}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in results), encoding="utf-8")
        report = evaluate(results, questions, 5)
        (RESULTS / f"metrics_{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(format_row(name, report["summary"]))
        return

    rows, stats = [], []
    for i, q in enumerate(questions, start=1):
        start = time.perf_counter()
        if args.two_hop:
            ranking, ranked_docs = two_hop_search(retriever, q["question"])
            contexts = [retriever.chunks[j].text for j, _ in ranking]
        else:
            ranking = retriever.search(q["question"], 30)
            ranked_docs = doc_ids(retriever.chunks, ranking)
            contexts = [retriever.chunks[j].text for j, _ in ranking[:CONTEXT_CHUNKS]]
        retrieval_s = time.perf_counter() - start
        before = (llm.total_prompt_tokens, llm.total_completion_tokens)
        start = time.perf_counter()
        answer = llm.chat(prompt_for(q["question"], contexts)).strip()
        generation_s = time.perf_counter() - start
        if is_abstention(answer):
            answer = ABSTENTION
        stats.append({"retrieval_s": retrieval_s, "generation_s": generation_s,
                      "prompt_tokens": llm.total_prompt_tokens - before[0],
                      "completion_tokens": llm.total_completion_tokens - before[1],
                      "context_tokens": sum(n_tokens(c) for c in contexts)})
        rows.append({"id": q["id"], "answer": answer, "contexts": contexts,
                     "retrieved_doc_ids": ranked_docs[:5]})
        print(f"[{i}/{len(questions)}] {q['id']} {answer[:90]!r}")

    if args.split == "test":
        out = HERE / "predictions_test.jsonl"
        lines = [{"id": r["id"], "answer": r["answer"], "retrieved_doc_ids": r["retrieved_doc_ids"]} for r in rows]
    else:
        out = RESULTS / f"answers_{name}.jsonl"
        lines = rows
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lines), encoding="utf-8")

    summary = {k: float(np.mean([s[k] for s in stats])) for k in stats[0]}
    summary.update({"system": name, "split": args.split, "n": len(rows), "usage": llm.usage_summary(),
                    "cost_usd": llm.total_cost_usd})
    (RESULTS / f"generation_stats_{name}_{args.split}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
