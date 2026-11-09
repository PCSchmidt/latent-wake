"""Score a frozen test set with every method and report detection per anomaly cell.

Usage:
    python -m latentwake.evaluate --testset data/testsets/chesapeake-test-v1 \\
        --processed data/processed/chesapeake --out reports/eval-v1 \\
        --model jepa=runs/jepa-s0/best.pt --model raw=runs/raw-s0/best.pt

Methods always included: the physics residual and the Kalman filter. Each
--model NAME=CHECKPOINT adds a learned model, calibrated on the validation split.
--fuse-with-kalman PREFIX adds the combined detector (see model_scores).

Rules baked in:
  * Behavioral kinds (route deviation, loitering) are compared only against
    normal windows from moving vessels. See inject/build.py for why.
  * AUPRC is reported next to AUROC: anomalies are rare in practice and AUROC
    alone flatters.

Operating point: each method's alert threshold is set on validation windows
(no injected anomalies) so that a fraction alert_fpr of them would alert
(default 1%). At that threshold the results report, per method, the false-alarm
rate on the test set's normal windows (a row with kind "normal",
fpr_at_budget) and, per anomaly cell, the share detected (detect_at_budget).
Thresholds never see the test set.

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
from latentwake.score import Calibrator


def cell_metrics(
    cells: pd.DataFrame, scores: dict[str, np.ndarray], thresholds: dict[str, float] | None = None
) -> pd.DataFrame:
    """One row per (method, kind, level) with AUROC and AUPRC against the right normals.

    With thresholds, adds detect_at_budget per cell and one row per method with
    kind "normal" holding the test false-alarm rate (fpr_at_budget).
    """
    thresholds = thresholds or {}
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
                    "detect_at_budget": float(np.mean(s[idx_a] > thresholds[method])) if method in thresholds else np.nan,
                }
            )
    for method, thr in thresholds.items():
        rows.append(
            {
                "method": method, "kind": "normal", "level": -1, "params": "{}",
                "n_anomalous": 0, "n_normal": int(normal.sum()),
                "fpr_at_budget": float(np.mean(scores[method][normal] > thr)),
                # Reported, not gated: most normals are anchored ships, which rarely
                # alert, so the overall rate can flatter vessels under way.
                "fpr_at_budget_moving": float(np.mean(scores[method][moving_normal] > thr))
                if moving_normal.any() else np.nan,
            }
        )
    return pd.DataFrame(rows)


def baseline_scores(X: np.ndarray) -> dict[str, np.ndarray]:
    """Window scores of the non-learned baselines for unnormalized windows X."""
    return {
        "physics": window_score(physics_residual(X)),
        "kalman": window_score(kalman_nis(X)),
    }


def _window_z(val_scores, val_vclass, test_scores, test_vclass) -> np.ndarray:
    """Robust z of window scores against validation windows of the same vessel class."""
    cal = Calibrator.fit(np.asarray(val_scores)[:, None], val_vclass)
    return cal.transform(np.asarray(test_scores)[:, None], test_vclass)[:, 0]


def model_scores(
    name_to_ckpt: dict[str, Path],
    ts: TestSet,
    processed: Path,
    fuse_with_kalman: str | None = None,
    kalman_val: np.ndarray | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Calibrated window scores for each model (test, val), plus fused detectors if requested.

    Fusion rule (fixed before any real data; nothing in it is fit to a test set):
    calibrate each detector's *window* score per vessel class on validation
    windows (median and MAD), then take the larger of the JEPA's and Kalman's
    z per window. Calibrating at the window level puts both on the same null
    scale even though one takes a max over 63 steps and the other over 7
    transitions. A model named PREFIX or PREFIX-sN, where PREFIX is
    fuse_with_kalman, yields a fused detector named fused or fused-sN.
    """
    import torch

    from latentwake.score import transition_errors
    from latentwake.train import load_model

    device = "cuda" if torch.cuda.is_available() else "cpu"
    windows = pd.read_parquet(Path(processed) / "windows.parquet").set_index("window_id")
    vclass_test = windows.loc[ts.cells.source_window.to_numpy(), "vessel_class"].to_numpy()
    Xn = Normalizer.load(Path(processed) / "normalizer.json").transform(ts.X)
    Xv, meta_v = load_split(processed, "val")
    vclass_val = meta_v.vessel_class.to_numpy()

    kz_test = kz_val = None
    if fuse_with_kalman:
        if kalman_val is None:
            kalman_val = window_score(kalman_nis(load_split(processed, "val", normalized=False)[0]))
        kalman_test = window_score(kalman_nis(ts.X))
        kz_test = _window_z(kalman_val, vclass_val, kalman_test, vclass_test)
        kz_val = _window_z(kalman_val, vclass_val, kalman_val, vclass_val)

    test, val = {}, {}
    for name, ckpt in name_to_ckpt.items():
        model = load_model(Path(ckpt), device=device)
        e_val = transition_errors(model, Xv, vclass_val)
        e_test = transition_errors(model, Xn, vclass_test)
        cal = Calibrator.fit(e_val, vclass_val)
        test[name] = cal.transform(e_test, vclass_test).max(axis=1)
        val[name] = cal.transform(e_val, vclass_val).max(axis=1)
        if kz_test is not None and (name == fuse_with_kalman or name.startswith(fuse_with_kalman + "-s")):
            fused = "fused" + name[len(fuse_with_kalman):]
            test[fused] = np.maximum(_window_z(val[name], vclass_val, test[name], vclass_test), kz_test)
            val[fused] = np.maximum(_window_z(val[name], vclass_val, val[name], vclass_val), kz_val)
    if fuse_with_kalman and not any(k.startswith("fused") for k in test):
        raise ValueError(f"fuse_with_kalman={fuse_with_kalman!r} matched no model name")
    return test, val


def alert_thresholds(val_scores: dict[str, np.ndarray], alert_fpr: float) -> dict[str, float]:
    """Per-method threshold at which a fraction alert_fpr of validation windows would alert."""
    return {m: float(np.quantile(v, 1.0 - alert_fpr)) for m, v in val_scores.items()}


def summarize(results: pd.DataFrame) -> str:
    """Markdown: AUROC per cell (rows) by method (columns), then a per-kind mean."""
    anom = results[results.kind != "normal"]
    piv = anom.pivot_table(index=["kind", "level", "params"], columns="method", values="auroc").round(3)
    kind = anom.groupby(["kind", "method"]).auroc.mean().unstack().round(3)
    text = (
        "## AUROC by kind (mean over severity levels)\n\n" + kind.to_markdown()
        + "\n\n## AUROC by cell\n\n" + piv.reset_index().drop(columns="params").to_markdown(index=False)
        + "\n"
    )
    if "detect_at_budget" in anom and anom.detect_at_budget.notna().any():
        det = anom.groupby(["kind", "method"]).detect_at_budget.mean().unstack().round(3)
        normals = results[results.kind == "normal"].set_index("method")
        cols = [c for c in ("fpr_at_budget", "fpr_at_budget_moving") if c in normals]
        fpr = normals[cols].round(4).rename(columns={"fpr_at_budget": "all normals", "fpr_at_budget_moving": "moving only"})
        text += (
            "\n## Operating point (threshold from validation)\n\n"
            + "False-alarm rate:\n\n" + fpr.T.to_markdown()
            + "\n\nShare detected, by kind (mean over severity levels):\n\n" + det.to_markdown() + "\n"
        )
    return text


def run(
    testset: Path,
    processed: Path,
    models: dict[str, Path],
    out: Path,
    fuse_with_kalman: str | None = None,
    alert_fpr: float = 0.01,
) -> pd.DataFrame:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ts = load_test_set(testset)
    scores = baseline_scores(ts.X)
    val_scores = baseline_scores(load_split(processed, "val", normalized=False)[0])
    if models:
        t, v = model_scores(models, ts, processed, fuse_with_kalman, kalman_val=val_scores["kalman"])
        scores.update(t)
        val_scores.update(v)
    results = cell_metrics(ts.cells, scores, alert_thresholds(val_scores, alert_fpr))
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
    p.add_argument("--fuse-with-kalman", default=None, metavar="PREFIX",
                   help="also score max(model z, Kalman z) for models named PREFIX or PREFIX-sN")
    p.add_argument("--alert-fpr", type=float, default=0.01, help="validation false-alarm budget for thresholds")
    a = p.parse_args(argv)
    models = dict(m.split("=", 1) for m in a.model)
    run(a.testset, a.processed, {k: Path(v) for k, v in models.items()}, a.out, a.fuse_with_kalman, a.alert_fpr)
    print((a.out / "summary.md").read_text())


if __name__ == "__main__":
    main()
