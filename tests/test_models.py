"""Tests for the model, SIGReg, baselines, calibration, training, and evaluation."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest
import torch

from latentwake.data.features import FEATURES, step_features
from latentwake.data.geo import KNOTS_TO_MPS, integrate_displacement
from latentwake.models.baselines import kalman_nis, physics_residual
from latentwake.models.blocks import SIGReg
from latentwake.models.jepa import ACTION_IDX, LatentWake, ModelConfig, effective_rank
from latentwake.score import Calibrator, step_scores

torch.manual_seed(0)


def tiny(**kw):
    base = dict(embed_dim=32, enc_depth=1, enc_heads=2, enc_mlp=64, proj_hidden=64, pred_dim=32,
                pred_depth=2, pred_heads=2, pred_mlp=64, dim_head=16, sigreg_proj=64, dropout=0.0)
    base.update(kw)
    return ModelConfig(**base)


def test_sigreg_prefers_gaussian_over_collapsed():
    sig = SIGReg(num_proj=128)
    g = torch.Generator().manual_seed(0)
    gauss = torch.randn(4, 512, 32, generator=g)
    collapsed = torch.ones(4, 512, 32) * 0.5 + 1e-3 * torch.randn(4, 512, 32, generator=g)
    s_g = sig(gauss, generator=torch.Generator().manual_seed(1))
    s_c = sig(collapsed, generator=torch.Generator().manual_seed(1))
    assert s_c > 20 * s_g  # the statistic is O(1) for Gaussian samples (it is scaled by N)
    again = sig(gauss, generator=torch.Generator().manual_seed(1))
    assert torch.equal(s_g, again)


def test_effective_rank():
    assert effective_rank(torch.randn(1000, 16)) > 14
    line = torch.randn(1000, 1) @ torch.randn(1, 16)
    assert effective_rank(line) < 1.1


@pytest.mark.parametrize("cfg", [tiny(), tiny(target="raw"), tiny(use_action=False), tiny(sigreg_weight=0.0)])
def test_forward_shapes_and_losses(cfg):
    m = LatentWake(cfg)
    x, v = torch.randn(8, 64, len(FEATURES)), torch.randint(0, 10, (8,))
    out = m(x, v)
    assert out["per_step"].shape == (8, 7)
    out["loss"].backward()
    if cfg.target == "raw" or cfg.sigreg_weight == 0:
        assert float(out["sigreg_loss"]) == 0.0
    else:
        assert float(out["sigreg_loss"]) > 0
    assert m.surprise(x, v).shape == (8, 7)


def test_actions_exclude_displacement():
    m = LatentWake(tiny())
    x = torch.randn(2, 64, len(FEATURES))
    y = x.clone()
    y[..., FEATURES.index("dx_m")] += 100.0
    y[..., FEATURES.index("dy_m")] -= 100.0
    assert torch.equal(m.actions(x), m.actions(y))
    assert m.actions(x).shape == (2, 7, 8 * len(ACTION_IDX))


def test_adaln_zero_ignores_action_at_init():
    m = LatentWake(tiny()).eval()
    z = torch.randn(3, 7, 32)
    a1, a2 = torch.randn(3, 7, 40), torch.randn(3, 7, 40)
    assert torch.allclose(m.predictor(z, a1), m.predictor(z, a2))


def test_predictions_are_causal():
    m = LatentWake(tiny()).eval()
    x, v = torch.randn(4, 64, len(FEATURES)), torch.randint(0, 10, (4,))
    y = x.clone()
    y[:, 40:48] += 5.0  # change chunk 5 only
    e_x, e_y = m.surprise(x, v), m.surprise(y, v)
    # Transitions 0-3 predict chunks 1-4 from chunks 0-3 and their actions: untouched.
    assert torch.allclose(e_x[:, :4], e_y[:, :4], atol=1e-6)
    assert not torch.allclose(e_x[:, 4:], e_y[:, 4:])


def test_a_few_steps_reduce_loss():
    torch.manual_seed(1)
    m = LatentWake(tiny())
    opt = torch.optim.AdamW(m.parameters(), lr=3e-3)
    x, v = torch.randn(64, 64, len(FEATURES)), torch.randint(0, 10, (64,))
    first = None
    for _ in range(40):
        loss = m(x, v)["loss"]
        first = first if first is not None else float(loss)
        opt.zero_grad()
        loss.backward()
        opt.step()
    assert float(loss) < 0.7 * first


def _straight(n=20, L=64, seed=0):
    rng = np.random.default_rng(seed)
    X = []
    for _ in range(n):
        c, s = rng.uniform(0, 360), rng.uniform(4, 15)
        step = s * KNOTS_TO_MPS * 120
        dx, dy = np.full(L, step * np.sin(np.radians(c))), np.full(L, step * np.cos(np.radians(c)))
        lat, lon = integrate_displacement(37.0, -76.3, dx, dy)
        f = step_features(lat, lon, np.full(L, s), np.full(L, c), np.full(L, c))
        f[0, :2] = f[1, :2]
        X.append(f)
    return np.stack(X)


def test_baselines_quiet_on_consistent_tracks_and_loud_on_jumps():
    X = _straight()
    assert physics_residual(X).max() < 1.0
    nis = kalman_nis(X)
    assert nis[:, 5:].mean() < 4.0  # about the 4 degrees of freedom or less
    J = X.copy()
    J[:, 30, FEATURES.index("dx_m")] += 1852.0  # 1 nmi jump east at step 30
    assert (kalman_nis(J)[:, 30] > 100 * nis[:, 30].max()).all()
    assert (physics_residual(J)[:, 30] > 1800).all()


def test_calibrator_and_step_scores(tmp_path):
    rng = np.random.default_rng(0)
    vclass = np.r_[np.ones(500, int), np.full(500, 4), np.full(5, 7)]  # class 7 is rare
    err = np.abs(rng.normal(0, 1, (len(vclass), 7))) * np.where(vclass == 4, 3.0, 1.0)[:, None]
    cal = Calibrator.fit(err, vclass)
    z = cal.transform(err, vclass)
    for c in (1, 4):
        assert abs(np.median(z[vclass == c])) < 1e-6  # each class centered on its own median
    assert 7 not in cal.median  # falls back to pooled stats
    cal.save(tmp_path / "cal.json")
    assert Calibrator.load(tmp_path / "cal.json").median == cal.median
    s = step_scores(z[:2], chunk_len=8, window_len=64)
    assert s.shape == (2, 64) and (s[:, :8] == 0).all()
    np.testing.assert_allclose(s[:, 8:16], np.repeat(z[:2, :1], 8, axis=1))


def test_train_and_evaluate_end_to_end(tmp_path):
    from latentwake.data import preprocess as pp
    from latentwake.data.synthetic import simulate_days, write_interim
    from latentwake.evaluate import run as evaluate
    from latentwake.inject.build import build_test_set, save_test_set
    from latentwake.train import TrainConfig, load_model, train

    write_interim(simulate_days(dt.date(2025, 4, 1), n_days=6, n_vessels=40, seed=5), tmp_path / "interim")
    pp.run(tmp_path / "interim", tmp_path / "processed")
    cfg = TrainConfig(processed=str(tmp_path / "processed"), out=str(tmp_path / "run"), model=tiny(),
                      epochs=2, batch_size=64, stationary_keep=1.0)
    hist = train(cfg, log=lambda *_: None)
    assert len(hist) == 2 and np.isfinite(hist[-1]["val_pred"])
    assert (tmp_path / "run" / "best.pt").exists()
    model = load_model(tmp_path / "run" / "best.pt")
    assert not model.training

    X, meta, raw = pp.load_split(tmp_path / "processed", "test", normalized=False, raw=True)
    save_test_set(build_test_set(X, raw, meta, seed=0, per_cell=5), tmp_path / "ts")
    models = {"jepa-s0": tmp_path / "run" / "best.pt", "jepa-s1": tmp_path / "run" / "best.pt"}
    res = evaluate(tmp_path / "ts", tmp_path / "processed", models, tmp_path / "eval", fuse_with_kalman="jepa")
    assert set(res.method) == {"physics", "kalman", "jepa-s0", "jepa-s1", "fused-s0", "fused-s1"}
    normals = res[res.kind == "normal"]
    assert len(normals) == 6 and normals.fpr_at_budget.between(0, 1).all()
    assert normals.fpr_at_budget_moving.dropna().between(0, 1).all()
    assert res[res.kind != "normal"].detect_at_budget.between(0, 1).all()
    with pytest.raises(ValueError, match="matched no model"):
        evaluate(tmp_path / "ts", tmp_path / "processed", models, tmp_path / "eval2", fuse_with_kalman="nope")
    assert res[res.kind != "normal"].auroc.between(0, 1).all()
    assert (tmp_path / "eval" / "summary.md").read_text().startswith("## AUROC")


def test_window_z_and_fusion_are_scale_free():
    from latentwake.evaluate import _window_z

    rng = np.random.default_rng(0)
    vclass = np.r_[np.zeros(400, int), np.ones(400, int)]
    small = rng.gamma(2.0, 1.0, 800)                 # e.g. JEPA window scores
    big = 1000 * rng.gamma(2.0, 1.0, 800)            # e.g. Kalman NIS, another scale
    z_small = _window_z(small, vclass, small, vclass)
    z_big = _window_z(big, vclass, big, vclass)
    for z in (z_small, z_big):
        for c in (0, 1):
            assert abs(np.median(z[vclass == c])) < 1e-9
    # Same calibrated scale regardless of the raw units.
    assert 0.5 < np.median(np.abs(z_big)) / np.median(np.abs(z_small)) < 2.0
