"""
管理员批处理 API
================
提供手动触发 KPI 期望值计算和异常检测的 REST 端点。

  POST /api/admin/compute-expected   — 为所有楼计算 kpi_expected_hourly
  POST /api/admin/detect-anomalies   — 基于 kpi_expected_hourly 运行异常检测
  POST /api/admin/rebuild-all        — 顺序执行以上两个步骤

开发模式下不要求 JWT 认证，方便调试和测试。
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session as get_db
from app.services.kpi_expected_service import compute_and_store_all_buildings
from app.services.anomaly_detection_service import detect_and_store_all_buildings

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
    logger.info(
        "admin: 异常检测完毕，flags=%d，events=%d", total_flags, total_events
    )
    return {
        "status": "ok",
        "total_flags": total_flags,
        "total_events": total_events,
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
    logger.info(
        "admin: rebuild-all 检测完毕，flags=%d，events=%d", total_flags, total_events
    )

    return {
        "status": "ok",
        "expected_rows": total_expected,
        "anomaly_flags": total_flags,
        "anomaly_events": total_events,
        "per_building_expected": expected_summary,
        "per_building_detection": detect_summary,
    }
