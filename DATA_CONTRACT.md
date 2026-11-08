# DATA_CONTRACT.md

**Project:** Latent Wake: JEPA surprise detection for maritime vessel tracks
**Owner:** Chris Schmidt
**Date:** 2026-11-07 (all decisions recorded; owner approval of the `data_contract` gate pending)
**Framework:** Meridian (ml-research recipe)

This document is the single source of truth for what this experiment is trying
to show. The agent implements; the human decides. Every DECIDE marker (square brackets, starting with DECIDE)
is a decision only the owner makes. `scripts/validate-data-contract.sh` blocks
the `data_contract` gate while any marker remains or any threshold is empty.
Once the gate passes, these thresholds are what `validate-metrics.sh` scores
the results against at `model_eval`.

**Provenance note.** This draft was written after a smoke run on *synthetic*
traffic (results in `reports/synthetic-smoke.md`). No model has seen real
NOAA data. Synthetic results show how the pipeline behaves, not how real
traffic will. Thresholds should be chosen on what result would be worth
reporting, not tuned to the synthetic numbers.

---

## Problem Statement

Maritime analysts need to find vessels whose AIS reports cannot be trusted:
spoofed positions, dark periods, and unusual behavior such as loitering or
leaving a route. Latent Wake scores each 2-hour vessel track by how much a
world model, trained only on normal traffic, is surprised by it. An analyst
reviews the vessels ranked highest. The research question is whether a JEPA
world model, which predicts in latent space and is conditioned on what a
vessel reports it is doing, catches anomalies that a classical physics filter
misses, without giving up the anomalies the filter already catches.

---

## Data Source

| Field | Value |
|-------|-------|
| Source | NOAA MarineCadastre AIS daily files (`ais-YYYY-MM-DD.csv.zst`) |
| Region | Chesapeake Bay and Hampton Roads, box in `latentwake/data/regions.py` |
| Period | 2025-04-01 to 2025-06-30 (three months) |
| Volume | Unknown until the first download; record it here after step 1 |
| Access | Public HTTPS, no key (`latentwake/data/download.py`) |
| License | Public US government data |
| Evaluation data | OMTAD (CC BY-NC, evaluation only, not redistributed) and its equation-grounded anomaly labels |

---

## Schema

```
Field name       | Type      | Description
-----------------|-----------|-------------------------------------------------
mmsi             | int64     | Vessel identity (9 digits; ship stations 2xx-7xx)
base_date_time   | timestamp | Report time, UTC
latitude         | float64   | Degrees
longitude        | float64   | Degrees
sog              | float64   | Speed over ground, knots (102.3 = not available)
cog              | float64   | Course over ground, degrees (360 = not available)
heading          | float64   | True heading, degrees (511 = not available)
vessel_type      | int32     | AIS ship-type code
(other columns kept but unused: vessel_name, imo, call_sign, status, length, width, draft, cargo, transceiver)
```

Model input per 2-minute step (`latentwake/data/features.py`): east and north
displacement (m), reported speed, sine and cosine of reported course, heading
change, heading-valid flag. Relative motion only; no absolute position.

### Known Data Quality Issues

- NOAA's 2025 files changed column names and file naming; the download step
  normalizes both schemas. Not yet verified against a real 2025 file.
- Sentinel values (SOG 102.3, COG 360, heading 511) become missing, not zero.
- Class B transponders often send no heading.
- Course is unreliable below about 1 knot.
- Single-report position glitches are removed; a lasting position jump is
  kept, since it may be real spoofing.
- Points on land are not removed yet (no coastline file).

---

## Target

| Field | Value |
|-------|-------|
| Output | Surprise score per 16-minute chunk; window score is the max |
| Type | Unsupervised anomaly detection (trained on normal traffic only) |
| Class balance | Test set: about one normal window per anomalous window per cell; field rate unknown and low |
| Ground truth | Seeded synthetic anomalies injected into held-out real tracks (5 kinds, severity sweeps), plus OMTAD's equation-grounded labels |

---

## Train / Val / Test Split

| Split | Share | Method |
|-------|-------|--------|
| Train | 70% of vessels | Windows ending before the cutoff |
| Validation | 15% of vessels | Windows starting on or after the cutoff |
| Test | 15% of vessels | Windows starting on or after the cutoff; frozen with a checksum before any model run |

**Temporal note:** The cutoff is two-thirds through the period by default
(about 2025-06-01). Vessels are assigned to pools by a seeded hash of MMSI, so
no vessel and no time period appears on both sides. Enforced by
`scripts/validate-splits.sh`.

---

## Success Metric

**Headline claim (owner decision, 2026-11-07):** the JEPA catches behavioral
anomalies that physics-based detection misses, and adding it to a Kalman
filter gives a better detector than either one alone.

`model_eval` passes only if **every** criterion in the block below holds,
computed from `reports/eval-v1/results.csv`. Each method's score is the mean
over each kind's severity cells, then weighted equally across the listed
kinds, then averaged across seeds (`jepa-s0`, `jepa-s1`, ...). Kinds are
`position_spoof`, `teleport`, `ais_gap` (kinematically inconsistent) and
`loitering`, `route_deviation` (behavioral). Behavioral kinds are always
scored against moving normal vessels only.

**The combined detector (`fused`)** is fixed before any real data and fits
nothing to a test set. Each detector's window score is turned into a robust
z-score per vessel class using validation windows (median and MAD). The
fused score is the larger of the JEPA's z and the Kalman filter's z.
Implemented in `latentwake/evaluate.py` (`model_scores`); `jepa-sN` yields
`fused-sN`.

**What the synthetic smoke run shows** (small model, one seed, CPU, synthetic
data only; see `reports/synthetic-smoke.md`):

| Criterion | AUROC difference | AUPRC difference |
|---|--:|--:|
| JEPA minus Kalman, behavioral kinds | +0.175 | +0.201 |
| Fused minus Kalman, all kinds | +0.065 | +0.011 |
| Fused minus JEPA, all kinds | +0.101 | +0.263 |

The AUPRC column matters. Taking the max of two scores gives each normal
window two chances to score high, which costs precision. By AUPRC, the fused
detector barely beats Kalman on this run.

**Metrics (owner decision, 2026-11-07): AUROC and AUPRC both gated, plus the
operating point.** Margins follow the agent's recommendation, accepted by the
owner. Where the synthetic run showed room, the margins require a real lead.
For fused versus Kalman by AUPRC, the weak spot of max-fusion, the margin
requires only no loss of precision.

**Operating point.** Each method's alert threshold is set on validation
windows so that 1% would alert (`alert_fpr` in `configs/eval.yaml`). At that
threshold, two things are gated:
- **Calibration holds:** the fused detector's false-alarm rate on the test
  set's normal windows is at most 2%, twice the budget.
- **Fusion does not cost detections:** averaged over all kinds, the fused
  detector catches at least as many anomalies as Kalman alone.

Time to detect is reported, not gated.

On the synthetic run, both operating-point criteria would fail. The fused
false-alarm rate was 2.7%, with a threshold estimated from only about 1,800
validation windows. Detection was 0.526 for fused versus 0.530 for Kalman, at
a higher false-alarm rate. These are gated anyway: an alerting system that
cannot hold its alarm budget is not deployable, and real data will settle
whether this result holds.

```yaml contract-thresholds
criteria:
  # Ranking quality: AUROC
  - id: behavioral_gain_over_kalman_auroc
    metric: auroc
    method: jepa
    kinds: [loitering, route_deviation]
    vs_method: kalman
    margin: 0.10
  - id: fused_beats_kalman_auroc
    metric: auroc
    method: fused
    kinds: [position_spoof, teleport, ais_gap, loitering, route_deviation]
    vs_method: kalman
    margin: 0.03
  - id: fused_beats_jepa_auroc
    metric: auroc
    method: fused
    kinds: [position_spoof, teleport, ais_gap, loitering, route_deviation]
    vs_method: jepa
    margin: 0.03
  # Precision under rarity: AUPRC
  - id: behavioral_gain_over_kalman_auprc
    metric: auprc
    method: jepa
    kinds: [loitering, route_deviation]
    vs_method: kalman
    margin: 0.05
  - id: fused_no_precision_loss_vs_kalman_auprc
    metric: auprc
    method: fused
    kinds: [position_spoof, teleport, ais_gap, loitering, route_deviation]
    vs_method: kalman
    margin: 0.0
  - id: fused_beats_jepa_auprc
    metric: auprc
    method: fused
    kinds: [position_spoof, teleport, ais_gap, loitering, route_deviation]
    vs_method: jepa
    margin: 0.03
  # Operating point: thresholds from validation at a 1% alert budget
  - id: fused_false_alarms_within_2x_budget
    metric: fpr_at_budget
    method: fused
    kinds: [normal]
    op: "<="
    value: 0.02
  - id: fused_detects_at_least_kalman_at_budget
    metric: detect_at_budget
    method: fused
    kinds: [position_spoof, teleport, ais_gap, loitering, route_deviation]
    vs_method: kalman
    margin: 0.0
```

**Reported, not gated:**
- JEPA versus Kalman on kinematic kinds (parity). The fused detector covers these.
- JEPA versus the raw-target ablation (does latent space help?), and the raw
  target fused with Kalman as a comparison point for the fused detector.
- Time to detect, and detection at a stricter 0.1% budget.

---

## Baseline

| Baseline | Description | Synthetic smoke result |
|----------|-------------|------------------------|
| Kalman filter | Constant velocity; observes position and reported velocity; score is max normalized innovation squared | AUROC about 1.0 on spoof and teleport, 0.81 gaps, 0.64 loitering, 0.58 route deviation |
| Physics residual | Observed displacement versus reported speed and course | AUROC 0.96 spoof and teleport, 0.75 gaps, about 0.45 behavioral |
| Raw-target predictor | Same predictor, predicting next-chunk features directly; no encoder, no SIGReg | AUROC 0.90 spoof, 0.92 teleport, 0.75 gaps, 0.94 loitering, 0.55 route deviation (beats the JEPA on kinematic kinds) |
| LSTM autoencoder, Isolation Forest, TrAISformer-style forecaster | Planned for weeks 7-9 | Not yet built |

**Why these baselines:** Kalman is the classical answer to "does this track
make physical sense?" and the bar any learned model has to clear on spoofing.
The raw-target predictor isolates whether predicting in latent space helps at all.

---

## Approach Constraints

Human-approved decisions about the approach (not to be overridden by the agent):

- **Model family:** Trajectory JEPA following LeWorldModel: chunk encoder,
  AdaLN-zero action-conditioned causal predictor, prediction loss plus SIGReg,
  no EMA or stop-gradient. Full size 10.1M parameters.
- **Action:** The next chunk's *reported* speed, course, and heading change,
  never its displacement.
- **Features:** Only the AIS fields above; no weather, charts, or external enrichment.
- **Hyperparameter search:** SIGReg weight by bisection on validation loss
  with effective rank as a guard; other settings fixed at the documented
  defaults. No search against the test set.
- **Seeds:** 3 per configuration; report mean and spread.
- **Rejected approaches:** Pixel or map rendering of tracks; supervised
  training on injected anomalies (it would learn the injector, not normal traffic).
- **Model selection and architecture changes** (pooling, chunk length,
  SIGReg weight) use only validation data: validation loss, plus a separate
  validation anomaly set built from the val split with its own seed. The test
  set is scored once per final configuration. A rerun is allowed only to fix a
  bug, and is logged in DECISIONS.md with the reason.
- The fusion rule and contract thresholds are fixed at approval. Changing
  them later requires amending this contract and re-approving the gate.
- Constraints confirmed by the owner, 2026-11-07, on the agent's recommendation.

---

## Deployment Target

| Field | Value |
|-------|-------|
| Serving | Static: precomputed scores for a replay week, loaded into Darkwater (GitHub Pages) |
| Inference mode | Batch, offline |
| Latency budget | None (offline); live ONNX scoring is a stretch goal |
| Model format | PyTorch checkpoint; ONNX only if the stretch goal is taken |
