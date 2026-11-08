"""Train a Latent Wake model on preprocessed windows.

Usage:
    python -m latentwake.train --processed data/processed/chesapeake --out runs/jepa-s0
    python -m latentwake.train ... --size small            # CPU-friendly
    python -m latentwake.train ... --target raw            # ablation: no encoder, no SIGReg
    python -m latentwake.train ... --no-action             # ablation: no action conditioning
    python -m latentwake.train ... --sigreg-weight 0       # ablation: expect collapse

Each run folder gets config.json, metrics.jsonl (one line per epoch), last.pt,
and best.pt (lowest validation loss). Watch `val_erank` in the log: the
effective rank of validation latents. Near the embedding size is healthy; a
slide toward 1 means the encoder is collapsing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch

from latentwake.data.preprocess import load_split
from latentwake.models.jepa import LatentWake, ModelConfig, collapse_signal, effective_rank


@dataclass
class TrainConfig:
    processed: str = "data/processed/chesapeake"
    out: str = "runs/jepa"
    model: ModelConfig = field(default_factory=ModelConfig)
    epochs: int = 30
    batch_size: int = 256
    lr: float = 3e-4
    weight_decay: float = 1e-3
    warmup_frac: float = 0.05
    grad_clip: float = 1.0
    stationary_keep: float = 0.25   # share of anchored/moored windows kept for training
    max_val_windows: int = 8192
    seed: int = 0
    device: str = "auto"
    amp: bool = True                # bf16 autocast on CUDA


def _device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


def _lr_at(step: int, total: int, cfg: TrainConfig) -> float:
    warm = max(1, int(cfg.warmup_frac * total))
    if step < warm:
        return cfg.lr * (step + 1) / warm
    progress = (step - warm) / max(1, total - warm)
    return cfg.lr * 0.5 * (1 + math.cos(math.pi * min(1.0, progress)))


def _subsample_stationary(meta, keep: float, rng: np.random.Generator) -> np.ndarray:
    idx = np.arange(len(meta))
    if keep >= 1.0:
        return idx
    stat = meta.is_stationary.to_numpy()
    return idx[~stat | (rng.random(len(meta)) < keep)]


@torch.no_grad()
def _validate(model, Xv, Vv, cfg: TrainConfig, device) -> dict:
    model.eval()
    preds, sigs, zs = [], [], []
    for a in range(0, len(Xv), cfg.batch_size):
        x = Xv[a : a + cfg.batch_size].to(device)
        v = Vv[a : a + cfg.batch_size].to(device)
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=cfg.amp and device.type == "cuda"):
            out = model(x, v)
        preds.append(float(out["pred_loss"]) * len(x))
        sigs.append(float(out["sigreg_loss"]) * len(x))
        zs.append(out["z"].float().cpu())
    model.train()
    n = len(Xv)
    z = torch.cat(zs)
    pred, sig = sum(preds) / n, sum(sigs) / n
    return {
        "val_pred": pred,
        "val_sigreg": sig,
        "val_loss": pred + model.cfg.sigreg_weight * sig * (model.encoder is not None),
        "val_erank": effective_rank(z),
        "val_z_std": float(z.reshape(-1, z.size(-1)).std(dim=0).mean()),
    }


def train(cfg: TrainConfig, log=None) -> list[dict]:
    log = log or (lambda msg: print(msg, flush=True))  # flush so redirected logs stay live
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    device = _device(cfg.device)
    out = Path(cfg.out)
    out.mkdir(parents=True, exist_ok=True)
    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    (out / "config.json").write_text(json.dumps({**asdict(cfg), "started_at": started_at}, indent=2))

    X, meta = load_split(cfg.processed, "train")
    keep = _subsample_stationary(meta, cfg.stationary_keep, rng)
    Xt = torch.from_numpy(X[keep])
    Vt = torch.from_numpy(meta.vessel_class.to_numpy()[keep].astype(np.int64))
    Xv_np, meta_v = load_split(cfg.processed, "val")
    if len(Xv_np) > cfg.max_val_windows:
        pick = rng.choice(len(Xv_np), cfg.max_val_windows, replace=False)
        Xv_np, meta_v = Xv_np[pick], meta_v.iloc[pick]
    Xv = torch.from_numpy(Xv_np)
    Vv = torch.from_numpy(meta_v.vessel_class.to_numpy().astype(np.int64))
    if len(Xt) < cfg.batch_size:
        raise ValueError(f"only {len(Xt)} training windows; lower --batch-size")

    model = LatentWake(cfg.model).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    steps_per_epoch = len(Xt) // cfg.batch_size
    total = steps_per_epoch * cfg.epochs
    log(
        f"device={device} params={model.n_params() / 1e6:.2f}M train={len(Xt)} "
        f"(of {len(X)}, stationary_keep={cfg.stationary_keep}) val={len(Xv)} steps={total}"
    )

    history, best, step = [], float("inf"), 0
    for epoch in range(1, cfg.epochs + 1):
        t0 = time.perf_counter()
        perm = torch.randperm(len(Xt))
        sums = {"pred": 0.0, "sigreg": 0.0, "loss": 0.0}
        for b in range(steps_per_epoch):
            idx = perm[b * cfg.batch_size : (b + 1) * cfg.batch_size]
            x, v = Xt[idx].to(device, non_blocking=True), Vt[idx].to(device, non_blocking=True)
            for g in opt.param_groups:
                g["lr"] = _lr_at(step, total, cfg)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=cfg.amp and device.type == "cuda"):
                o = model(x, v)
            opt.zero_grad(set_to_none=True)
            o["loss"].backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
            opt.step()
            step += 1
            sums["pred"] += o["pred_loss"].item()
            sums["sigreg"] += o["sigreg_loss"].item()
            sums["loss"] += o["loss"].item()
        rec = {"epoch": epoch, "step": step, **{f"train_{k}": v / steps_per_epoch for k, v in sums.items()}}
        rec.update(_validate(model, Xv, Vv, cfg, device))
        rec["lr"] = _lr_at(step - 1, total, cfg)
        rec["seconds"] = round(time.perf_counter() - t0, 1)
        if model.encoder is not None:
            reason = collapse_signal([h["val_erank"] for h in history] + [rec["val_erank"]], cfg.model.embed_dim)
            if reason:
                rec["warning"] = f"possible collapse: {reason}"
        history.append(rec)
        with open(out / "metrics.jsonl", "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        ckpt = {"model": model.state_dict(), "model_cfg": asdict(cfg.model), "epoch": epoch, "metrics": rec}
        torch.save(ckpt, out / "last.pt")
        if rec["val_loss"] < best:
            best = rec["val_loss"]
            torch.save(ckpt, out / "best.pt")
        log(
            f"epoch {epoch:3d} train_pred={rec['train_pred']:.4f} sigreg={rec['train_sigreg']:.3f} "
            f"val_pred={rec['val_pred']:.4f} val_erank={rec['val_erank']:.1f} ({rec['seconds']}s)"
            + (f"  WARNING: {rec['warning']}" if "warning" in rec else "")
        )
    return history


def load_model(checkpoint: Path, device: str = "cpu") -> LatentWake:
    ckpt = torch.load(checkpoint, map_location=device, weights_only=False)
    model = LatentWake(ModelConfig(**ckpt["model_cfg"]))
    model.load_state_dict(ckpt["model"])
    return model.to(device).eval()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Train a Latent Wake world model.")
    p.add_argument("--processed", default="data/processed/chesapeake")
    p.add_argument("--out", required=True)
    p.add_argument("--size", choices=["full", "small"], default="full")
    p.add_argument("--target", choices=["latent", "raw"], default="latent")
    p.add_argument("--no-action", action="store_true")
    p.add_argument("--sigreg-weight", type=float, default=0.09)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--stationary-keep", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--device", default="auto")
    a = p.parse_args(argv)
    mk = dict(target=a.target, use_action=not a.no_action, sigreg_weight=a.sigreg_weight)
    model_cfg = ModelConfig.small(**mk) if a.size == "small" else ModelConfig(**mk)
    cfg = TrainConfig(
        processed=a.processed, out=a.out, model=model_cfg, epochs=a.epochs, batch_size=a.batch_size,
        lr=a.lr, stationary_keep=a.stationary_keep, seed=a.seed, device=a.device,
    )
    train(cfg)


if __name__ == "__main__":
    main()
