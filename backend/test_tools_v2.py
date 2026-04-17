"""验证：动态 building_id + 新增工具（list + compare）"""
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from app.core.config import get_settings
from app.db.session import _build_connect_args

from app.schemas.mcp_schemas import (
    TimeRange, MetricType,
    QueryEnergyMetricsInput, CompareMetricAcrossBuildingsInput,
    DetectEnergyAnomaliesInput, CalculateSystemCOPInput,
)
from app.mcp.tools.data_query import (
    list_available_buildings, compare_metric_across_buildings,
    query_energy_metrics,
)
from app.mcp.tools.physics_calc import detect_energy_anomalies, calculate_system_cop

get_settings.cache_clear()
settings = get_settings()

DATABASE_URL = settings.DATABASE_URL
engine = create_async_engine(
    DATABASE_URL,
    connect_args=_build_connect_args(DATABASE_URL),
    echo=False,
)
Session = async_sessionmaker(engine, expire_on_commit=False)

TR = TimeRange(
    start=datetime(2016, 4, 5, tzinfo=timezone.utc),
    end=datetime(2016, 4, 30, 23, 59, tzinfo=timezone.utc),
)

def sec(t): print(f"\n{'='*52}\n  {t}\n{'='*52}")
def ok(m):  print(f"  ✅  {m}")
def fail(m):print(f"  ❌  {m}")

async def main():
    async with Session() as session:

        # ── Tool 9：list_available_buildings ──────────────────────────────
        sec("Tool 9 · list_available_buildings（动态列举建筑）")
        r9 = await list_available_buildings(session)
        ok(f"共 {r9.total} 栋建筑：")
        for b in r9.buildings:
            ok(f"  building_type='{b.building_type}'  meter={b.meter_device_id}  {b.sqm:.0f}㎡")

        # ── Tool 10：compare_metric_across_buildings ───────────────────────
        sec("Tool 10 · compare（所有楼宇平均湿度对比）")
        r10 = await compare_metric_across_buildings(
            CompareMetricAcrossBuildingsInput(
                building_ids=[],           # 空 = 全部楼宇
                time_range=TR,
                metric=MetricType.HUMIDITY_RH_PCT,
                aggregation="avg",
            ),
            session,
        )
        if hasattr(r10, "results"):
            ok(f"对比 {len(r10.results)} 栋楼，指标 {r10.metric.value}（{r10.aggregation}）：")
            for s in r10.results:
                ok(f"  {s.building_type:12s} → {s.aggregated_value:.2f} {s.unit}  ({s.data_points} 条)")
        else:
            fail(str(r10.error))

        # ── Tool 10：两楼对比 ─────────────────────────────────────────────
        sec("Tool 10 · compare（A楼 vs B楼 平均湿度差值）")
        r10b = await compare_metric_across_buildings(
            CompareMetricAcrossBuildingsInput(
                building_ids=["Office", "Education"],
                time_range=TR,
                metric=MetricType.HUMIDITY_RH_PCT,
                aggregation="avg",
            ),
            session,
        )
        if hasattr(r10b, "results") and len(r10b.results) == 2:
            a, b_ = r10b.results[0], r10b.results[1]
            diff = abs(a.aggregated_value - b_.aggregated_value)
            ok(f"{a.building_type} 平均湿度 {a.aggregated_value:.2f}%RH")
            ok(f"{b_.building_type} 平均湿度 {b_.aggregated_value:.2f}%RH")
            ok(f"差值 = {diff:.2f}%RH")
        else:
            fail(str(r10b))

        # ── Tool 3：COP（修复后验证）─────────────────────────────────────
        sec("Tool 3 · calculate_system_cop（修复后）")
        r3 = await calculate_system_cop(
            CalculateSystemCOPInput(building_id="Office", time_range=TR),
            session,
        )
        if hasattr(r3, "cop_mean"):
            ok(f"COP 均值={r3.cop_mean}  最小={r3.cop_min}  最大={r3.cop_max}")
            ok(f"低于 GB 50189 国标基准: {r3.is_below_gb}")
        else:
            fail(str(r3.error))

        # ── Tool 6：异常检测（修复后验证）────────────────────────────────
        sec("Tool 6 · detect_energy_anomalies（修复后）")
        r6 = await detect_energy_anomalies(
            DetectEnergyAnomaliesInput(building_id="Education", time_range=TR),
            session,
        )
        if hasattr(r6, "anomalies"):
            ok(f"检出 {r6.total_anomalies} 条异常")
            for a in r6.anomalies[:3]:
                ok(f"  {a.timestamp.date()} | {a.rule_triggered.value} | 实际值={a.actual_value:.1f}")
        else:
            fail(str(r6.error))

        # ── 动态扩展验证：新楼宇被 DB 层拒绝而非 Schema 层 ───────────────
        sec("动态扩展验证：'Hospital' 被 DB 层拒绝（不是 Schema 层）")
        r_new = await query_energy_metrics(
            QueryEnergyMetricsInput(
                building_id="Hospital",   # Schema 不拦截，DB 查不到才报错
                time_range=TR,
                metrics=[MetricType.ELECTRICITY_KWH],
            ),
            session,
        )
        if hasattr(r_new, "error") and r_new.error_code == "BUILDING_NOT_FOUND":
            ok(f"正确：DB 层拦截，错误码 {r_new.error_code}")
            ok(f"错误提示：{r_new.error}")
        else:
            fail(f"预期 BUILDING_NOT_FOUND，实际: {r_new}")

    await engine.dispose()
    print(f"\n{'='*52}\n  全部验证完成\n{'='*52}\n")

asyncio.run(main())
