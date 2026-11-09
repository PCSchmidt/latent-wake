"""The Latent Wake world model: a trajectory JEPA in the LeWorldModel style.

A 64-step window (about 2 hours on the 2-minute grid) is cut into 8 chunks of
8 steps. Each chunk is encoded to a latent z_t. A causal predictor, conditioned
on the *reported* kinematics of the next chunk (speed, course, heading change),
predicts z_{t+1}. Training minimizes prediction error plus SIGReg, end to end,
with no EMA target, stop-gradient, or pretrained encoder.

The action deliberately excludes the next chunk's displacements: the predictor
must infer where the ship goes from what its AIS says it is doing. When the
positions disagree with the reports (spoofing), the prediction error spikes.

Ablations are config switches:
    target="raw"        no encoder and no SIGReg; predict the next chunk's
                        normalized features directly (does latent space help?)
    use_action=False    no action conditioning (does knowing the reports help?)
    sigreg_weight=0     no anti-collapse term (does the encoder collapse?)
    use_position=True   add a location-cell embedding per chunk (does knowing
                        where the ship is help with route deviation?)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import nn

from latentwake.data.features import FEATURES, VESSEL_CLASSES
from latentwake.models.blocks import MLP, Block, ConditionalBlock, SIGReg

ACTION_FEATURES = ("sog_kn", "sin_cog", "cos_cog", "dheading_deg", "heading_valid")
ACTION_IDX = [FEATURES.index(f) for f in ACTION_FEATURES]


@dataclass
class ModelConfig:
    window_len: int = 64
    chunk_len: int = 8
    n_features: int = len(FEATURES)
    n_vessel_classes: int = len(VESSEL_CLASSES)
    embed_dim: int = 192
    enc_depth: int = 4
    enc_heads: int = 6
    enc_mlp: int = 768
    proj_hidden: int = 1024
    pred_dim: int = 256
    pred_depth: int = 6
    pred_heads: int = 8
    pred_mlp: int = 1024
    dim_head: int = 32
    dropout: float = 0.1
    target: str = "latent"      # "latent" or "raw"
    pooling: str = "mean"       # "mean" or "attention" over a chunk's steps
    use_action: bool = True
    # Position context (contract v2 option): add an embedding of the location
    # grid cell to each chunk, so the model can learn where lanes run and where
    # ships normally turn or slow. Off by default; route deviation is otherwise
    # invisible to a model that sees only relative motion.
    use_position: bool = False
    n_cells: int = 0            # grid size; set from the processed data when use_position
    sigreg_weight: float = 0.09  # LeWM default
    sigreg_knots: int = 17
    sigreg_proj: int = 1024

    @property
    def n_chunks(self) -> int:
        return self.window_len // self.chunk_len

    @classmethod
    def small(cls, **kw) -> "ModelConfig":
        """A CPU-friendly size for smoke tests and laptop-free debugging."""
        base = dict(embed_dim=64, enc_depth=2, enc_heads=4, enc_mlp=256, proj_hidden=256,
                    pred_dim=96, pred_depth=3, pred_heads=4, pred_mlp=384, sigreg_proj=256)
        base.update(kw)
        return cls(**base)


class ChunkEncoder(nn.Module):
    """Encode each 8-step chunk independently: per-step embed, transformer, mean-pool, projector."""

    def __init__(self, cfg: ModelConfig):
        super().__init__()
        d = cfg.embed_dim
        self.step_embed = nn.Linear(cfg.n_features, d)
        self.pos = nn.Parameter(torch.randn(1, cfg.chunk_len, d) * 0.02)
        self.vessel = nn.Embedding(cfg.n_vessel_classes, d)
        if cfg.use_position and cfg.n_cells <= 0:
            raise ValueError("use_position needs n_cells > 0")
        self.place = nn.Embedding(cfg.n_cells, d) if cfg.use_position else None
        self.blocks = nn.ModuleList(
            Block(d, cfg.enc_heads, cfg.dim_head, cfg.enc_mlp, cfg.dropout) for _ in range(cfg.enc_depth)
        )
        self.norm = nn.LayerNorm(d)
        if cfg.pooling not in ("mean", "attention"):
            raise ValueError(f"unknown pooling {cfg.pooling!r}")
        # Attention pooling scores each step, so a single anomalous step (a
        # spoof's jump) can dominate the chunk embedding instead of being
        # averaged away with seven normal steps.
        self.pool_score = nn.Linear(d, 1) if cfg.pooling == "attention" else None
        self.projector = MLP(d, cfg.proj_hidden, d, norm="batch")

    def forward(self, chunks: torch.Tensor, vclass: torch.Tensor, cells: torch.Tensor | None = None) -> torch.Tensor:
        """chunks: (B, T, C, F); vclass: (B,); cells: (B, T) one grid cell per chunk. Returns (B, T, D)."""
        B, T, C, F = chunks.shape
        h = self.step_embed(chunks.reshape(B * T, C, F)) + self.pos
        h = h + self.vessel(vclass).repeat_interleave(T, dim=0)[:, None, :]
        if self.place is not None:
            if cells is None:
                raise ValueError("position-context encoder needs cells")
            h = h + self.place(cells.reshape(B * T))[:, None, :]
        for blk in self.blocks:
            h = blk(h)
        h = self.norm(h)
        if self.pool_score is None:
            h = h.mean(dim=1)
        else:
            w = torch.softmax(self.pool_score(h).squeeze(-1), dim=1)
            h = (w.unsqueeze(-1) * h).sum(dim=1)
        return self.projector(h).reshape(B, T, -1)


class Predictor(nn.Module):
    """Causal transformer over chunk latents, AdaLN-zero conditioned on the next chunk's reports."""

    def __init__(self, cfg: ModelConfig, in_dim: int, out_dim: int):
        super().__init__()
        p = cfg.pred_dim
        self.input_proj = nn.Linear(in_dim, p)
        self.pos = nn.Parameter(torch.randn(1, cfg.n_chunks, p) * 0.02)
        self.action = nn.Sequential(
            nn.Linear(cfg.chunk_len * len(ACTION_IDX), 4 * p), nn.SiLU(), nn.Linear(4 * p, p)
        )
        self.blocks = nn.ModuleList(
            ConditionalBlock(p, cfg.pred_heads, cfg.dim_head, cfg.pred_mlp, cfg.dropout) for _ in range(cfg.pred_depth)
        )
        self.norm = nn.LayerNorm(p)
        self.out = MLP(p, max(p, out_dim) * 4, out_dim, norm="batch")

    def forward(self, z: torch.Tensor, act: torch.Tensor) -> torch.Tensor:
        """z: (B, T, in_dim) context latents; act: (B, T, C*A). Returns (B, T, out_dim)."""
        T = z.size(1)
        h = self.input_proj(z) + self.pos[:, :T]
        c = self.action(act)
        for blk in self.blocks:
            h = blk(h, c)
        return self.out(self.norm(h))


class LatentWake(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.cfg = cfg
        raw_dim = cfg.chunk_len * cfg.n_features
        if cfg.target == "latent":
            self.encoder = ChunkEncoder(cfg)
            dim = cfg.embed_dim
        elif cfg.target == "raw":
            self.encoder = None
            dim = raw_dim
        else:
            raise ValueError(f"unknown target {cfg.target!r}")
        self.predictor = Predictor(cfg, dim, dim)
        self.sigreg = SIGReg(cfg.sigreg_knots, cfg.sigreg_proj)

    # ----------------------------------------------------------------- pieces

    def chunk(self, x: torch.Tensor) -> torch.Tensor:
        B, L, F = x.shape
        c = self.cfg.chunk_len
        return x[:, : (L // c) * c].reshape(B, L // c, c, F)

    def chunk_cells(self, cells: torch.Tensor | None) -> torch.Tensor | None:
        """(B, L) per-step cells -> (B, T) the cell at each chunk's first step."""
        if cells is None or not self.cfg.use_position:
            return None
        c = self.cfg.chunk_len
        return cells[:, : (cells.size(1) // c) * c : c].long()

    def embed(self, x: torch.Tensor, vclass: torch.Tensor, cells: torch.Tensor | None = None) -> torch.Tensor:
        chunks = self.chunk(x)
        if self.encoder is None:
            return chunks.flatten(2)
        return self.encoder(chunks, vclass, self.chunk_cells(cells))

    def actions(self, x: torch.Tensor) -> torch.Tensor:
        """Action for transition t is the reported kinematics of chunk t+1: (B, T-1, C*A)."""
        a = self.chunk(x)[:, 1:, :, ACTION_IDX].flatten(2)
        return a if self.cfg.use_action else torch.zeros_like(a)

    # ------------------------------------------------------------------ train

    def forward(self, x: torch.Tensor, vclass: torch.Tensor, cells: torch.Tensor | None = None) -> dict[str, torch.Tensor]:
        z = self.embed(x, vclass, cells)               # (B, T, D)
        pred = self.predictor(z[:, :-1], self.actions(x))
        target = z[:, 1:]
        per_step = (pred - target).pow(2).mean(dim=-1)  # (B, T-1)
        out = {"pred_loss": per_step.mean(), "per_step": per_step, "z": z}
        if self.encoder is not None and self.cfg.sigreg_weight > 0:
            out["sigreg_loss"] = self.sigreg(z.transpose(0, 1))
            out["loss"] = out["pred_loss"] + self.cfg.sigreg_weight * out["sigreg_loss"]
        else:
            out["sigreg_loss"] = torch.zeros((), device=x.device)
            out["loss"] = out["pred_loss"]
        return out

    # ------------------------------------------------------------- inference

    @torch.no_grad()
    def surprise(self, x: torch.Tensor, vclass: torch.Tensor, cells: torch.Tensor | None = None) -> torch.Tensor:
        """Per-transition prediction error, (B, T-1). Transition t scores chunk t+1."""
        was = self.training
        self.eval()
        out = self.forward(x, vclass, cells)["per_step"]
        self.train(was)
        return out

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())

    def config_dict(self) -> dict:
        return asdict(self.cfg)


@torch.no_grad()
def effective_rank(z: torch.Tensor) -> float:
    """exp(entropy) of normalized singular values: about D for spread-out latents, about 1 when collapsed."""
    z = z.reshape(-1, z.size(-1)).float()
    z = z - z.mean(dim=0, keepdim=True)
    s = torch.linalg.svdvals(z)
    p = s / s.sum().clamp_min(1e-12)
    p = p[p > 0]
    return float(torch.exp(-(p * p.log()).sum()))


def collapse_signal(eranks: list[float], embed_dim: int, floor_frac: float = 0.25, drop_frac: float = 0.85,
                    min_epochs: int = 4) -> str | None:
    """Return a reason if the effective-rank history looks like collapse, else None.

    Two signals, because a BatchNorm projector prevents constant collapse and
    collapse shows up as rank loss instead: a rank below floor_frac of the
    embedding size, or a sustained fall to below drop_frac of the best rank
    seen. In the synthetic smoke run, no-SIGReg training fell from 18 to 10 of
    64 (caught by the fall) while the healthy run rose from 13 to 25.
    """
    if not eranks:
        return None
    last = eranks[-1]
    if last < floor_frac * embed_dim:
        return f"latent effective rank {last:.1f} is below {floor_frac:.0%} of embed_dim ({embed_dim})"
    if len(eranks) >= min_epochs and last < drop_frac * max(eranks):
        return f"latent effective rank fell to {last:.1f} from a peak of {max(eranks):.1f}"
    return None
