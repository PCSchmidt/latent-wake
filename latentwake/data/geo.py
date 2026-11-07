"""Small geodesy helpers shared by the pipeline, the simulator, and the injectors.

Distances in this project are short (a 2-hour window covers at most a few tens
of nautical miles), so a local equirectangular projection is accurate to well
under 1% and much faster than full geodesics.
"""

from __future__ import annotations

import numpy as np

EARTH_RADIUS_M = 6_371_008.8
METERS_PER_NMI = 1852.0
KNOTS_TO_MPS = METERS_PER_NMI / 3600.0


def to_local_xy(lat, lon, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    """Degrees -> east/north meters relative to (lat0, lon0)."""
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    x = np.radians(lon - lon0) * EARTH_RADIUS_M * np.cos(np.radians(lat0))
    y = np.radians(lat - lat0) * EARTH_RADIUS_M
    return x, y


def from_local_xy(x, y, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    """East/north meters relative to (lat0, lon0) -> degrees."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    lat = lat0 + np.degrees(y / EARTH_RADIUS_M)
    lon = lon0 + np.degrees(x / (EARTH_RADIUS_M * np.cos(np.radians(lat0))))
    return lat, lon


def step_displacement(lat, lon) -> tuple[np.ndarray, np.ndarray]:
    """East/north meters moved between consecutive points; first entry is NaN.

    Each step is projected around its own starting point, so long tracks keep
    the same accuracy as short ones.
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    dx = np.full(lat.shape, np.nan)
    dy = np.full(lat.shape, np.nan)
    if lat.size > 1:
        dlon = np.radians(np.diff(lon))
        dlat = np.radians(np.diff(lat))
        coslat = np.cos(np.radians(lat[:-1]))
        dx[1:] = dlon * EARTH_RADIUS_M * coslat
        dy[1:] = dlat * EARTH_RADIUS_M
    return dx, dy


def integrate_displacement(lat0: float, lon0: float, dx, dy) -> tuple[np.ndarray, np.ndarray]:
    """Exact inverse of step_displacement: rebuild positions from per-step moves.

    dx[0] and dy[0] are ignored (the first point is (lat0, lon0)), matching the
    NaN that step_displacement returns there.
    """
    dx = np.nan_to_num(np.asarray(dx, dtype=np.float64))
    dy = np.nan_to_num(np.asarray(dy, dtype=np.float64))
    dlat = np.degrees(dy[1:] / EARTH_RADIUS_M)
    lat = lat0 + np.r_[0.0, np.cumsum(dlat)]
    dlon = np.degrees(dx[1:] / (EARTH_RADIUS_M * np.cos(np.radians(lat[:-1]))))
    lon = lon0 + np.r_[0.0, np.cumsum(dlon)]
    return lat, lon


def course_from_xy(dx, dy) -> np.ndarray:
    """Compass course in degrees [0, 360) for an east/north displacement."""
    return np.mod(np.degrees(np.arctan2(dx, dy)), 360.0)


def wrap_deg(angle) -> np.ndarray:
    """Wrap degrees to [-180, 180)."""
    return np.mod(np.asarray(angle, dtype=np.float64) + 180.0, 360.0) - 180.0


def circular_interp(t_new, t, deg) -> np.ndarray:
    """Interpolate angles in degrees without the 359 -> 0 jump."""
    rad = np.radians(np.asarray(deg, dtype=np.float64))
    s = np.interp(t_new, t, np.sin(rad))
    c = np.interp(t_new, t, np.cos(rad))
    return np.mod(np.degrees(np.arctan2(s, c)), 360.0)
