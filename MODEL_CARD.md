# Model card: Latent Wake JEPA (contract v2.1)

## Summary

A trajectory world model in the LeWorldModel style that scores how surprising
a vessel's next 16 minutes of AIS reports are, given the previous ones. High
surprise flags candidate anomalies. It runs alongside a Kalman filter, and a
fused detector takes whichever of the two is more alarmed. Research and
portfolio use only.

## Model

| | |
|---|---|
| Architecture | Chunk encoder (4-layer transformer, 192-dim, mean pooling, BatchNorm projector) plus a 6-layer causal predictor conditioned by AdaLN-zero on the next chunk's *reported* speed, course, and heading change |
| Parameters | 10.10M |
| Input | 64 steps on a 2-minute grid (about 2 hours), cut into 8 chunks of 8 steps; per step: east/north displacement, reported speed, sine/cosine of course, heading change, heading-valid flag; vessel class embedding |
| Objective | Next-chunk latent prediction error (MSE) + 0.09 × SIGReg (Epps-Pulley, 17 knots, 1,024 projections); no EMA, no stop-gradient |
| Anomaly score | Per-transition prediction error, calibrated per vessel class × under way on validation, max over the window, then converted to a per-stratum validation tail probability |
| Seeds | 3 (jepa-s0, -s1, -s2); final validation effective rank 125.3 to 125.7 of 192, no collapse warnings |
| Training | 30 epochs, batch 256, AdamW (lr 3e-4, weight decay 1e-3), cosine schedule with 5% warmup, bf16 autocast; about 40 minutes per seed on one RTX A4500 |
| Code | `latentwake/models/jepa.py`, `latentwake/train.py`; SIGReg and AdaLN-zero blocks adapted from LeWorldModel (MIT) |

## Data

NOAA MarineCadastre AIS (public domain), 2025-04-01 to 2025-06-30, cropped to
Chesapeake Bay and Hampton Roads. Class A transceivers only (21.9M of 43.9M
reports). Split by time *and* vessel: training uses reports before 2025-05-31
from 70% of vessels by MMSI hash; validation and test use later reports from
disjoint vessel sets (198 and 180 vessels).

| Split | Windows | Vessels | Stationary share |
|---|--:|--:|--:|
| Train | 447,193 (25% of stationary windows kept for training: 209,221) | 1,129 | 71% |
| Validation | 60,207 | 198 | 67% |
| Test | 55,776 | 180 | 75% |

## Evaluation

Anomalies are synthetic, injected into real held-out tracks: position
spoofs, teleports, and AIS gaps (all Class A vessels), and loitering and
route deviation (moving cargo, tanker, and passenger vessels only, scored
against moving normals of the same classes). Criteria and margins were fixed
in DATA_CONTRACT.md before the test set was scored. The test set was frozen
(sha256 826137bdb526) before any model trained, and was scored once.

Results: see [EVAL_RESULTS.md](EVAL_RESULTS.md). On the validation anomaly
set, averaged over three seeds, six of eight criteria were met; the JEPA's
behavioral AUROC gain over Kalman was +0.090 against a 0.10 margin, and the
fused detector's AUROC gain over Kalman +0.023 against 0.03.

## Intended use

- Research on self-supervised world models for vessel-track anomaly detection.
- A demonstration panel in Darkwater.

Not for operational maritime enforcement, sanctions screening, or any
decision about a real vessel or its crew. A flag means "unusual for this
model," not "wrongdoing."

## Limitations

- **Synthetic anomalies.** Real spoofing, dark activity, and loitering may
  look different from the injectors; results measure detection of the
  injected patterns.
- **One region, one season, Class A only.** Chesapeake Bay and Hampton Roads,
  April to June 2025. Pleasure craft and other Class B traffic are out of
  scope.
- **Weak on small kinematic anomalies alone.** The JEPA is near chance on the
  smallest spoofs and teleports, where Kalman and a raw-target predictor are
  above 0.9 AUROC; the fused detector relies on Kalman for those.
- **Low detection at a 1% alert budget for behavioral anomalies.** About 10%
  to 17% of injected loitering is caught at that budget on validation.
- **Small strata.** Tanker strata have fewer than 200 validation windows and
  fall back to coarser calibration groups.
- **Location is not used.** A learned location embedding helped route
  deviation but generalized poorly, so the main model sees relative motion
  only.
