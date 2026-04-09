from __future__ import annotations

from datetime import datetime, timezone
import json

from langchain_core.messages import AIMessage, ToolMessage

from app.graph.tool_payloads import build_tool_content_and_artifact
from app.graph.viz_engine import build_data_summary, generate_viz_artifacts
from app.api.routes_chat import _build_raw_data_snapshot_artifact, _artifact_event


def test_build_tool_content_and_artifact_preserves_full_payload():
    payload = {
        "building_id": "Education",
        "records": [
            {
                "timestamp": datetime(2026, 1, day, 0, 0, tzinfo=timezone.utc),
                "building_id": "Education",
                "metric": "air_temp_c",
                "value": 8.0 + day * 0.1,
                "unit": "degC",
                "meter_device_id": "EM_AC_Fox_education_Louie",
            }
            for day in range(1, 32)
            for _ in range(6)
        ],
        "total_count": 186,
        "meter_device_id": "EM_AC_Fox_education_Louie",
    }

    content, artifact = build_tool_content_and_artifact(
        tool_name="query_energy_metrics",
        result=payload,
        max_chars=240,
    )

    assert len(content) <= 240
    assert artifact["records"][0]["timestamp"] == "2026-01-01T00:00:00+00:00"
    assert content.startswith("tool=query_energy_metrics")


def test_viz_engine_uses_tool_artifact_when_content_is_truncated():
    daily_payload = {
        "building_id": "Education",
        "granularity": "day",
        "date_range_days": 31,
        "records": [
            {
                "day": f"2026-01-{day:02d}",
                "building_id": "Education",
                "total_electricity_kwh": 100 + day,
                "avg_ambient_temp": 5 + day * 0.2,
                "total_water_m3": 10 + day * 0.1,
                "total_hac_energy": 30 + day * 0.3,
                "avg_supply_temp": 7.0,
                "avg_return_temp": 12.0,
                "avg_humidity": 50.0,
                "avg_dew_temp": 2.0,
            }
            for day in range(1, 32)
        ],
    }
    metric_payload = {
        "building_id": "Education",
        "meter_device_id": "EM_AC_Fox_education_Louie",
        "total_count": 31,
        "records": [
            {
                "timestamp": f"2026-01-{day:02d}T12:00:00+08:00",
                "building_id": "Education",
                "metric": "air_temp_c",
                "value": 5 + day * 0.3,
                "unit": "degC",
                "meter_device_id": "EM_AC_Fox_education_Louie",
            }
            for day in range(1, 32)
        ],
    }

    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_daily",
                    "name": "query_daily_energy_summary",
                    "args": {"building_id": "Education", "granularity": "day"},
                }
            ],
        ),
        ToolMessage(
            content="... truncated json ...",
            artifact=daily_payload,
            tool_call_id="call_daily",
            name="query_daily_energy_summary",
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_metric",
                    "name": "query_energy_metrics",
                    "args": {"building_id": "Education", "metrics": ["air_temp_c"]},
                }
            ],
        ),
        ToolMessage(
            content="... truncated json ...",
            artifact=metric_payload,
            tool_call_id="call_metric",
            name="query_energy_metrics",
        ),
    ]

    summary = build_data_summary(messages)
    artifacts = generate_viz_artifacts(messages, user_question="Analyze January daily energy and weather correlation")

    assert not summary.startswith("（")
    assert artifacts


def test_raw_snapshot_artifact_is_sse_serializable_with_datetime_payload():
    payload = {
        "building_id": "Education",
        "records": [
            {
                "timestamp": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
                "building_id": "Education",
                "metric": "air_temp_c",
                "value": 12.3,
                "unit": "degC",
                "meter_device_id": "EM_AC_Fox_education_Louie",
            }
        ],
        "total_count": 1,
        "meter_device_id": "EM_AC_Fox_education_Louie",
    }

    snapshot = _build_raw_data_snapshot_artifact("query_energy_metrics", payload)
    assert snapshot is not None

    event = _artifact_event(snapshot)
    assert event.startswith("data: ")
    parsed = json.loads(event[6:].strip())
    record = parsed["data_payload"]["records"][0]
    assert record["timestamp"] == "2026-01-01T12:00:00+00:00"
