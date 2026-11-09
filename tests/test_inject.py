"""Tests for the anomaly injectors and the frozen test-set builder."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from latentwake.data.features import FEATURES, step_features
from latentwake.data.geo import KNOTS_TO_MPS, METERS_PER_NMI, integrate_displacement, step_displacement
from latentwake.inject.anomalies import DEFAULT_GRID, INJECTORS
from latentwake.inject.build import build_test_set, load_test_set, save_test_set

L = 64


def straight_window(course=45.0, speed_kn=12.0, lat0=37.0, lon0=-76.3):
    """A perfectly consistent straight-line transit on the 2-minute grid."""
    step = speed_kn * KNOTS_TO_MPS * 120
    dx = np.full(L, step * np.sin(np.radians(course)))
    dy = np.full(L, step * np.cos(np.radians(course)))
    lat, lon = integrate_displacement(lat0, lon0, dx, dy)
    return {
        "lat": lat,
        "lon": lon,
        "sog": np.full(L, speed_kn),
        "cog": np.full(L, course),
        "heading": np.full(L, course),
    }


def consistency_residual(f):
    """Meters between observed displacement and what reported speed and course predict."""
    v = f[:, FEATURES.index("sog_kn")] * KNOTS_TO_MPS * 120
    px = v * f[:, FEATURES.index("sin_cog")]
    py = v * f[:, FEATURES.index("cos_cog")]
    return np.hypot(f[:, 0] - px, f[:, 1] - py)


def _feats(inj):
    return step_features(inj.lat, inj.lon, inj.sog, inj.cog, inj.heading)


def test_clean_window_is_consistent():
    raw = straight_window()
    assert consistency_residual(_feats(type("I", (), raw)))[1:].max() < 1.0


@pytest.mark.parametrize("kind", sorted(INJECTORS))
def test_common_contract(kind):
    raw = straight_window()
    level = DEFAULT_GRID[kind][-1]
    a = INJECTORS[kind](raw, np.random.default_rng(7), **level)
    b = INJECTORS[kind](raw, np.random.default_rng(7), **level)
    assert a.kind == kind
    assert a.label.shape == (L,) and a.label.any() and not a.label[0]
    assert a.lat[0] == raw["lat"][0] and a.lon[0] == raw["lon"][0]  # step 0 untouched
    for f in ("lat", "lon", "sog", "cog"):
        assert np.isfinite(getattr(a, f)).all()
        np.testing.assert_array_equal(getattr(a, f), getattr(b, f))  # same seed, same result
    assert a.params["onset"] >= L // 4


def test_spoof_moves_positions_but_not_reports():
    raw = straight_window()
    inj = INJECTORS["position_spoof"](raw, np.random.default_rng(1), offset_nmi=2.0, duration_steps=16)
    np.testing.assert_array_equal(inj.sog, raw["sog"])
    np.testing.assert_array_equal(inj.cog, raw["cog"])
    def track_xy(lat, lon):
        dx, dy = step_displacement(lat, lon)
        dx[0] = dy[0] = 0.0
        return np.cumsum(dx), np.cumsum(dy)

    x0, y0 = track_xy(raw["lat"], raw["lon"])
    x1, y1 = track_xy(inj.lat, inj.lon)
    shift = np.hypot(x1 - x0, y1 - y0)
    np.testing.assert_allclose(shift[inj.label], 2.0 * METERS_PER_NMI, rtol=1e-6)
    assert shift[~inj.label].max() < 1e-6
    res = consistency_residual(_feats(inj))
    assert res[inj.params["onset"]] > 3000  # the jump disagrees with the reports


def test_teleport_changes_one_step():
    raw = straight_window()
    inj = INJECTORS["teleport"](raw, np.random.default_rng(2), distance_nmi=1.0)
    # Positions match to float precision everywhere except the teleported step.
    moved = np.hypot((inj.lat - raw["lat"]) * 111_000, (inj.lon - raw["lon"]) * 89_000)
    assert (moved > 1.0).sum() == 1 and (moved[inj.label] > 1000).all()
    assert moved[~inj.label].max() < 0.5


@pytest.mark.parametrize("kind,level", [("route_deviation", {"turn_deg": 45.0}), ("loitering", {"duration_steps": 16})])
def test_behavioral_anomalies_stay_physically_consistent(kind, level):
    raw = straight_window()
    inj = INJECTORS[kind](raw, np.random.default_rng(3), **level)
    res = consistency_residual(_feats(inj))
    assert res[1:].max() < 1.0  # reports still match the motion everywhere
    assert not np.allclose(inj.lat, raw["lat"])  # but the path changed


def test_route_deviation_turns_by_the_requested_angle():
    raw = straight_window(course=10.0)
    inj = INJECTORS["route_deviation"](raw, np.random.default_rng(4), turn_deg=30.0, speed_factor=1.0)
    dx, dy = step_displacement(inj.lat, inj.lon)
    final_course = np.degrees(np.arctan2(dx[-1], dy[-1])) % 360
    assert abs(((final_course - 10.0 + 180) % 360) - 180) == pytest.approx(30.0, abs=0.01)


def test_ais_gap_holds_stale_reports_and_jumps():
    raw = straight_window()
    inj = INJECTORS["ais_gap"](raw, np.random.default_rng(5), gap_steps=10, jump_nmi=3.0)
    s, g = inj.params["onset"], inj.params["gap_steps"]
    assert (inj.sog[s : s + g] == raw["sog"][s - 1]).all()
    dx, dy = step_displacement(inj.lat, inj.lon)
    d0x, d0y = step_displacement(raw["lat"], raw["lon"])
    # After reappearing, the ship moves normally again from its displaced position.
    np.testing.assert_allclose(dx[s + g + 1 :], d0x[s + g + 1 :], atol=0.5)
    np.testing.assert_allclose(dy[s + g + 1 :], d0y[s + g + 1 :], atol=0.5)


def _toy_pool(n=120, seed=0):
    rng = np.random.default_rng(seed)
    raws = [straight_window(course=float(rng.uniform(0, 360)), speed_kn=float(rng.uniform(1, 15))) for _ in range(n)]
    raw = {f: np.stack([r[f] for r in raws]) for f in raws[0]}
    X = np.stack([step_features(*(r[f] for f in ("lat", "lon", "sog", "cog", "heading"))) for r in raws])
    X[:, 0] = 0.0  # stand in for the pre-window displacement
    # Alternate cargo (1) and tug_tow (5): only the cargo half may take behavioral anomalies.
    meta = pd.DataFrame({"window_id": np.arange(n), "mean_sog": raw["sog"].mean(axis=1),
                         "vessel_class": np.where(np.arange(n) % 2 == 0, 1, 5)})
    return X.astype(np.float32), raw, meta


def test_build_is_deterministic_and_keeps_normals_clean():
    X, raw, meta = _toy_pool()
    a = build_test_set(X, raw, meta, seed=0, per_cell=5, n_normal=40)
    b = build_test_set(X, raw, meta, seed=0, per_cell=5, n_normal=40)
    np.testing.assert_array_equal(a.X, b.X)
    pd.testing.assert_frame_equal(a.cells, b.cells)
    normal = a.cells.kind == "normal"
    assert normal.sum() == 40 and not a.step_label[normal.to_numpy()].any()
    assert a.label[~normal.to_numpy()].all()
    assert set(a.cells[normal].source_window).isdisjoint(a.cells[~normal].source_window)
    moving_kinds = a.cells.kind.isin(["route_deviation", "loitering"])
    assert (a.cells[moving_kinds].source_mean_sog >= 3.0).all()
    assert np.isfinite(a.X).all()


def test_freeze_detects_tampering_and_refuses_overwrite(tmp_path):
    X, raw, meta = _toy_pool()
    ts = build_test_set(X, raw, meta, seed=1, per_cell=3, n_normal=20)
    save_test_set(ts, tmp_path / "v1")
    loaded = load_test_set(tmp_path / "v1")
    np.testing.assert_array_equal(loaded.X, ts.X)
    with pytest.raises(FileExistsError):
        save_test_set(ts, tmp_path / "v1")
    cells = pd.read_csv(tmp_path / "v1" / "cells.csv")
    cells.loc[0, "kind"] = "edited"
    cells.to_csv(tmp_path / "v1" / "cells.csv", index=False)
    with pytest.raises(ValueError, match="checksum"):
        load_test_set(tmp_path / "v1")


def test_behavioral_kinds_only_in_moving_transit_vessels():
    from latentwake.inject.build import TRANSIT_CLASSES

    X, raw, meta = _toy_pool(n=160)
    ts = build_test_set(X, raw, meta, seed=0, per_cell=4, n_normal=40)
    beh = ts.cells.kind.isin(["route_deviation", "loitering"])
    assert beh.any()
    assert ts.cells[beh].source_vessel_class.isin(TRANSIT_CLASSES).all()
    kin = ts.cells.kind.isin(["position_spoof", "teleport", "ais_gap"])
    assert (ts.cells[kin].source_vessel_class == 5).any()  # kinematic kinds still hit every class


def test_location_cells_follow_injected_positions_and_are_checksummed(tmp_path):
    from latentwake.data.regions import get_region

    region = get_region("chesapeake")
    X, raw, meta = _toy_pool()
    loc = region.cell_index(raw["lat"], raw["lon"])
    ts = build_test_set(X, raw, meta, seed=2, per_cell=3, n_normal=20, loc=loc,
                        cell_fn=lambda la, lo: region.cell_index(la, lo))
    assert ts.loc.shape == ts.step_label.shape and ts.loc.dtype == np.int32
    normal = (ts.cells.kind == "normal").to_numpy()
    np.testing.assert_array_equal(ts.loc[normal], loc[ts.cells[normal].source_window.to_numpy()])
    save_test_set(ts, tmp_path / "v2")
    np.testing.assert_array_equal(load_test_set(tmp_path / "v2").loc, ts.loc)
    arrays = dict(np.load(tmp_path / "v2" / "arrays.npz"))
    arrays["loc"] = arrays["loc"] + 1
    np.savez_compressed(tmp_path / "v2" / "arrays.npz", **arrays)
    with pytest.raises(ValueError, match="checksum"):
        load_test_set(tmp_path / "v2")
