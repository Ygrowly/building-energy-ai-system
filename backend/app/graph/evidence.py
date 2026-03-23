from __future__ import annotations

from typing import Any


def extract_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Best-effort extraction of auditable evidence from tool payloads.

    This keeps the AgentState.evidence list lightweight and UI-friendly.
    """
    evidence: list[dict[str, Any]] = []

    # RAG: payload like {"results":[{"source_doc":..., "page":..., "similarity":...}, ...], ...}
    results = payload.get("results")
    if isinstance(results, list):
        for r in results:
            if not isinstance(r, dict):
                continue
            source_doc = r.get("source_doc")
            page = r.get("page")
            similarity = r.get("similarity")
            if source_doc:
                evidence.append({
                    "type": "rag",
                    "source_doc": source_doc,
                    "page": page,
                    "similarity": similarity,
                })

    # DB query/view: most MCP tools include source_table/source_view.
    source_table = payload.get("source_table")
    source_view = payload.get("source_view")
    meter_device_id = payload.get("meter_device_id") or payload.get("meter_device_id".upper())
    timestamp = None
    if "period_start" in payload:
        timestamp = payload.get("period_start")
    elif "records" in payload and isinstance(payload.get("records"), list) and payload["records"]:
        first = payload["records"][0]
        if isinstance(first, dict):
            timestamp = first.get("timestamp") or first.get("day")

    if source_table:
        evidence.append({
            "type": "db_query",
            "source_table": source_table,
            "meter_device_id": meter_device_id,
            "timestamp": timestamp,
        })
    if source_view:
        evidence.append({
            "type": "db_view",
            "source_view": source_view,
            "timestamp": timestamp,
        })

    return evidence

