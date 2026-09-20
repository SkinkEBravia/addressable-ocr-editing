"""Regenerate manuscript figures from the tracked result snapshot."""

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "paper" / "data" / "results.csv"
OUT = Path(__file__).resolve().parent
COL = {"V4 Flash": "#0072B2", "V4.1 Flash": "#009E73", "M3": "#D55E00"}
MODEL_KEYS = {"V4 Flash": "v4", "V4.1 Flash": "v41", "M3": "m3"}
ARMS = ["patch-find-replace", "find-replace", "find-replace-numkey", "rewrite"]
LABELS = ["local patch", "global F/R", "global + keys", "rewrite"]


def load_rows():
    with DATA.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def cmer(rows, model, arm):
    return [float(row["cmer"]) for row in rows
            if row["model"] == model and row["arm"] == arm]


def main():
    rows = load_rows()
    plt.rcParams.update({"font.family": "serif", "font.size": 9,
                         "axes.titlesize": 10, "axes.labelsize": 9,
                         "legend.fontsize": 8, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 160})
    fig, axes = plt.subplots(1, 2, figsize=(6.8, 2.8),
                             gridspec_kw={"width_ratios": [1.35, 1]})
    x = np.arange(len(ARMS)); width = .24
    for j, (label, model) in enumerate(MODEL_KEYS.items()):
        med = [float(np.median(cmer(rows, model, arm))) for arm in ARMS]
        p90 = [sorted(cmer(rows, model, arm))[int(.9 * 33)] for arm in ARMS]
        axes[0].bar(x + (j - 1) * width, med, width, label=label,
                    color=COL[label], alpha=.92)
        axes[1].bar(x + (j - 1) * width, p90, width, label=label,
                    color=COL[label], alpha=.92)
    for ax, title in zip(axes, ["Median cMER", "P90 cMER (tail)"]):
        ax.set_xticks(x); ax.set_xticklabels(LABELS, rotation=28, ha="right")
        ax.set_title(title); ax.grid(axis="y", alpha=.2); ax.set_ylim(bottom=0)
    axes[0].set_ylabel("lower is better")
    axes[1].legend(frameon=False, loc="upper left")
    fig.tight_layout(w_pad=1.3)
    fig.savefig(OUT / "interface-distributions.pdf", bbox_inches="tight")
    fig.savefig(OUT / "interface-distributions.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    arms = ["patch-find-replace", "find-replace", "find-replace-numkey",
            "find-replace-blocked", "patch-find-replace-noatt",
            "patch-find-replace-unstable", "rewrite", "rewrite-numkey"]
    labels = ["local patch", "global F/R", "global + keys", "blocked F/R",
              "patch no-attn", "unstable IDs", "rewrite", "rewrite + keys"]
    done, edited = [], []
    for arm in arms:
        subset = [row for row in rows if row["model"] == "m3" and row["arm"] == arm]
        done.append(sum(row["status"] == "done" for row in subset) / len(subset) * 100)
        edited.append(sum(float(row["edit_spans"]) > 0 for row in subset) / len(subset) * 100)
    fig, ax = plt.subplots(figsize=(6.8, 2.8)); xx = np.arange(len(labels)); w = .36
    ax.bar(xx - w / 2, done, w, label="protocol completed", color="#56B4E9")
    ax.bar(xx + w / 2, edited, w, label="effective edits", color="#D55E00")
    ax.set_ylabel("tasks (%)"); ax.set_ylim(0, 105); ax.set_xticks(xx)
    ax.set_xticklabels(labels, rotation=32, ha="right"); ax.grid(axis="y", alpha=.2)
    ax.legend(frameon=False, ncol=2, loc="upper left"); fig.tight_layout()
    fig.savefig(OUT / "m3-compliance.pdf", bbox_inches="tight")
    fig.savefig(OUT / "m3-compliance.png", dpi=300, bbox_inches="tight")


if __name__ == "__main__":
    main()
