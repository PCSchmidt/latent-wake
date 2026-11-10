# Ablation results (validation)

All results are on the validation anomaly set `data/testsets/chesapeake-val-v2`
(sha256 7417d50e998a), with contract v2.1 calibration. The test set was not
used; it has been scored once, for the main model only (EVAL_RESULTS.md).

Each ablation changes one setting of the main JEPA (SIGReg weight 0.09, action
conditioning on, 25% of anchored windows kept, 192-dim latent, 64-step
context, mean pooling, 8-step chunks). Per the plan in DECISIONS.md, every
ablation that landed within 0.02 of the main model with one seed was rerun
with seeds 1 and 2. Raw output: `reports/ablation-val/summary.md` (one seed)
and `reports/ablation-val-seeds/summary.md` (three seeds).

## Summary

Behavioral = mean AUROC over loitering and route deviation (the headline
kinds). Kinematic = mean over position spoof, teleport, and AIS gap. Ranges
are over seeds.

| Variant | Seeds | Behavioral | Change | Kinematic | Change | Final val rank |
|---|--:|--:|--:|--:|--:|--:|
| **Main JEPA** | 3 | **0.705** (0.703–0.710) | | 0.838 (0.835–0.843) | | 125 / 192 |
| SIGReg weight 0.02 | 3 | 0.701 (0.697–0.711) | −0.004 | 0.831 (0.829–0.833) | −0.007 | 88 / 192 |
| Latent size 64 | 3 | 0.700 (0.687–0.711) | −0.005 | **0.867** (0.863–0.870) | **+0.029** | 61 / 64 |
| SIGReg weight 0.3 | 3 | 0.693 (0.691–0.699) | −0.012 | 0.842 (0.841–0.843) | +0.004 | 151 / 192 |
| Keep all anchored windows | 3 | 0.690 (0.680–0.702) | −0.015 | 0.832 (0.825–0.839) | −0.006 | 144 / 192 |
| Context 32 steps | 1 | 0.680 | −0.025 | 0.796 | −0.042 | 147 / 192 |
| Raw target (no encoder, no SIGReg) | 3 | 0.675 (0.673–0.677) | −0.030 | 0.939 (0.938–0.939) | +0.101 | n/a |
| No action conditioning | 1 | 0.666 | −0.039 | 0.790 | −0.048 | 94 / 192 |
| SIGReg weight 0 | 1 | 0.598 | −0.107 | 0.668 | −0.170 | **2.6** / 192 (collapsed) |
| *Kalman (reference)* | | *0.615* | | *0.932* | | |

Changes are against the main JEPA's three-seed mean. One-seed variants are
outside the 0.02 band by a clear margin, so a second or third seed would not
change their reading.

## What each component contributes

**SIGReg is necessary, and its weight is not sensitive.** Without it the
encoder collapses: latent effective rank falls to 2.6 of 192 and prediction
loss goes to zero, because predicting a near-constant latent is trivial. The
collapsed model does worse than Kalman on behavioral anomalies (0.598 vs
0.615) and far worse on kinematic ones. Across a fifteenfold range of weights
(0.02 to 0.3) the behavioral mean moves by at most 0.012 and the kinematic by
at most 0.007, while latent rank goes from 88 to 151. At 0.02 the seeds
overlap the main model's; at 0.3 they sit consistently about 0.01 lower (all
three seeds below the main model's lowest). The LeWorldModel default (0.09)
is the best of the three, by a small margin.

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
raw-target predictor (same predictor, no encoder, no SIGReg) is 0.030 lower
on behavioral kinds, entirely from loitering (0.727 vs 0.800, three seeds
each; on route deviation it is 0.012 higher), and 0.101 higher on kinematic
kinds, where it matches Kalman. A likely reason is that the encoder pools each
8-step chunk into one latent, which dilutes the single-step jumps kinematic
anomalies produce; attention pooling, tried during model selection, did not
recover them.

**Longer context helps.** Halving the context to 32 steps (about an hour)
costs 0.025 behavioral and 0.042 kinematic.

**A smaller latent is at least as good.** With three seeds, a 64-dim latent
matches the main model on behavioral kinds (0.700 vs 0.705; the ranges
overlap, and the one-seed reading of −0.016 was its lowest seed) and is
consistently better on kinematic kinds (+0.029, every seed above every main
seed), and it uses nearly all of its space (rank 61 of 64). It also had the lowest false-alarm rate on
moving validation normals (0.4% to 0.8%). Found after the test scoring, so it
is not swapped in for the reported model; it is the configuration to carry
into any next version.

**Keeping all anchored windows does not help on validation.** Loitering is
unchanged (0.803 vs 0.800, three seeds each) and route deviation falls
consistently (0.577 vs 0.611; every seed below every main seed). Whether
it fixes the JEPA's extra false alarms on anchored cargo ships on *test*
vessels cannot be answered here: calibration sets every validation stratum's
alert rate to the budget by construction, so validation cannot show a
stratum-level false-alarm problem.

**The main configuration was not a poor choice for the headline.** No single
change improves the behavioral mean, the quantity the headline criterion
missed, beyond seed noise. The miss in EVAL_RESULTS.md is not explained by an
untuned setting among those tested here. The 64-dim latent would have been
equal on that measure and better on kinematic anomalies.

## Not covered

VICReg and EMA/stop-gradient in place of SIGReg (deferred, DECISIONS.md),
pooling and chunk length (compared during model selection,
reports/validation-v2.md), and location context (reports/validation-v2.md).
