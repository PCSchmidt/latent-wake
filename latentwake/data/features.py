"""Per-step model features, shared by preprocessing and anomaly injection.

Both stages call `step_features`, so an injected anomaly is described in exactly
the same terms as real traffic. Features are deliberately relative (how far the
ship moved this step, what it reports) rather than absolute positions, so the
model learns motion, not the map.

Feature order (last axis of every window array):
    dx_m, dy_m      east/north displacement since the previous step, meters
    sog_kn          reported speed over ground, knots
    sin_cog, cos_cog  reported course over ground
    dheading_deg    change in reported heading since the previous step
    heading_valid   1 if both headings were reported, else 0 (dheading is 0)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from latentwake.data.geo import step_displacement, wrap_deg

FEATURES = ("dx_m", "dy_m", "sog_kn", "sin_cog", "cos_cog", "dheading_deg", "heading_valid")
# Features that are standardized; the flag stays 0/1.
SCALED = ("dx_m", "dy_m", "sog_kn", "dheading_deg")
RAW_FIELDS = ("lat", "lon", "sog", "cog", "heading")

VESSEL_CLASSES = (
    "unknown", "cargo", "tanker", "passenger", "fishing", "tug_tow",
    "pleasure", "military_law", "high_speed", "other",
)


def step_features(lat, lon, sog, cog, heading) -> np.ndarray:
    """Return a (T, len(FEATURES)) float32 array. Row 0 has NaN displacement."""
    dx, dy = step_displacement(lat, lon)
    cog_rad = np.radians(np.asarray(cog, dtype=np.float64))
    heading = np.asarray(heading, dtype=np.float64)
    hv = np.isfinite(heading)
    dh = np.zeros_like(heading)
    hv_pair = np.zeros(heading.shape, dtype=bool)
    if heading.size > 1:
        hv_pair[1:] = hv[1:] & hv[:-1]
        dh[1:] = np.where(hv_pair[1:], wrap_deg(heading[1:] - heading[:-1]), 0.0)
    out = np.stack(
        [dx, dy, np.asarray(sog, dtype=np.float64), np.sin(cog_rad), np.cos(cog_rad), dh, hv_pair.astype(float)],
        axis=-1,
    )
    return out.astype(np.float32)


def vessel_class(code) -> int:
    """Map an AIS ship-type code (or NOAA's 1001-1025 codes) to a coarse class index."""
    try:
        c = int(code)
    except (TypeError, ValueError):
        return 0
    if 70 <= c <= 79 or c in (1003, 1004, 1016):
        name = "cargo"
    elif 80 <= c <= 89 or c == 1024:
        name = "tanker"
    elif 60 <= c <= 69 or 1012 <= c <= 1015:
        name = "passenger"
    elif c == 30 or c in (1001, 1002):
        name = "fishing"
    elif c in (21, 22, 31, 32, 52, 1023, 1025):
        name = "tug_tow"
    elif c in (36, 37, 1019):
        name = "pleasure"
    elif c in (35, 51, 55, 1018, 1021):
        name = "military_law"
    elif 40 <= c <= 49:
        name = "high_speed"
    elif c == 0:
        name = "unknown"
    elif 20 <= c <= 99 or 1001 <= c <= 1025:
        name = "other"
    else:
        name = "unknown"
    return VESSEL_CLASSES.index(name)


@dataclass
class Normalizer:
    """Standardizes the scaled features with statistics from the training split only."""

    mean: dict[str, float]
    std: dict[str, float]

    @classmethod
    def fit(cls, windows: np.ndarray) -> "Normalizer":
        flat = windows.reshape(-1, windows.shape[-1]).astype(np.float64)
        mean, std = {}, {}
        for name in SCALED:
            col = flat[:, FEATURES.index(name)]
            col = col[np.isfinite(col)]
            mean[name] = float(col.mean())
            std[name] = float(max(col.std(), 1e-6))
        return cls(mean, std)

    def transform(self, windows: np.ndarray) -> np.ndarray:
        out = windows.astype(np.float32, copy=True)
        for name in SCALED:
            i = FEATURES.index(name)
            out[..., i] = (out[..., i] - self.mean[name]) / self.std[name]
        return out

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"features": FEATURES, "mean": self.mean, "std": self.std}, indent=2))

    @classmethod
    def load(cls, path: Path) -> "Normalizer":
        d = json.loads(path.read_text())
        if tuple(d["features"]) != FEATURES:
            raise ValueError("normalizer was fit on a different feature set")
        return cls(d["mean"], d["std"])
