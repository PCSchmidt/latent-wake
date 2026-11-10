"""Pick each learned baseline's setting from a validation grid (rule fixed in DECISIONS.md).

Grid runs are evaluated on the validation anomaly set under names
KIND_TAG (for example iforest_n100_stats). For each KIND the winner is the
tag with the highest mean AUROC over the five anomaly kinds, each kind
weighted equally; ties go to the tag listed first in GRID (the smaller one).

Usage (all on validation; the test set is not touched):
    python -m latentwake.select_baselines grid                 # train every setting, seed 0
    python -m latentwake.select_baselines evaluate             # score them on the validation anomaly set
    python -m latentwake.select_baselines select --train-seeds # pick winners, train seeds 1 and 2
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd

# Tag -> train_baseline flags. Smaller settings first (tie-break).
GRID: dict[str, dict[str, list[str]]] = {
    "iforest": {
        "n100_stats": ["--n-estimators", "100", "--features", "stats"],
        "n100_diffs": ["--n-estimators", "100", "--features", "stats+diffs"],
        "n300_stats": ["--n-estimators", "300", "--features", "stats"],
        "n300_diffs": ["--n-estimators", "300", "--features", "stats+diffs"],
    },
    "lstm_ae": {"h64": ["--hidden", "64"], "h128": ["--hidden", "128"]},
    "traisformer": {"d128": ["--d-model", "128"], "d256": ["--d-model", "256"]},
}


def select(results: pd.DataFrame) -> pd.DataFrame:
    anom = results[results.kind != "normal"]
    per_kind = anom.groupby(["method", "kind"]).auroc.mean().unstack()
    score = per_kind.mean(axis=1)
    rows = []
    for kind, tags in GRID.items():
        cands = [(t, score.get(f"{kind}_{t}")) for t in tags]
        cands = [(t, s) for t, s in cands if s is not None and pd.notna(s)]
        if not cands:
            continue
        best = max(cands, key=lambda ts: ts[1])  # max keeps the first of equal values
        for t, s in cands:
            rows.append({"kind": kind, "tag": t, "mean_auroc": round(float(s), 4), "chosen": t == best[0],
                         "flags": " ".join(GRID[kind][t])})
    return pd.DataFrame(rows)


SHORT = {"iforest": "iforest", "lstm_ae": "lstmae", "traisformer": "trais"}
GRID_DIR = Path("runs/grid")


def run_grid(processed: Path, grid_dir: Path = GRID_DIR) -> None:
    from latentwake.train_baseline import main as train

    for kind, tags in GRID.items():
        for tag, flags in tags.items():
            out = grid_dir / f"{kind}_{tag}"
            if (out / "baseline.pt").exists():
                print(f"{out} exists; skipping", flush=True)
                continue
            print(f"--- {kind} {tag}", flush=True)
            train(["--kind", kind, "--processed", str(processed), "--out", str(out), "--seed", "0", *flags])


def evaluate_grid(valset: Path, processed: Path, out: Path, grid_dir: Path = GRID_DIR) -> None:
    from latentwake.evaluate import run

    models = {d.name: d / "baseline.pt" for d in sorted(grid_dir.iterdir()) if (d / "baseline.pt").exists()}
    run(valset, processed, models, out, calibration="tail")
    print((out / "summary.md").read_text().split("## AUROC by cell")[0])


def train_seeds(table: pd.DataFrame, processed: Path, grid_dir: Path = GRID_DIR, runs: Path = Path("runs")) -> None:
    """Copy each winner's seed-0 grid run to runs/SHORT-s0 and train seeds 1 and 2 with the same flags."""
    from latentwake.train_baseline import main as train

    for _, r in table[table.chosen].iterrows():
        kind, tag, flags = r["kind"], r["tag"], r["flags"].split()  # r.flags is pandas' own attribute
        short = SHORT[kind]
        s0 = runs / f"{short}-s0"
        if not s0.exists():
            shutil.copytree(grid_dir / f"{kind}_{tag}", s0)
        for seed in (1, 2):
            out = runs / f"{short}-s{seed}"
            if (out / "baseline.pt").exists():
                continue
            print(f"--- {short} seed {seed} ({' '.join(flags)})", flush=True)
            train(["--kind", kind, "--processed", str(processed), "--out", str(out), "--seed", str(seed), *flags])


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Choose learned-baseline settings on validation.")
    p.add_argument("--processed", type=Path, default=Path("data/processed/chesapeake"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("grid")
    e = sub.add_parser("evaluate")
    e.add_argument("--valset", type=Path, default=Path("data/testsets/chesapeake-val-v2"))
    e.add_argument("--out", type=Path, default=Path("reports/baseline-grid"))
    s = sub.add_parser("select")
    s.add_argument("results", type=Path, nargs="?", default=Path("reports/baseline-grid/results.csv"))
    s.add_argument("--train-seeds", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "grid":
        run_grid(a.processed)
    elif a.cmd == "evaluate":
        evaluate_grid(a.valset, a.processed, a.out)
    else:
        table = select(pd.read_csv(a.results))
        print(table.to_markdown(index=False), flush=True)
        if a.train_seeds:
            train_seeds(table, a.processed)


if __name__ == "__main__":
    main()
