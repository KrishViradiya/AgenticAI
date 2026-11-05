"""Retrieval check: does search() find the right style guide document?

Each query is phrased the way the agent would ask (without the answer in it), and names the ACTIVE
document that holds the rule. We report hit@k (the document is among the top k) and whether the
ACTIVE version is ranked above its DEPRECATED predecessor.

    uv run python task2_own_agent/test_rag.py [-k 4]
"""

from __future__ import annotations

import argparse

from rag import StyleGuideIndex

# (query, expected ACTIVE document, deprecated predecessor or None)
CASES = [
    ("What format must the page title have?", "SG-02", None),
    ("Which language attribute should the html element have?", "SG-02", None),
    ("What are the day mode background and text colors?", "SG-11", "SG-10"),
    ("What are the night mode background and text colors?", "SG-13", "SG-12"),
    ("Which accent color must be used and how is it defined?", "SG-14", None),
    ("How is the theme switched between day and night mode?", "SG-20", None),
    ("How is the user's theme choice remembered between visits?", "SG-21", "SG-19"),
    ("What does the theme toggle button look like?", "SG-22", None),
    ("How must a member card be structured?", "SG-30", None),
    ("What is the hot take badge?", "SG-31", None),
    ("What are the rules for member photos?", "SG-33", None),
    ("What text goes into the footer?", "SG-40", "SG-39"),
    ("At which width does the mobile layout start?", "SG-50", "SG-49"),
    ("Which unit must font sizes use?", "SG-52", None),
    ("Which fonts should the page use?", "SG-51", None),
    ("Which sections must the page have and what are their ids?", "SG-35", None),
    ("How many h1 headings may the page have?", "SG-36", None),
    ("What are the rules for animations and transitions?", "SG-55", None),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", type=int, default=4)
    args = parser.parse_args()

    index = StyleGuideIndex.build()
    hits, rr, order_ok, order_total = 0, 0.0, 0, 0
    for query, expected, old in CASES:
        ranked = [c.doc_id for c in index.search(query, k=len(index.chunks))]
        rank = ranked.index(expected) + 1
        hit = rank <= args.k
        hits += hit
        rr += 1 / rank
        note = ""
        if old:
            order_total += 1
            if rank < ranked.index(old) + 1:
                order_ok += 1
            else:
                note = f"   <-- deprecated {old} ranked higher"
        top = " ".join(ranked[: args.k])
        print(f"{'OK  ' if hit else 'MISS'} rank {rank:>2}  {expected}  [{top}]  {query}{note}")

    n = len(CASES)
    print(f"\nhit@{args.k}: {hits}/{n} = {hits / n:.0%}   MRR: {rr / n:.2f}   "
          f"active above deprecated: {order_ok}/{order_total}")


if __name__ == "__main__":
    main()
