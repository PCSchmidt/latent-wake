"""Seeded synthetic anomalies, applied to one resampled window at a time.

Every injector takes the window's raw fields (lat, lon, sog, cog, heading, each
shape (L,)), a numpy Generator, and a severity parameter. It returns an
`Injection` with modified copies, a per-step boolean label, and the exact
parameters used. Step 0 is never modified, so its displacement feature (which
depends on the step before the window) stays valid.

Two families, on purpose:
    Kinematically inconsistent  position_spoof, teleport, ais_gap
        positions disagree with the reported speed and course. These are what an
        action-conditioned world model should catch.
    Kinematically consistent    route_deviation, loitering
        reported speed and course match the motion; only the behavior is unusual.
        These are a fair test of whether the model learned normal behavior at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from latentwake.data.geo import KNOTS_TO_MPS, METERS_PER_NMI, integrate_displacement, step_displacement

STEP_S = 120  # must match the preprocessing grid


@dataclass
class Injection:
    kind: str
    lat: np.ndarray
    lon: np.ndarray
    sog: np.ndarray
    cog: np.ndarray
    heading: np.ndarray
    label: np.ndarray
    params: dict = field(default_factory=dict)

    def fields(self) -> dict[str, np.ndarray]:
        return {"lat": self.lat, "lon": self.lon, "sog": self.sog, "cog": self.cog, "heading": self.heading}


def _xy(raw):
    """Track coordinates: running sum of the same per-step moves the features use.

    Editing x/y and converting back with integrate_displacement is exact, so an
    injected anomaly changes the features by precisely what it intends.
    """
    lat0, lon0 = float(raw["lat"][0]), float(raw["lon"][0])
    dx, dy = step_displacement(raw["lat"], raw["lon"])
    dx[0] = dy[0] = 0.0
    return np.cumsum(dx), np.cumsum(dy), lat0, lon0


def _onset(rng: np.random.Generator, L: int, duration: int, min_context: int | None = None) -> int:
    """Start step: leave at least a quarter of the window as clean context."""
    lo = min_context if min_context is not None else L // 4
    hi = max(lo, L - duration)
    return int(rng.integers(lo, hi + 1))


def _finish(kind, raw, x, y, lat0, lon0, label, params, sog=None, cog=None, heading=None) -> Injection:
    lat, lon = integrate_displacement(lat0, lon0, np.diff(x, prepend=x[0]), np.diff(y, prepend=y[0]))
    return Injection(
        kind=kind,
        lat=lat,
        lon=lon,
        sog=np.array(raw["sog"] if sog is None else sog, dtype=np.float64),
        cog=np.array(raw["cog"] if cog is None else cog, dtype=np.float64),
        heading=np.array(raw["heading"] if heading is None else heading, dtype=np.float64),
        label=label,
        params=params,
    )


def position_spoof(raw, rng, offset_nmi: float, duration_steps: int | None = None) -> Injection:
    """Shift reported positions by a fixed offset while speed and course stay unchanged."""
    L = len(raw["lat"])
    d = int(duration_steps or rng.integers(8, 33))  # 1 to 4 chunks
    s = _onset(rng, L, d)
    bearing = float(rng.uniform(0, 360))
    x, y, lat0, lon0 = _xy(raw)
    off = offset_nmi * METERS_PER_NMI
    e = min(L, s + d)
    x, y = x.copy(), y.copy()
    x[s:e] += off * np.sin(np.radians(bearing))
    y[s:e] += off * np.cos(np.radians(bearing))
    label = np.zeros(L, dtype=bool)
    label[s:e] = True
    params = {"offset_nmi": offset_nmi, "duration_steps": e - s, "onset": s, "bearing_deg": bearing}
    return _finish("position_spoof", raw, x, y, lat0, lon0, label, params)


def teleport(raw, rng, distance_nmi: float) -> Injection:
    """One report jumps away, then the track returns to normal."""
    L = len(raw["lat"])
    s = _onset(rng, L, 1)
    bearing = float(rng.uniform(0, 360))
    x, y, lat0, lon0 = _xy(raw)
    x, y = x.copy(), y.copy()
    off = distance_nmi * METERS_PER_NMI
    x[s] += off * np.sin(np.radians(bearing))
    y[s] += off * np.cos(np.radians(bearing))
    label = np.zeros(L, dtype=bool)
    label[s] = True
    params = {"distance_nmi": distance_nmi, "onset": s, "bearing_deg": bearing}
    return _finish("teleport", raw, x, y, lat0, lon0, label, params)


def route_deviation(raw, rng, turn_deg: float, speed_factor: float | None = None, ramp_steps: int = 4) -> Injection:
    """Turn off the original route (and optionally change speed) from onset to the end of the window.

    Displacements are rotated and scaled, and reported speed, course, and heading
    are updated to match, so the motion stays physically consistent.
    """
    L = len(raw["lat"])
    s = _onset(rng, L, L // 4)
    sign = float(rng.choice([-1.0, 1.0]))
    speed_factor = float(speed_factor if speed_factor is not None else rng.uniform(0.8, 1.2))
    x, y, lat0, lon0 = _xy(raw)
    dx, dy = np.diff(x, prepend=x[0]), np.diff(y, prepend=y[0])
    k = np.arange(L)
    ramp = np.clip((k - s + 1) / max(ramp_steps, 1), 0.0, 1.0)
    ang = np.radians(sign * turn_deg) * ramp  # 0 before onset
    scale = np.where(k >= s, 1.0 + (speed_factor - 1.0) * ramp, 1.0)
    c, si = np.cos(ang), np.sin(ang)
    # Compass rotation (clockwise for positive angles): east/north components.
    ndx = (dx * c + dy * si) * scale
    ndy = (-dx * si + dy * c) * scale
    nx, ny = np.cumsum(ndx), np.cumsum(ndy)
    turn = np.degrees(ang)
    cog = np.mod(np.asarray(raw["cog"]) + turn, 360.0)
    heading = np.where(np.isfinite(raw["heading"]), np.mod(np.asarray(raw["heading"]) + turn, 360.0), np.nan)
    sog = np.asarray(raw["sog"]) * scale
    label = k >= s
    params = {"turn_deg": sign * turn_deg, "speed_factor": speed_factor, "onset": s}
    return _finish("route_deviation", raw, nx, ny, lat0, lon0, label, params, sog=sog, cog=cog, heading=heading)


def loitering(raw, rng, duration_steps: int, speed_kn: float | None = None, radius_m: float | None = None) -> Injection:
    """Replace a stretch of normal transit with slow circling, then resume the original motion."""
    L = len(raw["lat"])
    d = int(min(duration_steps, L - L // 4))
    s = _onset(rng, L, d)
    speed_kn = float(speed_kn if speed_kn is not None else rng.uniform(1.0, 3.0))
    radius_m = float(radius_m if radius_m is not None else rng.uniform(200.0, 600.0))
    x, y, lat0, lon0 = _xy(raw)
    dx, dy = np.diff(x, prepend=x[0]), np.diff(y, prepend=y[0])
    sog = np.asarray(raw["sog"], dtype=np.float64).copy()
    cog = np.asarray(raw["cog"], dtype=np.float64).copy()
    heading = np.asarray(raw["heading"], dtype=np.float64).copy()

    step_m = speed_kn * KNOTS_TO_MPS * STEP_S
    dtheta = step_m / radius_m * float(rng.choice([-1.0, 1.0]))  # radians of arc per step
    c0 = np.radians(cog[s - 1]) if np.isfinite(cog[s - 1]) else 0.0
    e = s + d
    for i in range(s, e):
        course = c0 + dtheta * (i - s + 1)
        dx[i], dy[i] = step_m * np.sin(course), step_m * np.cos(course)
        sog[i] = speed_kn
        cog[i] = np.mod(np.degrees(course), 360.0)
        if np.isfinite(heading[i]):
            heading[i] = cog[i]
    nx, ny = np.cumsum(dx), np.cumsum(dy)
    label = np.zeros(L, dtype=bool)
    label[s:e] = True
    params = {"duration_steps": d, "speed_kn": speed_kn, "radius_m": radius_m, "onset": s}
    return _finish("loitering", raw, nx, ny, lat0, lon0, label, params, sog=sog, cog=cog, heading=heading)


def ais_gap(raw, rng, gap_steps: int, jump_nmi: float = 1.0) -> Injection:
    """The vessel goes dark, then reappears somewhere its last report did not predict.

    On the 2-minute grid a gap looks like what resampling produces: a straight
    line from the last report to the next, with speed, course, and heading held
    at their last reported (stale) values.
    """
    L = len(raw["lat"])
    g = int(min(gap_steps, L - L // 4 - 1))
    s = _onset(rng, L, g + 1)
    e = s + g  # first report after the gap
    bearing = float(rng.uniform(0, 360))
    x, y, lat0, lon0 = _xy(raw)
    x, y = x.copy(), y.copy()
    off = jump_nmi * METERS_PER_NMI
    x[e:] += off * np.sin(np.radians(bearing))
    y[e:] += off * np.cos(np.radians(bearing))
    frac = np.arange(1, g + 1) / (g + 1)
    x[s:e] = x[s - 1] + (x[e] - x[s - 1]) * frac
    y[s:e] = y[s - 1] + (y[e] - y[s - 1]) * frac
    sog = np.asarray(raw["sog"], dtype=np.float64).copy()
    cog = np.asarray(raw["cog"], dtype=np.float64).copy()
    heading = np.asarray(raw["heading"], dtype=np.float64).copy()
    sog[s:e], cog[s:e], heading[s:e] = sog[s - 1], cog[s - 1], heading[s - 1]
    label = np.zeros(L, dtype=bool)
    label[s : e + 1] = True
    params = {"gap_steps": g, "jump_nmi": jump_nmi, "onset": s, "bearing_deg": bearing}
    return _finish("ais_gap", raw, x, y, lat0, lon0, label, params, sog=sog, cog=cog, heading=heading)


INJECTORS = {
    "position_spoof": position_spoof,
    "teleport": teleport,
    "route_deviation": route_deviation,
    "loitering": loitering,
    "ais_gap": ais_gap,
}

# Severity sweeps: one test cell per (kind, level). Small levels are meant to be
# nearly invisible so the detection-vs-severity curve has a real lower end.
DEFAULT_GRID: dict[str, list[dict]] = {
    "position_spoof": [{"offset_nmi": v} for v in (0.1, 0.25, 0.5, 1.0, 2.0, 5.0)],
    "teleport": [{"distance_nmi": v} for v in (0.1, 0.25, 0.5, 1.0, 2.0, 5.0)],
    "route_deviation": [{"turn_deg": v} for v in (5.0, 10.0, 20.0, 45.0, 90.0)],
    "loitering": [{"duration_steps": v} for v in (8, 16, 32)],
    "ais_gap": [{"gap_steps": g, "jump_nmi": j} for g in (5, 10, 20) for j in (0.0, 1.0, 3.0)],
}

# Kinds that only make sense for a vessel that is actually under way.
NEEDS_MOTION = {"route_deviation", "loitering"}
