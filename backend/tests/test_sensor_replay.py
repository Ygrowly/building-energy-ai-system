from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.sensor_replay import (
    load_checkpoint,
    load_replay_rounds,
    save_checkpoint,
)


TEST_TMP_ROOT = BACKEND_DIR / "tests" / ".tmp"


def _case_dir() -> Path:
    path = TEST_TMP_ROOT / str(uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_load_replay_rounds_groups_by_source_timestamp():
    csv_path = _case_dir() / "sample.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timestamp,building_id,air_temp_c,dew_temp_c,humidity_rh_pct,water_m3,electricity_kwh,sim_supply_temp_c,sim_return_temp_c,hac_energy",
                "2026-04-01 00:00:00,Fox_education_Louie,18.3,-6.7,20.83,74.3,4.4642,18.3,18.3,1.2484",
                "2026-04-01 00:00:00,Fox_office_Alice,19.3,-5.7,21.83,75.3,5.4642,19.3,19.3,2.2484",
                "2026-04-01 01:00:00,Fox_public_Henry,20.3,-4.7,22.83,76.3,6.4642,20.3,20.3,3.2484",
            ]
        ),
        encoding="utf-8",
    )

    rounds = load_replay_rounds(csv_path)

    assert len(rounds) == 2
    assert rounds[0].index == 0
    assert rounds[0].source_timestamp == datetime.fromisoformat("2026-04-01 00:00:00")
    assert [row.building_id for row in rounds[0].rows] == [
        "Fox_education_Louie",
        "Fox_office_Alice",
    ]
    assert rounds[1].index == 1
    assert [row.building_id for row in rounds[1].rows] == ["Fox_public_Henry"]


def test_load_replay_rounds_rejects_missing_required_fields():
    csv_path = _case_dir() / "sample.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timestamp,building_id,air_temp_c",
                "2026-04-01 00:00:00,Fox_education_Louie,18.3",
            ]
        ),
        encoding="utf-8",
    )

    try:
        load_replay_rounds(csv_path)
    except ValueError as exc:
        assert "CSV 缺少必要列" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing required fields")


def test_checkpoint_roundtrip():
    case_dir = _case_dir()
    checkpoint_path = case_dir / "checkpoint.json"
    rounds_csv = case_dir / "sample.csv"
    rounds_csv.write_text(
        "\n".join(
            [
                "timestamp,building_id,air_temp_c,dew_temp_c,humidity_rh_pct,water_m3,electricity_kwh,sim_supply_temp_c,sim_return_temp_c,hac_energy",
                "2026-04-01 00:00:00,Fox_education_Louie,18.3,-6.7,20.83,74.3,4.4642,18.3,18.3,1.2484",
            ]
        ),
        encoding="utf-8",
    )
    round_item = load_replay_rounds(rounds_csv)[0]

    save_checkpoint(
        checkpoint_path,
        next_round_index=1,
        round_item=round_item,
        ingest_ts=datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc),
    )
    payload = load_checkpoint(checkpoint_path)

    assert payload is not None
    assert payload["next_round_index"] == 1
    assert payload["source_hour_index"] == 0
    assert payload["source_timestamp"] == "2026-04-01 00:00:00"
    assert payload["last_ingest_ts"] == "2026-04-02T00:00:00+00:00"

    raw = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert raw["rows_written"] == 1
