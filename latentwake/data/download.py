"""Download NOAA MarineCadastre daily AIS files and crop them to a region.

Each national daily file is large, so this module streams it to disk, crops it
to a bounding box with DuckDB (which reads the Zstandard-compressed CSV without
unpacking it), writes a small Parquet file per day, and by default deletes the
raw file afterwards. Re-running is safe: finished days are skipped.

Usage (from the repo root):

    python -m latentwake.data.download --region chesapeake \\
        --start 2025-04-01 --end 2025-06-30

Outputs:
    data/raw/ais-YYYY-MM-DD.csv.zst            (deleted after cropping unless --keep-raw)
    data/interim/<region>/ais-YYYY-MM-DD.parquet
    data/interim/<region>/manifest.jsonl       (one line per finished day)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from latentwake.data.regions import BBox, get_region

log = logging.getLogger("latentwake.download")

BASE_URL = "https://noaaocm.blob.core.windows.net/ais/csv2"
USER_AGENT = "latent-wake-ais-downloader/0.1"

# Canonical column names (the 2025 snake_case schema) and the aliases seen in
# other years. Keys are compared after lowercasing and stripping non-alphanumerics,
# so "BaseDateTime", "base_date_time" and "BASE DATE TIME" all match.
CANONICAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "mmsi": ("mmsi", "mmis"),
    "base_date_time": ("basedatetime",),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon", "long"),
    "sog": ("sog",),
    "cog": ("cog",),
    "heading": ("heading",),
    "vessel_name": ("vesselname",),
    "imo": ("imo",),
    "call_sign": ("callsign",),
    "vessel_type": ("vesseltype",),
    "status": ("status",),
    "length": ("length",),
    "width": ("width",),
    "draft": ("draft",),
    "cargo": ("cargo",),
    "transceiver": ("transceiver", "transceiverclass"),
}
REQUIRED = ("mmsi", "base_date_time", "latitude", "longitude", "sog", "cog")

# SQL type for each canonical column. Everything is read as text first and
# converted with TRY_CAST, so one malformed value nulls a cell instead of
# failing a whole day.
COLUMN_TYPES: dict[str, str] = {
    "mmsi": "BIGINT",
    "base_date_time": "TIMESTAMP",
    "latitude": "DOUBLE",
    "longitude": "DOUBLE",
    "sog": "DOUBLE",
    "cog": "DOUBLE",
    "heading": "DOUBLE",
    "vessel_name": "VARCHAR",
    "imo": "VARCHAR",
    "call_sign": "VARCHAR",
    "vessel_type": "INTEGER",
    "status": "INTEGER",
    "length": "DOUBLE",
    "width": "DOUBLE",
    "draft": "DOUBLE",
    "cargo": "INTEGER",
    "transceiver": "VARCHAR",
}


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def map_columns(raw_columns: list[str]) -> dict[str, str]:
    """Map canonical name -> raw column name for the columns present."""
    by_key = {_key(c): c for c in raw_columns}
    mapping: dict[str, str] = {}
    for canonical, aliases in CANONICAL_COLUMNS.items():
        for alias in aliases:
            if alias in by_key:
                mapping[canonical] = by_key[alias]
                break
    missing = [c for c in REQUIRED if c not in mapping]
    if missing:
        raise ValueError(f"File is missing required columns {missing}; saw {raw_columns}")
    return mapping


def daily_filename(day: dt.date) -> str:
    return f"ais-{day:%Y-%m-%d}.csv.zst"


def daily_url(day: dt.date, base_url: str = BASE_URL) -> str:
    if day.year < 2025:
        # Earlier years use a different naming scheme and archive format that
        # this project has not verified yet. Fail loudly instead of guessing.
        raise NotImplementedError(
            "Only the 2025+ daily file format (ais-YYYY-MM-DD.csv.zst) is supported so far."
        )
    return f"{base_url}/csv{day.year}/{daily_filename(day)}"


def date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    if end < start:
        raise ValueError("end date is before start date")
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def download(url: str, dest: Path, retries: int = 4, timeout: float = 120.0) -> int:
    """Stream url to dest atomically. Returns bytes on disk. Skips if dest exists."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest.stat().st_size
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as fh:
                expected = resp.headers.get("Content-Length")
                shutil.copyfileobj(resp, fh, length=8 * 1024 * 1024)
            size = tmp.stat().st_size
            if expected is not None and size != int(expected):
                raise IOError(f"short read: got {size} of {expected} bytes")
            tmp.replace(dest)
            return size
        except urllib.error.HTTPError as err:
            tmp.unlink(missing_ok=True)
            if err.code == 404:
                raise FileNotFoundError(f"{url} not found (file not published yet?)") from err
            last = err
        except (urllib.error.URLError, OSError, TimeoutError) as err:
            tmp.unlink(missing_ok=True)
            last = err
        wait = 2**attempt
        log.warning("download failed (%s), attempt %d/%d; retrying in %ds", last, attempt, retries, wait)
        time.sleep(wait)
    raise RuntimeError(f"giving up on {url}: {last}")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def crop_to_parquet(raw_path: Path, out_path: Path, box: BBox, memory_limit: str = "4GB") -> dict:
    """Crop one daily CSV (plain or .zst) to box and write Parquet. Returns stats."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(f"SET memory_limit = '{memory_limit}'")
        compression = "zstd" if raw_path.suffix == ".zst" else "auto"
        src = (
            f"read_csv({_quote_literal(raw_path)}, header = true, all_varchar = true, "
            f"compression = '{compression}', ignore_errors = true)"
        )
        raw_columns = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
        mapping = map_columns(raw_columns)

        selects = []
        for canonical, raw in mapping.items():
            col = _quote(raw)
            if canonical == "base_date_time":
                expr = f"TRY_CAST(replace({col}, 'T', ' ') AS TIMESTAMP)"
            else:
                expr = f"TRY_CAST({col} AS {COLUMN_TYPES[canonical]})"
            selects.append(f"{expr} AS {canonical}")

        lat, lon = _quote(mapping["latitude"]), _quote(mapping["longitude"])
        where = (
            f"TRY_CAST({lat} AS DOUBLE) BETWEEN {box.lat_min} AND {box.lat_max} "
            f"AND TRY_CAST({lon} AS DOUBLE) BETWEEN {box.lon_min} AND {box.lon_max}"
        )
        tmp = out_path.with_name(out_path.name + ".part")
        con.execute(
            f"COPY (SELECT {', '.join(selects)} FROM {src} WHERE {where} "
            f"ORDER BY mmsi, base_date_time) "
            f"TO {_quote_literal(tmp)} (FORMAT parquet, COMPRESSION zstd)"
        )
        tmp.replace(out_path)
        rows, vessels = con.execute(
            f"SELECT count(*), count(DISTINCT mmsi) FROM read_parquet({_quote_literal(out_path)})"
        ).fetchone()
    finally:
        con.close()
    return {
        "rows": int(rows),
        "vessels": int(vessels),
        "raw_columns": raw_columns,
        "missing_optional": [c for c in CANONICAL_COLUMNS if c not in mapping],
    }


def _quote_literal(path: Path) -> str:
    # Forward slashes keep Windows paths valid inside a SQL string literal.
    return "'" + path.as_posix().replace("'", "''") + "'"


@dataclass
class DayResult:
    date: str
    status: str  # "done", "skipped", "missing", "failed"
    url: str = ""
    raw_bytes: int = 0
    rows: int = 0
    vessels: int = 0
    seconds: float = 0.0
    error: str = ""
    raw_columns: list | None = None
    missing_optional: list | None = None


def process_day(
    day: dt.date,
    box: BBox,
    data_dir: Path,
    keep_raw: bool = False,
    base_url: str = BASE_URL,
    memory_limit: str = "4GB",
) -> DayResult:
    out_path = data_dir / "interim" / box.name / f"ais-{day:%Y-%m-%d}.parquet"
    if out_path.exists():
        return DayResult(date=day.isoformat(), status="skipped")
    url = daily_url(day, base_url)
    raw_path = data_dir / "raw" / daily_filename(day)
    t0 = time.perf_counter()
    try:
        raw_bytes = download(url, raw_path)
        stats = crop_to_parquet(raw_path, out_path, box, memory_limit=memory_limit)
    except FileNotFoundError as err:
        return DayResult(date=day.isoformat(), status="missing", url=url, error=str(err))
    except Exception as err:  # keep going; the manifest records what failed
        log.exception("failed on %s", day)
        return DayResult(date=day.isoformat(), status="failed", url=url, error=repr(err))
    if not keep_raw:
        raw_path.unlink(missing_ok=True)
    return DayResult(
        date=day.isoformat(),
        status="done",
        url=url,
        raw_bytes=raw_bytes,
        seconds=round(time.perf_counter() - t0, 1),
        **stats,
    )


def run(
    region: str,
    start: dt.date,
    end: dt.date,
    data_dir: Path = Path("data"),
    workers: int = 2,
    keep_raw: bool = False,
    base_url: str = BASE_URL,
    memory_limit: str = "4GB",
) -> list[DayResult]:
    box = get_region(region)
    days = date_range(start, end)
    manifest = data_dir / "interim" / box.name / "manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    results: list[DayResult] = []
    log.info("%s: %d days, %s to %s, %d workers", box.name, len(days), start, end, workers)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(process_day, d, box, data_dir, keep_raw, base_url, memory_limit): d for d in days
        }
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            if res.status != "skipped":
                with open(manifest, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(asdict(res)) + "\n")
            log.info("%s %-7s rows=%d vessels=%d %s", res.date, res.status, res.rows, res.vessels, res.error)
    results.sort(key=lambda r: r.date)
    counts = {s: sum(r.status == s for r in results) for s in ("done", "skipped", "missing", "failed")}
    log.info("finished: %s", counts)
    return results


def _parse_date(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--region", default="chesapeake")
    p.add_argument("--start", type=_parse_date, default=dt.date(2025, 4, 1))
    p.add_argument("--end", type=_parse_date, default=dt.date(2025, 6, 30))
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--workers", type=int, default=2, help="days processed in parallel")
    p.add_argument("--keep-raw", action="store_true", help="keep national daily files after cropping")
    p.add_argument("--memory-limit", default="4GB", help="DuckDB memory limit per worker")
    p.add_argument("--base-url", default=BASE_URL)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    results = run(
        args.region, args.start, args.end, args.data_dir, args.workers,
        args.keep_raw, args.base_url, args.memory_limit,
    )
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
