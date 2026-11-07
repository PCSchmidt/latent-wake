"""Synthetic AIS traffic for tests and offline prototyping.

This is not a realistic model of Chesapeake traffic: there is no coastline and
routes are random. It exists so every stage after the download can be built,
tested, and smoke-trained without network access, using files in exactly the
format the download step writes.

Each vessel follows simple kinematics (turn-rate-limited steering toward
waypoints, speed that wanders around a cruise value), reports roughly once a
minute like NOAA's downsampled feed, and carries realistic flaws: position
noise, unreliable course at low speed, dropped reports, occasional dark gaps,
missing headings on Class B units, and NOAA's "not available" sentinel values.

Usage:
    python -m latentwake.data.synthetic --days 7 --vessels 60 --out data/interim/synthetic
"""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from latentwake.data.download import CANONICAL_COLUMNS
from latentwake.data.geo import KNOTS_TO_MPS, from_local_xy, wrap_deg
from latentwake.data.regions import BBox, get_region


@dataclass(frozen=True)
class Archetype:
    name: str
    vessel_types: tuple[int, ...]
    cruise_kn: tuple[float, float]
    max_turn_deg_s: float
    leg_km: tuple[float, float]
    class_b_prob: float
    length_m: tuple[float, float]


ARCHETYPES = {
    "transit": Archetype("transit", (70, 71, 79, 80, 84), (10.0, 16.0), 0.4, (15.0, 40.0), 0.0, (150, 300)),
    "tug": Archetype("tug", (31, 52), (4.0, 9.0), 1.5, (3.0, 12.0), 0.3, (20, 40)),
    "ferry": Archetype("ferry", (60, 69), (11.0, 15.0), 1.0, (8.0, 15.0), 0.0, (40, 90)),
    "fishing": Archetype("fishing", (30,), (2.0, 6.0), 2.0, (1.0, 4.0), 0.6, (12, 30)),
    "anchored": Archetype("anchored", (70, 80), (0.0, 0.0), 0.0, (0.0, 0.0), 0.0, (150, 300)),
}
MIX = {"transit": 0.35, "tug": 0.2, "ferry": 0.1, "fishing": 0.15, "anchored": 0.2}

SIM_DT_S = 10.0
REPORT_EVERY_S = 60.0


@dataclass
class Vessel:
    mmsi: int
    archetype: Archetype
    vessel_type: int
    class_b: bool
    length: float
    home_x: float
    home_y: float


def make_fleet(n: int, box: BBox, rng: np.random.Generator) -> list[Vessel]:
    names = list(MIX)
    probs = np.array([MIX[k] for k in names])
    half_w, half_h = _box_half_extent_m(box)
    fleet = []
    for i in range(n):
        arch = ARCHETYPES[rng.choice(names, p=probs / probs.sum())]
        fleet.append(
            Vessel(
                mmsi=366_000_000 + i * 7 + int(rng.integers(0, 7)),  # US MID, distinct
                archetype=arch,
                vessel_type=int(rng.choice(arch.vessel_types)),
                class_b=bool(rng.random() < arch.class_b_prob),
                length=float(rng.uniform(*arch.length_m)),
                home_x=float(rng.uniform(-0.6, 0.6) * half_w),
                home_y=float(rng.uniform(-0.6, 0.6) * half_h),
            )
        )
    return fleet


def _box_half_extent_m(box: BBox) -> tuple[float, float]:
    lat0 = (box.lat_min + box.lat_max) / 2
    half_h = np.radians(box.lat_max - box.lat_min) / 2 * 6_371_008.8
    half_w = np.radians(box.lon_max - box.lon_min) / 2 * 6_371_008.8 * np.cos(np.radians(lat0))
    return float(half_w), float(half_h)


def _route(v: Vessel, rng: np.random.Generator, half_w: float, half_h: float, n_legs: int):
    """Waypoints in local meters, kept inside 90% of the box."""
    pts = [(v.home_x, v.home_y)]
    heading = rng.uniform(0, 2 * np.pi)
    for _ in range(n_legs):
        leg = rng.uniform(*v.archetype.leg_km) * 1000
        heading += rng.normal(0, 0.6)
        x = float(np.clip(pts[-1][0] + leg * np.sin(heading), -0.9 * half_w, 0.9 * half_w))
        y = float(np.clip(pts[-1][1] + leg * np.cos(heading), -0.9 * half_h, 0.9 * half_h))
        pts.append((x, y))
    if v.archetype.name == "ferry":
        pts = pts[:2] * 8  # shuttle between two terminals
    return pts


def simulate_vessel_day(v: Vessel, day: dt.date, box: BBox, rng: np.random.Generator) -> pd.DataFrame:
    half_w, half_h = _box_half_extent_m(box)
    lat0 = (box.lat_min + box.lat_max) / 2
    lon0 = (box.lon_min + box.lon_max) / 2
    arch = v.archetype

    # Active window within the day.
    start_s = float(rng.uniform(0, 6 * 3600))
    dur_s = float(rng.uniform(6 * 3600, 18 * 3600))
    n_steps = int(dur_s / SIM_DT_S)

    x, y = v.home_x, v.home_y
    cruise = float(rng.uniform(*arch.cruise_kn)) if arch.cruise_kn[1] > 0 else 0.0
    speed = cruise
    route = _route(v, rng, half_w, half_h, n_legs=12) if cruise > 0 else [(x, y)]
    wp = 1
    course = float(rng.uniform(0, 360))
    dwell = 0.0
    swing = float(rng.uniform(0, 360))  # anchored ships swing on the chain

    xs = np.empty(n_steps)
    ys = np.empty(n_steps)
    sogs = np.empty(n_steps)
    cogs = np.empty(n_steps)
    heads = np.empty(n_steps)
    for k in range(n_steps):
        if cruise == 0.0:
            swing += rng.normal(0, 0.5)
            ang = np.radians(swing)
            xs[k], ys[k] = x + 40 * np.sin(ang), y + 40 * np.cos(ang)
            sogs[k], cogs[k], heads[k] = abs(rng.normal(0, 0.1)), rng.uniform(0, 360), np.mod(swing + 180, 360)
            continue
        if dwell > 0:
            dwell -= SIM_DT_S
            speed = max(0.0, speed - 0.5)
        elif wp < len(route):
            tx, ty = route[wp]
            dist = np.hypot(tx - x, ty - y)
            if dist < 300:
                wp += 1
                if arch.name == "ferry":
                    dwell = float(rng.uniform(10, 25) * 60)
            desired = np.degrees(np.arctan2(tx - x, ty - y)) % 360
            turn = np.clip(wrap_deg(desired - course), -arch.max_turn_deg_s * SIM_DT_S, arch.max_turn_deg_s * SIM_DT_S)
            course = (course + turn) % 360
            speed += 0.05 * (cruise - speed) + rng.normal(0, 0.05)
        else:
            speed = max(0.0, speed - 0.3)  # route finished: slow to a stop
        speed = max(0.0, speed)
        mps = speed * KNOTS_TO_MPS
        x += mps * SIM_DT_S * np.sin(np.radians(course))
        y += mps * SIM_DT_S * np.cos(np.radians(course))
        xs[k], ys[k], sogs[k], cogs[k] = x, y, speed, course
        heads[k] = (course + rng.normal(0, 1.5)) % 360

    # Report about once a minute with jitter, dropped messages, and maybe a dark gap.
    t_sim = start_s + np.arange(n_steps) * SIM_DT_S
    report_t, t = [], start_s
    while t < t_sim[-1]:
        report_t.append(t)
        t += REPORT_EVERY_S + rng.uniform(-8, 8)
    report_t = np.array(report_t)
    keep = rng.random(report_t.size) > 0.03
    if rng.random() < 0.15 and report_t.size > 200:
        g0 = rng.integers(50, report_t.size - 100)
        keep[g0 : g0 + int(rng.uniform(35, 90))] = False
    report_t = report_t[keep]
    idx = np.clip(np.searchsorted(t_sim, report_t), 0, n_steps - 1)

    px = xs[idx] + rng.normal(0, 8, idx.size)
    py = ys[idx] + rng.normal(0, 8, idx.size)
    lat, lon = from_local_xy(px, py, lat0, lon0)
    sog = np.round(np.clip(sogs[idx] + rng.normal(0, 0.1, idx.size), 0, None), 1)
    cog_noise = np.minimum(180.0, 2.0 + 15.0 / np.maximum(sogs[idx], 0.2))
    cog = np.round(np.mod(cogs[idx] + rng.normal(0, 1, idx.size) * cog_noise, 360), 1)
    heading = np.round(heads[idx]).astype(float)
    if v.class_b:
        heading[:] = 511  # Class B units often send no heading
    # Sprinkle NOAA "not available" sentinels.
    sog[rng.random(idx.size) < 0.002] = 102.3
    cog[rng.random(idx.size) < 0.002] = 360.0

    base = pd.Timestamp(day)
    times = base + pd.to_timedelta(np.round(report_t), unit="s")
    n = idx.size
    df = pd.DataFrame(
        {
            "mmsi": np.full(n, v.mmsi, dtype=np.int64),
            "base_date_time": times,
            "latitude": np.round(lat, 5),
            "longitude": np.round(lon, 5),
            "sog": sog,
            "cog": cog,
            "heading": heading,
            "vessel_name": f"SIM {v.mmsi}",
            "imo": None,
            "call_sign": None,
            "vessel_type": np.full(n, v.vessel_type, dtype=np.int32),
            "status": np.full(n, 1 if v.archetype.name == "anchored" else 0, dtype=np.int32),
            "length": round(v.length, 0),
            "width": round(v.length / 6, 0),
            "draft": 10.0 if v.archetype.name in ("transit", "anchored") else 3.0,
            "cargo": np.full(n, v.vessel_type, dtype=np.int32),
            "transceiver": "B" if v.class_b else "A",
        }
    )
    df = df[(df.base_date_time < base + pd.Timedelta(days=1))]
    inside = df.latitude.between(box.lat_min, box.lat_max) & df.longitude.between(box.lon_min, box.lon_max)
    return df[inside]


def simulate_days(
    start: dt.date, n_days: int, n_vessels: int, seed: int = 0, region: str = "chesapeake", active_frac: float = 0.7
) -> dict[dt.date, pd.DataFrame]:
    """Simulate several days for a persistent fleet; each day a random subset is active."""
    box = get_region(region)
    rng = np.random.default_rng(seed)
    fleet = make_fleet(n_vessels, box, rng)
    out = {}
    for d in range(n_days):
        day = start + dt.timedelta(days=d)
        frames = [
            simulate_vessel_day(v, day, box, rng) for v in fleet if rng.random() < active_frac
        ]
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(CANONICAL_COLUMNS))
        out[day] = df[list(CANONICAL_COLUMNS)].sort_values(["mmsi", "base_date_time"]).reset_index(drop=True)
    return out


def write_interim(days: dict[dt.date, pd.DataFrame], out_dir: Path) -> list[Path]:
    """Write one Parquet file per day in the same layout as the download step."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for day, df in days.items():
        p = out_dir / f"ais-{day:%Y-%m-%d}.parquet"
        df.to_parquet(p, index=False)
        paths.append(p)
    return paths


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Write synthetic AIS days in the interim Parquet format.")
    p.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2025, 4, 1))
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--vessels", type=int, default=60)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, default=Path("data/interim/synthetic"))
    a = p.parse_args(argv)
    paths = write_interim(simulate_days(a.start, a.days, a.vessels, a.seed), a.out)
    print(f"wrote {len(paths)} files to {a.out}")


if __name__ == "__main__":
    main()
