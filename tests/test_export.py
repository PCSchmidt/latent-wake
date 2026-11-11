import datetime as dt
import sqlite3

import pytest
import yaml

from latentwake.data import preprocess as pp
from latentwake.data.synthetic import simulate_days, write_interim
from latentwake.evaluate import run as evaluate
from latentwake.export_panel import run as export
from latentwake.inject.build import build_from_processed, save_test_set
from latentwake.models.jepa import ModelConfig
from latentwake.models.learned_baselines import BaselineConfig
from latentwake.train import TrainConfig, train
from latentwake.train_baseline import train_baseline

SCHEMA = """
CREATE TABLE lw_meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE lw_window(id INTEGER PRIMARY KEY, vessel TEXT, ship_type TEXT, vessel_class TEXT, kind TEXT,
  level INTEGER, severity TEXT, featured INTEGER, under_way INTEGER, mean_sog REAL);
CREATE TABLE lw_point(window_id INTEGER, step INTEGER, lat REAL, lon REAL, injected INTEGER);
CREATE TABLE lw_score(window_id INTEGER, detector TEXT, score REAL, threshold REAL);
CREATE TABLE lw_step(window_id INTEGER, detector TEXT, step INTEGER, value REAL);
CREATE TABLE lw_density(lat REAL, lon REAL, n INTEGER);
CREATE TABLE lw_result(detector TEXT, kind TEXT, auroc REAL, auprc REAL, detect REAL);
"""


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    r = tmp_path_factory.mktemp("export")
    write_interim(simulate_days(dt.date(2025, 4, 1), n_days=6, n_vessels=40, seed=5), r / "interim")
    pp.run(r / "interim", r / "processed")
    save_test_set(build_from_processed(r / "processed", "test", seed=0, per_cell=3), r / "ts")
    train(TrainConfig(processed=str(r / "processed"), out=str(r / "runs/jepa-s0"), epochs=1, batch_size=32,
                      stationary_keep=1.0, device="cpu",
                      model=ModelConfig.small(embed_dim=16, enc_depth=1, pred_depth=1, proj_hidden=32,
                                              pred_dim=16, pred_mlp=32, enc_mlp=32, sigreg_proj=16)),
          log=lambda *_: None)
    train_baseline(BaselineConfig(kind="traisformer", d_model=16, n_layers=1, n_heads=2, epochs=1, batch_size=32),
                   r / "processed", r / "runs/trais-s0", stationary_keep=1.0, device="cpu", log=lambda *_: None)
    common = {"interim": str(r / "interim"), "processed": str(r / "processed"), "testset": str(r / "ts"),
              "calibration": "tail", "alert_fpr": 0.01}
    main = {**common, "out": str(r / "eval"), "fuse_with_kalman": "jepa",
            "models": {"jepa-s0": str(r / "runs/jepa-s0/best.pt")}}
    base = {**common, "out": str(r / "evalb"), "fuse_with_kalman": None,
            "models": {"trais-s0": str(r / "runs/trais-s0/baseline.pt")}}
    for c in (main, base):
        evaluate(r / "ts", r / "processed", {k: v for k, v in c["models"].items()}, c["out"],
                 c["fuse_with_kalman"], calibration="tail")
        (r / "eval" / "benchmark.json").write_text('{"testset_sha256": "abc123abc123", "scored_at": "now"}') \
            if c is main else None
    for name, c in (("main.yaml", main), ("base.yaml", base)):
        (r / name).write_text(yaml.safe_dump(c))
    return r


def test_export_is_loadable_anonymized_and_consistent(setup):
    r = setup
    out = export(r / "main.yaml", r / "base.yaml", r / "data.sql", per_kind=3, normals=6, featured_vessels=2)
    sql = out.read_text()
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA + sql)
    n = db.execute("SELECT count(*) FROM lw_window").fetchone()[0]
    assert n >= 6 + 3 * 5
    assert db.execute("SELECT count(*) FROM lw_point").fetchone()[0] == 64 * n
    assert db.execute("SELECT count(DISTINCT detector) FROM lw_score").fetchone()[0] == 3
    # Injected steps only in anomalous windows.
    assert db.execute("""SELECT count(*) FROM lw_point p JOIN lw_window w ON w.id = p.window_id
                         WHERE w.kind = 'normal' AND p.injected = 1""").fetchone()[0] == 0
    # No MMSI or timestamp leaves the machine.
    import pandas as pd

    mmsis = pd.read_parquet(r / "processed" / "windows.parquet").mmsi.astype(str).unique()
    assert not any(m in sql for m in mmsis)
    cols = [c[1] for c in db.execute("PRAGMA table_info(lw_window)")]
    assert "mmsi" not in cols and "t_start" not in cols
    # Tracks stay in the region box.
    lo = db.execute("SELECT min(lat), max(lat) FROM lw_point").fetchone()
    assert 36 < lo[0] and lo[1] < 40.5
