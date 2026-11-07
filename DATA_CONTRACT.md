# DATA_CONTRACT.md

**Project:** Latent Wake: JEPA surprise detection for maritime vessel tracks
**Owner:** Chris Schmidt
**Date:** 2026-11-07 (draft; approval pending)
**Framework:** Meridian (ml-research recipe)

This document is the single source of truth for what this experiment is trying
to show. The agent implements; the human decides. Every `[DECIDE ...]` marker
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

`model_eval` passes only if **every** criterion in the block below holds,
computed from `reports/eval-v1/results.csv` and averaged over the severity
levels of the listed kinds and over seeds. Kinds are `position_spoof`,
`teleport`, `ais_gap` (kinematically inconsistent) and `loitering`,
`route_deviation` (behavioral). Behavioral kinds are always scored against
moving normal vessels only.

What the synthetic smoke run suggests (small model, CPU, synthetic data only):
the Kalman filter is near 1.0 AUROC on spoofs and teleports while the JEPA is
near 0.75; the JEPA is near 0.94 on loitering while Kalman is near 0.64. A
JEPA-beats-Kalman-everywhere criterion would likely fail on the kinematic
kinds. The raw-target ablation also beat the JEPA on spoofs and teleports, so a
latent-beats-raw criterion would fail today on those kinds (one seed, small
model; see `reports/synthetic-smoke.md` for the caveats and a hypothesis). The
decision below is what result counts as a success worth reporting.

[DECIDE: the project's headline claim. Options: (a) the JEPA beats Kalman on
behavioral anomalies by a margin while staying within a tolerance of it on
kinematic ones; (b) a combined detector (JEPA plus Kalman) beats either alone;
(c) an honest comparison with no win required, where success means the full
evaluation is complete and reproducible. Then fill in the margins below.]

```yaml contract-thresholds
criteria:
  - id: behavioral_gain_over_kalman
    metric: auroc
    method: jepa
    kinds: [loitering, route_deviation]
    vs_method: kalman
    margin: null        # [DECIDE: required lead over Kalman, for example 0.10]
  - id: kinematic_parity_with_kalman
    metric: auroc
    method: jepa
    kinds: [position_spoof, teleport, ais_gap]
    vs_method: kalman
    margin: null        # [DECIDE: allowed shortfall versus Kalman, for example -0.10]
  - id: latent_beats_raw_target
    metric: auroc
    method: jepa
    kinds: [position_spoof, teleport, ais_gap, loitering, route_deviation]
    vs_method: raw
    margin: null        # [DECIDE: required lead over the raw-target ablation, for example 0.0]
```

Operating-point metrics (false alarms per 1,000 vessel-hours, time to detect)
are reported but not gated. [DECIDE: keep them ungated, or add a criterion.]

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
- [DECIDE: confirm these constraints, or edit them.]

---

## Deployment Target

| Field | Value |
|-------|-------|
| Serving | Static: precomputed scores for a replay week, loaded into Darkwater (GitHub Pages) |
| Inference mode | Batch, offline |
| Latency budget | None (offline); live ONNX scoring is a stretch goal |
| Model format | PyTorch checkpoint; ONNX only if the stretch goal is taken |
