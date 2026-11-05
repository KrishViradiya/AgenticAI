"""Retrieval over the UPB Agentic SE Web Style Guide.

Pipeline:
    1. load    – read every style_guide/SG-*.md file, parse id, title, status, category
    2. chunk   – split each document at its "## " sections; long sections are split at blank lines.
                 Every chunk starts with a short header (id, title, status), so the model always
                 knows where a rule comes from and whether it is DEPRECATED.
    3. embed   – embed all chunks with the gateway embedding model, cache the vectors on disk
    4. search  – embed the query, cosine similarity against all chunks, return the top k

Usage from Python:
    from rag import StyleGuideIndex
    index = StyleGuideIndex.build()
    for chunk in index.search("night mode colors", k=4):
        print(chunk.doc_id, chunk.score)
    text = index.format_results(index.search("footer text", k=4))   # ≤ 1,000 tokens

Command line (quick manual test):
    uv run python task2_own_agent/rag.py "night mode colors" -k 4
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.llm_client import LLMClient, count_tokens  # noqa: E402

STYLE_GUIDE_DIR = Path(__file__).resolve().parent / "style_guide"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"

MAX_CHUNK_TOKENS = 250          # a single chunk never gets larger than this
OBSERVATION_TOKEN_LIMIT = 1000  # lab rule: one search observation ≤ 1,000 tokens of style guide text

# qwen3-embedding is trained with an instruction in front of the query (not in front of the documents).
QUERY_INSTRUCTION = "Instruct: Given a question about building a website, retrieve the style guide rule that answers it\nQuery: "


@dataclass
class Chunk:
    doc_id: str        # e.g. "SG-13"
    title: str         # e.g. "Night mode palette (version 2)"
    status: str        # e.g. "ACTIVE (version 2)" or "DEPRECATED – replaced by SG-13"
    section: str       # "## ..." heading of this part, "" for the intro part
    text: str          # the chunk text as it is embedded and shown to the model
    score: float = 0.0 # cosine similarity, set by search()

    @property
    def deprecated(self) -> bool:
        return self.status.upper().startswith("DEPRECATED")


# --------------------------------------------------------------------- loading + chunking

HEADER_RE = re.compile(r"^#\s+(SG-\d+):\s*(.+)$", re.M)
STATUS_RE = re.compile(r"^Status:\s*(.+)$", re.M)
CATEGORY_RE = re.compile(r"^Category:\s*(.+)$", re.M)


def load_documents(directory: Path = STYLE_GUIDE_DIR) -> list[dict]:
    docs = []
    for path in sorted(directory.glob("SG-*.md")):
        raw = path.read_text(encoding="utf-8")
        header = HEADER_RE.search(raw)
        status = STATUS_RE.search(raw)
        category = CATEGORY_RE.search(raw)
        # The body is everything after the "Category:" line (or after the title if it is missing).
        body_start = (category or status or header).end() if (category or status or header) else 0
        docs.append({
            "doc_id": header.group(1) if header else path.stem.split("_")[0],
            "title": header.group(2).strip() if header else path.stem,
            "status": status.group(1).strip() if status else "UNKNOWN",
            "category": category.group(1).strip() if category else "",
            "body": raw[body_start:].strip(),
        })
    return docs


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split a document body at '## ' headings. Returns (heading, text) pairs."""
    parts = re.split(r"^(## .+)$", body, flags=re.M)
    sections = [("", parts[0].strip())] if parts[0].strip() else []
    for i in range(1, len(parts), 2):
        sections.append((parts[i][3:].strip(), parts[i + 1].strip()))
    return sections


def _split_long(text: str, budget: int) -> list[str]:
    """Split text at blank lines into pieces of at most `budget` tokens (paragraphs are kept whole)."""
    pieces, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        candidate = f"{current}\n\n{para}".strip()
        if current and count_tokens(candidate) > budget:
            pieces.append(current)
            current = para
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def chunk_documents(docs: list[dict], max_tokens: int = MAX_CHUNK_TOKENS) -> list[Chunk]:
    chunks = []
    for doc in docs:
        header = f"[{doc['doc_id']}] {doc['title']} | Status: {doc['status']}"
        for heading, text in _split_sections(doc["body"]) or [("", "")]:
            prefix = header + (f" | Section: {heading}" if heading else "")
            budget = max_tokens - count_tokens(prefix) - 2
            for piece in _split_long(text, budget):
                chunks.append(Chunk(doc["doc_id"], doc["title"], doc["status"], heading, f"{prefix}\n{piece}"))
    return chunks


# --------------------------------------------------------------------- index

class StyleGuideIndex:
    def __init__(self, chunks: list[Chunk], vectors: np.ndarray, llm: LLMClient):
        self.chunks = chunks
        self.vectors = vectors   # shape (n_chunks, dim), rows are L2-normalised
        self.llm = llm

    @classmethod
    def build(cls, llm: LLMClient | None = None, max_tokens: int = MAX_CHUNK_TOKENS) -> "StyleGuideIndex":
        llm = llm or LLMClient(log_path=REPO_ROOT / "task2_own_agent" / "logs" / "rag_index.jsonl")
        chunks = chunk_documents(load_documents(), max_tokens)
        texts = [c.text for c in chunks]

        # Cache: the key depends on the chunk texts and the model, so a change in either re-embeds.
        key = hashlib.sha256(("\n\x00".join(texts) + str(llm.embedding_model)).encode("utf-8")).hexdigest()[:16]
        cache_file = CACHE_DIR / f"style_guide_{key}.npy"
        if cache_file.exists():
            vectors = np.load(cache_file)
        else:
            vectors = _normalise(llm.embed(texts))
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            np.save(cache_file, vectors)
        return cls(chunks, vectors, llm)

    def search(self, query: str, k: int = 4) -> list[Chunk]:
        """Return the k chunks most similar to `query` (cosine similarity), best first."""
        q = _normalise(self.llm.embed([QUERY_INSTRUCTION + query]))[0]
        scores = self.vectors @ q          # rows are normalised, so the dot product is the cosine
        best = np.argsort(-scores)[:k]
        results = []
        for i in best:
            c = self.chunks[i]
            results.append(Chunk(c.doc_id, c.title, c.status, c.section, c.text, float(scores[i])))
        return results

    @staticmethod
    def format_results(chunks: list[Chunk], max_tokens: int = OBSERVATION_TOKEN_LIMIT) -> str:
        """Join chunks into one observation of at most `max_tokens` tokens of style guide text.

        Chunks are added best first; a chunk that would exceed the budget is left out (never cut
        in half, a half rule is worse than none).
        """
        parts, used = [], 0
        for c in chunks:
            n = count_tokens(c.text)
            if used + n > max_tokens:
                continue
            parts.append(c.text)
            used += n
        return "\n\n---\n\n".join(parts) if parts else "(no style guide text fits into the budget)"


def _normalise(m: np.ndarray) -> np.ndarray:
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-12, None)


# Module-level helper with the signature from the lab sheet: search(query, k)
_default_index: StyleGuideIndex | None = None


def search(query: str, k: int = 4) -> list[Chunk]:
    global _default_index
    if _default_index is None:
        _default_index = StyleGuideIndex.build()
    return _default_index.search(query, k)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search the style guide.")
    parser.add_argument("query")
    parser.add_argument("-k", type=int, default=4)
    args = parser.parse_args()

    index = StyleGuideIndex.build()
    print(f"{len(index.chunks)} chunks from {len({c.doc_id for c in index.chunks})} documents\n")
    results = index.search(args.query, args.k)
    for c in results:
        flag = "  (DEPRECATED)" if c.deprecated else ""
        print(f"{c.score:.3f}  {c.doc_id}  {c.title}{flag}")
    observation = index.format_results(results)
    print(f"\nObservation: {count_tokens(observation)} tokens (limit {OBSERVATION_TOKEN_LIMIT})")
