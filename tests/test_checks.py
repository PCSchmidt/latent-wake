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
from latentwake.inject.build import build_test_set, save_test_set

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
    X, meta, raw = pp.load_split(p, "test", normalized=False, raw=True)
    save_test_set(build_test_set(X, raw, meta, seed=0, per_cell=3), processed / "ts")
    checks.check_testset(processed / "ts", p)
    Xv, meta_v, raw_v = pp.load_split(p, "val", normalized=False, raw=True)
    save_test_set(build_test_set(Xv, raw_v, meta_v, seed=0, per_cell=3), processed / "ts-val")
    with pytest.raises(checks.Blocked, match="expected only 'test'"):
        checks.check_testset(processed / "ts-val", p)


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
