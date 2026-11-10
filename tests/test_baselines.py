import datetime as dt
import json

import numpy as np
import pytest
import yaml

from latentwake.data import preprocess as pp
from latentwake.data.synthetic import simulate_days, write_interim
from latentwake.evaluate import run as evaluate
from latentwake.inject.build import build_from_processed, save_test_set
from latentwake.models.learned_baselines import (BaselineConfig, LearnedBaseline, four_hot, is_baseline,
                                                 window_stats)
from latentwake.train_baseline import train_baseline


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    r = tmp_path_factory.mktemp("baselines")
    write_interim(simulate_days(dt.date(2025, 4, 1), n_days=6, n_vessels=40, seed=5), r / "interim")
    pp.run(r / "interim", r / "processed")
    save_test_set(build_from_processed(r / "processed", "test", seed=0, per_cell=3), r / "ts")
    return r


SMALL = {
    "iforest": dict(n_estimators=20),
    "lstm_ae": dict(hidden=16, epochs=1, batch_size=32),
    "traisformer": dict(d_model=32, n_layers=1, n_heads=2, epochs=1, batch_size=32),
}


@pytest.mark.parametrize("kind", list(SMALL))
def test_train_save_load_score(root, kind):
    out = root / "runs" / kind
    path = train_baseline(BaselineConfig(kind=kind, **SMALL[kind]), root / "processed", out,
                          stationary_keep=1.0, device="cpu", log=lambda *_: None)
    assert is_baseline(path)
    assert json.loads((out / "config.json").read_text())["started_at"]
    X, meta = pp.load_split(root / "processed", "val", normalized=False)
    b = LearnedBaseline.load(path)
    s = b.window_scores(X, meta.vessel_class.to_numpy(), device="cpu")
    assert s.shape == (len(X),) and np.isfinite(s).all()
    # Deterministic: loading again gives the same scores.
    s2 = LearnedBaseline.load(path).window_scores(X, meta.vessel_class.to_numpy(), device="cpu")
    np.testing.assert_allclose(s, s2, rtol=1e-5, atol=1e-6)


def test_evaluate_scores_baselines_alongside_jepa_free_runs(root):
    models = {f"{k}-s0": root / "runs" / k / "baseline.pt" for k in SMALL}
    for k in SMALL:
        if not models[f"{k}-s0"].exists():
            train_baseline(BaselineConfig(kind=k, **SMALL[k]), root / "processed", root / "runs" / k,
                           stationary_keep=1.0, device="cpu", log=lambda *_: None)
    res = evaluate(root / "ts", root / "processed", models, root / "eval", calibration="tail")
    assert {"iforest-s0", "lstm_ae-s0", "traisformer-s0", "kalman"} <= set(res.method)
    anom = res[res.kind != "normal"]
    assert anom.auroc.between(0, 1).all()


def test_feature_helpers():
    X = np.zeros((2, 64, 7), np.float32)
    assert window_stats(X, "stats").shape == (2, 28)
    assert window_stats(X, "stats+diffs").shape == (2, 42)
    with pytest.raises(ValueError):
        window_stats(X, "nope")
    X[..., 0] = 5000.0          # dx far beyond the clip
    X[..., 4] = 1.0             # cos_cog = 1 -> course 0
    bins = four_hot(X, BaselineConfig(kind="traisformer"))
    assert bins.shape == (2, 64, 4) and bins[..., 0].max() == 59 and bins[..., 3].max() == 0


def test_posthoc_ais_type_breakdown(root):
    from latentwake import posthoc

    types = posthoc.vessel_ais_types(root / "interim", [])
    assert types == {}
    w = __import__("pandas").read_parquet(root / "processed" / "windows.parquet")
    some = w.mmsi.unique()[:5]
    types = posthoc.vessel_ais_types(root / "interim", some)
    assert set(types) <= {int(m) for m in some} and len(types) > 0
    assert posthoc.ais_type_name(50) == "pilot vessel" and posthoc.ais_type_name(33).startswith("dredging")
    assert posthoc.ais_type_name(75) == "cargo" and posthoc.ais_type_name(None) == "missing"


def test_select_baselines_rule():
    import pandas as pd

    from latentwake.select_baselines import select

    rows = []
    for m, a in (("iforest_n100_stats", 0.70), ("iforest_n300_diffs", 0.70), ("iforest_n100_diffs", 0.69),
                 ("lstm_ae_h64", 0.6), ("lstm_ae_h128", 0.65)):
        for k in ("loitering", "teleport"):
            rows.append({"method": m, "kind": k, "level": 0, "auroc": a})
    rows.append({"method": "kalman", "kind": "normal", "level": -1, "auroc": None})
    t = select(pd.DataFrame(rows))
    chosen = dict(zip(t[t.chosen].kind, t[t.chosen].tag))
    assert chosen == {"iforest": "n100_stats", "lstm_ae": "h128"}  # tie goes to the smaller setting


def test_train_seeds_copies_winner_and_trains_two_more(tmp_path, monkeypatch):
    import pandas as pd

    import latentwake.train_baseline as tb
    from latentwake.select_baselines import train_seeds

    grid = tmp_path / "grid" / "lstm_ae_h128"
    grid.mkdir(parents=True)
    (grid / "baseline.pt").write_bytes(b"x")
    calls = []
    monkeypatch.setattr(tb, "main", lambda argv: calls.append(argv))
    table = pd.DataFrame([{"kind": "lstm_ae", "tag": "h128", "chosen": True, "flags": "--hidden 128"}])
    train_seeds(table, tmp_path / "processed", grid_dir=tmp_path / "grid", runs=tmp_path / "runs")
    assert (tmp_path / "runs" / "lstmae-s0" / "baseline.pt").exists()
    assert [c[c.index("--seed") + 1] for c in calls] == ["1", "2"] and all("--hidden" in c for c in calls)
