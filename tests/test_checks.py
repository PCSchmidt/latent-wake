"""Tests for the gate checks behind Meridian's pre-hooks (latentwake/checks.py)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest

from latentwake import checks
from latentwake.data import preprocess as pp
from latentwake.data.synthetic import simulate_days, write_interim
from latentwake.inject.build import build_from_processed, build_test_set, save_test_set

FILLED = """# DATA_CONTRACT.md

```yaml contract-thresholds
criteria:
  - id: behavioral
    metric: auroc
    method: jepa
    kinds: [loitering, route_deviation]
    vs_method: kalman
    margin: 0.10
  - id: floor
    metric: auroc
    method: jepa
    kinds: [position_spoof]
    value: 0.80
```
"""


def _write(tmp_path, text, name="DATA_CONTRACT.md"):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_contract_blocks_open_decisions_and_empty_thresholds(tmp_path):
    with pytest.raises(checks.Blocked, match="open decision"):
        checks.check_contract(_write(tmp_path, FILLED + "\n[DECIDE: pick one]\n"))
    with pytest.raises(checks.Blocked, match="set value, or vs_method and margin"):
        checks.check_contract(_write(tmp_path, FILLED.replace("margin: 0.10", "margin: null")))
    with pytest.raises(checks.Blocked, match="no ```yaml contract-thresholds"):
        checks.check_contract(_write(tmp_path, "# empty\n"))
    checks.check_contract(_write(tmp_path, FILLED))  # passes


def test_the_repo_contract_is_blocked_until_the_owner_decides():
    contract = Path(__file__).resolve().parents[1] / "DATA_CONTRACT.md"
    if not contract.exists():
        pytest.skip("no DATA_CONTRACT.md in this checkout")
    text = contract.read_text()
    if "[DECIDE" not in text:
        pytest.skip("contract already decided")
    with pytest.raises(checks.Blocked):
        checks.check_contract(contract)


def _results(rows):
    return pd.DataFrame(rows, columns=["method", "kind", "level", "auroc", "auprc"])


def test_metric_criteria_average_seeds_and_compare_methods():
    res = _results(
        [
            ("jepa-s0", "loitering", 0, 0.90, 0.9), ("jepa-s1", "loitering", 0, 0.80, 0.8),
            ("jepa-s0", "route_deviation", 0, 0.70, 0.7), ("jepa-s1", "route_deviation", 0, 0.60, 0.6),
            ("kalman", "loitering", 0, 0.60, 0.6), ("kalman", "route_deviation", 0, 0.55, 0.5),
            ("jepa-s0", "position_spoof", 0, 0.85, 0.8), ("jepa-s1", "position_spoof", 0, 0.75, 0.7),
        ]
    )
    crit = checks.THRESHOLD_BLOCK.search(FILLED).group(1)
    import yaml

    out = {r["id"]: r for r in checks.evaluate_criteria(res, yaml.safe_load(crit)["criteria"])}
    # jepa mean 0.75 vs kalman 0.575: lead 0.175 >= 0.10
    assert out["behavioral"]["passed"]
    # jepa spoof mean 0.80 >= 0.80
    assert out["floor"]["passed"]
    res.loc[res.method == "kalman", "auroc"] = 0.70
    assert not checks.evaluate_criteria(res, yaml.safe_load(crit)["criteria"])[0]["passed"]


@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    root = tmp_path_factory.mktemp("checks")
    write_interim(simulate_days(dt.date(2025, 4, 1), n_days=6, n_vessels=30, seed=4), root / "interim")
    pp.run(root / "interim", root / "processed")
    return root


def test_splits_pass_and_catch_leaks(processed):
    p = processed / "processed"
    checks.check_splits(p)
    w = pd.read_parquet(p / "windows.parquet")
    leaked = w.copy()
    victim = leaked[leaked.split == "test"].mmsi.iat[0]
    leaked.loc[leaked.index[leaked.split == "train"][0], "mmsi"] = victim
    bad = processed / "leaky"
    bad.mkdir(exist_ok=True)
    leaked.to_parquet(bad / "windows.parquet")
    (bad / "stats.json").write_text((p / "stats.json").read_text())
    with pytest.raises(checks.Blocked, match="both training and evaluation"):
        checks.check_splits(bad)


def test_preprocessing_check(processed):
    with pytest.raises(checks.Blocked, match="training windows"):
        checks.check_preprocessing(processed / "processed", min_train_windows=10**9)
    checks.check_preprocessing(processed / "processed", min_train_windows=10)


def test_testset_check_requires_test_split_and_freeze_time(processed):
    p = processed / "processed"
    save_test_set(build_from_processed(p, "test", seed=0, per_cell=3), processed / "ts")
    checks.check_testset(processed / "ts", p)
    save_test_set(build_from_processed(p, "val", seed=0, per_cell=3), processed / "ts-val")
    with pytest.raises(checks.Blocked, match="expected only 'test'"):
        checks.check_testset(processed / "ts-val", p)
    # A test set built the v1 way (no location cells) no longer passes.
    X, meta, raw = pp.load_split(p, "test", normalized=False, raw=True)
    save_test_set(build_test_set(X, raw, meta, seed=0, per_cell=3), processed / "ts-v1")
    with pytest.raises(checks.Blocked, match="location cells"):
        checks.check_testset(processed / "ts-v1", p)


def test_preprocessing_check_requires_class_a(processed, tmp_path):
    import shutil

    p = tmp_path / "copy"
    shutil.copytree(processed / "processed", p)
    stats = json.loads((p / "stats.json").read_text())
    stats["config"]["transceivers"] = None
    (p / "stats.json").write_text(json.dumps(stats))
    with pytest.raises(checks.Blocked, match="Class A"):
        checks.check_preprocessing(p, min_train_windows=10)


def _fake_run(root: Path, name: str, started_at: str, erank: float, target="latent", sigreg=0.09) -> Path:
    run = root / "runs" / name
    run.mkdir(parents=True, exist_ok=True)
    cfg = {"model": {"target": target, "sigreg_weight": sigreg, "embed_dim": 64}, "started_at": started_at}
    (run / "config.json").write_text(json.dumps(cfg))
    (run / "metrics.jsonl").write_text(json.dumps({"epoch": 1, "val_pred": 0.01, "val_erank": erank}) + "\n")
    (run / "best.pt").write_text("")
    return run / "best.pt"


def test_training_and_freeze_order(tmp_path):
    ts = tmp_path / "ts"
    ts.mkdir()
    (ts / "manifest.json").write_text(json.dumps({"frozen_at": "2026-11-07T12:00:00+00:00"}))
    after = "2026-11-07T13:00:00+00:00"
    models = {f"jepa-s{i}": str(_fake_run(tmp_path, f"jepa-s{i}", after, 20.0)) for i in range(3)}
    models["nosig-s0"] = str(_fake_run(tmp_path, "nosig-s0", after, 1.0, sigreg=0.0))  # ablation: skipped
    cfg = {"testset": str(ts), "processed": "x", "out": "x", "models": models}
    cfg_path = tmp_path / "eval.yaml"
    import yaml

    cfg_path.write_text(yaml.safe_dump(cfg))
    checks.check_training(cfg_path)
    checks.check_freeze_order(cfg)

    two = dict(cfg, models={k: v for k, v in models.items() if k != "jepa-s2"})
    cfg_path.write_text(yaml.safe_dump(two))
    with pytest.raises(checks.Blocked, match="need 3"):
        checks.check_training(cfg_path)

    early = dict(cfg, models={"jepa-s0": str(_fake_run(tmp_path, "early", "2026-11-07T11:00:00+00:00", 20.0))})
    with pytest.raises(checks.Blocked, match="before the test set was frozen"):
        checks.check_freeze_order(early)

    collapsed = dict(cfg, models={f"c-s{i}": str(_fake_run(tmp_path, f"c-s{i}", after, 10.0)) for i in range(3)})
    cfg_path.write_text(yaml.safe_dump(collapsed))
    with pytest.raises(checks.Blocked, match="collapse"):
        checks.check_training(cfg_path)


def test_cli_exit_codes(tmp_path):
    assert checks.main(["contract", str(_write(tmp_path, FILLED))]) == 0
    assert checks.main(["contract", str(tmp_path / "missing.md")]) == checks.BLOCK
    assert checks.main(["schema", str(tmp_path)]) == checks.BLOCK


def test_collapse_signal_on_the_smoke_run_shapes():
    from latentwake.models.jepa import collapse_signal

    healthy = [13.2, 13.3, 13.9, 15.0, 15.9, 18.0, 20.2, 22.6, 24.0, 24.5, 24.6]
    falling = [18.3, 14.7, 13.1, 12.1, 11.4, 10.9, 10.4, 10.1]  # no SIGReg
    assert collapse_signal(healthy, 64) is None
    assert "fell" in collapse_signal(falling, 64) or "below" in collapse_signal(falling, 64)
    assert "below" in collapse_signal([30.0, 12.0], 64)


def test_contract_intro_text_is_not_an_open_decision(tmp_path):
    text = "Every DECIDE marker (square brackets, starting with DECIDE) is an owner decision.\n" + FILLED
    checks.check_contract(_write(tmp_path, text))


def test_operating_point_criteria():
    import yaml

    crit = yaml.safe_load("""
criteria:
  - {id: fpr, metric: fpr_at_budget, method: fused, kinds: [normal], op: "<=", value: 0.02}
  - {id: det, metric: detect_at_budget, method: fused, kinds: [loitering], vs_method: kalman, margin: 0.0}
""")["criteria"]
    res = pd.DataFrame([
        {"method": "fused-s0", "kind": "normal", "level": -1, "fpr_at_budget": 0.015},
        {"method": "fused-s1", "kind": "normal", "level": -1, "fpr_at_budget": 0.019},
        {"method": "fused-s0", "kind": "loitering", "level": 0, "detect_at_budget": 0.5},
        {"method": "fused-s1", "kind": "loitering", "level": 0, "detect_at_budget": 0.4},
        {"method": "kalman", "kind": "loitering", "level": 0, "detect_at_budget": 0.44},
    ])
    out = {r["id"]: r["passed"] for r in checks.evaluate_criteria(res, crit)}
    assert out == {"fpr": True, "det": True}  # fpr 0.017 <= 0.02; detection 0.45 >= 0.44
    res.loc[1, "fpr_at_budget"] = 0.05
    assert not checks.evaluate_criteria(res, crit)[0]["passed"]


def test_contract_rejects_bad_metric_and_op(tmp_path):
    bad_metric = FILLED.replace("metric: auroc", "metric: accuracy", 1)
    with pytest.raises(checks.Blocked, match="metric must be one of"):
        checks.check_contract(_write(tmp_path, bad_metric))
    bad_op = FILLED.replace("    vs_method: kalman\n    margin: 0.10", "    vs_method: kalman\n    margin: 0.10\n    op: \"<=\"")
    with pytest.raises(checks.Blocked, match="op <= needs an absolute value"):
        checks.check_contract(_write(tmp_path, bad_op))


def test_benchmark_scores_once_and_records_a_miss(processed, tmp_path, monkeypatch):
    import yaml

    import latentwake.evaluate as ev

    p = processed / "processed"
    ts = tmp_path / "ts"
    save_test_set(build_from_processed(p, "test", seed=0, per_cell=3), ts)
    later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1)).isoformat(timespec="seconds")
    models = {"jepa-s0": str(_fake_run(tmp_path, "jepa-s0", later, 20.0))}
    out = tmp_path / "eval"
    cfg_path = tmp_path / "eval.yaml"
    cfg = {"testset": str(ts), "processed": str(p), "out": str(out), "models": models,
           "fuse_with_kalman": "jepa", "alert_fpr": 0.01, "calibration": "tail"}
    cfg_path.write_text(yaml.safe_dump(cfg))

    calls = []

    def fake_run(testset, processed_dir, models_, out_dir, *args):
        calls.append(args)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        rows = [{"method": m, "kind": k, "level": 0, "auroc": a}
                for m, a in (("jepa-s0", 0.70), ("kalman", 0.65)) for k in ("loitering", "route_deviation")]
        rows += [{"method": "jepa-s0", "kind": "position_spoof", "level": 0, "auroc": 0.9}]
        pd.DataFrame(rows).to_csv(Path(out_dir) / "results.csv", index=False)
        (Path(out_dir) / "summary.md").write_text("## AUROC by kind\n\n(table)\n")

    monkeypatch.setattr(ev, "run", fake_run)
    checks.run_benchmark(cfg_path)
    checks.run_benchmark(cfg_path)            # identical inputs: no second scoring
    assert len(calls) == 1
    cfg_path.write_text(yaml.safe_dump(dict(cfg, alert_fpr=0.02)))
    with pytest.raises(checks.Blocked, match="second look"):
        checks.run_benchmark(cfg_path)
    assert len(calls) == 1
    cfg_path.write_text(yaml.safe_dump(cfg))

    contract = _write(tmp_path, FILLED)      # behavioral margin 0.10: 0.70 vs 0.65 misses
    with pytest.raises(checks.Blocked, match="not met"):
        checks.check_metrics(out / "results.csv", contract)
    checks.check_metrics(out / "results.csv", contract, record=True)
    verdict = json.loads((out / "criteria.json").read_text())
    assert verdict["failed"] == ["behavioral"] and not verdict["all_passed"]

    dest = tmp_path / "EVAL_RESULTS.md"
    checks.write_eval_results(cfg_path, dest)
    text = dest.read_text()
    assert "1 of 2 criteria met; not met: behavioral" in text and "### AUROC by kind" in text
    with pytest.raises(checks.Blocked, match="--force"):
        checks.write_eval_results(cfg_path, dest)


def test_posthoc_reproduces_recorded_rates_and_bootstraps(processed, tmp_path):
    import numpy as np
    import yaml

    from latentwake import posthoc
    from latentwake.evaluate import cell_metrics

    p = processed / "processed"
    ts_dir = tmp_path / "ts"
    ts = build_from_processed(p, "test", seed=0, per_cell=3)
    save_test_set(ts, ts_dir)
    rng = np.random.default_rng(0)
    anom = (ts.cells.kind != "normal").to_numpy()
    scores = {m: rng.normal(size=len(ts.cells)) + shift * anom
              for m, shift in (("kalman", 0.5), ("jepa-s0", 1.0), ("jepa-s1", 1.0), ("fused-s0", 1.2))}
    thr = {m: 1.5 for m in scores}
    out = tmp_path / "eval"
    out.mkdir()
    res = cell_metrics(ts.cells, scores, thr)
    res.to_csv(out / "results.csv", index=False)
    np.savez_compressed(out / "scores.npz", **scores)
    contract = _write(tmp_path, FILLED)
    cfg = tmp_path / "eval.yaml"
    cfg.write_text(yaml.safe_dump({"testset": str(ts_dir), "processed": str(p), "out": str(out),
                                   "models": {}, "contract": str(contract), "interim": str(processed / "interim")}))
    dest = posthoc.run(cfg, n_boot=20)
    by_type = pd.read_csv(dest / "false_alarms_by_ais_type.csv")
    for m in scores:  # shares of each method's false alarms sum to one
        assert by_type[m].sum() == pytest.approx(1.0) or by_type[m].sum() == 0
    top = pd.read_csv(dest / "top_alarming_vessels.csv")
    assert {"mmsi", "ais_type", "lat", "lon"} <= set(top.columns)
    assert top.lat.between(36.6, 39.7).all()

    normal = (ts.cells.kind == "normal").to_numpy()
    rec = json.loads((dest / "thresholds.json").read_text())
    recorded = res[res.kind == "normal"].set_index("method").fpr_at_budget
    for m, t in rec.items():
        assert np.mean(scores[m][normal] > t) == pytest.approx(recorded[m])
    boot = pd.read_csv(dest / "bootstrap.csv")
    assert list(boot.criterion) == ["behavioral"]
    assert boot.ci_low.iat[0] <= boot.difference.iat[0] <= boot.ci_high.iat[0]
    assert (dest / "POSTHOC.md").read_text().startswith("# Post-hoc analysis")
