"""Build and freeze a labeled test set from held-out windows.

The test set mixes untouched normal windows with anomalous copies of other
windows: one cell per (anomaly kind, severity level). Every random choice comes
from a seed derived from (seed, kind, level, window), so a rebuild with the same
inputs is byte-identical. Saving writes a SHA-256 checksum; loading verifies it,
which is how "test sets frozen before any model run" is enforced in code.

Usage:
    python -m latentwake.inject.build --processed data/processed/chesapeake \\
        --split test --out data/testsets/chesapeake-test-v1 --per-cell 200
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from latentwake.data.features import FEATURES, Normalizer, step_features
from latentwake.inject.anomalies import DEFAULT_GRID, INJECTORS, NEEDS_MOTION, Injection

MOVING_SOG_KN = 3.0


@dataclass
class TestSet:
    X: np.ndarray            # (N, L, F) features, unnormalized
    step_label: np.ndarray   # (N, L) bool
    cells: pd.DataFrame      # one row per window: kind, level, params, source window, source speed

    # Evaluate kinds in NEEDS_MOTION only against normals with
    # source_mean_sog >= MOVING_SOG_KN. Otherwise "moving vs anchored" leaks in
    # as a fake detection signal: anchored ships are easy to call normal.

    @property
    def label(self) -> np.ndarray:
        return self.step_label.any(axis=1)


def features_after_injection(x_orig: np.ndarray, inj: Injection) -> np.ndarray:
    """Recompute features for an injected window; step 0 keeps its original row."""
    f = step_features(inj.lat, inj.lon, inj.sog, inj.cog, inj.heading)
    f[0] = x_orig[0]
    return f


def build_test_set(
    X: np.ndarray,
    raw: dict[str, np.ndarray],
    meta: pd.DataFrame,
    seed: int = 0,
    per_cell: int = 200,
    n_normal: int | None = None,
    grid: dict[str, list[dict]] | None = None,
) -> TestSet:
    """X is unnormalized (N, L, F); raw holds (N, L) lat/lon/sog/cog/heading for the same windows."""
    grid = grid or DEFAULT_GRID
    N, L, _ = X.shape
    rng = np.random.default_rng(seed)
    order = rng.permutation(N)
    n_cells = sum(len(v) for v in grid.values())
    n_normal = n_normal if n_normal is not None else min(N, per_cell * n_cells)

    # Normal windows come from one slice of the shuffled pool; anomalies are
    # injected into copies of the rest, so no window appears both ways.
    normal_idx = order[:n_normal]
    pool = order[n_normal:] if N > n_normal else order
    moving = meta.mean_sog.to_numpy() >= MOVING_SOG_KN

    xs, ys, rows = [X[normal_idx]], [np.zeros((len(normal_idx), L), dtype=bool)], []
    for i in normal_idx:
        rows.append(
            {
                "kind": "normal",
                "level": -1,
                "params": "{}",
                "source_window": int(meta.window_id.iat[i]),
                "source_mean_sog": float(meta.mean_sog.iat[i]),
            }
        )

    for k_i, (kind, levels) in enumerate(sorted(grid.items())):
        candidates = pool[moving[pool]] if kind in NEEDS_MOTION else pool
        if candidates.size == 0:
            continue
        for lvl_i, level in enumerate(levels):
            cell_rng = np.random.default_rng([seed, k_i, lvl_i])
            picks = cell_rng.choice(candidates, size=per_cell, replace=candidates.size < per_cell)
            for j, w in enumerate(picks):
                win_rng = np.random.default_rng([seed, k_i, lvl_i, j])
                r = {f: raw[f][w] for f in raw}
                inj = INJECTORS[kind](r, win_rng, **level)
                xs.append(features_after_injection(X[w], inj)[None])
                ys.append(inj.label[None])
                rows.append(
                    {
                        "kind": kind,
                        "level": lvl_i,
                        "params": json.dumps(inj.params, sort_keys=True),
                        "source_window": int(meta.window_id.iat[w]),
                        "source_mean_sog": float(meta.mean_sog.iat[w]),
                    }
                )
    return TestSet(
        X=np.concatenate(xs).astype(np.float32),
        step_label=np.concatenate(ys),
        cells=pd.DataFrame(rows),
    )


def _digest(X: np.ndarray, step_label: np.ndarray, cells_csv: str) -> str:
    # Hash the CSV text exactly as stored; re-serializing a parsed frame is not
    # byte-stable (float formatting can change).
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(X).tobytes())
    h.update(np.ascontiguousarray(step_label).tobytes())
    h.update(cells_csv.encode())
    return h.hexdigest()


def save_test_set(ts: TestSet, out_dir: Path, info: dict | None = None) -> str:
    out_dir = Path(out_dir)
    if (out_dir / "manifest.json").exists():
        raise FileExistsError(f"{out_dir} already holds a frozen test set; use a new version name")
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_dir / "arrays.npz", X=ts.X, step_label=ts.step_label)
    cells_csv = ts.cells.to_csv(index=False, lineterminator="\n")
    (out_dir / "cells.csv").write_bytes(cells_csv.encode())
    digest = _digest(ts.X, ts.step_label, cells_csv)
    counts = ts.cells.groupby("kind").size().to_dict()
    frozen_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    manifest = {"sha256": digest, "frozen_at": frozen_at, "features": FEATURES, "n": int(len(ts.cells)),
                "counts": counts, **(info or {})}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return digest


def load_test_set(out_dir: Path, normalizer: Normalizer | None = None) -> TestSet:
    out_dir = Path(out_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text())
    arrays = np.load(out_dir / "arrays.npz")
    cells_csv = (out_dir / "cells.csv").read_bytes().decode()
    if _digest(arrays["X"], arrays["step_label"], cells_csv) != manifest["sha256"]:
        raise ValueError(f"test set in {out_dir} does not match its checksum; it was modified after freezing")
    cells = pd.read_csv(io.StringIO(cells_csv), dtype={"params": str})
    ts = TestSet(X=arrays["X"], step_label=arrays["step_label"], cells=cells)
    if normalizer is not None:
        ts.X = normalizer.transform(ts.X)
    return ts


def main(argv: list[str] | None = None) -> None:
    from latentwake.data.preprocess import load_split

    p = argparse.ArgumentParser(description="Build and freeze a labeled anomaly test set.")
    p.add_argument("--processed", type=Path, default=Path("data/processed/chesapeake"))
    p.add_argument("--split", default="test", choices=["val", "test"])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--per-cell", type=int, default=200)
    a = p.parse_args(argv)
    X, meta, raw = load_split(a.processed, a.split, normalized=False, raw=True)
    ts = build_test_set(X, raw, meta, seed=a.seed, per_cell=a.per_cell)
    digest = save_test_set(ts, a.out, info={"split": a.split, "seed": a.seed, "processed": str(a.processed)})
    print(f"froze {len(ts.cells)} windows to {a.out} (sha256 {digest[:12]})")


if __name__ == "__main__":
    main()
