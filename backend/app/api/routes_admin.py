"""
管理员批处理 API
================
提供手动触发 KPI 期望值计算、异常检测和预测预警的 REST 端点。

  POST /api/admin/compute-expected   — 为所有楼计算 kpi_expected_hourly
  POST /api/admin/detect-anomalies   — 基于 kpi_expected_hourly 运行异常检测
  POST /api/admin/rebuild-all        — 顺序执行以上两个步骤
  POST /api/admin/run-forecast       — 手动批量执行预测预警

开发模式下不要求 JWT 认证，方便调试和测试。
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Building
from app.db.session import get_db_session as get_db
from app.services.kpi_expected_service import compute_and_store_all_buildings
from app.services.anomaly_detection_service import detect_and_store_all_buildings
from app.services.forecast_service import forecast_building_kpi
from app.schemas.mcp_schemas import MCPError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/compute-expected")
async def compute_expected(db: AsyncSession = Depends(get_db)):
    """
    为数据库中所有建筑批量计算 kpi_expected_hourly 额定期望值。
    已存在的行按 (building_id, timestamp) 做幂等 upsert（可重复执行）。
    """
    logger.info("admin: 开始计算 kpi_expected_hourly ...")
    summary = await compute_and_store_all_buildings(db)
    total = sum(summary.values())
    logger.info("admin: kpi_expected_hourly 计算完毕，共写入 %d 行", total)
    return {
        "status": "ok",
        "total_rows": total,
        "per_building": summary,
    }


@router.post("/detect-anomalies")
async def detect_anomalies(db: AsyncSession = Depends(get_db)):
    """
    基于已有 kpi_expected_hourly 数据，对所有建筑运行双阈值异常检测，
    结果写入 kpi_anomaly_flags 和 anomaly_events。
    如果 kpi_expected_hourly 尚未填充，请先调用 /compute-expected。
    """
    logger.info("admin: 开始异常检测 ...")
    summary = await detect_and_store_all_buildings(db)
    total_flags = sum(v["flags"] for v in summary.values())
    total_events = sum(v["events"] for v in summary.values())
    total_telemetry = sum(v.get("telemetry", 0) for v in summary.values())
    total_device_status = sum(v.get("device_status", 0) for v in summary.values())
    total_attributions = sum(v.get("attributions", 0) for v in summary.values())
    logger.info(
        "admin: 异常检测完毕，flags=%d，events=%d，telemetry=%d，status=%d，attrib=%d",
        total_flags, total_events, total_telemetry, total_device_status, total_attributions,
    )
    return {
        "status": "ok",
        "total_flags": total_flags,
        "total_events": total_events,
        "device_telemetry_rows": total_telemetry,
        "device_status_updated": total_device_status,
        "anomaly_attributions": total_attributions,
        "per_building": summary,
    }


@router.post("/rebuild-all")
async def rebuild_all(db: AsyncSession = Depends(get_db)):
    """
    完整重建：先计算期望值，再运行异常检测。
    这是最常用的"一键重建"入口，适合在 energy_data 更新后调用。
    """
    logger.info("admin: rebuild-all 开始 ...")

    expected_summary = await compute_and_store_all_buildings(db)
    total_expected = sum(expected_summary.values())
    logger.info("admin: rebuild-all 期望值写入 %d 行", total_expected)

    detect_summary = await detect_and_store_all_buildings(db)
    total_flags = sum(v["flags"] for v in detect_summary.values())
    total_events = sum(v["events"] for v in detect_summary.values())
    total_telemetry = sum(v.get("telemetry", 0) for v in detect_summary.values())
    total_device_status = sum(v.get("device_status", 0) for v in detect_summary.values())
    total_attributions = sum(v.get("attributions", 0) for v in detect_summary.values())
    logger.info(
        "admin: rebuild-all 完毕，flags=%d，events=%d，telemetry=%d，device_status=%d，attributions=%d",
        total_flags, total_events, total_telemetry, total_device_status, total_attributions,
    )

    return {
        "status": "ok",
        "expected_rows": total_expected,
        "anomaly_flags": total_flags,
        "anomaly_events": total_events,
        "device_telemetry_rows": total_telemetry,
        "device_status_updated": total_device_status,
        "anomaly_attributions": total_attributions,
        "per_building_expected": expected_summary,
        "per_building_detection": detect_summary,
    }


# ---------------------------------------------------------------------------
# 预测预警批量执行
# ---------------------------------------------------------------------------
class RunForecastRequest(BaseModel):
    building_id: Optional[str] = None
    as_of: Optional[datetime] = None


@router.post("/run-forecast")
async def run_forecast(
    body: RunForecastRequest = RunForecastRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    手动批量执行预测预警。

    - 不传 building_id 时对所有楼宇逐一执行
    - 可选传入 as_of 指定预测基准时刻
    - 复用 forecast_building_kpi()，未来可被 lifespan 中的调度器直接调用
    - 调度接入点预留于 main.py lifespan 中（见注释），本轮不启用自动周期任务
    """
    if body.building_id:
        building_types = [body.building_id]
    else:
        result = await db.execute(
            select(Building.primary_space_usage).distinct()
        )
        building_types = [r[0] for r in result.fetchall()]

    succeeded = 0
    failed = 0
    total_warnings = 0
    per_building: dict[str, dict] = {}

    for bt in building_types:
        res = await forecast_building_kpi(
            building_id=bt,
            session=db,
            as_of=body.as_of,
        )
        if isinstance(res, MCPError):
            failed += 1
            per_building[bt] = {"status": "error", "error": res.error}
            logger.warning("run-forecast: %s failed: %s", bt, res.error)
        else:
            succeeded += 1
            total_warnings += res.warnings_count
            per_building[bt] = {
                "status": "ok",
                "warnings_count": res.warnings_count,
                "data_rows_used": res.data_rows_used,
                "persisted": res.persisted,
            }

    logger.info(
        "admin: run-forecast done, buildings=%d, success=%d, fail=%d, warnings=%d",
        len(building_types), succeeded, failed, total_warnings,
    )
    return {
        "status": "ok",
        "total_buildings": len(building_types),
        "succeeded": succeeded,
        "failed": failed,
        "total_warnings": total_warnings,
        "per_building": per_building,
    }
