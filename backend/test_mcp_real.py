"""真实数据库 MCP 工具集成测试"""
import asyncio
import sys
import os

import ssl
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.schemas.mcp_schemas import (
    BuildingID, MetricType, QueryEnergyMetricsInput, TimeRange,
    QueryDailyEnergySummaryInput, GetDeviceLiveStatusInput,
)
from app.mcp.tools.data_query import (
    query_energy_metrics,
    query_daily_energy_summary,
    get_device_live_status,
)
from datetime import datetime, timezone


# ── 构建 Session Pooler 引擎 ──────────────────────────────────────────────
_ssl = ssl.create_default_context()
_ssl.check_hostname = False
_ssl.verify_mode = ssl.CERT_NONE

DATABASE_URL = (
    "postgresql+asyncpg://postgres.qbtwwbkqlwwhchlbzwis:bhzd%21FWWB%2101"
    "@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"
)
engine = create_async_engine(DATABASE_URL, connect_args={"ssl": _ssl}, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# ── 辅助打印 ──────────────────────────────────────────────────────────────
def section(title: str):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print('='*55)

def ok(msg): print(f"  ✅  {msg}")
def fail(msg): print(f"  ❌  {msg}")


async def main():
    async with SessionLocal() as session:

        # ── Tool 1: query_energy_metrics ──────────────────────────────
        section("Tool 1 · query_energy_metrics（查时序原表）")
        inp1 = QueryEnergyMetricsInput(
            building_id=BuildingID.OFFICE,
            time_range=TimeRange(
                start=datetime(2016, 4, 5, tzinfo=timezone.utc),
                end=datetime(2016, 4, 7, 23, 59, tzinfo=timezone.utc),
            ),
            metrics=[MetricType.ELECTRICITY_KWH, MetricType.AMBIENT_TEMP_C],
        )
        result1 = await query_energy_metrics(inp1, session)
        if hasattr(result1, "records"):
            ok(f"返回 {result1.total_count} 条记录，设备 ID: {result1.meter_device_id}")
            if result1.records:
                r = result1.records[0]
                ok(f"最新记录: {r.timestamp.date()} | {r.metric.value} = {r.value} {r.unit}")
        else:
            fail(f"工具报错: {result1.error}")

        # ── Tool 2: get_device_live_status ────────────────────────────
        section("Tool 2 · get_device_live_status（实时设备快照）")
        # 先查真实的 meter_device_id
        from sqlalchemy import text
        row = await session.execute(text("SELECT meter_device_id FROM buildings LIMIT 1"))
        meter_id = row.scalar_one_or_none()
        if meter_id:
            inp2 = GetDeviceLiveStatusInput(meter_device_id=meter_id)
            result2 = await get_device_live_status(inp2, session)
            if hasattr(result2, "meter_device_id"):
                ok(f"设备: {result2.meter_device_id}")
                ok(f"运行状态: {result2.operation_status.value}")
                ok(f"电耗: {result2.electricity_kwh} kWh  温度: {result2.ambient_temp_c}°C")
            else:
                fail(f"工具报错: {result2.error}")
        else:
            fail("buildings 表无数据")

        # ── Tool 4: query_daily_energy_summary ────────────────────────
        section("Tool 4 · query_daily_energy_summary（物化视图）")
        inp4 = QueryDailyEnergySummaryInput(
            building_id=BuildingID.EDUCATION,
            date_range=TimeRange(
                start=datetime(2016, 4, 2, tzinfo=timezone.utc),
                end=datetime(2016, 5, 2, 23, 59, tzinfo=timezone.utc),
            ),
        )
        result4 = await query_daily_energy_summary(inp4, session)
        if hasattr(result4, "records"):
            ok(f"返回 {len(result4.records)} 天数据，查询耗时 {result4.query_ms} ms")
            for rec in result4.records[:3]:
                ok(f"  {rec.day}: 总电耗 {rec.total_electricity_kwh:.1f} kWh  "
                   f"均温 {rec.avg_ambient_temp:.1f}°C")
        else:
            fail(f"工具报错: {result4.error}")

        # ── 建筑白名单检查 ─────────────────────────────────────────────
        section("buildings 表内容核对")
        bldgs = await session.execute(text("SELECT building_id, building_type, meter_device_id FROM buildings"))
        for b in bldgs.fetchall():
            ok(f"{b[0]:12s} | {b[1]:20s} | {b[2]}")

    await engine.dispose()
    print(f"\n{'='*55}")
    print("  全部 MCP 工具测试完成")
    print(f"{'='*55}\n")


asyncio.run(main())
