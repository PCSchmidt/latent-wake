# DECISIONS.md

Decisions made so far, why, and what else was considered. Newest first.
"Owner" marks decisions Chris made; the rest are implementation choices open
to review at the `data_contract` gate.

| Date | Decision | Why | Alternatives considered | By |
|------|----------|-----|-------------------------|----|
| 2026-11-09 | Before running seeds 1 and 2, compare jepa-s0 with raw-s0 on a validation anomaly set (val split, seed 1) to decide whether chunk pooling needs changing | The synthetic run had the raw target beating the JEPA on spoofs; settling it on validation data first avoids spending three seeds on an architecture that may change, and keeps the test set untouched | Run three seeds now; check on the test set (not allowed) | Agent |
| 2026-11-09 | Report the false-alarm rate on moving normal vessels next to the gated overall rate | 74% of real windows are anchored or moored and rarely alert; on synthetic data the moving-only rate was about double the overall rate | Gate on moving-only (would amend the approved contract) | Agent |
| 2026-11-07 | Gate on AUROC and AUPRC (margins: behavioral +0.10 / +0.05; fused over Kalman +0.03 / 0.0; fused over JEPA +0.03 / +0.03) and on the operating point at a 1% validation alert budget (fused test false alarms at most 2%; fused detection at least Kalman's) | AUPRC exposes max-fusion's precision cost that AUROC hides; an alerting system must hold its alarm budget. Margins demand a lead where synthetic data showed room, and non-inferiority where fusion is weakest | AUROC only; AUPRC only; operating point reported, not gated | Owner (on agent recommendation) |
| 2026-11-07 | Constraints confirmed, plus: architecture and model choices use validation data only (val loss plus a separate validation anomaly set); test set scored once per final configuration; fusion rule and thresholds fixed at approval | The smoke run suggests pooling changes worth trying; this allows them without touching the test set | Freeze the architecture now | Owner (on agent recommendation) |
| 2026-11-07 | Headline claim: JEPA beats Kalman on behavioral anomalies, and a fused JEPA+Kalman detector beats either alone. Kinematic parity and latent-vs-raw are reported, not gated | Synthetic smoke run suggests parity with Kalman on kinematic anomalies is unlikely; fusion lets the system cover them while the JEPA contributes behavioral detection | (a) alone with parity gated; (b) alone; (c) no win required | Owner |
| 2026-11-07 | Fusion rule: max of window z-scores calibrated per vessel class on validation; kinds weighted equally in contract metrics | Nothing fit to the test set; window-level calibration puts both detectors on one scale; equal kind weights stop gaps (9 levels) outweighing loitering (3) | Learned fusion weights; rank averaging; cell-weighted means | Agent |
| 2026-11-07 | Adopt Meridian (ml-research recipe), gates adapted to the 12-week plan | Lock metrics before real data; independent evaluation of result claims; memory across sessions | Continue without a harness | Owner |
| 2026-11-07 | Loitering injector ramps into and out of the circle over 4 steps | An instant switch from transit speed to circling let a constant-velocity Kalman filter score 0.95 AUROC on an artifact; with the ramp, 0.64 | Instant switch | Agent |
| 2026-11-07 | Score behavioral anomalies only against moving normal vessels | They are injected only into moving ships; against all normals, a physics check scored 0.73 by telling moving from anchored, 0.48 when matched | Score against all normals | Agent |
| 2026-11-07 | Kalman baseline observes reported velocity as well as position | The strongest classical detector of position-versus-report disagreement; the bar the JEPA must clear | Position-only Kalman (weaker, easier to beat) | Agent |
| 2026-11-07 | Keep 25% of anchored and moored windows in training | Anchored windows are a large share of real traffic and carry little motion to learn | Keep all; drop all | Agent |
| 2026-11-07 | Positions stored as float64 for injection | Float32 latitude is good only to about half a meter, visible in recomputed displacements | Float32 throughout | Agent |
| 2026-11-07 | Outlier filter drops a report only if it is fast in *and* fast out | The earlier rule also dropped the good report after a glitch; a lasting jump is kept as possibly real spoofing | Drop every fast-in report | Agent |
| 2026-11-07 | Split by time *and* vessel (70/15/15 by MMSI hash; cutoff two-thirds through) | Test vessels and test period never seen in training | Time-only split; random windows | Agent |
| 2026-11-07 | Test sets are write-once with a SHA-256 checksum and a frozen_at time; models must start training after it | Enforces "test sets frozen before any model run" in code | Convention only | Agent |
| 2026-11-07 | Action = next chunk's reported speed, course, heading change; never displacement | The model must infer where the ship goes from what it reports; spoofing is disagreement between the two | Include displacement; no action | Agent |
| 2026-11-07 | Relative-motion features only, 2-minute grid, 64-step windows in 8 chunks | Learn motion, not the map; 16-minute chunks; 2-hour context | Absolute positions; 1-minute grid | Agent |
| 2026-11-07 | SIGReg and AdaLN-zero blocks adapted from LeWorldModel (MIT) with its defaults (weight 0.09, 17 knots, 1,024 projections) | Reuse the reference implementation rather than reinvent it | Own implementation; VICReg | Agent |
| 2026-11-06 | Training region: Chesapeake Bay and Hampton Roads | Mixed deep-draft, tug, ferry, and Navy traffic; harder and more defense-relevant than a container port | LA / Long Beach, Gulf of Mexico, Puget Sound, Hawaii | Owner |
| 2026-11-06 | 12-week timeline, four 3-week phases | Fits a part-time pace alongside JHU coursework | 8 weeks | Owner |
| 2026-11-05 | Project: JEPA surprise detection on AIS tracks (Latent Wake) | Original, defense-relevant, laptop-sized, reuses Darkwater and chokepoint_app | LeWM reproduction; frozen V-JEPA 2.1 features on overhead video | Owner |

## Open questions for the owner

See every `[DECIDE ...]` marker in DATA_CONTRACT.md. The main one is the
headline claim, which sets the success thresholds.
