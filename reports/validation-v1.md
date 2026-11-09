# Validation anomaly set v1 (2026-11-09)

**What this is:** jepa-s0 and raw-s0 (one seed each, full size, 30 epochs on
three months of real Chesapeake data) scored on a validation anomaly set
built from the val split with seed 1 (`chesapeake-val-v1`, sha256
26c7fc58062f). It is used for architecture and calibration choices, as the
contract allows. The frozen test set has not been scored. Normal windows
here also feed calibration, so false-alarm rates read slightly low; the bias
is the same for every method.

## AUROC by kind (mean over severity levels)

| kind | fused-s0 | jepa-s0 | kalman | physics | raw-s0 |
|:--|--:|--:|--:|--:|--:|
| ais_gap | 0.807 | 0.808 | 0.805 | 0.774 | **0.832** |
| loitering | 0.566 | **0.751** | 0.594 | 0.473 | 0.671 |
| position_spoof | 0.980 | 0.856 | **0.986** | 0.968 | 0.980 |
| route_deviation | 0.511 | 0.527 | 0.521 | 0.481 | **0.541** |
| teleport | 0.984 | 0.830 | **0.988** | 0.968 | **0.988** |

Small anomalies, where the methods separate:

| cell | jepa-s0 | raw-s0 | kalman |
|:--|--:|--:|--:|
| spoof 0.1 nmi | 0.542 | 0.917 | 0.937 |
| spoof 0.25 nmi | 0.706 | 0.972 | 0.982 |
| teleport 0.1 nmi | 0.526 | 0.946 | 0.944 |
| teleport 0.25 nmi | 0.563 | 0.985 | 0.984 |

## Operating point (1% validation budget)

| false-alarm rate | physics | kalman | jepa-s0 | fused-s0 | raw-s0 |
|:--|--:|--:|--:|--:|--:|
| all normals | 1.22% | 1.33% | 1.05% | 1.45% | 1.14% |
| moving only | 5.69% | 5.86% | **2.12%** | 6.88% | 4.84% |

## Findings

1. **The JEPA misses small kinematic anomalies.** It is near chance on
   spoofs and teleports at 0.1 to 0.25 nmi, where raw-target and Kalman are
   above 0.9. All methods are near 1.0 from 1 nmi up. This matches the
   synthetic run and the hypothesis that mean-pooling a chunk dilutes a
   one-step jump.
2. **The JEPA leads on loitering:** 0.751, against 0.671 raw and 0.594 Kalman.
3. **Route deviation is near chance for every method.** The features are
   relative motion only, so no model knows where the lanes are; a turn looks
   like ordinary maneuvering.
4. **The contracted fusion rule underperforms Kalman alone** (0.770 vs 0.779
   mean AUROC) and drops loitering to 0.566. Kalman's per-class z-scores mix
   anchored and moving windows, so moving vessels get inflated Kalman scores
   (5.9% moving false alarms), which swamp the JEPA under a max.
5. **The JEPA holds its alarm budget on moving vessels** (2.1%) far better
   than Kalman (5.9%) or raw-target (4.8%).
6. Raw-target training overfits: its validation loss is flat after epoch 2
   (about 0.106) while training loss keeps falling.

## Against the contract (AUROC, approximate, one seed)

- JEPA over Kalman, behavioral: +0.081 (needs +0.10), fail
- Fused over Kalman, all kinds: -0.009 (needs +0.03), fail
- Fused over JEPA, all kinds: +0.015 (needs +0.03), fail

## Next

- Pooling variants (attention pooling; 4-step chunks): architecture changes
  on validation, no contract change.
- Calibration by vessel class and motion state: changes the fusion rule, so
  it needs a contract amendment and re-approval.
- Route deviation: try coarse position context as an architecture variant
  before considering any change to the criteria.
