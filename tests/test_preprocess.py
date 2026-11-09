"""Tests for cleaning, segmentation, resampling, windowing, splits, and the full run."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from latentwake.data import preprocess as pp
from latentwake.data.features import FEATURES, SCALED, vessel_class
from latentwake.data.synthetic import simulate_days, write_interim

CFG = pp.PreprocessConfig()


def _pts(rows):
    """rows: (mmsi, 'HH:MM:SS', lat, lon, sog, cog, heading)."""
    df = pd.DataFrame(rows, columns=["mmsi", "t", "lat", "lon", "sog", "cog", "heading"])
    df["t"] = pd.to_datetime("2025-04-01 " + df.t)
    df["vessel_type"] = 70
    return df


def test_epoch_seconds_ignores_timestamp_resolution():
    s_ns = pd.Series(pd.to_datetime(["2025-04-01 00:00:00", "2025-04-01 00:02:00"]))
    s_us = s_ns.astype("datetime64[us]")
    assert np.allclose(pp._epoch_s(s_ns), pp._epoch_s(s_us))
    assert pp._epoch_s(s_ns)[1] - pp._epoch_s(s_ns)[0] == 120


def test_clean_rules():
    df = _pts(
        [
            (366000001, "00:00:00", 37.0, -76.3, 10.0, 90.0, 90),
            (366000001, "00:00:00", 37.0, -76.3, 10.0, 90.0, 90),     # duplicate
            (366000001, "00:01:00", 37.0, -76.2967, 102.3, 360.0, 511),  # sentinels -> NaN
            (366000001, "00:02:00", 37.5, -76.2934, 10.0, 90.0, 90),  # 30 nmi jump in 1 min -> outlier
            (366000001, "00:03:00", 37.0, -76.2901, 10.0, 90.0, 90),
            (366000001, "00:04:00", 37.0, -76.2868, 75.0, 90.0, 90),  # SOG over 50 kn -> dropped
            (993660001, "00:00:00", 37.0, -76.3, 0.0, 0.0, 0),        # aid to navigation -> dropped
        ]
    )
    out, stats = pp.clean(df, CFG)
    assert stats["rows_in"] == 7
    assert out.mmsi.unique().tolist() == [366000001]
    assert len(out) == 3
    assert out.lat.max() < 37.1  # the jump is gone
    sentinel = out[out.t == pd.Timestamp("2025-04-01 00:01:00")].iloc[0]
    assert np.isnan(sentinel.sog) and np.isnan(sentinel.cog) and np.isnan(sentinel.heading)


def test_segment_splits_long_silences_and_logs_them():
    rows = [(366000001, f"00:{m:02d}:00", 37.0, -76.3 + m * 1e-3, 5.0, 90.0, 90) for m in range(12)]
    rows += [(366000001, f"01:{m:02d}:00", 37.0, -76.2 + m * 1e-3, 5.0, 90.0, 90) for m in range(12)]
    df, _ = pp.clean(_pts(rows), CFG)
    pts, gaps = pp.segment(df, CFG)
    assert pts.track_id.nunique() == 2
    assert len(gaps) == 1
    assert gaps.gap_s.iat[0] == 49 * 60
    assert gaps.jump_m.iat[0] > 0


def test_resample_grid_interpolation_and_validity():
    t = np.array([0, 60, 130, 250, 1000, 1060], dtype=float) + 1_743_465_600  # 2025-04-01
    lat = np.linspace(37.0, 37.01, t.size)
    lon = np.full(t.size, -76.3)
    sog = np.full(t.size, 8.0)
    cog = np.array([358.0, 359.0, 1.0, 2.0, 3.0, 4.0])
    heading = np.array([358.0, 359.0, 1.0, np.nan, np.nan, 4.0])
    r = pp.resample_track(t, lat, lon, sog, cog, heading, CFG)
    assert np.all(np.mod(r["t"], 120) == 0)
    assert np.all(np.diff(r["t"]) == 120)
    # Grid points inside the 750-second hole are invalid; the rest are valid.
    rel = r["t"] - t[0]
    hole = (rel > 250) & (rel < 1000)
    assert not r["valid"][hole].any() and r["valid"][~hole].all()
    # Course interpolates across north (~0), not through south (~180).
    near_north = np.minimum(r["cog"], 360 - r["cog"])
    assert near_north.max() < 10
    np.testing.assert_allclose(r["lat"], np.interp(r["t"], t, lat))


def test_windows_only_cover_valid_runs():
    n = 200
    tracks = pd.DataFrame(
        {
            "track_id": np.r_[np.zeros(150, int), np.ones(50, int)],
            "mmsi": 366000001,
            "vessel_class": 1,
            "t": pd.date_range("2025-04-01", periods=n, freq="2min"),
            "sog_kn": 5.0,
            "feat_valid": True,
        }
    )
    tracks.loc[0, "feat_valid"] = False
    tracks.loc[100, "feat_valid"] = False  # breaks track 0 into runs of 99 and 49
    w = pp.make_windows(tracks, CFG)
    assert w.row0.tolist() == [1, 17, 33]  # only the 99-step run fits a 64-step window
    fv = tracks.feat_valid.to_numpy()
    for r0 in w.row0:
        assert fv[r0 : r0 + 64].all()
        assert tracks.track_id.iat[r0] == tracks.track_id.iat[r0 + 63]


def test_vessel_class_mapping():
    assert vessel_class(71) == vessel_class(1004) != vessel_class(84)
    assert vessel_class(None) == vessel_class(0) == 0


@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic")
    write_interim(simulate_days(dt.date(2025, 4, 1), n_days=6, n_vessels=30, seed=3), root / "interim")
    stats = pp.run(root / "interim", root / "processed")
    return root / "processed", stats


def test_run_writes_outputs(processed):
    out, stats = processed
    for name in ("tracks.parquet", "windows.parquet", "gaps.parquet", "normalizer.json", "stats.json"):
        assert (out / name).exists()
    assert stats["windows"]["train"] > 0 and stats["windows"].get("test", 0) > 0


def test_splits_do_not_leak(processed):
    out, stats = processed
    w = pd.read_parquet(out / "windows.parquet")
    cutoff = pd.Timestamp(stats["split_cutoff"])
    train, held = w[w.split == "train"], w[w.split.isin(["val", "test"])]
    assert set(train.mmsi).isdisjoint(held.mmsi)
    assert set(w[w.split == "val"].mmsi).isdisjoint(w[w.split == "test"].mmsi)
    assert (train.t_end < cutoff).all() and (held.t_start >= cutoff).all()


def test_loaded_training_windows_are_standardized(processed):
    out, _ = processed
    X, meta = pp.load_split(out, "train")
    assert X.shape[1:] == (64, len(FEATURES)) and len(meta) == len(X)
    assert np.isfinite(X).all()
    for name in SCALED:
        col = X[..., FEATURES.index(name)]
        assert abs(col.mean()) < 1e-3 and abs(col.std() - 1) < 1e-2


def test_raw_fields_line_up_with_features(processed):
    out, _ = processed
    X, _, raw = pp.load_split(out, "val", normalized=False, raw=True)
    from latentwake.data.features import step_features

    f = step_features(raw["lat"][0], raw["lon"][0], raw["sog"][0], raw["cog"][0], raw["heading"][0])
    np.testing.assert_allclose(f[1:, :2], X[0, 1:, :2], atol=0.05)  # meters


def _windows_reference(fv, tid, L, stride):
    """Slow, obviously-correct windowing used to check the fast version."""
    starts, i, n = [], 0, len(fv)
    while i < n:
        if not fv[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and fv[j + 1] and tid[j + 1] == tid[i]:
            j += 1
        starts.extend(range(i, j - L + 2, stride))
        i = j + 1
    return starts


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_fast_windows_match_reference(seed):
    rng = np.random.default_rng(seed)
    n = 5000
    tid = np.cumsum(rng.random(n) < 0.01)
    fv = rng.random(n) > 0.005
    tracks = pd.DataFrame({"track_id": tid, "mmsi": 366000001, "vessel_class": 1,
                           "t": pd.date_range("2025-04-01", periods=n, freq="2min"), "sog_kn": 5.0, "feat_valid": fv})
    assert pp.make_windows(tracks, CFG).row0.tolist() == _windows_reference(fv, tid, 64, 16)


def test_windowing_scales_linearly():
    import time

    n = 2_000_000
    rng = np.random.default_rng(0)
    tracks = pd.DataFrame({"track_id": np.cumsum(rng.random(n) < 0.003), "mmsi": 366000001, "vessel_class": 1,
                           "t": pd.Timestamp("2025-04-01"), "sog_kn": 5.0, "feat_valid": rng.random(n) > 0.002})
    t0 = time.perf_counter()
    pp.make_windows(tracks, CFG)
    assert time.perf_counter() - t0 < 5.0  # the quadratic version took hours at this size
