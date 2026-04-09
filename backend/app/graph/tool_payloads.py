from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from decimal import Decimal


_SUMMARY_PREVIEW_ITEMS = 3
_SUMMARY_MAX_TEXT = 180


def normalize_tool_payload(value: Any) -> Any:
    """Normalize tool results / artifacts into JSON-friendly Python data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "model_dump"):
        try:
            return normalize_tool_payload(value.model_dump(mode="json"))
        except TypeError:
            return normalize_tool_payload(value.model_dump())
    if isinstance(value, dict):
        return {
            str(k): normalize_tool_payload(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [normalize_tool_payload(item) for item in value]
    return str(value)


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


def extract_tool_payload(value: Any) -> Any | None:
    """Extract structured payload from a ToolMessage-like object or raw callback output."""
    artifact = normalize_tool_payload(getattr(value, "artifact", None))
    if artifact is not None:
        return artifact

    raw = normalize_tool_payload(value)
    if isinstance(raw, (dict, list)):
        return raw

    text = _stringify_content(getattr(value, "content", raw))
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _clip_text(value: Any, max_chars: int = _SUMMARY_MAX_TEXT) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _build_numeric_summary(records: list[dict[str, Any]]) -> list[str]:
    grouped: dict[str, list[float]] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        metric = row.get("metric")
        value = row.get("value")
        if isinstance(metric, str) and isinstance(value, (int, float)):
            grouped.setdefault(metric, []).append(float(value))

    lines: list[str] = []
    for metric, values in grouped.items():
        if not values:
            continue
        avg_val = sum(values) / len(values)
        lines.append(
            f"- {metric}: {len(values)} points, avg={avg_val:.2f}, "
            f"min={min(values):.2f}, max={max(values):.2f}"
        )
    return lines


def summarize_tool_payload(tool_name: str, payload: Any) -> str:
    """Build a compact text summary for the LLM while the full payload stays in artifact."""
    normalized = normalize_tool_payload(payload)
    if not isinstance(normalized, dict):
        return _clip_text(normalized)

    lines = [f"tool={tool_name}"]
    for key in (
        "status",
        "building_id",
        "building_type",
        "device_id",
        "meter_device_id",
        "metric",
        "granularity",
        "total_count",
        "date_range_days",
        "source_table",
        "unit",
        "ticket_id",
        "component_type",
        "title",
    ):
        value = normalized.get(key)
        if value not in (None, "", [], {}):
            lines.append(f"{key}={value}")

    for key in ("date_range", "time_range"):
        value = normalized.get(key)
        if isinstance(value, dict):
            start = value.get("start")
            end = value.get("end")
            if start or end:
                lines.append(f"{key}={start or '?'} -> {end or '?'}")

    records = normalized.get("records")
    if isinstance(records, list):
        lines.append(f"records={len(records)}")
        if records:
            first = records[0] if isinstance(records[0], dict) else {}
            last = records[-1] if isinstance(records[-1], dict) else {}
            start = first.get("timestamp") or first.get("day")
            end = last.get("timestamp") or last.get("day")
            if start or end:
                lines.append(f"span={start or '?'} -> {end or '?'}")
            lines.extend(_build_numeric_summary(records))
            preview = [
                {
                    k: _clip_text(v, 80) if isinstance(v, str) else v
                    for k, v in row.items()
                    if k in ("timestamp", "day", "metric", "value", "unit", "total_electricity_kwh", "avg_ambient_temp")
                }
                for row in records[:_SUMMARY_PREVIEW_ITEMS]
                if isinstance(row, dict)
            ]
            if preview:
                lines.append(
                    "records_preview=" + json.dumps(preview, ensure_ascii=False, default=str)
                )

    results = normalized.get("results")
    if isinstance(results, list):
        lines.append(f"results={len(results)}")
        preview = []
        for row in results[:_SUMMARY_PREVIEW_ITEMS]:
            if isinstance(row, dict):
                preview.append(
                    {
                        k: _clip_text(v, 100) if isinstance(v, str) else v
                        for k, v in row.items()
                        if k in (
                            "source_doc",
                            "page",
                            "similarity",
                            "score",
                            "content",
                            "snippet",
                            "title",
                            "aggregated_value",
                            "building_type",
                            "unit",
                        )
                    }
                )
            else:
                preview.append(_clip_text(row, 100))
        if preview:
            lines.append(
                "results_preview=" + json.dumps(preview, ensure_ascii=False, default=str)
            )

    error = normalized.get("error")
    if error:
        lines.append(f"error={_clip_text(error)}")

    lines.append("full_payload=tool_artifact")
    return "\n".join(lines)


def build_tool_content_and_artifact(
    tool_name: str,
    result: Any,
    max_chars: int,
) -> tuple[str, Any]:
    """Return (content, artifact) for StructuredTool response_format='content_and_artifact'."""
    artifact = normalize_tool_payload(result)
    if isinstance(artifact, str):
        raw = artifact
    else:
        try:
            raw = json.dumps(artifact, ensure_ascii=False, default=str)
        except Exception:
            raw = str(artifact)

    if len(raw) <= max_chars:
        return raw, artifact

    summary = summarize_tool_payload(tool_name, artifact)
    if len(summary) > max_chars:
        summary = summary[: max_chars - 3] + "..."
    return summary, artifact
