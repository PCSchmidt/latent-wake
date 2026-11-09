"""Exploratory analysis of an already-scored test set. Never re-scores anything.

Reads the scores, results, and test set that the benchmark saved, and asks
two questions the pre-registered criteria do not:

1. How uncertain are the criterion differences? Windows from one vessel are
   correlated, so the effective sample size is closer to the number of
   vessels than the number of windows. A cluster bootstrap over source
   vessels gives an interval for each AUROC/AUPRC difference.
2. Where do the test false alarms come from? Thresholds set on validation
   vessels may not transfer to test vessels. This breaks false alarms on
   normal windows down by calibration stratum and by vessel.

Everything this writes is post hoc and labeled so; it does not change the
contract verdict.

Usage:
    python -m latentwake.posthoc                       # paths from configs/eval.yaml
    python -m latentwake.posthoc --bootstrap 500
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from latentwake.checks import _method_mean, load_thresholds
from latentwake.data.features import VESSEL_CLASSES
from latentwake.evaluate import cell_metrics, strata
from latentwake.inject.build import load_test_set

GROUP = re.compile(r"-s\d+$")


def recover_thresholds(scores: dict[str, np.ndarray], normal: np.ndarray, results: pd.DataFrame) -> dict[str, float]:
    """Thresholds the benchmark used, recovered from its recorded false-alarm rates.

    The benchmark stores each method's rate fpr = mean(score > threshold) on
    test normals but not the threshold. Any value between the k-th and
    (k+1)-th largest normal score reproduces that rate exactly, so the
    breakdowns below match the recorded totals.
    """
    out = {}
    fpr = results[results.kind == "normal"].set_index("method").fpr_at_budget
    for m, s in scores.items():
        if m not in fpr.index:
            continue
        v = np.sort(np.asarray(s)[normal])
        k = int(round(fpr[m] * len(v)))
        out[m] = float(v[len(v) - k - 1]) if k < len(v) else float(v[0]) - 1.0
    return out


def false_alarms_by_stratum(scores, thresholds, normal, key) -> pd.DataFrame:
    rows = []
    for k in np.unique(key[normal]):
        sel = normal & (key == k)
        row = {"vessel_class": VESSEL_CLASSES[int(k) // 2], "under_way": bool(k % 2), "n_normal": int(sel.sum())}
        for m, t in thresholds.items():
            row[m] = float((scores[m][sel] > t).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def false_alarms_by_vessel(scores, thresholds, normal, mmsi) -> pd.DataFrame:
    """Per method: how many vessels raise the false alarms, and how concentrated they are."""
    n_vessels = len(np.unique(mmsi[normal]))
    rows = []
    for m, t in thresholds.items():
        fa = normal & (scores[m] > t)
        counts = pd.Series(mmsi[fa]).value_counts()
        rows.append({
            "method": m,
            "false_alarms": int(fa.sum()),
            "vessels_alarming": int(len(counts)),
            "of_vessels": n_vessels,
            "top5_share": float(counts.head(5).sum() / max(counts.sum(), 1)),
        })
    return pd.DataFrame(rows)


def _diffs(results: pd.DataFrame, criteria: list[dict]) -> dict[str, float]:
    out = {}
    for c in criteria:
        if c.get("vs_method") is None or c["metric"] not in ("auroc", "auprc"):
            continue
        a = _method_mean(results, c["method"], c["metric"], c["kinds"])
        b = _method_mean(results, c["vs_method"], c["metric"], c["kinds"])
        out[c["id"]] = a - b
    return out


def cluster_bootstrap(cells: pd.DataFrame, scores: dict[str, np.ndarray], mmsi: np.ndarray, criteria: list[dict],
                      n_boot: int = 200, seed: int = 0) -> pd.DataFrame:
    """Resample source vessels with replacement; recompute each AUROC/AUPRC criterion difference."""
    needed = {c[k] for c in criteria for k in ("method", "vs_method") if c.get(k)}
    methods = {m: s for m, s in scores.items() if GROUP.sub("", m) in needed}
    point = _diffs(cell_metrics(cells, methods), criteria)
    vessels = np.unique(mmsi)
    by_vessel = {v: np.flatnonzero(mmsi == v) for v in vessels}
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        pick = rng.choice(vessels, len(vessels), replace=True)
        idx = np.concatenate([by_vessel[v] for v in pick])
        sub = cells.iloc[idx].reset_index(drop=True)
        try:
            draws.append(_diffs(cell_metrics(sub, {m: s[idx] for m, s in methods.items()}), criteria))
        except Exception:  # a resample can miss a kind entirely; skip it
            continue
    d = pd.DataFrame(draws)
    margin = {c["id"]: float(c["margin"]) for c in criteria if c["id"] in point}
    return pd.DataFrame([
        {
            "criterion": k,
            "difference": point[k],
            "ci_low": float(d[k].quantile(0.025)),
            "ci_high": float(d[k].quantile(0.975)),
            "margin": margin[k],
            "share_of_draws_meeting_margin": float((d[k] >= margin[k]).mean()),
            "draws": int(d[k].notna().sum()),
        }
        for k in point
    ])


def run(cfg_path: Path = Path("configs/eval.yaml"), n_boot: int = 200, out_name: str = "posthoc") -> Path:
    cfg = yaml.safe_load(Path(cfg_path).read_text())
    out_dir = Path(cfg["out"])
    dest = out_dir / out_name
    dest.mkdir(parents=True, exist_ok=True)
    ts = load_test_set(Path(cfg["testset"]))
    with np.load(out_dir / "scores.npz") as z:
        scores = {k: z[k] for k in z.files}
    results = pd.read_csv(out_dir / "results.csv")
    windows = pd.read_parquet(Path(cfg["processed"]) / "windows.parquet", columns=["window_id", "mmsi", "vessel_class"])
    w = windows.set_index("window_id").loc[ts.cells.source_window.to_numpy()]
    mmsi, vclass = w.mmsi.to_numpy(), w.vessel_class.to_numpy()
    normal = (ts.cells.kind == "normal").to_numpy()
    key = strata(vclass, ts.X)

    thresholds = recover_thresholds(scores, normal, results)
    by_stratum = false_alarms_by_stratum(scores, thresholds, normal, key)
    by_vessel = false_alarms_by_vessel(scores, thresholds, normal, mmsi)
    boot = cluster_bootstrap(ts.cells, scores, mmsi, load_thresholds(Path(cfg.get("contract", "DATA_CONTRACT.md"))),
                             n_boot=n_boot)
    for name, df in (("false_alarms_by_stratum", by_stratum), ("false_alarms_by_vessel", by_vessel),
                     ("bootstrap", boot)):
        df.to_csv(dest / f"{name}.csv", index=False)

    n_test_vessels = len(np.unique(mmsi))
    md = [
        "# Post-hoc analysis of the test results (exploratory)",
        "",
        "Computed after the single scoring from the saved scores; nothing was re-scored and the contract "
        "verdict is unchanged.",
        "",
        f"## Uncertainty: cluster bootstrap over {n_test_vessels} source vessels ({n_boot} draws)",
        "",
        boot.round(3).to_markdown(index=False),
        "",
        "## Test false alarms by vessel (thresholds from validation, 1% budget)",
        "",
        by_vessel.round(3).to_markdown(index=False),
        "",
        "## Test false-alarm rate by stratum",
        "",
        by_stratum.round(4).to_markdown(index=False),
        "",
    ]
    (dest / "POSTHOC.md").write_text("\n".join(md))
    (dest / "thresholds.json").write_text(json.dumps(thresholds, indent=2) + "\n")
    print("\n".join(md))
    return dest


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Exploratory analysis of a scored test set (never re-scores).")
    p.add_argument("--config", type=Path, default=Path("configs/eval.yaml"))
    p.add_argument("--bootstrap", type=int, default=200)
    a = p.parse_args(argv)
    run(a.config, a.bootstrap)


if __name__ == "__main__":
    main()
