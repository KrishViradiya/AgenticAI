"""Chunking for Task 3: fixed-size (R2) and recursive (R3, also used by R1/R4/R5).

Every chunk starts with a one-line header built from the document metadata, e.g.
    [config | ingress.interval_s (PaderQueue 2.x) | version 2.x]
so that the type, title and version are searchable (BM25 and embeddings) and visible to the generator.
The chunk size is measured in tokens (tiktoken cl100k_base) and applies to the body; the header comes on top.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import tiktoken

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "data" / "corpus.jsonl"
ENC = tiktoken.get_encoding("cl100k_base")


def n_tokens(text: str) -> int:
    return len(ENC.encode(text))


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_type: str
    title: str
    version: str
    text: str  # header + body: what is embedded, indexed and shown to the generator


def load_corpus(path: Path = CORPUS) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def header(doc: dict) -> str:
    version = doc.get("version") or "-"
    return f"[{doc['type']} | {doc['title']} | version {version}]"


def _make(doc: dict, bodies: list[str]) -> list[Chunk]:
    head = header(doc)
    return [Chunk(f"{doc['doc_id']}#{i}", doc["doc_id"], doc["type"], doc["title"], doc.get("version", ""),
                  f"{head}\n{body.strip()}") for i, body in enumerate(bodies) if body.strip()]


# --------------------------------------------------------------------------- R2: fixed-size

def fixed_chunks(doc: dict, size: int, overlap: int) -> list[Chunk]:
    """Cut the body every `size` tokens, ignoring its structure; consecutive windows share `overlap` tokens."""
    tokens = ENC.encode(doc["text"])
    step = max(1, size - overlap)
    bodies = []
    for start in range(0, len(tokens), step):
        bodies.append(ENC.decode(tokens[start:start + size]))
        if start + size >= len(tokens):
            break
    return _make(doc, bodies)


# --------------------------------------------------------------------------- R3: recursive

# Separators from coarse to fine: markdown headings, paragraphs, lines, sentences.
SEPARATORS = [
    (re.compile(r"(?m)^(?=#{1,6} )"), "\n"),  # split before a heading, the heading stays with its section
    (re.compile(r"\n\s*\n"), "\n\n"),
    (re.compile(r"\n"), "\n"),
    (re.compile(r"(?<=[.!?])\s+"), " "),
]


def _split(text: str, size: int, level: int = 0) -> list[tuple[str, str]]:
    """Return (piece, joiner) pairs, each piece <= size tokens (except unsplittable ones, cut by tokens)."""
    if n_tokens(text) <= size:
        return [(text, "\n")]
    for depth in range(level, len(SEPARATORS)):
        pattern, joiner = SEPARATORS[depth]
        parts = [p for p in pattern.split(text) if p.strip()]
        if len(parts) > 1:
            pieces = []
            for part in parts:
                pieces.extend(_split(part, size, depth + 1) if n_tokens(part) > size else [(part, joiner)])
            return pieces
    tokens = ENC.encode(text)  # last resort: a single sentence longer than the budget
    return [(ENC.decode(tokens[i:i + size]), " ") for i in range(0, len(tokens), size)]


def recursive_chunks(doc: dict, size: int) -> list[Chunk]:
    """Split at headings, then paragraphs, lines, sentences; then merge neighbours up to `size` tokens."""
    bodies, current = [], ""
    for piece, joiner in _split(doc["text"], size):
        candidate = f"{current}{joiner}{piece}" if current else piece
        if current and n_tokens(candidate) > size:
            bodies.append(current)
            current = piece
        else:
            current = candidate
    if current:
        bodies.append(current)
    return _make(doc, bodies)


# --------------------------------------------------------------------------- all documents

def chunk_corpus(docs: list[dict], method: str, size: int, overlap: int = 0) -> list[Chunk]:
    chunks = []
    for doc in docs:
        if method == "fixed":
            chunks.extend(fixed_chunks(doc, size, overlap))
        elif method == "recursive":
            chunks.extend(recursive_chunks(doc, size))
        else:
            raise ValueError(method)
    return chunks


if __name__ == "__main__":
    docs = load_corpus()
    for method, size, overlap in [("fixed", 128, 32), ("recursive", 64, 0), ("recursive", 128, 0), ("recursive", 256, 0)]:
        chunks = chunk_corpus(docs, method, size, overlap)
        lengths = [n_tokens(c.text) for c in chunks]
        print(f"{method:<10} size={size:<4} overlap={overlap:<3} chunks={len(chunks):<5} "
              f"avg tokens={sum(lengths) / len(lengths):.0f} max={max(lengths)}")
