"""Draw the Task 3 figures from the result files (no new experiments, no API calls).

    uv run --with matplotlib python task3_rag/make_figures.py

Reads results/retrieval_report.json, results/judge_*.jsonl and results/two_hop_context_check.json,
writes PNGs to results/figures/.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
OUT = RESULTS / "figures"

# Reference palette (light mode): categorical slots 1 and 2, text and surface tokens.
BLUE, ORANGE = "#2a78d6", "#eb6834"
GREY = "#b9b7b0"
TEXT, TEXT2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e4df", "#fcfcfb"
CATEGORIES = ["identifier", "paraphrase", "multi-hop", "version"]
SYSTEMS = [("R1", "R1 keywords"), ("R2", "R2 meaning, fixed chunks"), ("R3", "R3 meaning, structure chunks"),
           ("R4", "R4 hybrid"), ("R5_pure", "Re-ranker alone"), ("R5", "R5 hybrid + re-ranker")]

plt.rcParams.update({
    "font.family": "Segoe UI", "font.size": 11, "text.color": TEXT, "axes.labelcolor": TEXT2,
    "xtick.color": TEXT2, "ytick.color": TEXT2, "axes.edgecolor": GRID, "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE, "axes.titleweight": "semibold", "axes.titlesize": 13,
})


def clean(ax, grid_axis="x"):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def overall(report):
    """Horizontal grouped bars: recall@5 on all questions vs the held-out half."""
    fig, ax = plt.subplots(figsize=(9, 4.4))
    names = [label for _, label in SYSTEMS]
    allv = [report["systems"][key]["all"]["overall"]["context_recall"] for key, _ in SYSTEMS]
    hold = [report["systems"][key]["holdout"]["overall"]["context_recall"] for key, _ in SYSTEMS]
    y = range(len(names))
    h = 0.36
    ax.barh([i - h / 2 - 0.01 for i in y], allv, height=h, color=BLUE, label="all 120 answerable questions")
    ax.barh([i + h / 2 + 0.01 for i in y], hold, height=h, color=ORANGE, label="held-out half (never tuned on)")
    for i, (a, b) in enumerate(zip(allv, hold)):
        ax.text(a + 0.008, i - h / 2 - 0.01, f"{a:.3f}", va="center", fontsize=10, color=TEXT,
                fontweight="bold" if names[i].startswith("R5 hybrid") else "normal")
        ax.text(b + 0.008, i + h / 2 + 0.01, f"{b:.3f}", va="center", fontsize=9, color=TEXT2)
    ax.set_yticks(list(y), names)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.18)
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_xlabel("recall@5  (share of needed documents in the top 5 – higher is better)")
    ax.set_title("Which search method finds the right documents?", loc="left")
    ax.legend(loc="upper right", frameon=False, fontsize=9.5)
    clean(ax)
    fig.tight_layout()
    fig.savefig(OUT / "1_overall_recall.png", dpi=160)


def heatmap(report):
    """Methods × question categories, sequential blue, value printed in each cell."""
    fig, ax = plt.subplots(figsize=(9, 4.4))
    names = [label for _, label in SYSTEMS]
    grid = [[report["systems"][key]["all"]["per_category"][c]["context_recall"] for c in CATEGORIES] for key, _ in SYSTEMS]
    cmap = LinearSegmentedColormap.from_list("blues", ["#f2f6fc", "#a9c8ef", BLUE, "#1d4f8f"])
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    from matplotlib.patches import Rectangle

    for r, row in enumerate(grid):
        for c, v in enumerate(row):
            col_best = max(grid[i][c] for i in range(len(grid)))
            ax.text(c, r, f"{v:.2f}", ha="center", va="center", fontsize=11,
                    color="white" if v > 0.62 else TEXT, fontweight="bold" if v == col_best else "normal")
            if v == col_best:  # outline the best method per category
                ax.add_patch(Rectangle((c - 0.47, r - 0.44), 0.94, 0.88, fill=False, edgecolor=TEXT, linewidth=1.8))
    ax.set_xticks(range(len(CATEGORIES)), ["identifier\n(exact codes)", "paraphrase\n(reworded)",
                                           "multi-hop\n(needs 2 docs)", "version\n(old versions)"])
    ax.set_yticks(range(len(names)), names)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, len(CATEGORIES))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(names))], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    ax.set_title("Who wins which question type?  (recall@5, outlined = best)", loc="left")
    fig.tight_layout()
    fig.savefig(OUT / "2_recall_by_category.png", dpi=160)


def tuning(report):
    """Two small line charts side by side: hybrid weight and re-ranker blend (TUNE half)."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.4))
    w = sorted((float(k), v["context_recall"]) for k, v in report["weight_grid_tune"].items())
    a1.plot([x for x, _ in w], [y for _, y in w], color=BLUE, linewidth=2, marker="o", markersize=5)
    best = max(w, key=lambda t: t[1])
    a1.annotate(f"chosen: {best[0]:.1f} → {best[1]:.3f}", best, xytext=(best[0] + 0.12, best[1] - 0.06),
                fontsize=9.5, color=TEXT, arrowprops={"arrowstyle": "-", "color": TEXT2, "lw": 0.8})
    a1.set_xlabel("keyword (BM25) share in the hybrid")
    a1.set_ylabel("recall@5 (TUNE half)")
    a1.set_title("R4: how much keyword search?", loc="left", fontsize=11.5)
    b = sorted((float(k), v["context_recall"]) for k, v in report["alpha_grid_tune"].items())
    a2.plot([x for x, _ in b], [y for _, y in b], color=BLUE, linewidth=2, marker="o", markersize=5)
    best = max(b, key=lambda t: t[1])
    a2.annotate(f"chosen: {best[0]:.2f} → {best[1]:.3f}", best, xytext=(best[0] + 0.06, best[1] + 0.018),
                fontsize=9.5, color=TEXT, arrowprops={"arrowstyle": "-", "color": TEXT2, "lw": 0.8})
    a2.annotate("re-ranker alone", b[-1], xytext=(b[-1][0] - 0.2, b[-1][1] - 0.04), fontsize=9.5, color=TEXT2)
    a2.set_xlabel("re-ranker share in R5 (1.0 = re-ranker alone)")
    a2.set_title("R5: how much re-ranker?", loc="left", fontsize=11.5)
    for ax in (a1, a2):
        clean(ax, "y")
        ax.set_ylim(0.55, 0.85)
    fig.tight_layout()
    fig.savefig(OUT / "3_tuning.png", dpi=160)


def judge():
    """Correct answers per system (50 judged questions), split into multi-hop and the rest."""
    systems = [("R4", "R4 hybrid"), ("R5", "R5 hybrid + re-ranker"), ("R5_2hop", "R5 + second search")]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.2), gridspec_kw={"width_ratios": [1.15, 1]})
    totals, multihop = [], []
    for key, _ in systems:
        rows = [json.loads(line) for line in (RESULTS / f"judge_{key}.jsonl").open(encoding="utf-8")]
        totals.append(sum(r["correctness"] for r in rows) / len(rows))
        multihop.append(sum(r["correctness"] for r in rows if r["category"] == "multi-hop"))
    labels = [label for _, label in systems]
    colors = [GREY, GREY, BLUE]
    a1.barh(labels, totals, color=colors, height=0.55)
    for i, v in enumerate(totals):
        a1.text(v + 0.01, i, f"{v:.0%}", va="center", fontsize=11, fontweight="bold" if i == 2 else "normal")
    a1.set_xlim(0, 1.05)
    a1.invert_yaxis()
    a1.set_title("Answers judged correct (50 questions)", loc="left", fontsize=11.5)
    a2.barh(labels, multihop, color=colors, height=0.55)
    for i, v in enumerate(multihop):
        a2.text(v + 0.15, i, f"{v:.0f} / 10", va="center", fontsize=11, fontweight="bold" if i == 2 else "normal")
    a2.set_xlim(0, 10.5)
    a2.set_yticks([])
    a2.invert_yaxis()
    a2.set_title("Multi-hop questions correct", loc="left", fontsize=11.5)
    for ax in (a1, a2):
        clean(ax)
    fig.tight_layout()
    fig.savefig(OUT / "4_answers_correct.png", dpi=160)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report = json.loads((RESULTS / "retrieval_report.json").read_text(encoding="utf-8"))
    overall(report)
    heatmap(report)
    tuning(report)
    judge()
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
