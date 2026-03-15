"""
报表导出接口。

端点：
  GET /api/reports/export — 导出统计报表（CSV 文件下载）
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Building, DailyEnergySummary, EnergyData
from app.db.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["报表"])


@router.get("/export", summary="导出统计报表 CSV")
async def export_report(
    building_type: str = Query(..., description="建筑类型，如 'Office'"),
    start_date: date = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: date = Query(..., description="结束日期 YYYY-MM-DD"),
    report_type: str = Query(
        "daily_summary",
        description="报表类型：daily_summary（每日汇总）/ energy_detail（原始明细）",
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """
    生成并下载 CSV 格式的统计报表。

    report_type 支持：
    - daily_summary: 从物化视图导出每日汇总（日期/总用电/平均温度/最大人员密度）
    - energy_detail: 从 energy_data 导出原始时序明细
    """
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    bld_result = await db.execute(
        select(Building).where(Building.primary_space_usage == building_type)
    )
    building = bld_result.scalar_one_or_none()
    if not building:
        raise HTTPException(status_code=404, detail=f"建筑类型 {building_type} 不存在")

    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == "daily_summary":
        writer.writerow([
            "日期", "建筑类型", "总用电量(kWh)", "总用水量(m³)", "平均温度(°C)",
        ])
        result = await db.execute(
            select(DailyEnergySummary)
            .where(
                DailyEnergySummary.building_id == building.building_id,
                DailyEnergySummary.day >= start_date,
                DailyEnergySummary.day <= end_date,
            )
            .order_by(DailyEnergySummary.day)
        )
        for r in result.scalars().all():
            writer.writerow([
                r.day.strftime("%Y-%m-%d") if r.day else "",
                building_type,
                round(r.total_electricity_kwh or 0, 2),
                round(r.total_water_m3 or 0, 2),
                round(r.avg_ambient_temp or 0, 1),
            ])

    elif report_type == "energy_detail":
        writer.writerow([
            "时间戳", "建筑类型", "电力(kWh)", "水耗(m³)",
            "热水(kWh)", "冷冻水(kWh)",
            "模拟供水温度(°C)", "模拟回水温度(°C)",
            "气温(°C)", "露点温度(°C)", "湿度(%RH)", "异常状态",
        ])
        result = await db.execute(
            select(EnergyData)
            .where(
                EnergyData.building_id == building.building_id,
                EnergyData.timestamp >= start_date,
                EnergyData.timestamp <= end_date,
            )
            .order_by(EnergyData.timestamp)
        )
        for r in result.scalars().all():
            writer.writerow([
                r.timestamp.isoformat() if r.timestamp else "",
                building_type,
                r.electricity_kwh,
                r.water_m3,
                r.hotwater_kwh,
                r.chilledwater_kwh,
                r.sim_supply_temp_c,
                r.sim_return_temp_c,
                r.air_temp_c,
                r.dew_temp_c,
                r.humidity_rh_pct,
                r.anomaly_status or "",
            ])
    else:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的报表类型 '{report_type}'，可选：daily_summary / energy_detail",
        )

    output.seek(0)
    filename = f"{building_type}_{report_type}_{start_date}_{end_date}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
