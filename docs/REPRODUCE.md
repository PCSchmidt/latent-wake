# Reproducing Latent Wake

Every step from raw NOAA files to the published panel, in order. Each step is
one command; outputs land under `data/`, `runs/`, and `reports/`. The
[README](../README.md) explains what each stage is for; the decision log is
[`DECISIONS.md`](../DECISIONS.md).

Hardware used: one laptop (RTX A4500, 16 GB; 64 GB RAM). About 40 minutes per
JEPA seed; the whole pipeline, three seeds of each learned model, ablations,
and baselines took roughly a day of GPU time.

## Setup

```bash
git clone https://github.com/PCSchmidt/latent-wake.git
cd latent-wake
uv venv --python 3.11
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
uv pip install -e ".[dev]"
pytest -q
```

## Step 1: download and crop AIS data

```bash
python -m latentwake.data.download --region chesapeake --start 2025-04-01 --end 2025-06-30
```

This streams each NOAA national daily file (`ais-YYYY-MM-DD.csv.zst`), crops it to the Chesapeake Bay and Hampton Roads box with DuckDB, writes `data/interim/chesapeake/ais-YYYY-MM-DD.parquet`, and deletes the national file. Re-running skips finished days. `data/interim/chesapeake/manifest.jsonl` records rows, vessels, and any failures for each day.

Useful flags: `--workers 2` (days in parallel), `--keep-raw` (keep national files, which are large), `--memory-limit 4GB` (DuckDB memory per worker). Try a single day first (`--start 2025-04-01 --end 2025-04-01`) and check the manifest's `missing_optional` field to confirm the schema matched.

The box in `latentwake/data/regions.py` is a loose first pass. Plot the first day's points and tighten it if needed. Only 2025-and-later daily files are supported so far.

## Step 2: clean, resample, and window

```bash
python -m latentwake.data.preprocess --interim data/interim/chesapeake --out data/processed/chesapeake
```

Keeps Class A transceivers only (contract v2; `--transceivers all` for the Class B secondary analysis, written to another `--out`), drops bad identities, NOAA "not available" sentinels, duplicates, and single-report position glitches; splits each vessel into tracks at silences over 30 minutes (logged to `gaps.parquet`); resamples to a shared 2-minute grid, marking any step that would need more than 3 missing steps of interpolation as invalid; computes per-step relative-motion features and a 0.05° location grid cell (used only by the position-context option); and cuts 64-step windows (about 2 hours) with stride 16 over fully valid stretches only.

Splits are by time *and* vessel: training uses 70% of vessels before the cutoff (two-thirds through the data by default); validation and test use the other 30% after it. No vessel or time period appears on both sides. Feature statistics come from the training split only. `stats.json` records row counts at every stage.

## Step 3: build and freeze a test set

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

## Step 4: train

```bash
python -m latentwake.train --processed data/processed/chesapeake --out runs/jepa-s0 --seed 0
```

Defaults follow LeWorldModel: SIGReg weight 0.09 with 17 knots and 1,024 projections, AdamW, gradient clip 1.0, no EMA or stop-gradient. Learning rate 3e-4 with warmup and cosine decay, batch 256, 30 epochs, bf16 on CUDA. Anchored and moored windows are kept at 25% (`--stationary-keep`) so they don't dominate training.

Each epoch logs training and validation prediction loss, SIGReg, and `val_erank`, the effective rank of validation latents. A healthy run stays well above 1. A slide toward 1 means collapse, and the log flags it. Ablations are flags: `--target raw` (no encoder, no SIGReg), `--no-action`, `--sigreg-weight 0`, `--embed-dim 64` (latent size), `--window-len 32` (context; each 64-step window is scored as two consecutive 32-step windows). Architecture options, chosen on validation data only: `--pooling attention`, `--chunk-len 4`, `--use-position` (adds a location-cell embedding per chunk). `--size small` is a 0.8M-parameter version for CPU debugging; the full model is 10.1M.

## Step 5: evaluate

```bash
python -m latentwake.evaluate --testset data/testsets/chesapeake-test-v2 \
    --processed data/processed/chesapeake --out reports/eval-v2 \
    --model jepa=runs/jepa-s0/best.pt --model raw=runs/raw-s0/best.pt
```

Always includes two non-learned baselines: a physics residual (observed motion versus reported speed and course) and a constant-velocity Kalman filter that observes position and reported velocity and scores each step by normalized innovation squared. Every detector, baselines included, is calibrated per stratum, vessel class × under way (mean reported speed ≥ 1 kn), as its validation tail probability (contract v2.1), so a fishing boat's jitter isn't scored like a tanker's, an anchored tanker isn't scored like one in the channel, and a 1% alert budget spreads across strata instead of piling onto the ones whose scores barely vary. `--calibration mad` gives the older median/MAD z-scores. Writes AUROC and AUPRC per anomaly cell to `results.csv` and `summary.md`.

Use `latentwake.evaluate` directly only on validation anomaly sets. The frozen test set is scored through `bash scripts/run-benchmark.sh`, which reads `configs/eval.yaml`, records its inputs, and refuses to score the test set a second time with different ones. `python -m latentwake.checks report` writes EVAL_RESULTS.md from what it recorded.

## Learned baselines

```bash
python -m latentwake.select_baselines grid                  # Isolation Forest, LSTM-AE, TrAISformer-style; seed 0
python -m latentwake.select_baselines evaluate              # validation anomaly set only
python -m latentwake.select_baselines select --train-seeds  # winner per kind, then seeds 1 and 2
python -m latentwake.checks benchmark configs/eval-baselines.yaml   # one recorded test scoring
```

Settings are picked on validation by a rule fixed in advance (DECISIONS.md); the test scoring is recorded and refuses a second look like the main benchmark. Each baseline scores a window with one number (Isolation Forest on window statistics; LSTM-autoencoder and TrAISformer-style per-step error or negative log-likelihood, maximum over the window) and is calibrated like every other detector.

## Step 6: post-hoc analysis

```bash
python -m latentwake.posthoc
```

Exploratory, from the saved scores only: a cluster bootstrap over source vessels for each criterion difference; test false alarms by stratum, by vessel, and by each vessel's AIS ship-type code (pilot boats and dredges sit in the "other" class); and the most-alarming vessels with their typical position. It never re-scores the test set and does not change the verdict.

## Step 7: export the Darkwater panel

```bash
python -m latentwake.export_panel --out ../darkwater/sql/latentwake/data.sql
cd ../darkwater && python3 build.py
```

Writes an anonymized sample of the scored test set (tracks, recorded scores and thresholds, per-step surprise for display, a traffic-density grid, and the recorded scoreboard) as SQL for Darkwater's [Latent Wake page](https://pcschmidt.github.io/darkwater/latent-wake.html). No MMSIs, names, or timestamps are exported.

## Working offline with synthetic traffic

```bash
python -m latentwake.data.synthetic --days 9 --vessels 50 --out data/interim/synthetic
python -m latentwake.data.preprocess --interim data/interim/synthetic --out data/processed/synthetic
```

`latentwake.data.synthetic` writes days in exactly the download step's format: simple ship kinematics (transits, tugs, ferries, fishing boats, anchored ships) with realistic reporting flaws. It has no coastline and is not a model of the real bay. It exists for tests and for building the model before real data arrives.


## Meridian gates

The project is governed by [Meridian](https://github.com/PCSchmidt/meridian); see the README for what each gate checks.

```bash
bash scripts/gate-engine.sh current                 # which gate is open
bash scripts/gate-engine.sh verify data_contract    # run its checks
bash scripts/gate-engine.sh mark-passed data_contract --approve "DATA CONTRACT APPROVED"   # owner only
```

Paths for every check live in `configs/eval.yaml`. The checks themselves are in `latentwake/checks.py`; each exits 2 to block. The success criteria are in [`DATA_CONTRACT.md`](DATA_CONTRACT.md), and the decision log is in [`DECISIONS.md`](DECISIONS.md). Meridian needs `jq` and [mikefarah's `yq`](https://github.com/mikefarah/yq).

