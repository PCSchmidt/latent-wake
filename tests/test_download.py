"""Tests for the download-and-crop step, using small fake NOAA daily files."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import duckdb
import pytest
import zstandard

from latentwake.data import download as dl
from latentwake.data.regions import BBox, get_region

NEW_HEADER = (
    "mmsi,base_date_time,longitude,latitude,sog,cog,heading,vessel_name,imo,"
    "call_sign,vessel_type,status,length,width,draft,cargo,transceiver"
)
OLD_HEADER = (
    "MMSI,BaseDateTime,LAT,LON,SOG,COG,Heading,VesselName,IMO,CallSign,"
    "VesselType,Status,Length,Width,Draft,Cargo,TransceiverClass"
)

# (mmsi, time, lat, lon) -> inside the Chesapeake box unless noted.
ROWS = [
    (367000001, "2025-04-01T00:00:00", 36.95, -76.30),  # Hampton Roads
    (367000001, "2025-04-01T00:02:00", 36.96, -76.29),
    (367000002, "2025-04-01T00:01:00", 39.25, -76.58),  # Baltimore
    (367000003, "2025-04-01T00:00:00", 40.70, -74.00),  # New York: outside
    (367000004, "2025-04-01T00:00:00", 29.30, -94.80),  # Galveston: outside
]


def _new_line(mmsi, t, lat, lon):
    return f"{mmsi},{t},{lon},{lat},10.5,180.0,179,TEST VESSEL,IMO1,CALL,70,0,100,20,8.5,70,A"


def _old_line(mmsi, t, lat, lon):
    return f"{mmsi},{t},{lat},{lon},10.5,180.0,179,TEST VESSEL,IMO1,CALL,70,0,100,20,8.5,70,A"


def _write_zst(path: Path, header: str, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join([header, *lines]) + "\n"
    path.write_bytes(zstandard.ZstdCompressor().compress(text.encode()))
    return path


def test_region_box_is_sane():
    box = get_region("chesapeake")
    assert box.contains(36.95, -76.30)  # Norfolk
    assert box.contains(39.27, -76.58)  # Baltimore
    assert not box.contains(40.70, -74.00)  # New York
    with pytest.raises(KeyError):
        get_region("atlantis")


def test_bbox_rejects_inverted_ranges():
    with pytest.raises(ValueError):
        BBox("bad", 10, 5, -1, 1)


def test_daily_url_and_dates():
    day = dt.date(2025, 4, 1)
    assert dl.daily_url(day) == f"{dl.BASE_URL}/csv2025/ais-2025-04-01.csv.zst"
    with pytest.raises(NotImplementedError):
        dl.daily_url(dt.date(2024, 4, 1))
    days = dl.date_range(dt.date(2025, 4, 29), dt.date(2025, 5, 2))
    assert [d.isoformat() for d in days] == ["2025-04-29", "2025-04-30", "2025-05-01", "2025-05-02"]


@pytest.mark.parametrize("header", [NEW_HEADER, OLD_HEADER])
def test_map_columns_handles_both_schemas(header):
    mapping = dl.map_columns(header.split(","))
    assert set(dl.REQUIRED) <= set(mapping)
    assert mapping["transceiver"] in ("transceiver", "TransceiverClass")


def test_map_columns_requires_core_fields():
    with pytest.raises(ValueError):
        dl.map_columns(["mmsi", "latitude"])


@pytest.mark.parametrize("header,line", [(NEW_HEADER, _new_line), (OLD_HEADER, _old_line)])
def test_crop_keeps_only_region_rows(tmp_path, header, line):
    raw = _write_zst(tmp_path / "day.csv.zst", header, [line(*r) for r in ROWS])
    out = tmp_path / "out.parquet"
    stats = dl.crop_to_parquet(raw, out, get_region("chesapeake"))
    assert stats["rows"] == 3 and stats["vessels"] == 2
    df = duckdb.sql(f"SELECT * FROM read_parquet('{out.as_posix()}')").df()
    assert list(df.columns) == list(dl.CANONICAL_COLUMNS)
    assert df["latitude"].between(36.6, 39.7).all()
    assert str(df["base_date_time"].dtype).startswith("datetime64")
    assert df["mmsi"].is_monotonic_increasing


def test_crop_survives_malformed_values(tmp_path):
    lines = [_new_line(*ROWS[0]), "367000009,not-a-time,-76.3,36.9,fast,180,179,X,,,,,,,,,A"]
    raw = _write_zst(tmp_path / "day.csv.zst", NEW_HEADER, lines)
    stats = dl.crop_to_parquet(raw, tmp_path / "out.parquet", get_region("chesapeake"))
    assert stats["rows"] == 2  # bad cells become nulls instead of failing the day
    nulls = duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{(tmp_path / 'out.parquet').as_posix()}') "
        "WHERE base_date_time IS NULL AND sog IS NULL"
    ).fetchall()[0][0]
    assert nulls == 1


def test_run_end_to_end_is_resumable(tmp_path):
    # Serve fake national files from a local folder with a file:// base URL.
    served = tmp_path / "served"
    for day in ("2025-04-01", "2025-04-02"):
        rows = [(m, t.replace("2025-04-01", day), la, lo) for m, t, la, lo in ROWS]
        _write_zst(served / "csv2025" / f"ais-{day}.csv.zst", NEW_HEADER, [_new_line(*r) for r in rows])
    data_dir = tmp_path / "data"
    kwargs = dict(
        region="chesapeake",
        start=dt.date(2025, 4, 1),
        end=dt.date(2025, 4, 2),
        data_dir=data_dir,
        workers=2,
        base_url=served.as_uri(),
    )
    first = dl.run(**kwargs)
    assert [r.status for r in first] == ["done", "done"]
    assert all(r.rows == 3 for r in first)
    assert not any((data_dir / "raw").glob("*.zst"))  # raw files removed by default

    manifest = data_dir / "interim" / "chesapeake" / "manifest.jsonl"
    entries = [json.loads(line) for line in manifest.read_text().splitlines()]
    assert len(entries) == 2 and entries[0]["missing_optional"] == []

    second = dl.run(**kwargs)
    assert [r.status for r in second] == ["skipped", "skipped"]
    assert len(manifest.read_text().splitlines()) == 2  # skips are not re-logged
