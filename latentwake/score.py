"""Turn a trained model's prediction errors into calibrated surprise scores.

Raw prediction error is not comparable across vessel types: fishing boats and
tugs are naturally less predictable than tankers. The calibrator fits a robust
z-score (median and MAD) per stratum (vessel class, or under contract v2
vessel class x under way) on validation windows, which contain
no injected anomalies, and falls back to the pooled statistics for rare classes.

Scores:
    transition z   (N, T-1)  one per chunk-to-chunk prediction
    window score   (N,)      max over transitions
    step score     (N, L)    each transition's z spread over the chunk it predicts
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from latentwake.models.jepa import LatentWake

MAD_TO_STD = 1.4826


@torch.no_grad()
def transition_errors(model: LatentWake, X: np.ndarray, vclass: np.ndarray, batch: int = 1024,
                      cells: np.ndarray | None = None) -> np.ndarray:
    """Per-transition prediction error for normalized windows X (N, L, F).

    cells (N, L) location grid ids are required by position-context models and
    ignored by the rest.
    """
    device = next(model.parameters()).device
    if model.cfg.use_position and cells is None:
        raise ValueError("this model uses position context; pass cells")
    out = []
    for a in range(0, len(X), batch):
        x = torch.as_tensor(np.ascontiguousarray(X[a : a + batch], dtype=np.float32), device=device)
        v = torch.as_tensor(np.ascontiguousarray(vclass[a : a + batch], dtype=np.int64), device=device)
        c = None
        if model.cfg.use_position:
            c = torch.as_tensor(np.ascontiguousarray(cells[a : a + batch], dtype=np.int64), device=device)
        out.append(model.surprise(x, v, c).float().cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, model.cfg.n_chunks - 1), dtype=np.float32)


@dataclass
class Calibrator:
    median: dict[int, float]
    mad: dict[int, float]
    pooled: tuple[float, float]
    min_count: int = 200

    @classmethod
    def fit(cls, errors: np.ndarray, vclass: np.ndarray, min_count: int = 200) -> "Calibrator":
        e = errors.reshape(len(errors), -1)
        flat = e.ravel()
        pooled = (float(np.median(flat)), float(max(np.median(np.abs(flat - np.median(flat))), 1e-9)))
        med, mad = {}, {}
        for c in np.unique(vclass):
            vals = e[vclass == c].ravel()
            if vals.size >= min_count:
                m = float(np.median(vals))
                med[int(c)] = m
                mad[int(c)] = float(max(np.median(np.abs(vals - m)), 1e-9))
        return cls(med, mad, pooled, min_count)

    def transform(self, errors: np.ndarray, vclass: np.ndarray) -> np.ndarray:
        m = np.array([self.median.get(int(c), self.pooled[0]) for c in vclass])[:, None]
        s = np.array([self.mad.get(int(c), self.pooled[1]) for c in vclass])[:, None]
        return (errors - m) / (MAD_TO_STD * s)

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(
            {"median": self.median, "mad": self.mad, "pooled": self.pooled, "min_count": self.min_count}, indent=2
        ))

    @classmethod
    def load(cls, path: Path) -> "Calibrator":
        d = json.loads(Path(path).read_text())
        return cls({int(k): v for k, v in d["median"].items()}, {int(k): v for k, v in d["mad"].items()},
                   tuple(d["pooled"]), d["min_count"])


def step_scores(z: np.ndarray, chunk_len: int, window_len: int) -> np.ndarray:
    """Spread transition scores over the steps of the chunk each one predicts; chunk 0 gets 0."""
    out = np.zeros((len(z), window_len), dtype=np.float32)
    out[:, chunk_len : chunk_len * (z.shape[1] + 1)] = np.repeat(z, chunk_len, axis=1)
    return out
