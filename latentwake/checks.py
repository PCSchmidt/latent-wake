"""Mechanical checks behind the Meridian gates.

Each subcommand prints what it checked and exits 0 (pass) or 2 (block); exit 2
is what Meridian's gate engine treats as a failed pre-hook. The shell wrappers
in scripts/ call these with paths from configs/eval.yaml.

    contract      DATA_CONTRACT.md has no open decisions and parseable thresholds
    schema        cropped daily files exist, and no day failed
    preprocessing processed outputs exist and are sane
    splits        no vessel or time period on both sides of the split
    testset       the frozen test set verifies and was built from held-out windows
    training      three or more seeds per latent model, none collapsed
    benchmark     every model was trained after the test set was frozen; then evaluate
    metrics       evaluation results meet every criterion in DATA_CONTRACT.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

BLOCK = 2
METRICS = {"auroc", "auprc", "detect_at_budget", "fpr_at_budget"}
OPEN_DECISION = re.compile(r"\[DECIDE[^\]]*\]")
THRESHOLD_BLOCK = re.compile(r"```yaml\s+contract-thresholds\s*\n(.*?)```", re.S)


class Blocked(Exception):
    pass


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise Blocked(msg)


def _ok(msg: str) -> None:
    print(f"  ok  {msg}")


# ------------------------------------------------------------------ contract

def load_thresholds(contract: Path) -> list[dict]:
    text = Path(contract).read_text(encoding="utf-8")
    m = THRESHOLD_BLOCK.search(text)
    _need(m is not None, "DATA_CONTRACT.md has no ```yaml contract-thresholds block")
    data = yaml.safe_load(m.group(1)) or {}
    crit = data.get("criteria")
    _need(isinstance(crit, list) and crit, "contract-thresholds has no criteria")
    return crit


def check_contract(contract: Path) -> None:
    _need(Path(contract).exists(), f"{contract} not found")
    text = Path(contract).read_text(encoding="utf-8")
    open_items = OPEN_DECISION.findall(text)
    _need(not open_items, f"{len(open_items)} open decision(s) left in {contract}: " + "; ".join(open_items[:5]))
    _ok("no open [DECIDE] markers")
    for c in load_thresholds(contract):
        cid = c.get("id", "?")
        _need(c.get("metric") in METRICS, f"criterion {cid}: metric must be one of {sorted(METRICS)}")
        _need(c.get("op", ">=") in (">=", "<="), f"criterion {cid}: op must be >= or <=")
        _need(c.get("op", ">=") == ">=" or c.get("value") is not None,
              f"criterion {cid}: op <= needs an absolute value")
        _need(c.get("method"), f"criterion {cid}: method is required")
        _need(isinstance(c.get("kinds"), list) and c["kinds"], f"criterion {cid}: kinds must be a non-empty list")
        has_abs = c.get("value") is not None
        has_rel = c.get("vs_method") is not None and c.get("margin") is not None
        _need(has_abs or has_rel, f"criterion {cid}: set value, or vs_method and margin")
        _ok(f"criterion {cid} is complete")


# -------------------------------------------------------------------- schema

def check_schema(interim: Path) -> None:
    manifest = Path(interim) / "manifest.jsonl"
    files = sorted(Path(interim).glob("ais-*.parquet"))
    _need(files, f"no cropped daily files in {interim}; run the download step")
    _need(manifest.exists(), f"{manifest} missing; files were not produced by the download step")
    last: dict[str, dict] = {}
    for line in manifest.read_text().splitlines():
        rec = json.loads(line)
        last[rec["date"]] = rec  # the latest attempt for each day wins
    failed = sorted(d for d, r in last.items() if r["status"] == "failed")
    _need(not failed, f"{len(failed)} day(s) failed to download or crop: {failed[:5]}")
    done = [r for r in last.values() if r["status"] == "done"]
    missing_cols = sorted({c for r in done for c in (r.get("missing_optional") or [])})
    if missing_cols:
        print(f"  note optional columns absent in some days: {missing_cols}")
    _ok(f"{len(files)} daily files, {sum(r['rows'] for r in done):,} rows, no failed days")


# ------------------------------------------------------------- preprocessing

def check_preprocessing(processed: Path, min_train_windows: int = 1000) -> None:
    from latentwake.data.features import FEATURES, Normalizer
    from latentwake.data.preprocess import load_split

    p = Path(processed)
    for name in ("tracks.parquet", "windows.parquet", "gaps.parquet", "normalizer.json", "stats.json"):
        _need((p / name).exists(), f"{p / name} missing; run the preprocessing step")
    stats = json.loads((p / "stats.json").read_text())
    Normalizer.load(p / "normalizer.json")  # raises if fit on a different feature set
    _ok("outputs present; normalizer matches the feature set")
    _need(stats["grid_valid_frac"] >= 0.5, f"only {stats['grid_valid_frac']:.0%} of grid steps are valid")
    n_train = stats["windows"].get("train", 0)
    _need(n_train >= min_train_windows, f"only {n_train} training windows (need {min_train_windows})")
    for split in ("val", "test"):
        _need(stats["windows"].get(split, 0) > 0, f"no {split} windows")
    X, _ = load_split(p, "train")
    _need(np.isfinite(X).all(), "non-finite values in training windows")
    _need(X.shape[-1] == len(FEATURES), "window feature count does not match FEATURES")
    _ok(f"{n_train:,} train / {stats['windows']['val']:,} val / {stats['windows']['test']:,} test windows, all finite")


# -------------------------------------------------------------------- splits

def check_splits(processed: Path) -> None:
    p = Path(processed)
    w = pd.read_parquet(p / "windows.parquet")
    cutoff = pd.Timestamp(json.loads((p / "stats.json").read_text())["split_cutoff"])
    train, val, test = (w[w.split == s] for s in ("train", "val", "test"))
    _need(set(train.mmsi).isdisjoint(val.mmsi) and set(train.mmsi).isdisjoint(test.mmsi),
          "a vessel appears in both training and evaluation")
    _need(set(val.mmsi).isdisjoint(test.mmsi), "a vessel appears in both validation and test")
    _ok("no vessel on both sides of any split")
    _need((train.t_end < cutoff).all(), "a training window ends after the cutoff")
    _need((val.t_start >= cutoff).all() and (test.t_start >= cutoff).all(), "an evaluation window starts before the cutoff")
    _ok(f"training ends before {cutoff.date()}; evaluation starts on or after it")


# ------------------------------------------------------------------- testset

def check_testset(testset: Path, processed: Path) -> None:
    from latentwake.inject.build import load_test_set

    t = Path(testset)
    _need((t / "manifest.json").exists(), f"no frozen test set at {t}; run latentwake.inject.build")
    try:
        ts = load_test_set(t)
    except ValueError as err:
        raise Blocked(str(err)) from err
    manifest = json.loads((t / "manifest.json").read_text())
    _ok(f"checksum verifies ({manifest['sha256'][:12]}), {len(ts.cells):,} windows")
    _need(manifest.get("frozen_at"), "manifest has no frozen_at time; rebuild with the current code")
    w = pd.read_parquet(Path(processed) / "windows.parquet").set_index("window_id")
    src = ts.cells.source_window.to_numpy()
    _need(np.isin(src, w.index.to_numpy()).all(), "test set references windows not in this processed dataset")
    splits = set(w.loc[src, "split"])
    _need(splits <= {"test"}, f"test set draws from split(s) {sorted(splits)}, expected only 'test'")
    _ok("every window comes from the held-out test split")


# ------------------------------------------------------------------ training

def check_training(cfg_path: Path, min_seeds: int = 3) -> None:
    """Every latent model with SIGReg on has >= min_seeds runs, none collapsed.

    Runs with sigreg_weight 0 are ablations expected to collapse and are skipped.
    """
    cfg = load_eval_config(cfg_path)
    _need(cfg["models"], "configs/eval.yaml lists no models")
    groups: dict[str, list[str]] = {}
    for name, ckpt in cfg["models"].items():
        run = Path(ckpt).parent
        _need((run / "config.json").exists() and (run / "metrics.jsonl").exists(), f"{name}: run files missing in {run}")
        model = json.loads((run / "config.json").read_text())["model"]
        if model["target"] != "latent" or model["sigreg_weight"] == 0:
            continue
        from latentwake.models.jepa import collapse_signal

        history = [json.loads(line) for line in (run / "metrics.jsonl").read_text().splitlines()]
        last = history[-1]
        _need(np.isfinite(last["val_pred"]), f"{name}: validation loss is not finite")
        reason = collapse_signal([h["val_erank"] for h in history], model["embed_dim"])
        _need(reason is None, f"{name}: possible collapse: {reason}")
        groups.setdefault(re.sub(r"-s\d+$", "", name), []).append(name)
        _ok(f"{name}: val_erank {last['val_erank']:.1f}, val_pred {last['val_pred']:.4f}")
    _need(groups, "no latent models with SIGReg on are listed in configs/eval.yaml")
    for method, runs in groups.items():
        _need(len(runs) >= min_seeds, f"{method}: {len(runs)} seed(s) listed, need {min_seeds} (name them {method}-s0, -s1, ...)")
        _ok(f"{method}: {len(runs)} stable seeds")


# ----------------------------------------------------------------- benchmark

def load_eval_config(path: Path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text())
    for key in ("testset", "processed", "out", "models"):
        _need(key in cfg, f"{path} is missing '{key}'")
    return cfg


def check_freeze_order(cfg: dict) -> None:
    frozen = json.loads((Path(cfg["testset"]) / "manifest.json").read_text()).get("frozen_at")
    _need(frozen, "test set has no frozen_at time")
    frozen_at = dt.datetime.fromisoformat(frozen)
    _need(cfg["models"], "configs/eval.yaml lists no models")
    for name, ckpt in cfg["models"].items():
        run_cfg = Path(ckpt).parent / "config.json"
        _need(run_cfg.exists(), f"{name}: {run_cfg} missing")
        started = json.loads(run_cfg.read_text()).get("started_at")
        _need(started, f"{name}: run has no started_at; retrain with the current code")
        _need(dt.datetime.fromisoformat(started) > frozen_at,
              f"{name}: training started {started}, before the test set was frozen at {frozen}")
    _ok(f"all {len(cfg['models'])} model(s) trained after the test set was frozen ({frozen})")


def run_benchmark(cfg_path: Path) -> None:
    from latentwake.evaluate import run as evaluate

    cfg = load_eval_config(cfg_path)
    check_testset(Path(cfg["testset"]), Path(cfg["processed"]))
    check_freeze_order(cfg)
    out = Path(cfg["out"])
    evaluate(Path(cfg["testset"]), Path(cfg["processed"]), {k: Path(v) for k, v in cfg["models"].items()}, out,
             cfg.get("fuse_with_kalman"), float(cfg.get("alert_fpr", 0.01)))
    _ok(f"results written to {out}")


# ------------------------------------------------------------------- metrics

def _method_mean(results: pd.DataFrame, method: str, metric: str, kinds: list[str]) -> float:
    """Mean over each kind's severity cells, then equally across kinds, then across seeds METHOD-sN.

    Weighting kinds equally keeps a kind with many severity levels (AIS gaps
    have 9) from outweighing one with few (loitering has 3).
    """
    sel = results[(results.method == method) | results.method.str.startswith(method + "-s")]
    sel = sel[sel.kind.isin(kinds)]
    _need(len(sel) > 0, f"no results for method '{method}' on kinds {kinds}")
    missing = set(kinds) - set(sel.kind)
    _need(not missing, f"method '{method}' has no results for kinds {sorted(missing)}")
    per_seed = sel.groupby(["method", "kind"])[metric].mean().groupby("method").mean()
    return float(per_seed.mean())


def evaluate_criteria(results: pd.DataFrame, criteria: list[dict]) -> list[dict]:
    out = []
    for c in criteria:
        got = _method_mean(results, c["method"], c["metric"], c["kinds"])
        if c.get("vs_method") is not None:
            ref = _method_mean(results, c["vs_method"], c["metric"], c["kinds"])
            passed = got - ref >= float(c["margin"])
            detail = f"{c['method']} {got:.3f} vs {c['vs_method']} {ref:.3f} (margin {float(c['margin']):+.3f})"
        else:
            op, val = c.get("op", ">="), float(c["value"])
            passed = got >= val if op == ">=" else got <= val
            detail = f"{c['method']} {got:.4f} (needs {op} {val:.4f})"
        out.append({"id": c.get("id", "?"), "passed": bool(passed), "detail": detail})
    return out


def check_metrics(results_csv: Path, contract: Path) -> None:
    _need(Path(results_csv).exists(), f"{results_csv} missing; run the benchmark first")
    rows = evaluate_criteria(pd.read_csv(results_csv), load_thresholds(contract))
    for r in rows:
        print(f"  {'ok  ' if r['passed'] else 'FAIL'} {r['id']}: {r['detail']}")
    failed = [r["id"] for r in rows if not r["passed"]]
    _need(not failed, f"{len(failed)} contract criterion/criteria not met: {failed}")


# ---------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("contract").add_argument("path", type=Path, nargs="?", default=Path("DATA_CONTRACT.md"))
    sub.add_parser("schema").add_argument("interim", type=Path)
    sub.add_parser("preprocessing").add_argument("processed", type=Path)
    sub.add_parser("splits").add_argument("processed", type=Path)
    t = sub.add_parser("testset")
    t.add_argument("testset", type=Path)
    t.add_argument("processed", type=Path)
    sub.add_parser("training").add_argument("config", type=Path, nargs="?", default=Path("configs/eval.yaml"))
    sub.add_parser("benchmark").add_argument("config", type=Path, nargs="?", default=Path("configs/eval.yaml"))
    m = sub.add_parser("metrics")
    m.add_argument("results", type=Path)
    m.add_argument("contract", type=Path, nargs="?", default=Path("DATA_CONTRACT.md"))
    a = p.parse_args(argv)
    print(f"[latentwake.checks {a.cmd}]")
    try:
        {
            "contract": lambda: check_contract(a.path),
            "schema": lambda: check_schema(a.interim),
            "preprocessing": lambda: check_preprocessing(a.processed),
            "splits": lambda: check_splits(a.processed),
            "testset": lambda: check_testset(a.testset, a.processed),
            "training": lambda: check_training(a.config),
            "benchmark": lambda: run_benchmark(a.config),
            "metrics": lambda: check_metrics(a.results, a.contract),
        }[a.cmd]()
    except Blocked as err:
        print(f"  BLOCKED {err}")
        return BLOCK
    except FileNotFoundError as err:
        print(f"  BLOCKED {err}")
        return BLOCK
    return 0


if __name__ == "__main__":
    sys.exit(main())
