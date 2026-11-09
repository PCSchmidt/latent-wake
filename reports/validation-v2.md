# Validation results, contract v2 (2026-11-09)

Validation anomaly set `data/testsets/chesapeake-val-v2` (val split, seed 1,
sha256 7417d50e998a, 11,600 windows). Class A data: 447,193 train / 60,207
val / 55,776 test windows. All models trained after test set v2 froze
(sha256 826137bdb526). One seed each. The test set has not been scored.

## Training

| Run | Params | Final val_pred | val_erank (of 192) | Epoch time |
|---|---|---|---|---|
| jepa-s0 (mean pooling, chunk 8) | 10.10M | 0.0021 | 125.3 | ~73 s |
| jepa-attn-s0 (attention pooling) | 10.10M | 0.0020 | 125.0 | ~85 s |
| jepa-c4-s0 (chunk 4) | 10.08M | 0.0017 | 125.2 | ~125 s |
| jepa-pos-s0 (location cells) | 10.58M | 0.0163 | 117.1 | ~90 s |
| raw-s0 (no encoder) | 7.75M | 0.0051 | n/a | ~29 s |

No collapse warnings. The position model's validation loss is eight times
the others' while its training loss is similar: it does not generalize well
to the validation vessels and period, most likely by memorizing per-cell
traffic.

## AUROC by kind (mean over severity levels)

| kind | attn | c4 | fused | jepa | kalman | physics | pos | raw |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| ais_gap | 0.829 | 0.813 | 0.830 | 0.830 | 0.799 | 0.760 | 0.770 | 0.846 |
| loitering | 0.809 | 0.749 | 0.722 | 0.809 | 0.606 | 0.428 | 0.706 | 0.743 |
| position_spoof | 0.856 | 0.904 | 0.978 | 0.861 | 0.983 | 0.959 | 0.782 | 0.990 |
| route_deviation | 0.604 | 0.593 | 0.587 | 0.599 | 0.529 | 0.479 | 0.698 | 0.611 |
| teleport | 0.833 | 0.887 | 0.977 | 0.832 | 0.985 | 0.960 | 0.757 | 0.994 |

Equal-weight means, computed by hand from the table (the contract check
`python -m latentwake.checks metrics reports/val-v2/results.csv` is
authoritative and also covers AUPRC):

- Behavioral gain, JEPA over Kalman: (0.203 + 0.070) / 2 = **0.137** (margin 0.10)
- Fused over Kalman, all kinds: 0.819 − 0.780 = **0.038** (margin 0.03)
- Fused over JEPA, all kinds: 0.819 − 0.786 = **0.033** (margin 0.03)

Contract v2 moved behavioral results the expected way: JEPA loitering 0.751
(v1) to 0.809, Kalman 0.594 to 0.606, route deviation now above chance for
the JEPA (0.599) and clearly for the position model (0.698).

## Operating point (1% validation budget)

| | physics | kalman | jepa | fused | raw | attn | c4 | pos |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| false alarms, all normals | 0.0103 | 0.0090 | 0.0110 | 0.0107 | 0.0083 | 0.0102 | 0.0098 | 0.0090 |
| false alarms, moving only | 0.0433 | 0.0366 | 0.0097 | **0** | 0.0157 | 0.0090 | 0.0149 | 0.0127 |
| detected, loitering | 0.008 | 0.013 | 0.098 | **0** | 0.007 | 0.137 | 0.055 | 0.043 |
| detected, route deviation | 0.012 | 0.028 | 0.019 | **0** | 0.012 | 0.021 | 0.032 | 0.095 |

**Fused detector anomaly.** The fused detector raises no alarm at all on
moving normal windows and detects no behavioral anomaly, while the JEPA alone
detects 10% of loitering. The fused detector's alerts all land on stopped
windows. The likely cause is double standardization: fused takes the max of
*window* z-scores computed per stratum (vessel class × under way), and some
stopped strata have a tiny median absolute deviation, so their z-scores are
huge and take the whole 1% budget. Version 2's finer strata make such tight
strata more likely. `val_alerts_by_stratum.csv`, now written by every
evaluation, will confirm or rule this out. The fused AUROC criteria pass
anyway, because AUROC is computed within each kind against its own normals.

## Architecture findings

- **Attention pooling**: no change from mean pooling (within 0.01 on every
  kind). Not carried forward.
- **Chunk length 4**: better on spoofs and teleports (+0.04 to +0.06) but
  worse on loitering (−0.06) and 70% slower. Fusion with Kalman already covers
  kinematic kinds, so this trades away the part the JEPA is for. Not carried
  forward.
- **Position context**: best on route deviation by far (0.698, and 0.818 at
  the largest turn) but worst on every kinematic kind and on loitering, with
  the generalization gap above. Worth one more attempt with location dropout
  (`--position-dropout 0.5`), which forces the model to predict from motion
  alone half the time.
- **Raw target** stays strongest on kinematic kinds and is second on
  loitering. The latent model's case rests on behavioral kinds.
