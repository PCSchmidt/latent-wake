"""Draw the write-up figures from committed results (no data or models needed).

    python scripts/make_writeup_figures.py
"""
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT = Path("docs/figures")
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#1f1f1e", "#6b6a64", "#e4e3de"
# Fixed categorical order (validated: CVD-safe adjacent pairs; low-contrast hues get direct labels).
SERIES = {"JEPA": "#2a78d6", "Kalman": "#eb6834", "Raw target": "#1baf7a",
          "TrAISformer-style": "#eda100", "LSTM autoencoder": "#e87ba4"}
MARKERS = {"JEPA": "o", "Kalman": "s", "Raw target": "^", "TrAISformer-style": "D", "LSTM autoencoder": "v"}
PREFIX = {"JEPA": "jepa", "Kalman": "kalman", "Raw target": "raw", "TrAISformer-style": "trais",
          "LSTM autoencoder": "lstmae"}
KINDS = [("loitering", "Loitering"), ("route_deviation", "Route deviation"), ("position_spoof", "Position spoof"),
         ("teleport", "Teleport"), ("ais_gap", "AIS gap")]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10, "axes.titlesize": 11,
    "axes.titleweight": "bold", "axes.titlecolor": INK, "legend.frameon": False,
})


def load_results():
    a = pd.read_csv("reports/eval-v2/results.csv")
    b = pd.read_csv("reports/eval-v2-baselines/results.csv")
    r = pd.concat([a, b[~b.method.isin(["kalman", "physics"])]])
    r = r[r.kind != "normal"].copy()
    r["group"] = r.method.str.replace(r"-s\d+$", "", regex=True)
    return r


def severity_curves(r):
    from latentwake.inject.anomalies import DEFAULT_GRID

    # Plot against the injected severity in real units. AIS gaps vary gap length and the
    # position jump across the gap; the jump is what makes a gap detectable, so average
    # over gap lengths and plot against the jump.
    axis = {
        "loitering": ("Loitering duration (minutes)", lambda p: p["duration_steps"] * 2),
        "route_deviation": ("Turn off course (degrees)", lambda p: p["turn_deg"]),
        "position_spoof": ("Spoof offset (nmi)", lambda p: p["offset_nmi"]),
        "teleport": ("Teleport distance (nmi)", lambda p: p["distance_nmi"]),
        "ais_gap": ("Position jump across the gap (nmi)", lambda p: p["jump_nmi"]),
    }
    fig, axes = plt.subplots(1, 5, figsize=(15, 3.8), sharey=True)
    for ax, (kind, title) in zip(axes, KINDS):
        label, value = axis[kind]
        x_of_level = {i: value(p) for i, p in enumerate(DEFAULT_GRID[kind])}
        xs = sorted(set(x_of_level.values()))
        pos = {v: i for i, v in enumerate(xs)}  # evenly spaced, labeled with real values
        for name, color in SERIES.items():
            sub = r[(r.group == PREFIX[name]) & (r.kind == kind)].copy()
            sub["x"] = sub.level.map(x_of_level)
            m = sub.groupby("x").auroc.mean()
            ax.plot([pos[v] for v in m.index], m.values, color=color, lw=2, marker=MARKERS[name], ms=6,
                    markeredgecolor=SURFACE, markeredgewidth=1.5, label=name)
        ax.axhline(0.5, color=MUTED, lw=1, ls=(0, (3, 3)))
        ax.set_title(title, loc="left")
        ax.set_xlabel(label)
        ax.set_xticks(range(len(xs)), [f"{v:g}" for v in xs])
        ax.set_ylim(0.4, 1.01)
    axes[0].set_ylabel("AUROC (three-seed mean)")
    axes[0].text(0.02, 0.505, "chance", color=MUTED, fontsize=8, va="bottom")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=5, bbox_to_anchor=(0.5, 1.04))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(OUT / "severity_curves.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def intervals():
    c = pd.read_csv("reports/eval-v2-baselines/posthoc/comparisons.csv")
    rows = [
        ("JEPA − Kalman, behavioral", "jepa", "kalman", "behavioral"),
        ("TrAISformer − Kalman, behavioral", "trais", "kalman", "behavioral"),
        ("TrAISformer − JEPA, behavioral", "trais", "jepa", "behavioral"),
        ("TrAISformer − JEPA, loitering", "trais", "jepa", "loitering"),
        ("TrAISformer − JEPA, route deviation", "trais", "jepa", "route_deviation"),
        ("TrAISformer − JEPA, kinematic", "trais", "jepa", "kinematic"),
        ("LSTM autoencoder − JEPA, behavioral", "lstmae", "jepa", "behavioral"),
    ]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for i, (label, a, b, kinds) in enumerate(rows):
        x = c[(c.a == a) & (c.b == b) & (c.kinds == kinds) & (c.metric == "auroc")].iloc[0]
        y = len(rows) - 1 - i
        ax.plot([x.ci_low, x.ci_high], [y, y], color=SERIES["JEPA"], lw=2, solid_capstyle="round")
        ax.plot(x.a_minus_b, y, "o", color=SERIES["JEPA"], ms=8, markeredgecolor=SURFACE, markeredgewidth=2)
        ax.text(max(x.ci_high, 0.10) + 0.006, y, f"{x.a_minus_b:+.3f}", va="center", fontsize=9, color=INK)
    ax.axvline(0, color=MUTED, lw=1)
    ax.axvline(0.10, color=MUTED, lw=1, ls=(0, (3, 3)))
    ax.text(0.102, -0.75, "pre-registered margin over Kalman", color=MUTED, fontsize=8, va="center")
    ax.set_ylim(-1.1, len(rows) - 0.5)
    ax.set_xlim(-0.11, 0.2)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows][::-1])
    ax.set_xlabel("Difference in mean AUROC, 95% vessel-level bootstrap interval")
    ax.grid(axis="y", visible=False)
    ax.set_title("Who beats whom on the test set", loc="left")
    fig.tight_layout()
    fig.savefig(OUT / "comparison_intervals.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def false_alarms_by_type():
    t = pd.read_csv("reports/eval-v2/posthoc/false_alarms_by_ais_type.csv")
    groups = {"fishing": "Fishing", "pilot vessel": "Pilot vessel", "dredging or underwater ops": "Dredge",
              "cargo": "Cargo", "tug": "Tug", "pleasure craft": "Pleasure craft"}
    t["g"] = t.name.map(groups).fillna("Everything else")
    order = list(groups.values()) + ["Everything else"]
    det = {"JEPA": [c for c in t if re.fullmatch(r"jepa-s\d", c)], "Kalman": ["kalman"],
           "Raw target": [c for c in t if re.fullmatch(r"raw-s\d", c)]}
    share = pd.DataFrame({n: t.groupby("g")[cols].sum().mean(axis=1) for n, cols in det.items()}).reindex(order)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    h, gap = 0.26, 0.02
    for j, n in enumerate(det):
        ys = [i + (j - 1) * (h + gap) for i in range(len(order))]
        ax.barh(ys, share[n] * 100, height=h, color=SERIES[n], label=n)
        for y, v in zip(ys, share[n] * 100):
            if v >= 5:
                ax.text(v + 0.8, y, f"{v:.0f}%", va="center", fontsize=8, color=INK)
    ax.set_yticks(range(len(order)), order)
    ax.invert_yaxis()
    ax.set_xlabel("Share of the detector's test false alarms (%)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right")
    ax.set_title("Which vessels raise the false alarms (AIS ship type)", loc="left")
    fig.tight_layout()
    fig.savefig(OUT / "false_alarms_by_type.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def ablations():
    rows = [("SIGReg weight 0.02", -0.004, -0.007), ("Latent size 64", -0.005, 0.029),
            ("SIGReg weight 0.3", -0.012, 0.004), ("Keep all anchored windows", -0.015, -0.006),
            ("Context 32 steps", -0.025, -0.042), ("Raw target", -0.030, 0.101),
            ("No action conditioning", -0.039, -0.048), ("SIGReg weight 0 (collapsed)", -0.107, -0.170)]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, k, title in ((axes[0], 1, "Behavioral (loitering, route deviation)"),
                         (axes[1], 2, "Kinematic (spoof, teleport, gap)")):
        for i, r in enumerate(rows):
            y = len(rows) - 1 - i
            ax.plot([0, r[k]], [y, y], color=GRID, lw=2)
            ax.plot(r[k], y, "o", color=SERIES["JEPA"], ms=7, markeredgecolor=SURFACE, markeredgewidth=1.5)
            ax.text(r[k] + (0.006 if r[k] >= 0 else -0.006), y, f"{r[k]:+.3f}", va="center",
                    ha="left" if r[k] >= 0 else "right", fontsize=8, color=INK)
        ax.axvline(0, color=MUTED, lw=1)
        ax.set_title(title, loc="left")
        ax.set_xlabel("Change in mean AUROC vs main JEPA (validation)")
        ax.grid(axis="y", visible=False)
        ax.set_xlim(-0.22, 0.14)
    axes[0].set_yticks(range(len(rows)), [r[0] for r in rows][::-1])
    fig.tight_layout()
    fig.savefig(OUT / "ablations.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    r = load_results()
    severity_curves(r)
    intervals()
    false_alarms_by_type()
    ablations()
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))
