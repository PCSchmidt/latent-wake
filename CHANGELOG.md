# Changelog

Changes to what the project measures and how, newest first. Code-level
detail is in the git history and pull requests; reasons are in DECISIONS.md.

## 2026-11-11: learned baselines and ship-type post-hoc check

- Isolation Forest, LSTM autoencoder, and TrAISformer-style forecaster:
  settings picked on validation by a rule fixed in advance, three seeds each,
  one separately recorded test scoring (`configs/eval-baselines.yaml`). The
  TrAISformer-style forecaster matches the JEPA on behavioral anomalies,
  beats it on kinematic ones, and has the lowest test false-alarm rate (1.6%).
- Post hoc: four vessels raise 85% of the JEPA's test false alarms (a moored
  cargo ship, a fishing vessel, a pilot boat, a dredge); dredge false alarms
  are unique to the JEPA.
- `latentwake.posthoc --compare` bootstraps pairwise differences across
  separately recorded benchmarks of the same test set.

## 2026-11-10: ablations (validation only)

- Nine ablations on the validation anomaly set, three seeds where a result
  landed within 0.02 of the main model (ABLATION_RESULTS.md). SIGReg prevents
  collapse and is insensitive to its weight; action conditioning carries the
  prediction; latent prediction helps loitering and costs kinematic
  detection; no setting improves the behavioral mean. A 64-dim latent matches
  the main model on behavioral kinds and beats it on kinematic ones.

## 2026-11-09: test set v2 scored once

- Frozen test set v2 (sha256 826137bdb526) scored once by `run-benchmark.sh`
  with three seeds each of the JEPA and the raw-target predictor. Verdict: 3
  of 8 contract criteria met (EVAL_RESULTS.md).
- `model_eval` now certifies a single, pre-registered scoring reported pass
  or fail; the benchmark refuses a second scoring with different inputs.
- Post-hoc analysis (`latentwake.posthoc`): vessel-level bootstrap intervals
  and a false-alarm breakdown by stratum and vessel.
- MODEL_CARD.md and EVAL_RESULTS.md written.

## 2026-11-09: contract v2.1

- Every detector, baselines included, calibrated as a per-stratum validation
  tail probability. Median/MAD z-scores had sent 99% of fused alerts to
  stopped windows and left the baselines uncalibrated. Margins unchanged.
- Location context dropped from the main model (generalized poorly); kept as
  an ablation result.

## 2026-11-09: contract v2

- Main study restricted to Class A transceivers (Class B, half the reports,
  becomes a secondary analysis).
- Behavioral anomalies injected only into moving cargo, tanker, and passenger
  windows and scored against moving normals of those classes.
- Calibration strata: vessel class × under way.
- Location-cell option, attention pooling, and 4-step chunks compared on
  validation; mean pooling with 8-step chunks kept.
- Test set v1 retired unscored; `data_contract` and `pipeline_validated`
  reopened and passed again (`scripts/reopen-gate.sh`).

## 2026-11-07 to 2026-11-08: contract v1 and the real-data pipeline

- DATA_CONTRACT.md approved: headline claim, margins, fusion rule, alert
  budget.
- Three months of NOAA AIS downloaded and cropped (43.9M reports); linear-time
  resampling and windowing; test set v1 frozen.
- Validation findings v1 (reports/validation-v1.md) led to contract v2.

## 2026-11-05 to 2026-11-07: scope and build

- Project scoped (docs/SCOPE.md); repository, pipeline, injectors, model,
  baselines, training, evaluation, and Meridian gates built and tested on
  synthetic traffic (reports/synthetic-smoke.md).
