"""Transformer building blocks and the SIGReg regularizer.

Adapted from LeWorldModel (https://github.com/lucas-maes/le-wm, module.py),
Copyright (c) 2026 Lucas Maes, MIT License. Changes: einops removed, the
attention mask made optional per call, a mean-pooling encoder block added,
and SIGReg given an optional generator so tests can be deterministic.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


def modulate(x, shift, scale):
    """AdaLN-zero modulation."""
    return x * (1 + scale) + shift


class SIGReg(nn.Module):
    """Sketched Isotropic Gaussian Regularizer.

    Projects embeddings onto random unit directions and measures, along each
    one, the Epps-Pulley distance between the empirical characteristic function
    and a standard normal's. Pushing that toward zero keeps embeddings spread
    out like an isotropic Gaussian, which blocks representation collapse.
    """

    def __init__(self, knots: int = 17, num_proj: int = 1024):
        super().__init__()
        self.num_proj = num_proj
        t = torch.linspace(0, 3, knots, dtype=torch.float32)
        dt = 3 / (knots - 1)
        weights = torch.full((knots,), 2 * dt, dtype=torch.float32)
        weights[[0, -1]] = dt
        window = torch.exp(-t.square() / 2.0)
        self.register_buffer("t", t)
        self.register_buffer("phi", window)
        self.register_buffer("weights", weights * window)

    def forward(self, proj: torch.Tensor, generator: torch.Generator | None = None) -> torch.Tensor:
        """proj: (T, B, D). Returns the statistic averaged over projections and time."""
        A = torch.randn(proj.size(-1), self.num_proj, device=proj.device, generator=generator)
        A = A.div_(A.norm(p=2, dim=0))
        x_t = (proj.float() @ A).unsqueeze(-1) * self.t
        err = (x_t.cos().mean(-3) - self.phi).square() + x_t.sin().mean(-3).square()
        statistic = (err @ self.weights) * proj.size(-2)
        return statistic.mean()


class FeedForward(nn.Module):
    def __init__(self, dim: int, hidden_dim: int, dropout: float = 0.0):
        super().__init__()
        self.net = nn.Sequential(
            nn.LayerNorm(dim),
            nn.Linear(dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, dim),
            nn.Dropout(dropout),
        )

    def forward(self, x):
        return self.net(x)


class Attention(nn.Module):
    def __init__(self, dim: int, heads: int = 8, dim_head: int = 64, dropout: float = 0.0):
        super().__init__()
        inner = dim_head * heads
        self.heads = heads
        self.dropout = dropout
        self.norm = nn.LayerNorm(dim)
        self.to_qkv = nn.Linear(dim, inner * 3, bias=False)
        self.to_out = nn.Sequential(nn.Linear(inner, dim), nn.Dropout(dropout))

    def forward(self, x, causal: bool):
        B, T, _ = x.shape
        x = self.norm(x)
        q, k, v = (t.view(B, T, self.heads, -1).transpose(1, 2) for t in self.to_qkv(x).chunk(3, dim=-1))
        drop = self.dropout if self.training else 0.0
        out = F.scaled_dot_product_attention(q, k, v, dropout_p=drop, is_causal=causal)
        return self.to_out(out.transpose(1, 2).reshape(B, T, -1))


class Block(nn.Module):
    """Standard pre-norm block."""

    def __init__(self, dim, heads, dim_head, mlp_dim, dropout=0.0, causal=False):
        super().__init__()
        self.causal = causal
        self.attn = Attention(dim, heads, dim_head, dropout)
        self.mlp = FeedForward(dim, mlp_dim, dropout)
        self.norm1 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.norm2 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)

    def forward(self, x, c=None):
        x = x + self.attn(self.norm1(x), causal=self.causal)
        return x + self.mlp(self.norm2(x))


class ConditionalBlock(nn.Module):
    """Causal block with AdaLN-zero conditioning on the action.

    The modulation starts at zero, so at initialization each block is the
    identity and the action's influence is learned from there.
    """

    def __init__(self, dim, heads, dim_head, mlp_dim, dropout=0.0):
        super().__init__()
        self.attn = Attention(dim, heads, dim_head, dropout)
        self.mlp = FeedForward(dim, mlp_dim, dropout)
        self.norm1 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.norm2 = nn.LayerNorm(dim, elementwise_affine=False, eps=1e-6)
        self.adaLN_modulation = nn.Sequential(nn.SiLU(), nn.Linear(dim, 6 * dim))
        nn.init.zeros_(self.adaLN_modulation[-1].weight)
        nn.init.zeros_(self.adaLN_modulation[-1].bias)

    def forward(self, x, c):
        s1, g1, a1, s2, g2, a2 = self.adaLN_modulation(c).chunk(6, dim=-1)
        x = x + a1 * self.attn(modulate(self.norm1(x), s1, g1), causal=True)
        return x + a2 * self.mlp(modulate(self.norm2(x), s2, g2))


class MLP(nn.Module):
    """Linear -> norm -> GELU -> Linear. LeWM uses BatchNorm here so SIGReg gradients flow."""

    def __init__(self, input_dim, hidden_dim, output_dim=None, norm: str = "batch"):
        super().__init__()
        norm_layer = {"batch": nn.BatchNorm1d, "layer": nn.LayerNorm}[norm](hidden_dim)
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim), norm_layer, nn.GELU(), nn.Linear(hidden_dim, output_dim or input_dim)
        )

    def forward(self, x):
        shape = x.shape
        return self.net(x.reshape(-1, shape[-1])).reshape(*shape[:-1], -1)
