# Synthetic smoke run (2026-11-07)

**What this is:** a pipeline check on *synthetic* traffic from
`latentwake/data/synthetic.py`, run on a 2-core CPU with the 0.8M-parameter
`--size small` model, one seed, 25 epochs. It shows the full pipeline works
end to end and points at questions for the real runs. It is **not** evidence
about real AIS traffic. The synthetic data has simple Gaussian noise and
perfectly consistent kinematics, which flatters physics-based baselines.

## Setup

- 24 synthetic days, 90 vessels, seed 11: 12,032 train / 1,763 val / 1,087 test windows
- Frozen test set: 60 windows per cell, 29 cells, plus normals (2,827 windows)
- Models: `jepa` (latent target, SIGReg 0.09, actions on); `raw` (same predictor,
  raw-feature target, no encoder or SIGReg); `noaction` (actions zeroed);
  `nosigreg` (SIGReg 0, 12 epochs)
- Behavioral kinds scored against moving normals only

## AUROC by kind (mean over severity levels)

| kind | jepa | raw | noaction | nosigreg | kalman | physics |
|:--|--:|--:|--:|--:|--:|--:|
| ais_gap | 0.781 | 0.749 | 0.606 | 0.735 | **0.812** | 0.753 |
| loitering | **0.939** | 0.936 | 0.863 | 0.898 | 0.638 | 0.426 |
| position_spoof | 0.769 | 0.898 | 0.606 | 0.710 | **0.998** | 0.960 |
| route_deviation | **0.632** | 0.550 | 0.589 | 0.580 | 0.581 | 0.495 |
| teleport | 0.730 | 0.917 | 0.598 | 0.723 | **0.999** | 0.963 |

## AUPRC by kind

| kind | jepa | raw | noaction | nosigreg | kalman | physics |
|:--|--:|--:|--:|--:|--:|--:|
| ais_gap | 0.286 | 0.434 | 0.071 | 0.177 | **0.612** | 0.388 |
| loitering | 0.580 | **0.772** | 0.350 | 0.541 | 0.173 | 0.093 |
| position_spoof | 0.312 | 0.691 | 0.079 | 0.232 | **0.950** | 0.849 |
| route_deviation | 0.167 | 0.156 | 0.136 | 0.135 | **0.171** | 0.128 |
| teleport | 0.266 | 0.738 | 0.072 | 0.343 | **0.965** | 0.851 |

Per-cell tables are produced by `latentwake.evaluate` (`summary.md`).

## Training

| run | final val pred loss | val effective rank (of 64) | sec/epoch |
|:--|--:|--:|--:|
| jepa | 0.0158 | 24.6 (rising from 13) | 24 |
| raw | 0.0142 | 27.4 (fixed; no encoder) | 4 |
| noaction | 0.0944 | 23.9 | 18 |
| nosigreg | 0.0005 | 10.1 (falling from 18) | 15 |

## Findings, with their limits

1. **Action conditioning carries the signal.** Without the reported
   kinematics, validation loss is 6x higher and detection drops on every kind.
   This supports the core design: predict where the ship goes from what it
   reports.
2. **SIGReg prevents dimensional collapse, not constant collapse.** Without it,
   prediction loss falls 30x and effective rank slides steadily. The BatchNorm
   projector keeps outputs from going constant, so collapse shows up as rank
   loss, not as zero variance. The first collapse warning (rank below 10% of
   the embedding size) would not have fired on this run, so the check now also
   flags a rank below 25% or a sustained fall below 85% of its peak
   (`collapse_signal` in `latentwake/models/jepa.py`). That catches this run
   and passes the healthy ones.
3. **The latent target did not beat the raw target on kinematic anomalies.**
   The raw-target predictor leads the JEPA on spoofs (0.90 vs 0.77) and
   teleports (0.92 vs 0.73), ties on loitering by AUROC, and leads on it by
   AUPRC. The JEPA leads only on route deviation (0.63 vs 0.55). One
   hypothesis, not yet tested: mean-pooling an 8-step chunk dilutes the
   single-step displacement spike that a spoof creates, while the raw target
   keeps it. Candidate fixes are attention or max pooling, shorter chunks, or
   a per-step prediction head.
4. **Kalman wins on kinematic anomalies here, and synthetic data favors it.**
   Real AIS has multipath, timing jitter, and interpolation artifacts that a
   constant-velocity filter with Gaussian noise will handle worse. Whether it
   keeps this lead is the first real-data question.
5. **Behavioral anomalies are where learned models separate from physics.**
   Every learned model beats Kalman and the physics check on loitering; route
   deviation stays hard for everyone.

## Fused detector (added after the headline-claim decision)

`fused` = the larger of the JEPA's and the Kalman filter's window z-scores,
each calibrated per vessel class on validation windows. Kinds are weighted
equally.

| method | AUROC, all kinds | AUPRC, all kinds | AUROC, behavioral | AUPRC, behavioral |
|:--|--:|--:|--:|--:|
| fused | **0.871** | **0.585** | 0.775 | 0.328 |
| kalman | 0.806 | 0.574 | 0.610 | 0.172 |
| raw | 0.810 | 0.558 | 0.743 | **0.464** |
| jepa | 0.770 | 0.322 | **0.785** | 0.373 |

By AUROC, fusion beats both of its parts (+0.065 over Kalman, +0.10 over
the JEPA). By AUPRC, it barely beats Kalman (+0.011): taking a max gives each
normal window two chances to score high, which costs precision. Whether the
contract gates on AUROC, AUPRC, or both is an owner decision. The raw-target
model fused with Kalman is a natural comparison point for the real runs.

## Operating point (1% validation alert budget)

| method | test false-alarm rate | share detected, all kinds |
|:--|--:|--:|
| kalman | 1.1% | 0.530 |
| fused | 2.7% | 0.526 |
| jepa | 3.3% | 0.286 |

At a fixed alert budget, fusion does not add detections on this run. It
spends part of the budget on the JEPA and loses some kinematic detections
(spoofs 0.86 versus Kalman's 0.98) for its gains on loitering (0.38 versus
0.07). False-alarm rates overshoot the budget, partly because the threshold
rests on about 18 validation windows. Real data will have far more.

Against the final contract, this run passes 6 of 8 criteria and fails both
operating-point criteria.

## What this means for DATA_CONTRACT.md

A "JEPA beats Kalman on every kind" criterion would fail on this evidence, and
a "latent beats raw target" criterion would fail today on kinematic kinds.
Neither result is final. They come from one seed of a small model on
synthetic data. But they should inform which claim the contract commits to
before any real-data run.
