"""Score a frozen test set with every method and report detection per anomaly cell.

Usage:
    python -m latentwake.evaluate --testset data/testsets/chesapeake-test-v2 \\
        --processed data/processed/chesapeake --out reports/eval-v2 \\
        --model jepa=runs/jepa-s0/best.pt --model raw=runs/raw-s0/best.pt

Methods always included: the physics residual and the Kalman filter. Each
--model NAME=CHECKPOINT adds a learned model, calibrated on the validation split.
--fuse-with-kalman PREFIX adds the combined detector (see model_scores).

Rules baked in:
  * Behavioral kinds (route deviation, loitering) are compared only against
    normal windows from moving transit-class vessels, the population they are
    injected into (contract v2). See inject/build.py for why.
  * Every detector is calibrated per stratum, vessel class x under way.
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

from latentwake.data.features import FEATURES, Normalizer
from latentwake.data.preprocess import load_cells, load_split
from latentwake.inject.anomalies import NEEDS_MOTION
from latentwake.inject.build import MOVING_SOG_KN, TRANSIT_CLASSES, TestSet, load_test_set
from latentwake.models.baselines import kalman_nis, physics_residual, window_score
from latentwake.score import Calibrator, TailCalibrator


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
    # Contract v2: behavioral kinds are injected only into moving transit-class
    # windows, so they are compared only with normals from that population.
    # Test sets built before v2 have no vessel class column and keep v1 behavior.
    if "source_vessel_class" in cells:
        behavioral_ref = moving_normal & np.isin(cells.source_vessel_class.to_numpy(), TRANSIT_CLASSES)
    else:
        behavioral_ref = moving_normal
    rows = []
    anomalous = cells[~normal]
    for (kind, level), g in anomalous.groupby(["kind", "level"], sort=True):
        ref = behavioral_ref if kind in NEEDS_MOTION else normal
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


UNDERWAY_SOG_KN = 1.0
_SOG = FEATURES.index("sog_kn")


def strata(vclass: np.ndarray, X_raw: np.ndarray) -> np.ndarray:
    """Calibration stratum per window: vessel class x under way (contract v2).

    Under way means the window's mean reported speed is at least 1 kn, read
    from the observed (unnormalized) window, as a deployed system would. A
    tanker at anchor and a tanker in the channel have different error scales;
    pooling them inflates z-scores for the moving ones.
    """
    underway = np.asarray(X_raw)[..., _SOG].mean(axis=1) >= UNDERWAY_SOG_KN
    return np.asarray(vclass, dtype=np.int64) * 2 + underway.astype(np.int64)


CALIBRATIONS = ("mad", "tail")


def _window_z(val_scores, val_key, test_scores, test_key, calibration: str = "mad") -> np.ndarray:
    """Window scores on a common null scale, fit on validation windows of the same stratum.

    "mad": robust z (median and MAD), the contract v2 rule. "tail": -log10 of
    the validation tail probability (TailCalibrator), which a nearly constant
    stratum cannot inflate.
    """
    if calibration == "tail":
        return TailCalibrator.fit(val_scores, val_key).transform(test_scores, test_key)
    cal = Calibrator.fit(np.asarray(val_scores)[:, None], val_key)
    return cal.transform(np.asarray(test_scores)[:, None], test_key)[:, 0]


def test_vessel_class(ts: TestSet, processed: Path) -> np.ndarray:
    windows = pd.read_parquet(Path(processed) / "windows.parquet", columns=["window_id", "vessel_class"])
    return windows.set_index("window_id").loc[ts.cells.source_window.to_numpy(), "vessel_class"].to_numpy()


def model_scores(
    name_to_ckpt: dict[str, Path],
    ts: TestSet,
    processed: Path,
    fuse_with_kalman: str | None = None,
    kalman_val: np.ndarray | None = None,
    X_val_raw: np.ndarray | None = None,
    calibration: str = "mad",
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Calibrated window scores for each model (test, val), plus fused detectors if requested.

    Fusion rule (fixed before any real data; nothing in it is fit to a test set):
    calibrate each detector's *window* score per stratum (vessel class x under
    way, see strata) on validation windows (median and MAD), then take the larger of the JEPA's and Kalman's
    z per window. Calibrating at the window level puts both on the same null
    scale even though one takes a max over 63 steps and the other over 7
    transitions. With calibration="tail", window scores are validation tail
    probabilities instead (see _window_z), for every detector. A model named PREFIX or PREFIX-sN, where PREFIX is
    fuse_with_kalman, yields a fused detector named fused or fused-sN.
    """
    import torch

    from latentwake.score import transition_errors
    from latentwake.train import load_model

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if calibration not in CALIBRATIONS:
        raise ValueError(f"calibration must be one of {CALIBRATIONS}")
    vclass_test = test_vessel_class(ts, processed)
    normalizer = Normalizer.load(Path(processed) / "normalizer.json")
    Xn = normalizer.transform(ts.X)
    if X_val_raw is None:
        X_val_raw, meta_v = load_split(processed, "val", normalized=False)
    else:
        meta_v = load_split(processed, "val")[1]
    Xv = normalizer.transform(X_val_raw)
    vclass_val = meta_v.vessel_class.to_numpy()
    key_test, key_val = strata(vclass_test, ts.X), strata(vclass_val, X_val_raw)
    loc_val = loc_test = None  # loaded only if a model uses position

    kz_test = kz_val = None
    if fuse_with_kalman:
        if kalman_val is None:
            kalman_val = window_score(kalman_nis(X_val_raw))
        kalman_test = window_score(kalman_nis(ts.X))
        kz_test = _window_z(kalman_val, key_val, kalman_test, key_test, calibration)
        kz_val = _window_z(kalman_val, key_val, kalman_val, key_val, calibration)

    test, val = {}, {}
    for name, ckpt in name_to_ckpt.items():
        model = load_model(Path(ckpt), device=device)
        if model.cfg.use_position:
            if ts.loc is None:
                raise ValueError(f"{name} uses position but the test set has no location cells; rebuild it (v2)")
            if loc_val is None:
                loc_val, loc_test = load_cells(processed, meta_v), ts.loc
            cv, ct = loc_val, loc_test
        else:
            cv = ct = None
        e_val = transition_errors(model, Xv, vclass_val, cells=cv)
        e_test = transition_errors(model, Xn, vclass_test, cells=ct)
        cal = Calibrator.fit(e_val, key_val)
        test[name] = cal.transform(e_test, key_test).max(axis=1)
        val[name] = cal.transform(e_val, key_val).max(axis=1)
        mz_test = _window_z(val[name], key_val, test[name], key_test, calibration)
        mz_val = _window_z(val[name], key_val, val[name], key_val, calibration)
        if kz_test is not None and (name == fuse_with_kalman or name.startswith(fuse_with_kalman + "-s")):
            fused = "fused" + name[len(fuse_with_kalman):]
            test[fused] = np.maximum(mz_test, kz_test)
            val[fused] = np.maximum(mz_val, kz_val)
        if calibration == "tail":
            test[name], val[name] = mz_test, mz_val
    if fuse_with_kalman and not any(k.startswith("fused") for k in test):
        raise ValueError(f"fuse_with_kalman={fuse_with_kalman!r} matched no model name")
    return test, val


def alert_thresholds(val_scores: dict[str, np.ndarray], alert_fpr: float) -> dict[str, float]:
    """Per-method threshold at which a fraction alert_fpr of validation windows would alert."""
    return {m: float(np.quantile(v, 1.0 - alert_fpr)) for m, v in val_scores.items()}


def alerts_by_stratum(val_scores: dict[str, np.ndarray], thresholds: dict[str, float],
                      key: np.ndarray) -> pd.DataFrame:
    """Validation alert rate per calibration stratum and method, at each method's threshold.

    A detector held to a 1% budget should spread its alerts roughly in
    proportion to where anomalies can happen. If one stratum takes nearly all
    of them (say, anchored tugs), its calibration scale is off.
    """
    from latentwake.data.features import VESSEL_CLASSES

    rows = []
    for k in np.unique(key):
        sel = key == k
        row = {"vessel_class": VESSEL_CLASSES[int(k) // 2], "under_way": bool(k % 2), "n": int(sel.sum())}
        for m, v in val_scores.items():
            row[m] = float((np.asarray(v)[sel] >= thresholds[m]).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_strata(by_stratum: pd.DataFrame) -> str:
    methods = [c for c in by_stratum.columns if c not in ("vessel_class", "under_way", "n")]
    w = by_stratum.n.to_numpy()
    uw = by_stratum.under_way.to_numpy()
    share = {m: float((by_stratum[m] * w)[uw].sum() / max((by_stratum[m] * w).sum(), 1e-12)) for m in methods}
    return (
        "\n## Validation alerts by stratum (alert rate at the 1% budget threshold)\n\n"
        + by_stratum.round(4).to_markdown(index=False)
        + f"\n\nShare of validation alerts on under-way windows ({uw @ w / w.sum():.0%} of windows are under way):\n\n"
        + pd.Series(share).round(3).to_frame("share").T.to_markdown() + "\n"
    )


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
    calibration: str = "tail",
) -> pd.DataFrame:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ts = load_test_set(testset)
    scores = baseline_scores(ts.X)
    X_val_raw, meta_val = load_split(processed, "val", normalized=False)
    val_scores = baseline_scores(X_val_raw)
    key_val = strata(meta_val.vessel_class.to_numpy(), X_val_raw)
    raw_kalman_val = val_scores["kalman"]
    if calibration == "tail":
        # Every detector, baselines included, gets the same per-stratum calibration.
        key_test = strata(test_vessel_class(ts, processed), ts.X)
        for m in list(scores):
            scores[m] = _window_z(val_scores[m], key_val, scores[m], key_test, "tail")
            val_scores[m] = _window_z(val_scores[m], key_val, val_scores[m], key_val, "tail")
    # Learned baselines (Isolation Forest, LSTM autoencoder, TrAISformer-style)
    # produce window scores directly and are calibrated like physics and Kalman.
    from latentwake.models.learned_baselines import LearnedBaseline, is_baseline

    baselines = {k: v for k, v in models.items() if is_baseline(Path(v))}
    models = {k: v for k, v in models.items() if k not in baselines}
    if baselines:
        vclass_test, vclass_val = test_vessel_class(ts, processed), meta_val.vessel_class.to_numpy()
        key_test = strata(vclass_test, ts.X)
        for name, path in baselines.items():
            b = LearnedBaseline.load(Path(path))
            t_raw, v_raw = b.window_scores(ts.X, vclass_test), b.window_scores(X_val_raw, vclass_val)
            if calibration == "tail":
                scores[name] = _window_z(v_raw, key_val, t_raw, key_test, "tail")
                val_scores[name] = _window_z(v_raw, key_val, v_raw, key_val, "tail")
            else:
                scores[name], val_scores[name] = t_raw, v_raw
    if models:
        t, v = model_scores(models, ts, processed, fuse_with_kalman, kalman_val=raw_kalman_val,
                            X_val_raw=X_val_raw, calibration=calibration)
        scores.update(t)
        val_scores.update(v)
    thresholds = alert_thresholds(val_scores, alert_fpr)
    results = cell_metrics(ts.cells, scores, thresholds)
    results.to_csv(out / "results.csv", index=False)
    by_stratum = alerts_by_stratum(val_scores, thresholds, key_val)
    by_stratum.to_csv(out / "val_alerts_by_stratum.csv", index=False)
    (out / "summary.md").write_text(summarize(results) + summarize_strata(by_stratum))
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
    p.add_argument("--calibration", choices=CALIBRATIONS, default="tail",
                   help="window-score calibration: tail (contract v2.1) or mad (median/MAD z, contract v2)")
    a = p.parse_args(argv)
    models = dict(m.split("=", 1) for m in a.model)
    run(a.testset, a.processed, {k: Path(v) for k, v in models.items()}, a.out, a.fuse_with_kalman, a.alert_fpr,
        a.calibration)
    print((a.out / "summary.md").read_text())


if __name__ == "__main__":
    main()
