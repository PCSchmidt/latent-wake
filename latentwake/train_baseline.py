"""Train one learned baseline (Isolation Forest, LSTM autoencoder, TrAISformer-style).

Usage:
    python -m latentwake.train_baseline --kind iforest --out runs/iforest-s0 --seed 0
    python -m latentwake.train_baseline --kind lstm_ae --out runs/lstmae-s0 --hidden 128
    python -m latentwake.train_baseline --kind traisformer --out runs/trais-s0 --d-model 128

Writes OUT/config.json (with started_at, checked against the test set's
freeze time) and OUT/baseline.pt. Uses the training split with the same
anchored-window subsampling as the JEPA.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from latentwake.data.features import Normalizer
from latentwake.data.preprocess import load_split
from latentwake.models.learned_baselines import KINDS, BaselineConfig, fit
from latentwake.train import _subsample_stationary


def train_baseline(cfg: BaselineConfig, processed: Path, out: Path, stationary_keep: float = 0.25,
                   device: str | None = None, log=print) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    (out / "config.json").write_text(json.dumps(
        {"baseline_kind": cfg.kind, **asdict(cfg), "processed": str(processed),
         "stationary_keep": stationary_keep, "started_at": started_at}, indent=2))
    X, meta = load_split(processed, "train", normalized=False)
    keep = _subsample_stationary(meta, stationary_keep, np.random.default_rng(cfg.seed))
    normalizer = Normalizer.load(Path(processed) / "normalizer.json")
    log(f"{cfg.kind}: {len(keep)} training windows (of {len(X)})")
    model = fit(cfg, X[keep], meta.vessel_class.to_numpy()[keep], normalizer, device=device, log=log)
    path = out / "baseline.pt"
    model.save(path)
    log(f"saved {path}")
    return path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Train a learned baseline.")
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--processed", type=Path, default=Path("data/processed/chesapeake"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--stationary-keep", type=float, default=0.25)
    p.add_argument("--n-estimators", type=int, default=300)
    p.add_argument("--features", choices=["stats", "stats+diffs"], default="stats+diffs")
    p.add_argument("--hidden", type=int, default=128)
    p.add_argument("--d-model", type=int, default=128)
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    cfg = BaselineConfig(kind=a.kind, seed=a.seed, n_estimators=a.n_estimators, features=a.features,
                         hidden=a.hidden, d_model=a.d_model, epochs=a.epochs)
    train_baseline(cfg, a.processed, a.out, a.stationary_keep, a.device,
                   log=lambda m: print(m, flush=True))


if __name__ == "__main__":
    main()
