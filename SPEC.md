# SPEC.md

**Project:** Latent Wake
**Owner:** Chris Schmidt
**Date:** 2026-11-07

JEPA surprise detection for maritime vessel tracks, benchmarked against classical baselines.

---

## Data Pipeline

Download NOAA daily files, crop them to the Chesapeake box, clean, split each
vessel into tracks, resample to a 2-minute grid, compute relative-motion
features, cut 64-step windows, and split by time and vessel. "Done" means the
pipeline runs end to end on three months of real data and passes
`pipeline_validated`. Code: `latentwake/data/`.

---

## Anomaly Test Sets

Seeded injection of position spoofs, teleports, AIS gaps, route deviations,
and loitering into held-out windows, with severity sweeps, matched normals,
and write-once checksummed storage. "Done" means a frozen test set exists for
the real test split before any model trains. Code: `latentwake/inject/`.

---

## Model Training

The trajectory JEPA (chunk encoder, action-conditioned predictor, SIGReg),
the training loop with collapse monitoring, and the ablation switches. "Done"
means three seeds train without collapse and pass `training_stable`. Code:
`latentwake/models/`, `latentwake/train.py`.

---

## Baselines

Physics residual, Kalman filter, raw-target predictor, plus the planned LSTM
autoencoder, Isolation Forest, and TrAISformer-style forecaster. "Done" means
every baseline scores the same frozen test set through `latentwake/evaluate.py`.

---

## Model Evaluation

Per-class calibration, per-cell AUROC and AUPRC, OMTAD benchmark numbers,
severity curves, and operating-point metrics, scored against
DATA_CONTRACT.md. "Done" means EVAL_RESULTS.md and MODEL_CARD.md are complete
and `model_eval` is approved.

---

## Ablation Study

SIGReg weight, SIGReg versus VICReg versus EMA, action on/off, context length,
and latent size, three seeds each. "Done" means ABLATION_RESULTS.md explains
what each component contributes and `ablation_study` is approved.

---

## Darkwater Demo

Precomputed scores for a replay week, loaded into Darkwater as a panel of
vessels ranked by surprise with the track and spike shown. "Done" means the
panel is live on GitHub Pages.

---

## Write-up

Results, figures, and reproduction instructions on pcschmidt.github.io, with
code, configs, and weights linked. "Done" means docs/WRITEUP.md is published
and `demo_shipped` is approved.
