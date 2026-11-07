# Latent Wake

**JEPA surprise detection for maritime vessel tracks.**

Latent Wake trains a small Joint-Embedding Predictive Architecture (JEPA) world model on normal vessel motion from public AIS data. It then flags tracks where the model is *surprised*: the vessel ends up somewhere its own reported speed and course say it shouldn't be. That signature covers spoofed positions, teleports, AIS gaps, loitering, and ship-to-ship rendezvous.

The model follows the [LeWorldModel](https://arxiv.org/abs/2603.19312) recipe (a next-latent prediction loss plus the SIGReg Gaussian regularizer, with no EMA, stop-gradient, or pretrained encoder), ported from pixels to trajectories. It is sized to train on a single laptop GPU (RTX A4500, 16 GB).

> **Status:** Week 1 of a 12-week build. The download, preprocessing, and anomaly-injection stages are written and tested on synthetic traffic; the first run on real NOAA data is next. The full scope is in [`docs/SCOPE.md`](docs/SCOPE.md).

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
- **Surprise score:** the same prediction error at inference, robust-z-scored per vessel type.

## Data

| Dataset | Role |
| --- | --- |
| [NOAA MarineCadastre AIS](https://marinecadastre.gov/ais) | Pretraining on normal traffic in Chesapeake Bay and Hampton Roads (three months to start) |
| [OMTAD](https://ro.ecu.edu.au/ecuworkspost2013/11764) | Benchmark evaluation (Australian waters, CC BY-NC, not redistributed here) |
| [Equation-grounded anomaly benchmark](https://github.com/snudial/open-maritime-anomaly-detection) | Labeled test sets (A1 spoofing-like, A2 route deviation, A3 close approach) |

Synthetic anomalies (position spoof, teleport, route deviation, loitering, rendezvous, AIS gap) are injected into held-out tracks with seeded, deterministic generators and a severity knob for each type.

## Evaluation plan

- **Baselines:** Kalman-filter innovation residual, Isolation Forest, LSTM autoencoder, the same predictor on raw features (the key JEPA ablation), and a TrAISformer-style forecaster.
- **Metrics:** AUROC, AUPRC, and best F1 per anomaly type; detection rate versus severity; false alarms per 1,000 vessel-hours; time to detect.
- **Ablations:** SIGReg weight, SIGReg vs. VICReg vs. EMA/stop-gradient, action conditioning on/off, context length, latent size.
- **Rigor:** 3 seeds per configuration; test sets frozen before the first model run.

## Roadmap

| Phase | Weeks | Gate |
| --- | --- | --- |
| 1. Data pipeline and test sets | 1–3 | Test sets frozen before any model run |
| 2. JEPA and quick baselines | 4–6 | JEPA trains without collapse across 3 seeds |
| 3. Full evaluation and ablations | 7–9 | Results tables frozen |
| 4. Darkwater demo panel and write-up | 10–12 | Repo, write-up, and demo shipped |

## Repository layout

```
latent-wake/
  configs/        # Hydra configs: data, model, train, eval, ablations
  latentwake/
    data/         # download, clean, segment, resample, windows
    inject/       # seeded synthetic anomaly generators
    models/       # encoder, predictor, SIGReg, baselines
  notebooks/      # latent probes, failure analysis, figures
  tests/
  reports/        # results tables and write-up figures
  docs/SCOPE.md   # full project scope
```

## Stack

Python 3.11, PyTorch (CUDA), uv, Hydra, Polars + DuckDB, Weights & Biases or MLflow, pytest.

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

Drops bad identities, NOAA "not available" sentinels, duplicates, and single-report position glitches; splits each vessel into tracks at silences over 30 minutes (logged to `gaps.parquet`); resamples to a shared 2-minute grid, marking any step that would need more than 3 missing steps of interpolation as invalid; computes per-step relative-motion features; and cuts 64-step windows (about 2 hours) with stride 16 over fully valid stretches only.

Splits are by time *and* vessel: training uses 70% of vessels before the cutoff (two-thirds through the data by default); validation and test use the other 30% after it. No vessel or time period appears on both sides. Feature statistics come from the training split only. `stats.json` records row counts at every stage.

### Step 3: build and freeze a test set

```bash
python -m latentwake.inject.build --processed data/processed/chesapeake --split test \
    --out data/testsets/chesapeake-test-v1
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

**Evaluation rule:** score `route_deviation` and `loitering` only against normal windows from moving vessels (`source_mean_sog >= 3`). Those anomalies are injected only into moving ships, and anchored ships are trivially "normal," so comparing against all normals rewards detecting motion, not anomalies. On synthetic data, a plain physics-consistency check scores about 0.73 AUROC on them unmatched and 0.48 matched.

### Working offline with synthetic traffic

```bash
python -m latentwake.data.synthetic --days 9 --vessels 50 --out data/interim/synthetic
python -m latentwake.data.preprocess --interim data/interim/synthetic --out data/processed/synthetic
```

`latentwake.data.synthetic` writes days in exactly the download step's format: simple ship kinematics (transits, tugs, ferries, fishing boats, anchored ships) with realistic reporting flaws. It has no coastline and is not a model of the real bay. It exists for tests and for building the model before real data arrives.

## Related projects

- [Darkwater](https://github.com/PCSchmidt/darkwater): maritime shadow-fleet demo. Latent Wake scores will feed a ranked-vessel panel there.
- [chokepoint_app](https://github.com/PCSchmidt/chokepoint_app): maritime chokepoint intelligence.

## Acknowledgments

The training recipe builds on [LeWorldModel](https://github.com/lucas-maes/le-wm) by Maes, Le Lidec, Scieur, LeCun, and Balestriero. SIGReg code will be adapted from that repository with attribution.

## License

MIT. Third-party datasets keep their own licenses and are not redistributed.
