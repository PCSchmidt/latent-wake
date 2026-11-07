# CONTRACT.md

**Project:** Latent Wake
**Owner:** Chris Schmidt
**Date:** 2026-11-07
**Framework:** Meridian (ml-research recipe)

---

## What This Project Does

Latent Wake trains a small JEPA world model on normal vessel motion from public
AIS data in Chesapeake Bay and Hampton Roads, then ranks vessels by how
surprised the model is by their tracks. It is a 12-week portfolio research
project: an original model, a frozen benchmark with classical baselines,
ablations that explain the result, and a demo panel in Darkwater. The full
plan is in `docs/SCOPE.md`; the success criteria are in `DATA_CONTRACT.md`.

---

## Scope

### In scope

- Download, cleaning, resampling, and windowing of three months of NOAA AIS
- Seeded synthetic anomaly injection and frozen, checksummed test sets
- The JEPA model, training, per-class calibration, and evaluation
- Baselines: physics residual, Kalman filter, raw-target predictor (built);
  LSTM autoencoder, Isolation Forest, TrAISformer-style forecaster (planned)
- Ablations: SIGReg weight, SIGReg vs VICReg vs EMA, action on/off, context length, latent size
- Evaluation on OMTAD's equation-grounded benchmark
- A static Darkwater panel of precomputed scores for a replay week
- A write-up with code, configs, and weights

### Out of scope

- Live or streaming scoring (stretch goal only)
- Pairwise anomalies such as rendezvous (stretch goal only)
- Coastline-aware cleaning beyond the implied-speed filter (unless time allows)
- Supervised training on labeled anomalies
- Any data beyond the AIS fields in DATA_CONTRACT.md

---

## Stack

| Layer | Technology |
|-------|-----------|
| ML framework | PyTorch |
| Data processing | DuckDB, pandas, NumPy (Parquet on disk) |
| Experiment tracking | metrics.jsonl per run (W&B optional) |
| Serving | Precomputed scores loaded by Darkwater |
| Deploy | GitHub Pages (Darkwater) |
| Compute | Dell Precision 7770, RTX A4500 16 GB |

---

## Acceptance Criteria

A feature is not complete until:

1. **Happy path works:** correct output for valid input
2. **Integration verified:** data flows end to end (NOAA, crop, process, test set, train, evaluate)
3. **Edge cases handled:** missing fields, sentinel values, gaps, empty days, short tracks
4. **Error handling present:** failures recorded (download manifest, check messages), not silent
5. **Hardened:** reproducible from config and seed; checkpoints and frozen test sets recoverable

Additionally for the ML component:
- Model meets every criterion in DATA_CONTRACT.md
- MODEL_CARD.md is complete and accurate
- Every reported number traces to a run folder and a frozen test-set checksum
