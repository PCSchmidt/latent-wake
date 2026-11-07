"""Non-learned baselines. Both read unnormalized feature windows (N, L, F).

physics_residual
    Per step, the distance between where the ship moved and where its reported
    speed and course say it should have moved. No state, no tuning.

kalman
    A constant-velocity Kalman filter over position and velocity. Each step it
    observes the position (from the displacements) and the reported velocity
    (from speed and course). The score is the normalized innovation squared
    (NIS): how surprising each new report is given everything before it, in
    units of its own expected uncertainty. This is the classical answer to
    "does this track make physical sense?" and the bar the JEPA has to clear.

Both return per-step scores (N, L) with step 0 set to 0, plus a window score
(the max over steps).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from latentwake.data.features import FEATURES
from latentwake.data.geo import KNOTS_TO_MPS

STEP_S = 120.0
_i = FEATURES.index


def _reported_velocity(X):
    v = X[..., _i("sog_kn")] * KNOTS_TO_MPS
    return v * X[..., _i("sin_cog")], v * X[..., _i("cos_cog")]


def physics_residual(X: np.ndarray) -> np.ndarray:
    """(N, L) meters of disagreement between observed and reported motion."""
    X = np.asarray(X, dtype=np.float64)
    vx, vy = _reported_velocity(X)
    res = np.hypot(X[..., _i("dx_m")] - vx * STEP_S, X[..., _i("dy_m")] - vy * STEP_S)
    res[:, 0] = 0.0
    return res


@dataclass
class KalmanConfig:
    accel_std: float = 0.02      # m/s^2, white-noise acceleration
    pos_std: float = 15.0        # m, position report noise (incl. resampling)
    vel_std: float = 0.3         # m/s, reported-velocity noise
    init_pos_std: float = 30.0
    init_vel_std: float = 2.0


def kalman_nis(X: np.ndarray, cfg: KalmanConfig | None = None) -> np.ndarray:
    """(N, L) normalized innovation squared per step, vectorized over windows."""
    cfg = cfg or KalmanConfig()
    X = np.asarray(X, dtype=np.float64)
    N, L, _ = X.shape
    dx = X[..., _i("dx_m")].copy()
    dy = X[..., _i("dy_m")].copy()
    dx[:, 0] = dy[:, 0] = 0.0
    px, py = np.cumsum(dx, axis=1), np.cumsum(dy, axis=1)
    vx, vy = _reported_velocity(X)

    dt = STEP_S
    Fm = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float64)
    q = cfg.accel_std**2
    Q1 = np.array([[dt**4 / 4, dt**3 / 2], [dt**3 / 2, dt**2]]) * q
    Q = np.zeros((4, 4))
    Q[np.ix_([0, 2], [0, 2])] = Q1
    Q[np.ix_([1, 3], [1, 3])] = Q1
    R = np.diag([cfg.pos_std**2, cfg.pos_std**2, cfg.vel_std**2, cfg.vel_std**2])

    x = np.stack([px[:, 0], py[:, 0], vx[:, 0], vy[:, 0]], axis=1)  # (N, 4); H = I
    P = np.broadcast_to(
        np.diag([cfg.init_pos_std**2] * 2 + [cfg.init_vel_std**2] * 2), (N, 4, 4)
    ).copy()
    nis = np.zeros((N, L))
    eye = np.eye(4)
    for k in range(1, L):
        x = x @ Fm.T
        P = Fm @ P @ Fm.T + Q
        z = np.stack([px[:, k], py[:, k], vx[:, k], vy[:, k]], axis=1)
        y = z - x
        S = P + R
        Sinv = np.linalg.inv(S)
        nis[:, k] = np.einsum("ni,nij,nj->n", y, Sinv, y)
        K = P @ Sinv
        x = x + np.einsum("nij,nj->ni", K, y)
        P = (eye - K) @ P
    return nis


def window_score(per_step: np.ndarray) -> np.ndarray:
    return np.asarray(per_step).max(axis=1)
