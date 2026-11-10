"""Retrievers for Task 3.

R1  BM25Retriever      keyword search (rank_bm25) on the recursive chunks
R2  DenseRetriever     embeddings on fixed-size chunks
R3  DenseRetriever     embeddings on recursive chunks
R4  HybridRetriever    min-max normalised BM25 and cosine scores, weighted: w * bm25 + (1 - w) * dense
R5  RerankRetriever    R4, then the top 30 chunks are re-scored by a cross-encoder

Every retriever has search(query, n) -> list of (chunk index, score), best first.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from chunking import Chunk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.llm_client import LLMClient  # noqa: E402

CACHE = HERE / ".cache"

# qwen3-embedding was trained with an instruction on the query side only.
QUERY_INSTRUCTION = ("Instruct: Given a question about the PaderQueue message queue, "
                     "retrieve the documentation passages that answer it\nQuery: ")


# --------------------------------------------------------------------------- BM25

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._\-/][a-z0-9]+)*")
STOPWORDS = set("a an and are as at be by do does for from how i in is it of on or our the this to was what "
                "when which who why will with my we you your can should there that".split())


def bm25_tokenize(text: str) -> list[str]:
    """Keep identifiers whole AND add their parts.

    `PQ-E4663` -> pq-e4663, pq, e4663      `spool.buffer_bytes` -> spool.buffer_bytes, spool, buffer, bytes
    so an exact identifier in the question matches strongly, and a partial mention still matches.
    """
    tokens = []
    for token in TOKEN_RE.findall(text.lower()):
        if token in STOPWORDS:
            continue
        tokens.append(token)
        parts = re.split(r"[._\-/]", token)
        if len(parts) > 1:
            tokens.extend(p for p in parts if p and p not in STOPWORDS)
    return tokens


class BM25Retriever:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.bm25 = BM25Okapi([bm25_tokenize(c.text) for c in chunks])

    def scores(self, query: str) -> np.ndarray:
        return np.asarray(self.bm25.get_scores(bm25_tokenize(query)), dtype=np.float32)

    def search(self, query: str, n: int = 20) -> list[tuple[int, float]]:
        return top_n(self.scores(query), n)


# --------------------------------------------------------------------------- embeddings

class Embedder:
    """Embeds documents and queries with the gateway model; caches everything on disk (.cache/)."""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.model = llm.embedding_model
        CACHE.mkdir(exist_ok=True)
        self.query_cache_path = CACHE / f"queries_{_slug(self.model)}.json"
        self.query_cache: dict[str, list[float]] = (
            json.loads(self.query_cache_path.read_text(encoding="utf-8")) if self.query_cache_path.exists() else {})

    def embed_chunks(self, chunks: list[Chunk]) -> tuple[np.ndarray, float | None]:
        """Returns (normalised vectors, seconds it took to embed them the first time)."""
        key = hashlib.sha256(("\n\x00".join(c.text for c in chunks) + self.model).encode()).hexdigest()[:16]
        path, meta = CACHE / f"chunks_{key}.npy", CACHE / f"chunks_{key}.json"
        if path.exists():
            return np.load(path), json.loads(meta.read_text())["embed_seconds"]
        start = time.time()
        vectors = _normalise(self.llm.embed([c.text for c in chunks], batch_size=64))
        seconds = time.time() - start
        np.save(path, vectors)
        meta.write_text(json.dumps({"n": len(chunks), "embed_seconds": seconds}))
        return vectors, seconds

    def embed_queries(self, queries: list[str]) -> np.ndarray:
        missing = [q for q in dict.fromkeys(queries) if q not in self.query_cache]
        if missing:
            vectors = _normalise(self.llm.embed([QUERY_INSTRUCTION + q for q in missing], batch_size=64))
            self.query_cache.update({q: v.tolist() for q, v in zip(missing, vectors)})
            self.query_cache_path.write_text(json.dumps(self.query_cache), encoding="utf-8")
        return np.asarray([self.query_cache[q] for q in queries], dtype=np.float32)


class DenseRetriever:
    def __init__(self, chunks: list[Chunk], embedder: Embedder):
        self.chunks = chunks
        self.embedder = embedder
        self.vectors, self.embed_seconds = embedder.embed_chunks(chunks)

    def scores(self, query: str) -> np.ndarray:
        return self.vectors @ self.embedder.embed_queries([query])[0]  # unit vectors: dot = cosine

    def search(self, query: str, n: int = 20) -> list[tuple[int, float]]:
        return top_n(self.scores(query), n)


# --------------------------------------------------------------------------- hybrid + re-ranking

class HybridRetriever:
    """BM25 scores are unbounded (0..~30), cosine is ~0.2..0.8: min-max normalise each over all chunks, then mix."""

    def __init__(self, bm25: BM25Retriever, dense: DenseRetriever, weight: float):
        assert bm25.chunks is dense.chunks, "hybrid needs both retrievers on the same chunks"
        self.chunks, self.bm25, self.dense, self.weight = bm25.chunks, bm25, dense, weight

    def scores(self, query: str) -> np.ndarray:
        return self.weight * _minmax(self.bm25.scores(query)) + (1 - self.weight) * _minmax(self.dense.scores(query))

    def search(self, query: str, n: int = 20) -> list[tuple[int, float]]:
        return top_n(self.scores(query), n)


class RerankRetriever:
    """Takes the top `pool` chunks of the base retriever and orders them by a cross-encoder score.

    A cross-encoder reads query and chunk together (one forward pass per pair), so it sees word order and
    negation; a bi-encoder only compares two independently computed vectors. Too slow for 2,000+ chunks,
    fine for 30.

    The final score blends both: alpha * cross-encoder + (1 - alpha) * base score (each min-max normalised over
    the pool). alpha = 1 is pure re-ranking. We found pure re-ranking hurts identifier questions: the ms-marco
    model was trained on web search and can't tell PQ-E3441 from PQ-E4934, so it pushes forum posts with a
    similar-looking code above the right error page. Keeping part of the hybrid score keeps that exact match.
    """

    MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, base, pool: int = 30, alpha: float = 1.0, model=None):
        from sentence_transformers import CrossEncoder

        self.chunks, self.base, self.pool, self.alpha = base.chunks, base, pool, alpha
        self.model = model or CrossEncoder(self.MODEL)
        self._memo: dict[str, tuple[list[int], np.ndarray, np.ndarray]] = {}

    def candidates(self, query: str) -> tuple[list[int], np.ndarray, np.ndarray]:
        """(chunk indices, base scores, cross-encoder scores) for the pool; memoised so alpha can be tuned cheaply."""
        if query not in self._memo:
            pool = self.base.search(query, self.pool)
            idx = [i for i, _ in pool]
            ce = np.asarray(self.model.predict([(query, self.chunks[i].text) for i in idx]), dtype=np.float32)
            self._memo[query] = (idx, np.asarray([s for _, s in pool], dtype=np.float32), ce)
        return self._memo[query]

    def search(self, query: str, n: int = 20) -> list[tuple[int, float]]:
        idx, base, ce = self.candidates(query)
        final = self.alpha * _minmax(ce) + (1 - self.alpha) * _minmax(base)
        order = np.argsort(-final)
        return [(idx[j], float(final[j])) for j in order[:n]]


# --------------------------------------------------------------------------- helpers

def top_n(scores: np.ndarray, n: int) -> list[tuple[int, float]]:
    idx = np.argsort(-scores)[:n]
    return [(int(i), float(scores[i])) for i in idx]


def doc_ids(chunks: list[Chunk], ranking: list[tuple[int, float]]) -> list[str]:
    """Chunk ranking -> document ids in rank order, duplicates removed (first occurrence counts)."""
    return list(dict.fromkeys(chunks[i].doc_id for i, _ in ranking))


def _minmax(x: np.ndarray) -> np.ndarray:
    lo, hi = float(x.min()), float(x.max())
    return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)


def _normalise(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text)
