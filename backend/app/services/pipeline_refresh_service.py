from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Literal

from sqlalchemy import select, text

from app.db.models import Building
from app.db.session import AsyncSessionLocal
from app.services.anomaly_detection_service import (
    attribute_anomalies_to_devices,
    derive_device_status,
    detect_for_building,
    generate_anomaly_events,
    upsert_anomaly_flags,
)
from app.services.kpi_expected_service import (
    compute_expected_for_building,
    upsert_expected_hourly,
)

logger = logging.getLogger(__name__)

ClearMode = Literal["none", "scoped", "global"]


async def _resolve_building_ids(building_ids: Iterable[str] | None) -> list[str]:
    if building_ids is not None:
        seen: set[str] = set()
        resolved: list[str] = []
        for bid in building_ids:
            if bid and bid not in seen:
                seen.add(bid)
                resolved.append(bid)
        return resolved

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Building.building_id).order_by(Building.building_id)
        )
        return [row[0] for row in result.fetchall()]


async def _clear_detection_scope(
    building_ids: list[str],
    *,
    mode: ClearMode,
) -> None:
    if not building_ids or mode == "none":
        return

    async with AsyncSessionLocal() as session:
        if mode == "global":
            await session.execute(text("TRUNCATE TABLE anomaly_events CASCADE"))
            await session.execute(text("TRUNCATE TABLE anomaly_device_attributions"))
            await session.execute(text("TRUNCATE TABLE device_telemetry_hourly"))
            await session.commit()
            return
        return


async def compute_expected_for_buildings(
    building_ids: Iterable[str] | None = None,
    *,
    target_timestamps: set | list | tuple | None = None,
) -> dict[str, int]:
    resolved_ids = await _resolve_building_ids(building_ids)
    summary: dict[str, int] = {}

    for bid in resolved_ids:
        async with AsyncSessionLocal() as session:
            rows = await compute_expected_for_building(
                bid,
                session,
                target_timestamps=target_timestamps,
            )
            count = await upsert_expected_hourly(rows, session)
            summary[bid] = count
            logger.info("expected refresh: %s -> %d rows", bid, count)

    return summary


async def rebuild_detection_for_buildings(
    building_ids: Iterable[str] | None = None,
    *,
    clear_mode: ClearMode = "none",
    target_timestamps: set | list | tuple | None = None,
) -> dict[str, dict[str, int | str | None]]:
    resolved_ids = await _resolve_building_ids(building_ids)
    await _clear_detection_scope(resolved_ids, mode=clear_mode)

    summary: dict[str, dict[str, int | str | None]] = {}
    for bid in resolved_ids:
        async with AsyncSessionLocal() as session:
            flag_rows = await detect_for_building(
                bid,
                session,
                target_timestamps=target_timestamps,
            )
            flags_count = await upsert_anomaly_flags(flag_rows, session)

        async with AsyncSessionLocal() as session:
            events_count = await generate_anomaly_events(
                bid,
                session,
                target_timestamps=target_timestamps,
            )

        async with AsyncSessionLocal() as session:
            telemetry_count, status_count = await derive_device_status(
                bid,
                session,
                target_timestamps=target_timestamps,
            )

        async with AsyncSessionLocal() as session:
            attribution_count = await attribute_anomalies_to_devices(
                bid,
                session,
                target_timestamps=target_timestamps,
            )

        summary[bid] = {
            "flags": flags_count,
            "events": events_count,
            "telemetry": telemetry_count,
            "device_status": status_count,
            "attributions": attribution_count,
            "work_orders_created": 0,
            "wo_error": None,
        }
        logger.info(
            "detection refresh: %s -> flags=%d events=%d telemetry=%d status=%d attrib=%d",
            bid,
            flags_count,
            events_count,
            telemetry_count,
            status_count,
            attribution_count,
        )

    return summary


async def run_pipeline_for_buildings(
    building_ids: Iterable[str] | None = None,
    *,
    clear_mode: ClearMode = "none",
    target_timestamps: set | list | tuple | None = None,
) -> tuple[dict[str, int], dict[str, dict[str, int | str | None]]]:
    expected_summary = await compute_expected_for_buildings(
        building_ids,
        target_timestamps=target_timestamps,
    )
    detection_summary = await rebuild_detection_for_buildings(
        building_ids,
        clear_mode=clear_mode,
        target_timestamps=target_timestamps,
    )
    return expected_summary, detection_summary
