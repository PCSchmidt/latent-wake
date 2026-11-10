"""Exploratory analysis of an already-scored test set. Never re-scores anything.

Reads the scores, results, and test set that the benchmark saved, and asks
two questions the pre-registered criteria do not:

1. How uncertain are the criterion differences? Windows from one vessel are
   correlated, so the effective sample size is closer to the number of
   vessels than the number of windows. A cluster bootstrap over source
   vessels gives an interval for each AUROC/AUPRC difference.
2. Where do the test false alarms come from? Thresholds set on validation
   vessels may not transfer to test vessels. This breaks false alarms on
   normal windows down by calibration stratum, by vessel, and by the AIS
   ship-type code behind each vessel (pilot boats and dredges fall in our
   "other" class), with the most-alarming vessels' typical position.

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


AIS_TYPE_NAMES = {
    0: "not available", 30: "fishing", 31: "towing", 32: "towing, long", 33: "dredging or underwater ops",
    34: "diving ops", 35: "military ops", 36: "sailing", 37: "pleasure craft", 50: "pilot vessel",
    51: "search and rescue", 52: "tug", 53: "port tender", 54: "anti-pollution", 55: "law enforcement",
    58: "medical transport", 59: "noncombatant",
}


def ais_type_name(code) -> str:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "missing"
    if c in AIS_TYPE_NAMES:
        return AIS_TYPE_NAMES[c]
    for lo, name in ((20, "wing in ground"), (40, "high speed craft"), (60, "passenger"), (70, "cargo"),
                     (80, "tanker"), (90, "other type")):
        if lo <= c <= lo + 9:
            return name
    return "reserved or NOAA code"


def vessel_ais_types(interim_dir: Path, mmsis) -> dict[int, int]:
    """Most frequent AIS ship-type code reported by each vessel in the downloaded data."""
    import duckdb

    ids = sorted({int(m) for m in mmsis})
    if not ids:
        return {}
    con = duckdb.connect()
    con.register("ids", pd.DataFrame({"mmsi": ids}))
    rows = con.execute(
        f"""
        SELECT mmsi, mode(vessel_type) AS vessel_type
        FROM read_parquet('{Path(interim_dir).as_posix()}/*.parquet') JOIN ids USING (mmsi)
        WHERE vessel_type IS NOT NULL
        GROUP BY mmsi
        """
    ).fetchall()
    return {int(m): int(t) for m, t in rows if t is not None}


def false_alarms_by_ais_type(scores, thresholds, normal, mmsi, types: dict[int, int]) -> pd.DataFrame:
    """Share of each method's test false alarms, by the AIS type code of the vessel raising them."""
    code = np.array([types.get(int(m), -1) for m in mmsi])
    rows = []
    for c in np.unique(code[normal]):
        sel = normal & (code == c)
        row = {"ais_type": int(c), "name": ais_type_name(c) if c >= 0 else "unknown", "n_normal": int(sel.sum()),
               "vessels": int(len(np.unique(mmsi[sel])))}
        for m, t in thresholds.items():
            fa = normal & (scores[m] > t)
            row[m] = float((fa & sel).sum() / max(fa.sum(), 1))
        rows.append(row)
    return pd.DataFrame(rows).sort_values("n_normal", ascending=False)


def top_alarming_vessels(scores, thresholds, normal, mmsi, types, lat, lon, methods, k: int = 10) -> pd.DataFrame:
    """The k vessels with the most false alarms for each method, with type and typical position."""
    rows = []
    for m in methods:
        if m not in thresholds:
            continue
        fa = normal & (scores[m] > thresholds[m])
        counts = pd.Series(mmsi[fa]).value_counts().head(k)
        for v, n in counts.items():
            sel = fa & (mmsi == v)
            t = types.get(int(v), -1)
            rows.append({"method": m, "mmsi": int(v), "false_alarms": int(n),
                         "normal_windows": int((normal & (mmsi == v)).sum()),
                         "ais_type": t, "name": ais_type_name(t) if t >= 0 else "unknown",
                         "lat": round(float(np.median(lat[sel])), 3), "lon": round(float(np.median(lon[sel])), 3)})
    return pd.DataFrame(rows)


def cell_centers(cells: np.ndarray, region, cell_deg: float) -> tuple[np.ndarray, np.ndarray]:
    _, cols = region.grid_shape(cell_deg)
    r, c = np.divmod(np.asarray(cells), cols)
    return region.lat_min + (r + 0.5) * cell_deg, region.lon_min + (c + 0.5) * cell_deg


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
    tables = {"false_alarms_by_stratum": by_stratum, "false_alarms_by_vessel": by_vessel, "bootstrap": boot}

    by_type = top = None
    interim = cfg.get("interim")
    if interim and any(Path(interim).glob("*.parquet")) and ts.loc is not None:
        from latentwake.data.preprocess import PreprocessConfig
        from latentwake.data.regions import get_region

        pcfg = PreprocessConfig(**json.loads((Path(cfg["processed"]) / "stats.json").read_text())["config"])
        lat, lon = cell_centers(ts.loc[:, 0], get_region(pcfg.region), pcfg.cell_deg)
        types = vessel_ais_types(Path(interim), mmsi[normal])
        by_type = false_alarms_by_ais_type(scores, thresholds, normal, mmsi, types)
        key_methods = [m for m in ("jepa-s0", "kalman", "raw-s0", "fused-s0") if m in thresholds]
        top = top_alarming_vessels(scores, thresholds, normal, mmsi, types, lat, lon, key_methods)
        tables.update(false_alarms_by_ais_type=by_type, top_alarming_vessels=top)
    for name, df in tables.items():
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
    if by_type is not None:
        md += [
            "## Share of test false alarms by AIS ship-type code",
            "",
            "Each vessel's most frequent reported type code. Pilot vessels (50) and dredging (33) fall in "
            "the model's \"other\" class.",
            "",
            by_type.round(3).to_markdown(index=False),
            "",
            "## Vessels with the most test false alarms",
            "",
            "Position: median grid-cell center of the false-alarm windows' first step (about 5 km cells).",
            "",
            top.to_markdown(index=False),
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
