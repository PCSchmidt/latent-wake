"""Export a small, anonymized sample of the scored test set for the Darkwater panel.

Reads only what the benchmarks already saved (scores, thresholds, the frozen
test set) plus the processed tracks, and writes SQL INSERT statements that
Darkwater's Latent Wake page loads into SQLite in the browser. Nothing is
re-scored for the reported numbers; per-step surprise curves for the sampled
windows are recomputed from the same checkpoints for display only.

What leaves the machine:
- a stratified random sample of test windows (normal and each anomaly kind),
  plus the false-alarm windows of the vessels that raise most of the JEPA's
  false alarms;
- each window's track, rebuilt from the test set's own displacements;
- each vessel's AIS ship type and an anonymous label, never its MMSI, name,
  or timestamps;
- a coarse traffic-density grid (counts only) to draw the chart;
- the scoreboard from the recorded results.

Usage:
    python -m latentwake.export_panel --out ../darkwater/sql/latentwake/data.sql
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from latentwake.checks import _method_mean
from latentwake.data.features import VESSEL_CLASSES
from latentwake.data.geo import integrate_displacement
from latentwake.data.preprocess import load_split
from latentwake.inject.build import load_test_set
from latentwake.posthoc import (ais_type_name, anonymize, recover_thresholds, top_alarming_vessels,
                                vessel_ais_types)

DETECTORS = {"jepa": "jepa-s0", "trais": "trais-s0", "kalman": "kalman"}
KINDS = ("loitering", "route_deviation", "position_spoof", "teleport", "ais_gap")
GROUP_OF = {"jepa": "jepa", "trais": "trais", "kalman": "kalman", "raw": "raw", "lstmae": "lstmae",
            "fused": "fused", "physics": "physics", "iforest": "iforest"}


def describe(kind: str, params: dict) -> str:
    if kind == "normal":
        return ""
    p = params
    return {
        "loitering": lambda: f"{p['duration_steps'] * 2} min circling",
        "route_deviation": lambda: f"{p['turn_deg']:g}° turn off course",
        "position_spoof": lambda: f"{p['offset_nmi']:g} nmi false offset",
        "teleport": lambda: f"{p['distance_nmi']:g} nmi jump",
        "ais_gap": lambda: f"{p['gap_steps'] * 2} min gap, {p['jump_nmi']:g} nmi jump",
    }.get(kind, lambda: "")()


def sql_value(v) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "NULL"
    if isinstance(v, (bool, np.bool_)):
        return str(int(v))
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return repr(round(float(v), 6))
    return "'" + str(v).replace("'", "''") + "'"


def inserts(table: str, rows: list[dict], chunk: int = 400) -> list[str]:
    if not rows:
        return []
    cols = list(rows[0])
    out = []
    for a in range(0, len(rows), chunk):
        vals = ",\n".join("(" + ",".join(sql_value(r[c]) for c in cols) + ")" for r in rows[a : a + chunk])
        out.append(f"INSERT INTO {table}({','.join(cols)}) VALUES\n{vals};")
    return out


def sample_windows(cells: pd.DataFrame, normal_fa: dict[int, np.ndarray], per_kind: int, normals: int,
                   seed: int) -> tuple[np.ndarray, set[int]]:
    """Stratified random sample, plus featured false-alarm windows. Returns indices and the featured set."""
    rng = np.random.default_rng(seed)
    pick = []
    for kind in ("normal",) + KINDS:
        idx = np.flatnonzero(cells.kind.to_numpy() == kind)
        n = normals if kind == "normal" else per_kind
        pick.append(rng.choice(idx, size=min(n, len(idx)), replace=False))
    featured = set()
    for idx in normal_fa.values():
        featured.update(int(i) for i in idx)
    allidx = np.unique(np.concatenate(pick + [np.array(sorted(featured), dtype=int)]))
    return allidx, featured


def run(config: Path, baselines: Path, out: Path, per_kind: int = 16, normals: int = 48, featured_vessels: int = 4,
        featured_per_vessel: int = 3, seed: int = 7, density_deg: float = 0.02, device: str = "cpu") -> Path:
    import torch

    from latentwake.data.features import Normalizer
    from latentwake.models.baselines import kalman_nis
    from latentwake.models.learned_baselines import LearnedBaseline, four_hot
    from latentwake.score import transition_errors
    from latentwake.train import load_model

    cfg = yaml.safe_load(Path(config).read_text())
    bcfg = yaml.safe_load(Path(baselines).read_text())
    if cfg["testset"] != bcfg["testset"]:
        raise ValueError("the two configs score different test sets")
    processed, interim = Path(cfg["processed"]), Path(cfg["interim"])
    ts = load_test_set(Path(cfg["testset"]))
    cells = ts.cells
    normal = (cells.kind == "normal").to_numpy()

    scores, thresholds = {}, {}
    for c in (cfg, bcfg):
        o = Path(c["out"])
        with np.load(o / "scores.npz") as z:
            s = {k: z[k] for k in z.files}
        thresholds.update(recover_thresholds(s, normal, pd.read_csv(o / "results.csv")))
        scores.update(s)

    windows = pd.read_parquet(processed / "windows.parquet", columns=["window_id", "mmsi", "vessel_class"])
    w = windows.set_index("window_id").loc[cells.source_window.to_numpy()]
    mmsi, vclass = w.mmsi.to_numpy(), w.vessel_class.to_numpy()

    # Featured: the vessels raising most of the JEPA's false alarms, labeled exactly as in the post-hoc report.
    from latentwake.data.preprocess import PreprocessConfig
    from latentwake.data.regions import get_region
    from latentwake.posthoc import cell_centers

    pcfg = PreprocessConfig(**json.loads((processed / "stats.json").read_text())["config"])
    region = get_region(pcfg.region)
    clat, clon = cell_centers(ts.loc[:, 0], region, pcfg.cell_deg)
    types = vessel_ais_types(interim, mmsi[normal])
    report_methods = [m for m in ("jepa-s0", "kalman", "raw-s0", "fused-s0") if m in thresholds]
    top = top_alarming_vessels(scores, thresholds, normal, mmsi, types, clat, clon, report_methods, show_mmsi=True)
    report_labels = dict(zip(top.mmsi, anonymize(top).vessel)) if len(top) else {}
    jfa = normal & (scores["jepa-s0"] > thresholds["jepa-s0"])
    lead = pd.Series(mmsi[jfa]).value_counts().head(featured_vessels).index
    normal_fa = {}
    for v in lead:
        idx = np.flatnonzero(jfa & (mmsi == v))
        normal_fa[int(v)] = idx[np.argsort(-scores["jepa-s0"][idx])][:featured_per_vessel]

    idx, featured = sample_windows(cells, normal_fa, per_kind, normals, seed)
    types.update(vessel_ais_types(interim, mmsi[idx]))

    # Anonymous labels: post-hoc labels where they exist, otherwise "<type> #n" in sample order.
    labels, n = {}, 0
    for v in mmsi[idx]:
        v = int(v)
        if v in labels:
            continue
        if v in report_labels:
            labels[v] = report_labels[v]
        else:
            n += 1
            labels[v] = f"{ais_type_name(types.get(v, -1)) if v in types else 'unknown'} #{n}"

    # Tracks rebuilt from the (injected) displacements, starting where the source window starts.
    Xr, meta, raw = load_split(processed, "test", normalized=False, raw=True)
    row_of = pd.Series(np.arange(len(meta)), index=meta.window_id.to_numpy())
    src_rows = row_of.loc[cells.source_window.to_numpy()[idx]].to_numpy()
    from latentwake.data.features import FEATURES

    dxi, dyi = FEATURES.index("dx_m"), FEATURES.index("dy_m")

    # Per-step surprise for display, scaled so 1.0 = the 99th percentile of normal steps in the sample.
    X = ts.X[idx]
    normalizer = Normalizer.load(processed / "normalizer.json")
    jepa = load_model(Path(cfg["models"][DETECTORS["jepa"]]), device=device)
    j_steps = transition_errors(jepa, normalizer.transform(X), vclass[idx])            # (n, T-1), chunk t+1
    trais = LearnedBaseline.load(Path(bcfg["models"][DETECTORS["trais"]]))
    with torch.no_grad():
        t_steps = trais.model.to(device).eval().step_nll(
            torch.as_tensor(four_hot(X, trais.cfg)), torch.as_tensor(vclass[idx].astype(np.int64))).numpy()
    k_steps = kalman_nis(X)
    C = jepa.cfg.chunk_len
    is_norm = (cells.kind.to_numpy()[idx] == "normal")

    def scaled(a):
        ref = np.nanpercentile(a[is_norm], 99) if is_norm.any() else np.nanpercentile(a, 99)
        return a / max(ref, 1e-9)

    j_steps, t_steps, k_steps = scaled(j_steps), scaled(t_steps), scaled(k_steps)

    win_rows, pt_rows, sc_rows, st_rows = [], [], [], []
    for r, i in enumerate(idx):
        kind = cells.kind.iat[i]
        params = json.loads(cells.params.iat[i]) if isinstance(cells.params.iat[i], str) else {}
        v = int(mmsi[i])
        sog = X[r, :, FEATURES.index("sog_kn")]
        win_rows.append({
            "id": int(i), "vessel": labels[v], "ship_type": ais_type_name(types[v]) if v in types else "unknown",
            "vessel_class": VESSEL_CLASSES[int(vclass[i])], "kind": kind,
            "level": int(cells.level.iat[i]), "severity": describe(kind, params),
            "featured": int(i in featured), "under_way": int(sog.mean() >= 1.0),
            "mean_sog": round(float(sog.mean()), 2),
        })
        lat, lon = integrate_displacement(raw["lat"][src_rows[r], 0], raw["lon"][src_rows[r], 0],
                                          X[r, :, dxi], X[r, :, dyi])
        for s in range(len(lat)):
            pt_rows.append({"window_id": int(i), "step": s, "lat": round(float(lat[s]), 5),
                            "lon": round(float(lon[s]), 5), "injected": int(ts.step_label[i, s])})
        for d, m in DETECTORS.items():
            sc_rows.append({"window_id": int(i), "detector": d, "score": float(scores[m][i]),
                            "threshold": float(thresholds[m])})
        for t in range(j_steps.shape[1]):
            st_rows.append({"window_id": int(i), "detector": "jepa", "step": (t + 1) * C + C // 2,
                            "value": float(j_steps[r, t])})
        for s in range(t_steps.shape[1]):
            st_rows.append({"window_id": int(i), "detector": "trais", "step": s + 1, "value": float(t_steps[r, s])})
        for s in range(k_steps.shape[1]):
            st_rows.append({"window_id": int(i), "detector": "kalman", "step": s, "value": float(k_steps[r, s])})

    # Coarse traffic density from every processed track point (counts only) to draw the chart.
    import duckdb

    dens = duckdb.connect().execute(f"""
        SELECT floor(lat / {density_deg}) * {density_deg} + {density_deg / 2} AS lat,
               floor(lon / {density_deg}) * {density_deg} + {density_deg / 2} AS lon, count(*) AS n
        FROM read_parquet('{(processed / 'tracks.parquet').as_posix()}') WHERE valid GROUP BY 1, 2
    """).df()
    dens_rows = [{"lat": round(float(a), 4), "lon": round(float(b), 4), "n": int(c)}
                 for a, b, c in dens.itertuples(index=False)]

    # Scoreboard from the recorded results (three-seed means), never recomputed.
    res = pd.concat([pd.read_csv(Path(cfg["out"]) / "results.csv"),
                     pd.read_csv(Path(bcfg["out"]) / "results.csv")]).drop_duplicates(["method", "kind", "level"])
    board = []
    for g in GROUP_OF:
        if not any((res.method == g) | res.method.str.startswith(g + "-s")):
            continue
        for kind in KINDS:
            board.append({"detector": g, "kind": kind, "auroc": _method_mean(res, g, "auroc", [kind]),
                          "auprc": _method_mean(res, g, "auprc", [kind]),
                          "detect": _method_mean(res, g, "detect_at_budget", [kind])})
        nm = res[(res.kind == "normal") & ((res.method == g) | res.method.str.startswith(g + "-s"))]
        board.append({"detector": g, "kind": "normal", "auroc": None, "auprc": None,
                      "detect": float(nm.fpr_at_budget.mean())})

    bench = json.loads((Path(cfg["out"]) / "benchmark.json").read_text())
    meta_rows = [
        {"key": "testset_sha256", "value": bench["testset_sha256"][:12]},
        {"key": "scored_at", "value": bench["scored_at"]},
        {"key": "region", "value": pcfg.region},
        {"key": "sample", "value": f"{len(idx)} test windows: {normals} normal and {per_kind} per anomaly kind "
                                   f"(seed {seed}), plus {len(featured)} false alarms from the "
                                   f"{len(normal_fa)} vessels that raise most of the JEPA's"},
        {"key": "step_scale", "value": "per-step surprise / 99th percentile of normal steps in the sample"},
    ]

    sql = ["-- Latent Wake panel data. Generated by latentwake.export_panel; do not edit by hand.",
           "-- Real NOAA AIS (Chesapeake Bay and Hampton Roads, June 2025), anonymized: no MMSIs, names, or times.",
           "BEGIN;"]
    for table, rows in (("lw_meta", meta_rows), ("lw_window", win_rows), ("lw_point", pt_rows),
                        ("lw_score", sc_rows), ("lw_step", st_rows), ("lw_density", dens_rows),
                        ("lw_result", board)):
        sql += inserts(table, rows)
    sql.append("COMMIT;")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sql) + "\n")
    print(f"wrote {out}: {len(win_rows)} windows, {len(pt_rows)} points, {len(dens_rows)} density cells, "
          f"{out.stat().st_size / 1e6:.2f} MB")
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Export an anonymized sample for the Darkwater Latent Wake panel.")
    p.add_argument("--config", type=Path, default=Path("configs/eval.yaml"))
    p.add_argument("--baselines", type=Path, default=Path("configs/eval-baselines.yaml"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--per-kind", type=int, default=16)
    p.add_argument("--normals", type=int, default=48)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--device", default="cpu")
    a = p.parse_args(argv)
    run(a.config, a.baselines, a.out, a.per_kind, a.normals, seed=a.seed, device=a.device)


if __name__ == "__main__":
    main()
