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
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import delete_cache_by_prefix
from app.db.models import Building
from app.db.session import get_db_session as get_db, AsyncSessionLocal
from app.services.dispatch_service import scan_dispatch_sla_states
from app.services.dispatch_operation_run_service import (
    DISPATCH_SLA_SCAN_OPERATION,
    record_dispatch_operation_run,
)
from app.services.kpi_expected_service import compute_and_store_all_buildings
from app.services.anomaly_detection_service import detect_and_store_all_buildings
from app.schemas.mcp_schemas import MCPError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _invalidate_operational_data_cache(
    *,
    include_predictions: bool = False,
    include_workorders: bool = False,
) -> None:
    await delete_cache_by_prefix("overview:")
    await delete_cache_by_prefix("anomalies:")
    await delete_cache_by_prefix("home:bundle:")
    await delete_cache_by_prefix("home:overview-bundle:")
    await delete_cache_by_prefix("home:section-bundle:")

    if include_predictions:
        await delete_cache_by_prefix("predictions:")

    if include_workorders:
        await delete_cache_by_prefix("workorders:")
        await delete_cache_by_prefix("incidents:")
        await delete_cache_by_prefix("operations:bundle:")


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
    await _invalidate_operational_data_cache(include_workorders=True)
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
async def rebuild_all():
    """
    完整重建：先计算期望值，再运行异常检测。
    这是最常用的"一键重建"入口，适合在 energy_data 更新后调用。

    两步分别使用独立的 Session，避免第一步长时间运行后连接被服务器关闭，
    导致第二步拿到死连接（asyncpg InterfaceError: underlying connection is closed）。
    """
    logger.info("admin: rebuild-all 开始 ...")

    async with AsyncSessionLocal() as db1:
        expected_summary = await compute_and_store_all_buildings(db1)
    total_expected = sum(expected_summary.values())
    logger.info("admin: rebuild-all 期望值写入 %d 行", total_expected)

    async with AsyncSessionLocal() as db2:
        detect_summary = await detect_and_store_all_buildings(db2)
    total_flags = sum(v["flags"] for v in detect_summary.values())
    total_events = sum(v["events"] for v in detect_summary.values())
    total_telemetry = sum(v.get("telemetry", 0) for v in detect_summary.values())
    total_device_status = sum(v.get("device_status", 0) for v in detect_summary.values())
    total_attributions = sum(v.get("attributions", 0) for v in detect_summary.values())
    logger.info(
        "admin: rebuild-all 完毕，flags=%d，events=%d，telemetry=%d，device_status=%d，attributions=%d",
        total_flags, total_events, total_telemetry, total_device_status, total_attributions,
    )
    await _invalidate_operational_data_cache(include_workorders=True)

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


class RebuildIncidentsRequest(BaseModel):
    building_id: Optional[str] = None
    include_alerts: bool = True
    include_predictions: bool = True
    trigger_ai_review: bool = False


@router.post("/run-forecast")
async def run_forecast(
    body: RunForecastRequest = RunForecastRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    手动批量执行预测预警。

    - 不传 building_id 时对所有楼宇逐一执行
    - 可选传入 as_of 指定预测基准时刻
    - 复用 forecast_building_kpi()，未来可被独立调度器直接调用
    - 默认不在 API 进程启动时自动触发周期任务
    """
    from app.services.forecast_service import forecast_building_kpi

    if body.building_id:
        building_ids = [body.building_id]
    else:
        result = await db.execute(
            select(Building.building_id).order_by(Building.building_id)
        )
        building_ids = [r[0] for r in result.fetchall()]

    succeeded = 0
    failed = 0
    total_warnings = 0
    per_building: dict[str, dict] = {}

    for bid in building_ids:
        res = await forecast_building_kpi(
            building_id=bid,
            session=db,
            as_of=body.as_of,
        )
        if isinstance(res, MCPError):
            failed += 1
            per_building[bid] = {"status": "error", "error": res.error}
            logger.warning("run-forecast: %s failed: %s", bid, res.error)
        else:
            succeeded += 1
            total_warnings += res.warnings_count
            per_building[bid] = {
                "status": "ok",
                "warnings_count": res.warnings_count,
                "data_rows_used": res.data_rows_used,
                "persisted": res.persisted,
            }

    logger.info(
        "admin: run-forecast done, buildings=%d, success=%d, fail=%d, warnings=%d",
        len(building_ids), succeeded, failed, total_warnings,
    )

    # 预测完成后：自动为高风险预警创建工单 + AI 审批
    total_wo_created = 0
    try:
        from app.services.auto_work_order_service import (
            auto_create_prediction_orders,
            trigger_ai_review_for_pending,
        )
        from app.db.session import AsyncSessionLocal

        # 需要查 building_id（非 building_type），查询所有楼宇
        bld_result = await db.execute(
            select(Building.building_id)
        )
        all_building_ids = [r[0] for r in bld_result.fetchall()]

        for bid in all_building_ids:
            try:
                async with AsyncSessionLocal() as session:
                    wo_result = await auto_create_prediction_orders(session, bid)
                    total_wo_created += wo_result.get("created", 0)
            except Exception:
                logger.exception("预警自动建工单失败: building=%s", bid)

        # 批量 AI 审批
        if total_wo_created > 0:
            async with AsyncSessionLocal() as session:
                await trigger_ai_review_for_pending(session)
    except Exception:
        logger.exception("预警工单流程异常")

    await _invalidate_operational_data_cache(
        include_predictions=True,
        include_workorders=True,
    )

    return {
        "status": "ok",
        "total_buildings": len(building_ids),
        "succeeded": succeeded,
        "failed": failed,
        "total_warnings": total_warnings,
        "work_orders_created": total_wo_created,
        "per_building": per_building,
    }


@router.post("/test-workorder")
async def test_workorder():
    """诊断端点：直接对第一个楼宇调用 auto_create_alert_orders，返回详细结果或错误。"""
    import traceback as _tb
    from app.db.session import AsyncSessionLocal
    from app.db.models import AnomalyEvent
    from sqlalchemy import select, func as sa_func

    results = {}
    for bid in ["Fox_education_Louie", "Fox_office_Alice", "Fox_public_Henry"]:
        try:
            # 先查 anomaly_events 数量
            async with AsyncSessionLocal() as s:
                cnt_r = await s.execute(
                    sa_func.count(AnomalyEvent.id)
                    .__class__(sa_func.count(AnomalyEvent.id))
                    if False else
                    select(sa_func.count(AnomalyEvent.id))
                    .where(AnomalyEvent.building_id == bid)
                )
                event_count = cnt_r.scalar()

            # 调用工单创建
            from app.services.auto_work_order_service import auto_create_alert_orders
            async with AsyncSessionLocal() as s:
                wo_result = await auto_create_alert_orders(s, bid)

            results[bid] = {"event_count": event_count, "wo_result": wo_result}
        except Exception as exc:
            results[bid] = {"error": str(exc), "traceback": _tb.format_exc()}

    return results


@router.post("/rebuild-incidents")
async def rebuild_incidents(
    body: RebuildIncidentsRequest = RebuildIncidentsRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    基于现有 anomaly_events / predicted_anomaly_events / work_orders 回填 incident 层。
    不删除旧工单，只为其补充 incident 归属与聚合视图。
    """
    from app.services.auto_work_order_service import (
        auto_create_alert_orders,
        auto_create_prediction_orders,
        trigger_ai_review_for_pending,
    )

    if not body.include_alerts and not body.include_predictions:
        return {
            "status": "ok",
            "message": "未选择任何回填来源，本次未执行。",
            "created": 0,
            "merged": 0,
            "skipped": 0,
            "reviewed": 0,
            "per_building": {},
        }

    if body.building_id:
        building_ids = [body.building_id]
    else:
        result = await db.execute(
            select(Building.building_id).order_by(Building.building_id)
        )
        building_ids = [r[0] for r in result.fetchall()]

    total_created = 0
    total_merged = 0
    total_skipped = 0
    reviewed = 0
    per_building: dict[str, dict[str, object]] = {}

    for bid in building_ids:
        building_summary: dict[str, dict[str, int]] = {}

        if body.include_alerts:
            alert_summary = await auto_create_alert_orders(db, bid)
            building_summary["alerts"] = alert_summary
            total_created += alert_summary.get("created", 0)
            total_merged += alert_summary.get("merged", 0)
            total_skipped += alert_summary.get("skipped_dup", 0)

        if body.include_predictions:
            prediction_summary = await auto_create_prediction_orders(db, bid)
            building_summary["predictions"] = prediction_summary
            total_created += prediction_summary.get("created", 0)
            total_merged += prediction_summary.get("merged", 0)
            total_skipped += prediction_summary.get("skipped_dup", 0)

        per_building[bid] = building_summary

    if body.trigger_ai_review:
        reviewed = await trigger_ai_review_for_pending(db)

    await delete_cache_by_prefix("workorders:")
    await delete_cache_by_prefix("incidents:")

    return {
        "status": "ok",
        "scope": "single_building" if body.building_id else "all_buildings",
        "include_alerts": body.include_alerts,
        "include_predictions": body.include_predictions,
        "created": total_created,
        "merged": total_merged,
        "skipped": total_skipped,
        "reviewed": reviewed,
        "per_building": per_building,
    }


@router.post("/scan-dispatch-sla")
async def scan_dispatch_sla(db: AsyncSession = Depends(get_db)):
    """
    手动扫描当前活跃派工任务的 SLA 状态。

    - 识别临期与超时
    - 写入 dispatch_events: timeout_warning / timeout_overdue
    - 刷新 incident/work_order 读模型
    """
    started_at = datetime.now(timezone.utc)
    try:
        summary = await scan_dispatch_sla_states(db)
        await db.commit()
        if summary.get("updated", 0) > 0:
            await delete_cache_by_prefix("workorders:")
            await delete_cache_by_prefix("incidents:")
        await record_dispatch_operation_run(
            operation_type=DISPATCH_SLA_SCAN_OPERATION,
            trigger_source="admin_api",
            run_status="success",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            summary=summary,
        )
        timings = summary.get("timings_ms") or {}
        logger.info(
            "admin: scan-dispatch-sla 完成 scanned=%d updated=%d warnings=%d overdue=%d timings_ms(total=%s load_dispatch=%s load_work_orders=%s load_assignees=%s prepare_candidates=%s process_loop=%s)",
            summary.get("scanned", 0),
            summary.get("updated", 0),
            summary.get("warning_events", 0),
            summary.get("overdue_events", 0),
            timings.get("total", 0),
            timings.get("load_dispatch_tasks", 0),
            timings.get("load_work_orders", 0),
            timings.get("load_current_assignees", 0),
            timings.get("prepare_candidate_context", 0),
            timings.get("process_loop", 0),
        )
        return {
            "status": "ok",
            **summary,
        }
    except Exception as exc:
        await db.rollback()
        await record_dispatch_operation_run(
            operation_type=DISPATCH_SLA_SCAN_OPERATION,
            trigger_source="admin_api",
            run_status="failed",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            error_message=str(exc),
        )
        raise
