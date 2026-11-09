"""Turn cropped daily AIS files into model-ready windows.

Stages (each one testable on its own):
    clean      drop bad identities, sentinel values, duplicates, and position outliers
    segment    split each vessel into tracks at long silences; log those silences
    resample   put every track on a shared 2-minute grid; mark steps that would
               need too much interpolation as invalid
    features   per-step relative-motion features (see features.py)
    windows    64-step windows with stride 16, only over fully valid steps
    split      time-and-vessel split, so test vessels are never seen in training
    normalize  feature statistics from the training split only

Usage:
    python -m latentwake.data.preprocess --interim data/interim/chesapeake \\
        --out data/processed/chesapeake

Writes tracks.parquet, windows.parquet, gaps.parquet, normalizer.json and
stats.json to the output folder.

Not done yet: dropping points on land. That needs a coastline file; the
implied-speed filter catches most position glitches in the meantime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from latentwake.data.features import FEATURES, RAW_FIELDS, Normalizer, step_features, vessel_class
from latentwake.data.geo import KNOTS_TO_MPS, circular_interp, course_from_xy, step_displacement
from latentwake.data.regions import get_region

log = logging.getLogger("latentwake.preprocess")


@dataclass
class PreprocessConfig:
    step_s: int = 120                 # resampling grid, seconds
    segment_gap_s: int = 1800         # silence that starts a new track (and is logged as a gap event)
    max_interp_span_s: int = 480      # at most 3 missing grid steps between real reports
    min_track_points: int = 10
    max_sog_kn: float = 50.0
    max_implied_speed_kn: float = 60.0
    outlier_passes: int = 3
    window_len: int = 64
    window_stride: int = 16
    stationary_sog_kn: float = 0.5
    split_cutoff: str | None = None   # ISO date; None = two-thirds through the data
    holdout_frac: float = 0.3         # share of vessels never used for training
    split_seed: int = 0
    region: str = "chesapeake"        # location grid for the optional position context
    cell_deg: float = 0.05            # grid cell size, degrees (about 5 km)
    # Main-study population (contract v2): Class A transceivers, the commercial
    # vessels US rules require to carry AIS. None keeps every transceiver class.
    transceivers: tuple[str, ...] | None = ("A",)
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------- load

def load_interim(interim_dir: Path) -> pd.DataFrame:
    files = sorted(Path(interim_dir).glob("ais-*.parquet"))
    if not files:
        raise FileNotFoundError(f"no ais-*.parquet files in {interim_dir}")
    pattern = (Path(interim_dir) / "ais-*.parquet").as_posix()
    df = duckdb.sql(
        "SELECT mmsi, base_date_time AS t, latitude AS lat, longitude AS lon, sog, cog, heading, vessel_type, "
        "transceiver "
        f"FROM read_parquet('{pattern}')"
    ).df()
    log.info("loaded %d rows from %d files", len(df), len(files))
    return df


# -------------------------------------------------------------------- clean

def _epoch_s(t: pd.Series) -> np.ndarray:
    """Seconds since 1970 as float, whatever the timestamp resolution (ns, us, ms)."""
    return t.to_numpy().astype("datetime64[ns]").astype("int64") / 1e9


def _pair_speed_kn(lat, lon, t_s) -> np.ndarray:
    dx, dy = step_displacement(lat, lon)
    dt = np.diff(t_s, prepend=np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.hypot(dx, dy) / dt / KNOTS_TO_MPS


def clean(df: pd.DataFrame, cfg: PreprocessConfig) -> tuple[pd.DataFrame, dict]:
    stats = {"rows_in": int(len(df))}
    df = df.dropna(subset=["mmsi", "t", "lat", "lon"]).copy()
    stats["after_nulls"] = int(len(df))

    # Ship stations carry a 9-digit MMSI whose first digit (the region of the
    # country code) is 2-7. Base stations, aids to navigation, SAR aircraft,
    # and placeholder IDs fall outside that range.
    df = df[(df.mmsi >= 200_000_000) & (df.mmsi <= 799_999_999)]
    stats["after_mmsi"] = int(len(df))
    if cfg.transceivers is not None and "transceiver" in df:
        df = df[df.transceiver.isin(list(cfg.transceivers))]
        stats["after_transceiver"] = int(len(df))

    df = df[df.lat.between(-90, 90) & df.lon.between(-180, 180)]
    # NOAA "not available" sentinels become missing values, not rows to drop.
    df.loc[df.sog >= 102.2, "sog"] = np.nan
    df.loc[df.cog >= 360.0, "cog"] = np.nan
    df.loc[(df.heading >= 360.0) | (df.heading < 0), "heading"] = np.nan
    df = df[~(df.sog > cfg.max_sog_kn)]
    stats["after_sog"] = int(len(df))

    df = df.sort_values(["mmsi", "t"]).drop_duplicates(["mmsi", "t"], keep="first")
    stats["after_dedupe"] = int(len(df))

    # Drop single-point position glitches: a report the ship could not have
    # reached from its previous one AND could not have left for its next one.
    # Requiring both keeps the good point after a glitch. A lasting jump (fast
    # in, normal out) is kept: it is real data, and possibly real spoofing.
    # Repeat a few times, since removing one point changes its neighbors.
    for _ in range(cfg.outlier_passes):
        t_s = _epoch_s(df.t)
        speed_in = _pair_speed_kn(df.lat.to_numpy(), df.lon.to_numpy(), t_s)
        mmsi = df.mmsi.to_numpy()
        same_prev = np.r_[False, mmsi[1:] == mmsi[:-1]]
        same_next = np.r_[mmsi[1:] == mmsi[:-1], False]
        fast_in = same_prev & (speed_in > cfg.max_implied_speed_kn)
        speed_out = np.r_[speed_in[1:], np.nan]
        fast_out = same_next & (speed_out > cfg.max_implied_speed_kn)
        spike = fast_in & fast_out
        after_spike = np.r_[False, spike[:-1]] & same_prev
        bad = spike | (fast_in & ~same_next & ~after_spike)  # a glitch on a vessel's last report
        if not bad.any():
            break
        df = df[~bad]
    stats["after_outliers"] = int(len(df))
    return df.reset_index(drop=True), stats


# ------------------------------------------------------------------ segment

def segment(df: pd.DataFrame, cfg: PreprocessConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assign track_id; return (points, gap_events)."""
    t_s = _epoch_s(df.t)
    mmsi = df.mmsi.to_numpy()
    same = np.r_[False, mmsi[1:] == mmsi[:-1]]
    dt = np.r_[np.nan, np.diff(t_s)]
    gap = same & (dt > cfg.segment_gap_s)

    dx, dy = step_displacement(df.lat.to_numpy(), df.lon.to_numpy())
    jump = np.hypot(dx, dy)
    gi = np.flatnonzero(gap)
    gaps = pd.DataFrame(
        {
            "mmsi": mmsi[gi],
            "gap_start": df.t.to_numpy()[gi - 1],
            "gap_end": df.t.to_numpy()[gi],
            "gap_s": dt[gi],
            "jump_m": jump[gi],
            "implied_kn": jump[gi] / dt[gi] / KNOTS_TO_MPS,
            "lat_before": df.lat.to_numpy()[gi - 1],
            "lon_before": df.lon.to_numpy()[gi - 1],
            "lat_after": df.lat.to_numpy()[gi],
            "lon_after": df.lon.to_numpy()[gi],
        }
    )

    new_track = ~same | gap
    df = df.assign(track_id=np.cumsum(new_track) - 1)
    sizes = df.groupby("track_id").size()
    keep = sizes.index[sizes >= cfg.min_track_points]
    df = df[df.track_id.isin(keep)].copy()
    df["track_id"] = pd.factorize(df.track_id)[0]  # renumber 0..n-1
    return df.reset_index(drop=True), gaps


# ----------------------------------------------------------------- resample

def resample_track(t_s, lat, lon, sog, cog, heading, cfg: PreprocessConfig) -> dict[str, np.ndarray] | None:
    """Resample one track onto absolute multiples of step_s (so vessels align in time)."""
    step = cfg.step_s
    g0 = np.ceil(t_s[0] / step) * step
    g1 = np.floor(t_s[-1] / step) * step
    if g1 < g0:
        return None
    grid = np.arange(g0, g1 + step / 2, step)

    right = np.clip(np.searchsorted(t_s, grid, side="left"), 0, len(t_s) - 1)
    exact = t_s[right] == grid
    left = np.where(exact, right, np.maximum(right - 1, 0))
    span = t_s[right] - t_s[left]
    valid = exact | (span <= cfg.max_interp_span_s)

    out = {
        "t": grid,
        "lat": np.interp(grid, t_s, lat),
        "lon": np.interp(grid, t_s, lon),
        "valid": valid,
    }

    m = np.isfinite(sog)
    out["sog"] = np.interp(grid, t_s[m], sog[m]) if m.sum() >= 1 else np.full(grid.shape, np.nan)

    m = np.isfinite(cog)
    out["cog"] = circular_interp(grid, t_s[m], cog[m]) if m.sum() >= 1 else np.full(grid.shape, np.nan)

    m = np.isfinite(heading)
    if m.sum() >= 1:
        h = circular_interp(grid, t_s[m], heading[m])
        h[~(m[left] & m[right])] = np.nan  # only trust heading where real reports bracket it
    else:
        h = np.full(grid.shape, np.nan)
    out["heading"] = h

    # Fill missing speed or course from the motion itself.
    dx, dy = step_displacement(out["lat"], out["lon"])
    if not np.isfinite(out["sog"]).any():
        out["sog"] = np.hypot(dx, dy) / step / KNOTS_TO_MPS
    if not np.isfinite(out["cog"]).any():
        out["cog"] = course_from_xy(dx, dy)
    return out


def _track_vessel_class(points: pd.DataFrame) -> dict[int, int]:
    """Most frequent reported ship type per track, mapped to a vessel class (vectorized)."""
    vt = points[["track_id", "vessel_type"]].dropna()
    if vt.empty:
        return {}
    counts = vt.groupby(["track_id", "vessel_type"]).size().reset_index(name="n")
    top = counts.sort_values(["track_id", "n"], ascending=[True, False]).drop_duplicates("track_id")
    code_to_class = {c: vessel_class(c) for c in top.vessel_type.unique()}
    return dict(zip(top.track_id.astype(int), top.vessel_type.map(code_to_class).astype(int)))


def resample(points: pd.DataFrame, cfg: PreprocessConfig) -> pd.DataFrame:
    """Resample every track. Accumulates plain arrays and builds one frame at the end;
    building a DataFrame per track was the bottleneck at 100k+ tracks."""
    t_all = _epoch_s(points.t)
    cols = {c: points[c].to_numpy(dtype=np.float64) for c in ("lat", "lon", "sog", "cog", "heading")}
    tid = points.track_id.to_numpy()
    mmsi = points.mmsi.to_numpy()
    vclass_of = _track_vessel_class(points)
    bounds = np.flatnonzero(np.r_[True, tid[1:] != tid[:-1], True])
    n_tracks = len(bounds) - 1
    acc: dict[str, list[np.ndarray]] = {k: [] for k in
                                        ("track_id", "mmsi", "t", "lat", "lon", "sog", "cog", "heading",
                                         "vessel_class", "valid", "feat_valid", "feats")}
    for k, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        if k and k % 20000 == 0:
            log.info("resampled %d of %d tracks", k, n_tracks)
        r = resample_track(t_all[a:b], *(cols[c][a:b] for c in ("lat", "lon", "sog", "cog", "heading")), cfg=cfg)
        if r is None:
            continue
        n = len(r["t"])
        feats = step_features(r["lat"], r["lon"], r["sog"], r["cog"], r["heading"])
        ok = r["valid"]
        acc["track_id"].append(np.full(n, tid[a], dtype=np.int64))
        acc["mmsi"].append(np.full(n, mmsi[a], dtype=np.int64))
        acc["vessel_class"].append(np.full(n, vclass_of.get(int(tid[a]), 0), dtype=np.int64))
        for key in ("t", "lat", "lon", "sog", "cog", "heading"):
            acc[key].append(r[key])
        acc["valid"].append(ok)
        acc["feat_valid"].append(ok & np.r_[False, ok[:-1]] & np.isfinite(feats).all(axis=1))
        acc["feats"].append(feats)
    if not acc["t"]:
        raise ValueError("no track survived resampling")
    cat = {k: np.concatenate(v) for k, v in acc.items()}
    out = pd.DataFrame(
        {
            "track_id": cat["track_id"],
            "mmsi": cat["mmsi"],
            "t": pd.to_datetime(cat["t"], unit="s"),
            **{k: cat[k] for k in ("lat", "lon", "sog", "cog", "heading")},
            "vessel_class": cat["vessel_class"],
            "valid": cat["valid"],
            "feat_valid": cat["feat_valid"],
        }
    )
    for i, name in enumerate(FEATURES):
        out[name] = cat["feats"][:, i]
    # Location grid cell per step, for the optional position context.
    out["cell"] = get_region(cfg.region).cell_index(out.lat.to_numpy(), out.lon.to_numpy(), cfg.cell_deg)
    return out


# ------------------------------------------------------------------ windows

def make_windows(tracks: pd.DataFrame, cfg: PreprocessConfig) -> pd.DataFrame:
    """Index of windows over fully valid steps. row0 points into `tracks`.

    Linear time: find each maximal run of valid steps within a track from its
    start and end positions, then lay windows along it with np.repeat. (The
    first version rescanned every row once per run, which is quadratic and
    never finished on three months of real data.)
    """
    L, stride = cfg.window_len, cfg.window_stride
    fv = tracks.feat_valid.to_numpy(dtype=bool)
    tid = tracks.track_id.to_numpy()
    same_next = np.r_[tid[1:] == tid[:-1], False]
    same_prev = np.r_[False, tid[1:] == tid[:-1]]
    run_start = fv & ~(np.r_[False, fv[:-1]] & same_prev)
    run_end = fv & ~(np.r_[fv[1:], False] & same_next)
    starts, ends = np.flatnonzero(run_start), np.flatnonzero(run_end)
    lengths = ends - starts + 1
    fits = lengths >= L
    starts, lengths = starts[fits], lengths[fits]
    counts = (lengths - L) // stride + 1
    offsets = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
    row0 = (np.repeat(starts, counts) + stride * offsets).astype(np.int64)
    if row0.size == 0:
        return pd.DataFrame(columns=["window_id", "row0", "track_id", "mmsi", "vessel_class", "t_start", "t_end",
                                     "mean_sog", "is_stationary"])
    sog = tracks.sog_kn.to_numpy()
    mean_sog = sog[row0[:, None] + np.arange(L)].mean(axis=1)
    w = pd.DataFrame(
        {
            "row0": row0,
            "track_id": tid[row0],
            "mmsi": tracks.mmsi.to_numpy()[row0],
            "vessel_class": tracks.vessel_class.to_numpy()[row0],
            "t_start": tracks.t.to_numpy()[row0],
            "t_end": tracks.t.to_numpy()[row0 + L - 1],
            "mean_sog": mean_sog,
            "is_stationary": mean_sog < cfg.stationary_sog_kn,
        }
    )
    w.insert(0, "window_id", np.arange(len(w)))
    return w


# -------------------------------------------------------------------- split

def _unit_hash(mmsi: int, seed: int) -> float:
    h = hashlib.blake2b(f"{seed}:{int(mmsi)}".encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") / 2**64


def assign_splits(windows: pd.DataFrame, cutoff: pd.Timestamp, cfg: PreprocessConfig) -> pd.Series:
    """train: training-pool vessels before the cutoff. val/test: held-out vessels after it.

    Everything else (held-out vessels before the cutoff, training vessels after
    it) is 'unused', so no vessel and no time period appears on both sides.
    """
    vessels = windows.mmsi.unique()
    u = windows.mmsi.map(dict(zip(vessels, (_unit_hash(m, cfg.split_seed) for m in vessels)))).to_numpy()
    holdout = u < cfg.holdout_frac
    late = windows.t_start.to_numpy() >= np.datetime64(cutoff)
    # Windows that straddle the cutoff are dropped from training.
    early = windows.t_end.to_numpy() < np.datetime64(cutoff)
    split = np.full(len(windows), "unused", dtype=object)
    split[~holdout & early] = "train"
    split[holdout & late & (u < cfg.holdout_frac / 2)] = "val"
    split[holdout & late & (u >= cfg.holdout_frac / 2)] = "test"
    return pd.Series(split, index=windows.index, name="split")


# --------------------------------------------------------------- arrays out

def window_array(tracks: pd.DataFrame, row0: np.ndarray, L: int, columns, dtype=np.float32) -> np.ndarray:
    """Gather (N, L, len(columns)) from tracks for the given window starts.

    Use float64 for raw positions: float32 latitude is only good to about half
    a meter, which is visible in recomputed displacements.
    """
    arr = tracks[list(columns)].to_numpy(dtype=dtype)
    return arr[np.asarray(row0)[:, None] + np.arange(L)]


def load_split(processed_dir: Path, split: str, normalized: bool = True, raw: bool = False):
    """Load one split. Returns (X, meta) or (X, meta, raw_dict) when raw=True.

    X is (N, L, len(FEATURES)); raw_dict maps lat/lon/sog/cog/heading to (N, L)
    arrays for anomaly injection.
    """
    processed_dir = Path(processed_dir)
    cfg = PreprocessConfig(**json.loads((processed_dir / "stats.json").read_text())["config"])
    tracks = pd.read_parquet(processed_dir / "tracks.parquet")
    windows = pd.read_parquet(processed_dir / "windows.parquet")
    meta = windows[windows.split == split].reset_index(drop=True)
    X = window_array(tracks, meta.row0.to_numpy(), cfg.window_len, FEATURES)
    if normalized:
        X = Normalizer.load(processed_dir / "normalizer.json").transform(X)
    if not raw:
        return X, meta
    R = window_array(tracks, meta.row0.to_numpy(), cfg.window_len, RAW_FIELDS, dtype=np.float64)
    return X, meta, {f: R[..., i] for i, f in enumerate(RAW_FIELDS)}


def load_cells(processed_dir: Path, meta: pd.DataFrame) -> np.ndarray:
    """Per-step location cells (N, L) for the windows in meta; zeros if the data predates cells."""
    processed_dir = Path(processed_dir)
    cfg = PreprocessConfig(**json.loads((processed_dir / "stats.json").read_text())["config"])
    try:
        cell = pd.read_parquet(processed_dir / "tracks.parquet", columns=["cell"]).cell.to_numpy()
    except (KeyError, ValueError):
        return np.zeros((len(meta), cfg.window_len), dtype=np.int32)
    return cell[meta.row0.to_numpy()[:, None] + np.arange(cfg.window_len)].astype(np.int32)


def grid_size(processed_dir: Path) -> int:
    cfg = PreprocessConfig(**json.loads((Path(processed_dir) / "stats.json").read_text())["config"])
    return get_region(cfg.region).n_cells(cfg.cell_deg)


# ---------------------------------------------------------------------- run

def run(interim_dir: Path, out_dir: Path, cfg: PreprocessConfig | None = None) -> dict:
    cfg = cfg or PreprocessConfig()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    clock0 = time.perf_counter()

    def stage(name: str) -> None:
        log.info("%-10s done at %6.0fs", name, time.perf_counter() - clock0)

    raw = load_interim(interim_dir)
    stage("load")
    points, stats = clean(raw, cfg)
    del raw
    stage("clean")
    points, gaps = segment(points, cfg)
    stats["tracks"] = int(points.track_id.nunique())
    stats["gap_events"] = int(len(gaps))
    stage("segment")
    log.info("resampling %d tracks", stats["tracks"])
    tracks = resample(points, cfg)
    del points
    stats["grid_rows"] = int(len(tracks))
    stats["grid_valid_frac"] = float(tracks.feat_valid.mean())
    stage("resample")

    windows = make_windows(tracks, cfg)
    stage("windows")
    if cfg.split_cutoff:
        cutoff = pd.Timestamp(cfg.split_cutoff)
    else:
        t0, t1 = tracks.t.min(), tracks.t.max()
        cutoff = (t0 + (t1 - t0) * 2 / 3).normalize()
    windows["split"] = assign_splits(windows, cutoff, cfg)
    stats["split_cutoff"] = str(cutoff.date())
    stats["windows"] = windows.split.value_counts().to_dict()
    stats["vessels"] = windows.groupby("split").mmsi.nunique().to_dict()
    stats["stationary_frac"] = windows.groupby("split").is_stationary.mean().round(3).to_dict()

    train = windows[windows.split == "train"]
    if train.empty:
        raise ValueError("no training windows; check the date range and split settings")
    norm = Normalizer.fit(window_array(tracks, train.row0.to_numpy(), cfg.window_len, FEATURES))

    stage("split+norm")
    tracks.to_parquet(out_dir / "tracks.parquet", index=False)
    windows.to_parquet(out_dir / "windows.parquet", index=False)
    gaps.to_parquet(out_dir / "gaps.parquet", index=False)
    norm.save(out_dir / "normalizer.json")
    stats["config"] = asdict(cfg)
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2, default=str))
    stage("write")
    log.info("done: %s", {k: v for k, v in stats.items() if k != "config"})
    return stats


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Clean, segment, resample, and window cropped AIS data.")
    p.add_argument("--interim", type=Path, default=Path("data/interim/chesapeake"))
    p.add_argument("--out", type=Path, default=Path("data/processed/chesapeake"))
    p.add_argument("--split-cutoff", default=None, help="ISO date; default is two-thirds through the data")
    p.add_argument("--holdout-frac", type=float, default=0.3)
    p.add_argument("--transceivers", default="A",
                   help="comma-separated transceiver classes to keep, or 'all' (the main study is A only; "
                        "write other populations to a different --out)")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    tx = None if a.transceivers == "all" else tuple(t.strip() for t in a.transceivers.split(","))
    run(a.interim, a.out, PreprocessConfig(split_cutoff=a.split_cutoff, holdout_frac=a.holdout_frac, transceivers=tx))


if __name__ == "__main__":
    main()
