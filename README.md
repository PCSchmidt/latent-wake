# Latent Wake

**JEPA surprise detection for maritime vessel tracks.**

Latent Wake trains a small Joint-Embedding Predictive Architecture (JEPA) world model on normal vessel motion from public AIS data. It then flags tracks where the model is *surprised*: the vessel ends up somewhere its own reported speed and course say it shouldn't be. The test set covers spoofed positions, teleports, AIS gaps, route deviation, and loitering; ship-to-ship rendezvous is a stretch goal.

The model follows the [LeWorldModel](https://arxiv.org/abs/2603.19312) recipe (a next-latent prediction loss plus the SIGReg Gaussian regularizer, with no EMA, stop-gradient, or pretrained encoder), ported from pixels to trajectories. It is sized to train on a single laptop GPU (RTX A4500, 16 GB).

> **Status (2026-11-09):** Phase 2 of 4, ahead of the 12-week plan. The pipeline ran on three months of real NOAA data, three seeds trained without collapse, and the frozen test set was scored once: **3 of 8 pre-registered criteria met** (see [Results](#results)). Next: ablations, the remaining baselines, then the Darkwater panel and write-up. The original plan is in [`docs/SCOPE.md`](docs/SCOPE.md).

## Why

In the June 2026 [equation-grounded maritime anomaly benchmark](https://arxiv.org/abs/2606.29721), every tested detector scored near chance (AUROC about 54) on *unexpected AIS activity*: position jumps with no matching change in reported speed or course. That is the classic spoofing signature. A world model that has learned how position should follow from reported kinematics is a natural fit for catching it. As far as I can find, no one has tried a JEPA on it yet.

## How it works

```mermaid
flowchart LR
    A["Chunk t<br/>(8 steps, 16 min)"] --> E1["Encoder + projector"] --> Z1["Latent z(t)"] --> P["Predictor<br/>6-layer, AdaLN-zero"]
    ACT["Action:<br/>reported SOG, COG,<br/>heading for next chunk"] --> P
    B["Chunk t+1"] --> E2["Encoder + projector<br/>(same weights)"] --> Z2["Latent z(t+1)"]
    P -->|"predicted z(t+1)"| ERR["Prediction error<br/>= loss, then surprise score"]
    Z2 --> ERR
    Z2 --> S["SIGReg<br/>(training only)"]
```

- **Observation:** a 16-minute chunk of relative motion (east/north displacement, SOG, sin/cos COG, heading delta).
- **Action:** what the vessel's AIS *claims* it will do next (reported SOG, COG, heading).
- **Loss:** `MSE(predicted z(t+1), z(t+1)) + λ · SIGReg(Z)`, with one hyperparameter.
- **Surprise score:** the same prediction error at inference, calibrated as a validation tail probability per vessel type × under way or stopped.

## Results

One scoring of the frozen test set (180 held-out vessels, June 2025, 11,600 windows), three seeds per learned model. Criteria and margins were fixed in [`DATA_CONTRACT.md`](DATA_CONTRACT.md) before scoring. Full tables: [`EVAL_RESULTS.md`](EVAL_RESULTS.md); model card: [`MODEL_CARD.md`](MODEL_CARD.md).

| AUROC (three-seed mean) | JEPA | Kalman | Raw-target predictor | Fused JEPA + Kalman |
|---|--:|--:|--:|--:|
| Loitering | **0.938** | 0.841 | 0.900 | 0.904 |
| Route deviation | 0.677 | 0.634 | **0.694** | 0.664 |
| Position spoof | 0.872 | **0.985** | 0.979 | 0.976 |
| Teleport | 0.843 | **0.989** | 0.987 | 0.981 |
| AIS gap | 0.832 | 0.815 | **0.835** | 0.835 |
| False alarms on test normals at a 1% validation budget | 5.0% | 2.1% | 2.5% | 4.1% |

- **The JEPA is the best loitering detector**, on validation and test, with every seed. That is also the one place where predicting in latent space clearly beats predicting raw features.
- **It does not clear the pre-registered margin over Kalman on behavioral anomalies**: +0.070 AUROC against 0.10 (vessel-level bootstrap 95% interval 0.032 to 0.115).
- **Fusing it with Kalman does not pay**: +0.019 AUROC and −0.061 AUPRC against Kalman alone.
- **No detector held the 1% alert budget on new vessels.** Post hoc, most false alarms come from a handful of test vessels: fishing boats under way trip every detector, and the JEPA also over-alarms on anchored cargo ships.
- On small spoofs and teleports the JEPA is near chance, where a Kalman filter is above 0.94.

## Data

| Dataset | Role |
| --- | --- |
| [NOAA MarineCadastre AIS](https://marinecadastre.gov/ais) | Pretraining on normal traffic in Chesapeake Bay and Hampton Roads (three months to start) |
| [OMTAD](https://ro.ecu.edu.au/ecuworkspost2013/11764) | Benchmark evaluation, planned (Australian waters, CC BY-NC, not redistributed here) |
| [Equation-grounded anomaly benchmark](https://github.com/snudial/open-maritime-anomaly-detection) | Labeled test sets, planned (A1 spoofing-like, A2 route deviation, A3 close approach) |

Synthetic anomalies (position spoof, teleport, AIS gap, route deviation, loitering) are injected into held-out tracks with seeded, deterministic generators and a severity knob for each type. Rendezvous needs pairwise input and is a stretch goal.

## Evaluation

- **Baselines built:** physics residual, Kalman-filter innovation (observes position and reported velocity), and the same predictor on raw features (the key JEPA ablation). **Planned:** Isolation Forest, LSTM autoencoder, TrAISformer-style forecaster.
- **Metrics:** AUROC and AUPRC per anomaly type and severity level; false-alarm and detection rates at a 1% validation alert budget. **Planned:** severity curves as figures, false alarms per 1,000 vessel-hours, time to detect.
- **Ablations ([`ABLATION_RESULTS.md`](ABLATION_RESULTS.md), validation):** SIGReg weight (0, 0.02, 0.09, 0.3), action conditioning on/off, raw vs. latent target, anchored-window share, latent size, context length. SIGReg prevents collapse; action conditioning carries the prediction; latent prediction helps loitering and costs kinematic detection; a 64-dim latent matches the main model on behavioral kinds and beats it on kinematic ones. VICReg and EMA/stop-gradient deferred. Attention pooling, 4-step chunks, and location context were already compared on validation ([`reports/validation-v2.md`](reports/validation-v2.md)).
- **Rigor:** 3 seeds per configuration; test set frozen before the first model run and scored once; pre-registered criteria; vessel-level bootstrap intervals.

## Roadmap

| Phase | Weeks | Gate | Status |
| --- | --- | --- | --- |
| 1. Data pipeline and test sets | 1–3 | Test sets frozen before any model run | Done (`data_contract`, `pipeline_validated`) |
| 2. JEPA and quick baselines | 4–6 | JEPA trains without collapse across 3 seeds | Done (`training_stable`); test set scored, `model_eval` pending owner approval |
| 3. Full evaluation and ablations | 7–9 | Results tables frozen | Ablations done ([`ABLATION_RESULTS.md`](ABLATION_RESULTS.md)); `ablation_study` pending owner approval; remaining baselines next |
| 4. Darkwater demo panel and write-up | 10–12 | Repo, write-up, and demo shipped | Not started (`demo_shipped`) |

## Repository layout

```
latent-wake/
  configs/eval.yaml   # paths, models, and settings for the gate checks and benchmark
  latentwake/
    data/             # download, clean, segment, resample, windows, synthetic traffic
    inject/           # seeded anomaly injectors, write-once test sets
    models/           # encoder, predictor, SIGReg, baselines
    train.py score.py evaluate.py posthoc.py checks.py
  scripts/            # Meridian gate checks (validate-*.sh, run-benchmark.sh) and Meridian tooling
  tests/
  reports/            # validation reports, test-set manifests, eval-v2 results and post-hoc analysis
  docs/SCOPE.md       # original project scope
  DATA_CONTRACT.md  DECISIONS.md  EVAL_RESULTS.md  MODEL_CARD.md  CHANGELOG.md
```

## Stack

Python 3.11, PyTorch (CUDA), DuckDB, pandas and NumPy on Parquet, scikit-learn metrics, pytest; per-run `metrics.jsonl` for tracking; [Meridian](https://github.com/PCSchmidt/meridian) for gates.

## Getting started

```bash
git clone https://github.com/PCSchmidt/latent-wake.git
cd latent-wake
uv venv --python 3.11
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
uv pip install -e ".[dev]"
pytest -q
```

### Step 1: download and crop AIS data

```bash
python -m latentwake.data.download --region chesapeake --start 2025-04-01 --end 2025-06-30
```

This streams each NOAA national daily file (`ais-YYYY-MM-DD.csv.zst`), crops it to the Chesapeake Bay and Hampton Roads box with DuckDB, writes `data/interim/chesapeake/ais-YYYY-MM-DD.parquet`, and deletes the national file. Re-running skips finished days. `data/interim/chesapeake/manifest.jsonl` records rows, vessels, and any failures for each day.

Useful flags: `--workers 2` (days in parallel), `--keep-raw` (keep national files, which are large), `--memory-limit 4GB` (DuckDB memory per worker). Try a single day first (`--start 2025-04-01 --end 2025-04-01`) and check the manifest's `missing_optional` field to confirm the schema matched.

The box in `latentwake/data/regions.py` is a loose first pass. Plot the first day's points and tighten it if needed. Only 2025-and-later daily files are supported so far.

### Step 2: clean, resample, and window

```bash
python -m latentwake.data.preprocess --interim data/interim/chesapeake --out data/processed/chesapeake
```

Keeps Class A transceivers only (contract v2; `--transceivers all` for the Class B secondary analysis, written to another `--out`), drops bad identities, NOAA "not available" sentinels, duplicates, and single-report position glitches; splits each vessel into tracks at silences over 30 minutes (logged to `gaps.parquet`); resamples to a shared 2-minute grid, marking any step that would need more than 3 missing steps of interpolation as invalid; computes per-step relative-motion features and a 0.05° location grid cell (used only by the position-context option); and cuts 64-step windows (about 2 hours) with stride 16 over fully valid stretches only.

Splits are by time *and* vessel: training uses 70% of vessels before the cutoff (two-thirds through the data by default); validation and test use the other 30% after it. No vessel or time period appears on both sides. Feature statistics come from the training split only. `stats.json` records row counts at every stage.

### Step 3: build and freeze a test set

```bash
python -m latentwake.inject.build --processed data/processed/chesapeake --split test \
    --out data/testsets/chesapeake-test-v2
```

Injects seeded anomalies into copies of held-out windows, one cell per kind and severity level, alongside untouched normal windows. The output carries a SHA-256 checksum: loading verifies it, and saving refuses to overwrite, so the test set is fixed before any model sees it.

| Kind | What changes | Severity knob |
| --- | --- | --- |
| `position_spoof` | Positions shift; reported speed and course do not | Offset, 0.1 to 5 nmi |
| `teleport` | One report jumps, then returns | Distance, 0.1 to 5 nmi |
| `ais_gap` | Vessel goes dark, reports go stale, reappears displaced | Gap length × jump distance |
| `route_deviation` | Vessel turns off its route, reports stay consistent | Turn, 5° to 90° |
| `loitering` | Transit replaced by slow circling, reports stay consistent | Duration, 16 to 64 min |

The first three are kinematically *inconsistent* (positions contradict reported motion). The last two are *consistent* (only the behavior is unusual), which tests whether a model learned normal behavior rather than just physics.

**Evaluation rule (contract v2):** `route_deviation` and `loitering` are injected only into moving cargo, tanker, and passenger windows, and scored only against normal windows from that same population (moving, `source_mean_sog >= 3`, transit class). Loitering is ordinary work for a tug or fishing boat, and anchored ships are trivially "normal," so any other comparison rewards telling vessel types or motion apart, not finding anomalies. On synthetic data, a plain physics-consistency check scores about 0.73 AUROC on them unmatched and 0.48 matched. The kinematic kinds go into every Class A vessel.

### Step 4: train

```bash
python -m latentwake.train --processed data/processed/chesapeake --out runs/jepa-s0 --seed 0
```

Defaults follow LeWorldModel: SIGReg weight 0.09 with 17 knots and 1,024 projections, AdamW, gradient clip 1.0, no EMA or stop-gradient. Learning rate 3e-4 with warmup and cosine decay, batch 256, 30 epochs, bf16 on CUDA. Anchored and moored windows are kept at 25% (`--stationary-keep`) so they don't dominate training.

Each epoch logs training and validation prediction loss, SIGReg, and `val_erank`, the effective rank of validation latents. A healthy run stays well above 1. A slide toward 1 means collapse, and the log flags it. Ablations are flags: `--target raw` (no encoder, no SIGReg), `--no-action`, `--sigreg-weight 0`, `--embed-dim 64` (latent size), `--window-len 32` (context; each 64-step window is scored as two consecutive 32-step windows). Architecture options, chosen on validation data only: `--pooling attention`, `--chunk-len 4`, `--use-position` (adds a location-cell embedding per chunk). `--size small` is a 0.8M-parameter version for CPU debugging; the full model is 10.1M.

### Step 5: evaluate

```bash
python -m latentwake.evaluate --testset data/testsets/chesapeake-test-v2 \
    --processed data/processed/chesapeake --out reports/eval-v2 \
    --model jepa=runs/jepa-s0/best.pt --model raw=runs/raw-s0/best.pt
```

Always includes two non-learned baselines: a physics residual (observed motion versus reported speed and course) and a constant-velocity Kalman filter that observes position and reported velocity and scores each step by normalized innovation squared. Every detector, baselines included, is calibrated per stratum, vessel class × under way (mean reported speed ≥ 1 kn), as its validation tail probability (contract v2.1), so a fishing boat's jitter isn't scored like a tanker's, an anchored tanker isn't scored like one in the channel, and a 1% alert budget spreads across strata instead of piling onto the ones whose scores barely vary. `--calibration mad` gives the older median/MAD z-scores. Writes AUROC and AUPRC per anomaly cell to `results.csv` and `summary.md`.

Use `latentwake.evaluate` directly only on validation anomaly sets. The frozen test set is scored through `bash scripts/run-benchmark.sh`, which reads `configs/eval.yaml`, records its inputs, and refuses to score the test set a second time with different ones. `python -m latentwake.checks report` writes EVAL_RESULTS.md from what it recorded.

### Step 6: post-hoc analysis

```bash
python -m latentwake.posthoc
```

Exploratory, from the saved scores only: a cluster bootstrap over source vessels for each criterion difference, and test false alarms by stratum and by vessel. It never re-scores the test set and does not change the verdict.

### Working offline with synthetic traffic

```bash
python -m latentwake.data.synthetic --days 9 --vessels 50 --out data/interim/synthetic
python -m latentwake.data.preprocess --interim data/interim/synthetic --out data/processed/synthetic
```

`latentwake.data.synthetic` writes days in exactly the download step's format: simple ship kinematics (transits, tugs, ferries, fishing boats, anchored ships) with realistic reporting flaws. It has no coastline and is not a model of the real bay. It exists for tests and for building the model before real data arrives.

## Governance: Meridian gates

This project runs under [Meridian](https://github.com/PCSchmidt/meridian) (`ml-research` recipe), adapted to the 12-week plan. Each phase ends at a gate that a script, not an agent's say-so, decides:

| Gate | Passes when | Check |
|---|---|---|
| `data_contract` (owner approves) | DATA_CONTRACT.md has no open `[DECIDE]` items and complete thresholds | `validate-data-contract.sh` |
| `pipeline_validated` | Real data cropped with no failed days, splits leak-free, test set frozen | `validate-schema/preprocessing/splits/testset.sh`, unit tests |
| `training_stable` | Three or more seeds per latent model, none collapsed | `validate-training.sh` |
| `model_eval` (owner approves) | Every model trained after the test set froze; the test set scored exactly once; the verdict on every contract criterion recorded in EVAL_RESULTS.md, pass or fail | `run-benchmark.sh`, `validate-metrics.sh` |
| `ablation_study` (owner approves) | ABLATION_RESULTS.md written | — |
| `demo_shipped` (owner approves) | Write-up, model card, changelog; full test suite green | `run-all-tests.sh` |

```bash
bash scripts/gate-engine.sh current                 # which gate is open
bash scripts/gate-engine.sh verify data_contract    # run its checks
bash scripts/gate-engine.sh mark-passed data_contract --approve "DATA CONTRACT APPROVED"   # owner only
```

Paths for every check live in `configs/eval.yaml`. The checks themselves are in `latentwake/checks.py`; each exits 2 to block. The success criteria are in [`DATA_CONTRACT.md`](DATA_CONTRACT.md), and the decision log is in [`DECISIONS.md`](DECISIONS.md). Meridian needs `jq` and [mikefarah's `yq`](https://github.com/mikefarah/yq).

## Related projects

- [Darkwater](https://github.com/PCSchmidt/darkwater): maritime shadow-fleet demo. Latent Wake scores will feed a ranked-vessel panel there.
- [chokepoint_app](https://github.com/PCSchmidt/chokepoint_app): maritime chokepoint intelligence.

## Acknowledgments

The training recipe builds on [LeWorldModel](https://github.com/lucas-maes/le-wm) by Maes, Le Lidec, Scieur, LeCun, and Balestriero. SIGReg and the AdaLN-zero transformer blocks in `latentwake/models/blocks.py` are adapted from that repository (MIT License, copyright 2026 Lucas Maes).

## License

MIT. Third-party datasets keep their own licenses and are not redistributed.
