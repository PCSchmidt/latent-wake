# Ablation results (validation, draft)

**Status:** one seed per ablation; extra seeds pending where the
pre-registered rule asks for them (below). Everything here is on the
validation anomaly set `data/testsets/chesapeake-val-v2` (sha256 7417d50e998a),
with contract v2.1 calibration. The test set was not used; it has been scored
once, for the main model only (EVAL_RESULTS.md).

Each ablation changes one setting of the main JEPA (SIGReg weight 0.09, action
conditioning on, 25% of anchored windows kept, 192-dim latent, 64-step
context, mean pooling, 8-step chunks), trained with seed 0. Raw output:
`reports/ablation-val/summary.md`.

## Summary

Behavioral = mean AUROC over loitering and route deviation (the headline
kinds). Kinematic = mean over position spoof, teleport, and AIS gap. Change is
against the main JEPA (seed 0).

| Variant | Behavioral | Change | Kinematic | Change | Final val rank (of latent size) |
|---|--:|--:|--:|--:|--:|
| **Main JEPA** | **0.704** | | 0.843 | | 125 / 192 |
| SIGReg weight 0.02 | 0.696 | −0.007 | 0.831 | −0.012 | 87 / 192 |
| SIGReg weight 0.3 | 0.690 | −0.013 | 0.841 | −0.002 | 151 / 192 |
| Keep all anchored windows | 0.688 | −0.016 | 0.839 | −0.004 | 143 / 192 |
| Latent size 64 | 0.687 | −0.016 | 0.868 | +0.025 | 61 / 64 |
| Context 32 steps | 0.680 | −0.024 | 0.796 | −0.047 | 147 / 192 |
| Raw target (no encoder, no SIGReg) | 0.676 | −0.027 | 0.939 | +0.095 | n/a |
| No action conditioning | 0.666 | −0.037 | 0.790 | −0.054 | 94 / 192 |
| SIGReg weight 0 | 0.598 | −0.106 | 0.668 | −0.176 | **2.6** / 192 (collapsed) |
| *Kalman (reference)* | *0.615* | | *0.932* | | |

For scale: the main JEPA's three seeds span 0.007 on the behavioral mean
(0.703 to 0.709).

## What each component contributes

**SIGReg is necessary, and its weight is not sensitive.** Without it the
encoder collapses: latent effective rank falls to 2.6 of 192 and prediction
loss goes to zero, because predicting a near-constant latent is trivial. The
collapsed model does worse than Kalman on behavioral anomalies (0.598 vs
0.615) and far worse on kinematic ones. Across a fifteenfold range of weights
(0.02 to 0.3) the behavioral mean moves by at most 0.013 and the kinematic by
at most 0.012, while latent rank goes from 87 to 151. The LeWorldModel
default (0.09) is the best of the three tried.

**Action conditioning carries most of the prediction.** Without the next
chunk's reported speed, course, and heading, validation prediction loss is
about 30 times higher (0.064 vs 0.0021), behavioral AUROC falls 0.037, and
kinematic AUROC falls 0.054. One exception: on the *smallest* spoofs and
teleports the unconditioned model does better (0.657 vs 0.573 and 0.689 vs
0.489 at the lowest level). Conditioning on reports that a spoof leaves
unchanged appears to let the model predict a plausible next chunk and absorb
a small position offset, while the unconditioned model is surprised by any
motion. At larger offsets conditioning wins clearly.

**Predicting in latent space helps behavioral detection, not kinematic.** The
raw-target predictor (same predictor, no encoder, no SIGReg) is 0.027 lower
on behavioral kinds, entirely from loitering (0.730 vs 0.798; on route
deviation it is 0.014 higher), and 0.095 higher on kinematic kinds, where it
matches Kalman. A likely reason is that the encoder pools each
8-step chunk into one latent, which dilutes the single-step jumps kinematic
anomalies produce; attention pooling, tried during model selection, did not
recover them.

**Longer context helps.** Halving the context to 32 steps (about an hour)
costs 0.024 behavioral and 0.047 kinematic.

**Latent size trades one kind for the other.** A 64-dim latent is 0.016 lower
on behavioral kinds and 0.025 higher on kinematic ones, and uses its space
almost fully (rank 61 of 64).

**Keeping all anchored windows does not help on validation.** Loitering rises
slightly (0.803 vs 0.798) and route deviation falls (0.573 vs 0.609). Whether
it fixes the JEPA's extra false alarms on anchored cargo ships on *test*
vessels cannot be answered here: calibration sets every validation stratum's
alert rate to the budget by construction, so validation cannot show a
stratum-level false-alarm problem.

**The main configuration was not a poor choice.** No single change improves
the behavioral mean, which is the quantity the headline criterion missed. The
miss in EVAL_RESULTS.md is not explained by an untuned setting among those
tested here.

## Extra seeds (pending)

The plan (DECISIONS.md, 2026-11-09) adds seeds where an ablation lands within
0.02 of the main model on the behavioral mean: SIGReg 0.02, SIGReg 0.3, all
anchored windows, and latent size 64. Seeds 1 and 2 for each will replace the
single-seed numbers above. Context 32 (−0.024) and the others are outside the
band and stay at one seed.

## Not covered

VICReg and EMA/stop-gradient in place of SIGReg (deferred, DECISIONS.md),
pooling and chunk length (compared during model selection,
reports/validation-v2.md), and location context (reports/validation-v2.md).
