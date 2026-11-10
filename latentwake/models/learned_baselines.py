"""Learned baselines: Isolation Forest, LSTM autoencoder, TrAISformer-style forecaster.

Each one turns a window into one anomaly score (higher is more anomalous),
scored on the same frozen test set and calibrated the same way as every other
detector (contract v2.1). Settings are chosen on the validation anomaly set
only (DECISIONS.md, 2026-11-10).

- iforest      Isolation Forest on per-window statistics of the normalized
               features (mean, std, min, max; optionally mean and max absolute
               step-to-step change).
- lstm_ae      Sequence-to-sequence LSTM autoencoder on normalized windows;
               per-step reconstruction error, window score = max.
- traisformer  TrAISformer-style forecaster: each step's east and north
               displacement, speed, and course are binned and embedded
               ("four-hot"); a causal transformer predicts the next step's
               bins; per-step negative log-likelihood, window score = max.
               Unlike TrAISformer it uses relative motion, not absolute
               latitude and longitude, to match every other model here.

Train: python -m latentwake.train_baseline --kind iforest --out runs/iforest-s0
"""

from __future__ import annotations

import io
import json
import math
import pickle
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch import nn

from latentwake.data.features import FEATURES, VESSEL_CLASSES, Normalizer

KINDS = ("iforest", "lstm_ae", "traisformer")
_DX, _DY = FEATURES.index("dx_m"), FEATURES.index("dy_m")
_SOG, _SIN, _COS = FEATURES.index("sog_kn"), FEATURES.index("sin_cog"), FEATURES.index("cos_cog")


@dataclass
class BaselineConfig:
    kind: str
    seed: int = 0
    # iforest
    n_estimators: int = 300
    features: str = "stats+diffs"  # "stats" or "stats+diffs"
    max_fit_windows: int = 200_000
    # neural
    hidden: int = 128               # lstm_ae hidden size
    d_model: int = 128              # traisformer width
    n_layers: int = 4               # traisformer depth
    n_heads: int = 4
    epochs: int = 10
    batch_size: int = 256
    lr: float = 1e-3
    # traisformer bins
    dxy_max_m: float = 1500.0       # displacement clipped to +/- this per 2-minute step
    dxy_bins: int = 60
    sog_max_kn: float = 30.0
    sog_bins: int = 60
    cog_bins: int = 72              # 5 degrees
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------- iforest

def window_stats(Xn: np.ndarray, features: str) -> np.ndarray:
    parts = [Xn.mean(1), Xn.std(1), Xn.min(1), Xn.max(1)]
    if features == "stats+diffs":
        d = np.abs(np.diff(Xn, axis=1))
        parts += [d.mean(1), d.max(1)]
    elif features != "stats":
        raise ValueError(f"unknown feature set {features!r}")
    return np.concatenate(parts, axis=1).astype(np.float32)


# ---------------------------------------------------------------- lstm_ae

class LSTMAutoencoder(nn.Module):
    def __init__(self, n_features: int, hidden: int):
        super().__init__()
        self.enc = nn.LSTM(n_features, hidden, batch_first=True)
        self.dec = nn.LSTM(hidden, hidden, batch_first=True)
        self.out = nn.Linear(hidden, n_features)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, (h, _) = self.enc(x)
        z = h[-1].unsqueeze(1).expand(-1, x.size(1), -1)
        y, _ = self.dec(z)
        return self.out(y)

    def step_errors(self, x: torch.Tensor) -> torch.Tensor:
        return (self.forward(x) - x).pow(2).mean(-1)


# ------------------------------------------------------------ traisformer

def four_hot(X_raw: np.ndarray, cfg: BaselineConfig) -> np.ndarray:
    """Bin each step's dx, dy, speed, and course: (N, L, 4) int64."""
    def lin(v, lo, hi, n):
        return np.clip(((v - lo) / (hi - lo) * n).astype(np.int64), 0, n - 1)

    m = cfg.dxy_max_m
    cog = (np.degrees(np.arctan2(X_raw[..., _SIN], X_raw[..., _COS])) + 360.0) % 360.0
    return np.stack([
        lin(X_raw[..., _DX], -m, m, cfg.dxy_bins),
        lin(X_raw[..., _DY], -m, m, cfg.dxy_bins),
        lin(X_raw[..., _SOG], 0.0, cfg.sog_max_kn, cfg.sog_bins),
        lin(cog, 0.0, 360.0, cfg.cog_bins),
    ], axis=-1)


class TrAISForecaster(nn.Module):
    def __init__(self, cfg: BaselineConfig, max_len: int = 64):
        super().__init__()
        d = cfg.d_model
        self.sizes = (cfg.dxy_bins, cfg.dxy_bins, cfg.sog_bins, cfg.cog_bins)
        self.emb = nn.ModuleList(nn.Embedding(n, d) for n in self.sizes)
        self.pos = nn.Parameter(torch.randn(1, max_len, d) * 0.02)
        self.vessel = nn.Embedding(len(VESSEL_CLASSES), d)
        layer = nn.TransformerEncoderLayer(d, cfg.n_heads, 4 * d, dropout=0.1, batch_first=True, norm_first=True)
        self.blocks = nn.TransformerEncoder(layer, cfg.n_layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)
        self.heads = nn.ModuleList(nn.Linear(d, n) for n in self.sizes)

    def step_nll(self, bins: torch.Tensor, vclass: torch.Tensor) -> torch.Tensor:
        """bins (B, L, 4) -> NLL of steps 1..L-1 given the steps before: (B, L-1)."""
        x = bins[:, :-1]
        T = x.size(1)
        h = sum(e(x[..., i]) for i, e in enumerate(self.emb)) + self.pos[:, :T] + self.vessel(vclass)[:, None]
        mask = torch.triu(torch.full((T, T), float("-inf"), device=h.device), diagonal=1)
        h = self.norm(self.blocks(h, mask=mask))
        target = bins[:, 1:]
        nll = 0
        for i, head in enumerate(self.heads):
            logp = torch.log_softmax(head(h).float(), dim=-1)
            nll = nll - logp.gather(-1, target[..., i : i + 1]).squeeze(-1)
        return nll


# ------------------------------------------------------------- the wrapper

class LearnedBaseline:
    """A fitted baseline that scores windows. Saved and loaded as one file."""

    def __init__(self, cfg: BaselineConfig, model, normalizer: Normalizer):
        self.cfg, self.model, self.normalizer = cfg, model, normalizer

    # scoring --------------------------------------------------------------
    @torch.no_grad()
    def window_scores(self, X_raw: np.ndarray, vclass: np.ndarray, batch: int = 2048,
                      device: str | None = None) -> np.ndarray:
        X_raw = np.asarray(X_raw, dtype=np.float32)
        if self.cfg.kind == "iforest":
            return -self.model.score_samples(window_stats(self.normalizer.transform(X_raw), self.cfg.features))
        dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model.to(dev).eval()
        out = []
        for a in range(0, len(X_raw), batch):
            xr = X_raw[a : a + batch]
            if self.cfg.kind == "lstm_ae":
                x = torch.as_tensor(self.normalizer.transform(xr), dtype=torch.float32, device=dev)
                e = self.model.step_errors(x)
            else:
                b = torch.as_tensor(four_hot(xr, self.cfg), device=dev)
                v = torch.as_tensor(np.array(vclass[a : a + batch], dtype=np.int64), device=dev)
                e = self.model.step_nll(b, v)
            out.append(e.max(dim=1).values.float().cpu().numpy())
        return np.concatenate(out)

    # persistence ----------------------------------------------------------
    def save(self, path: Path) -> None:
        if self.cfg.kind == "iforest":
            payload = pickle.dumps(self.model)
        else:
            buf = io.BytesIO()
            torch.save(self.model.state_dict(), buf)
            payload = buf.getvalue()
        torch.save({"cfg": asdict(self.cfg), "model": payload,
                    "normalizer": {"mean": self.normalizer.mean, "std": self.normalizer.std}},
                   path)

    @classmethod
    def load(cls, path: Path) -> "LearnedBaseline":
        blob = torch.load(path, map_location="cpu", weights_only=False)
        cfg = BaselineConfig(**blob["cfg"])
        norm = Normalizer(mean=blob["normalizer"]["mean"], std=blob["normalizer"]["std"])
        if cfg.kind == "iforest":
            model = pickle.loads(blob["model"])
        else:
            model = _build(cfg)
            model.load_state_dict(torch.load(io.BytesIO(blob["model"]), map_location="cpu"))
        return cls(cfg, model, norm)


def _build(cfg: BaselineConfig):
    if cfg.kind == "lstm_ae":
        return LSTMAutoencoder(len(FEATURES), cfg.hidden)
    if cfg.kind == "traisformer":
        return TrAISForecaster(cfg)
    raise ValueError(f"unknown kind {cfg.kind!r}")


def is_baseline(checkpoint: Path) -> bool:
    """True if a checkpoint was written by train_baseline (its run folder says so)."""
    cfg = Path(checkpoint).parent / "config.json"
    return cfg.exists() and "baseline_kind" in json.loads(cfg.read_text())


# ----------------------------------------------------------------- training

def fit(cfg: BaselineConfig, X_raw: np.ndarray, vclass: np.ndarray, normalizer: Normalizer,
        device: str | None = None, log=print) -> LearnedBaseline:
    rng = np.random.default_rng(cfg.seed)
    torch.manual_seed(cfg.seed)
    if cfg.kind == "iforest":
        from sklearn.ensemble import IsolationForest

        idx = rng.permutation(len(X_raw))[: cfg.max_fit_windows]
        feats = window_stats(normalizer.transform(X_raw[idx]), cfg.features)
        model = IsolationForest(n_estimators=cfg.n_estimators, random_state=cfg.seed, n_jobs=-1).fit(feats)
        log(f"iforest fit on {len(idx)} windows, {feats.shape[1]} features")
        return LearnedBaseline(cfg, model, normalizer)

    dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = _build(cfg).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=1e-4)
    steps = max(1, len(X_raw) // cfg.batch_size)
    total = steps * cfg.epochs
    if cfg.kind == "lstm_ae":
        data = torch.as_tensor(normalizer.transform(X_raw), dtype=torch.float32)
    else:
        data = torch.as_tensor(four_hot(X_raw, cfg))
    V = torch.as_tensor(np.asarray(vclass, dtype=np.int64))
    step = 0
    for epoch in range(1, cfg.epochs + 1):
        perm = torch.randperm(len(data))
        total_loss = 0.0
        for b in range(steps):
            idx = perm[b * cfg.batch_size : (b + 1) * cfg.batch_size]
            x = data[idx].to(dev)
            for g in opt.param_groups:  # cosine decay
                g["lr"] = cfg.lr * 0.5 * (1 + math.cos(math.pi * step / total))
            if cfg.kind == "lstm_ae":
                loss = model.step_errors(x).mean()
            else:
                loss = model.step_nll(x, V[idx].to(dev)).mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            step += 1
            total_loss += loss.item()
        log(f"epoch {epoch:3d} loss={total_loss / steps:.4f}")
    return LearnedBaseline(cfg, model.cpu().eval(), normalizer)
