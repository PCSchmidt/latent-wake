"""Score a frozen test set with every method and report detection per anomaly cell.

Usage:
    python -m latentwake.evaluate --testset data/testsets/chesapeake-test-v1 \\
        --processed data/processed/chesapeake --out reports/eval-v1 \\
        --model jepa=runs/jepa-s0/best.pt --model raw=runs/raw-s0/best.pt

Methods always included: the physics residual and the Kalman filter. Each
--model NAME=CHECKPOINT adds a learned model, calibrated on the validation split.

Rules baked in:
  * Behavioral kinds (route deviation, loitering) are compared only against
    normal windows from moving vessels. See inject/build.py for why.
  * AUPRC is reported next to AUROC: anomalies are rare in practice and AUROC
    alone flatters.

Writes results.csv (long format), summary.md (AUROC table per cell), and
scores.npz (window scores per method, for plots).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from latentwake.data.features import Normalizer
from latentwake.data.preprocess import load_split
from latentwake.inject.anomalies import NEEDS_MOTION
from latentwake.inject.build import MOVING_SOG_KN, TestSet, load_test_set
from latentwake.models.baselines import kalman_nis, physics_residual, window_score


def cell_metrics(cells: pd.DataFrame, scores: dict[str, np.ndarray]) -> pd.DataFrame:
    """One row per (method, kind, level) with AUROC and AUPRC against the right normals."""
    normal = cells.kind.to_numpy() == "normal"
    moving_normal = normal & (cells.source_mean_sog.to_numpy() >= MOVING_SOG_KN)
    rows = []
    anomalous = cells[~normal]
    for (kind, level), g in anomalous.groupby(["kind", "level"], sort=True):
        ref = moving_normal if kind in NEEDS_MOTION else normal
        idx_a = g.index.to_numpy()
        idx_n = np.flatnonzero(ref)
        y = np.r_[np.zeros(len(idx_n)), np.ones(len(idx_a))]
        for method, s in scores.items():
            sc = np.r_[s[idx_n], s[idx_a]]
            rows.append(
                {
                    "method": method,
                    "kind": kind,
                    "level": int(level),
                    "params": g.params.iat[0],
                    "n_anomalous": len(idx_a),
                    "n_normal": len(idx_n),
                    "auroc": roc_auc_score(y, sc),
                    "auprc": average_precision_score(y, sc),
                }
            )
    return pd.DataFrame(rows)


def baseline_scores(ts: TestSet) -> dict[str, np.ndarray]:
    return {
        "physics": window_score(physics_residual(ts.X)),
        "kalman": window_score(kalman_nis(ts.X)),
    }


def model_scores(name_to_ckpt: dict[str, Path], ts: TestSet, processed: Path) -> dict[str, np.ndarray]:
    import torch

    from latentwake.score import Calibrator, transition_errors
    from latentwake.train import load_model

    device = "cuda" if torch.cuda.is_available() else "cpu"
    windows = pd.read_parquet(Path(processed) / "windows.parquet").set_index("window_id")
    vclass_test = windows.loc[ts.cells.source_window.to_numpy(), "vessel_class"].to_numpy()
    Xn = Normalizer.load(Path(processed) / "normalizer.json").transform(ts.X)
    Xv, meta_v = load_split(processed, "val")
    out = {}
    for name, ckpt in name_to_ckpt.items():
        model = load_model(Path(ckpt), device=device)
        cal = Calibrator.fit(transition_errors(model, Xv, meta_v.vessel_class.to_numpy()),
                             meta_v.vessel_class.to_numpy())
        z = cal.transform(transition_errors(model, Xn, vclass_test), vclass_test)
        out[name] = z.max(axis=1)
    return out


def summarize(results: pd.DataFrame) -> str:
    """Markdown: AUROC per cell (rows) by method (columns), then a per-kind mean."""
    piv = results.pivot_table(index=["kind", "level", "params"], columns="method", values="auroc").round(3)
    kind = results.groupby(["kind", "method"]).auroc.mean().unstack().round(3)
    return (
        "## AUROC by kind (mean over severity levels)\n\n" + kind.to_markdown()
        + "\n\n## AUROC by cell\n\n" + piv.reset_index().drop(columns="params").to_markdown(index=False)
        + "\n"
    )


def run(testset: Path, processed: Path, models: dict[str, Path], out: Path) -> pd.DataFrame:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ts = load_test_set(testset)
    scores = baseline_scores(ts)
    scores.update(model_scores(models, ts, processed) if models else {})
    results = cell_metrics(ts.cells, scores)
    results.to_csv(out / "results.csv", index=False)
    (out / "summary.md").write_text(summarize(results))
    np.savez_compressed(out / "scores.npz", **scores)
    return results


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Evaluate detectors on a frozen test set.")
    p.add_argument("--testset", type=Path, required=True)
    p.add_argument("--processed", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model", action="append", default=[], help="NAME=CHECKPOINT; repeatable")
    a = p.parse_args(argv)
    models = dict(m.split("=", 1) for m in a.model)
    run(a.testset, a.processed, {k: Path(v) for k, v in models.items()}, a.out)
    print((a.out / "summary.md").read_text())


if __name__ == "__main__":
    main()
