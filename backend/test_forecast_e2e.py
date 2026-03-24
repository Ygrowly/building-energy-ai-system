"""
端到端冒烟测试：数据异常预测（forecast）
=========================================
直连 Supabase 数据库，验证完整的预测链路：
  1. 生产工具 building_kpi_forecast_6h_12h（通过 MCP call_tool）
  2. 调试工具 building_kpi_forecast_from_features（直传特征）

用法（PowerShell）::

  $env:PYTHONPATH = "e:/code/work/construction-management/backend"
  & "e:/code/work/construction-management/.venv-forecast/Scripts/python.exe" test_forecast_e2e.py
"""
import asyncio
import ssl

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

DATABASE_URL = (
    "postgresql+asyncpg://postgres.qbtwwbkqlwwhchlbzwis:bhzd%21FWWB%2101"
    "@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"
)
_ssl = ssl.create_default_context()
_ssl.check_hostname = False
_ssl.verify_mode = ssl.CERT_NONE
engine = create_async_engine(DATABASE_URL, connect_args={"ssl": _ssl}, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)


def sec(t):
    print(f"\n{'='*60}\n  {t}\n{'='*60}")


def ok(m):
    print(f"  ✅  {m}")


def fail(m):
    print(f"  ❌  {m}")


async def main():
    from app.mcp.server import call_tool, list_tools

    # ── 0. 确认工具已注册 ─────────────────────────────────
    sec("0. 确认预测工具已注册")
    tools = list_tools()
    names = [t["name"] for t in tools]
    assert "building_kpi_forecast_6h_12h" in names
    assert "building_kpi_forecast_from_features" in names
    ok(f"共注册 {len(names)} 个工具，预测工具（生产 + 调试）均已就位")

    async with Session() as session:

        # ── 1. 生产工具：完整预测链路 ────────────────────────
        sec("1. building_kpi_forecast_6h_12h（Education 楼）")
        result = await call_tool(
            "building_kpi_forecast_6h_12h",
            {"building_id": "Education"},
            session=session,
        )

        if hasattr(result, "error"):
            fail(f"错误：{result.error}")
            fail(f"错误码：{result.error_code}")
        else:
            ok(f"建筑：{result.building_id}")
            ok(f"模型：{result.model_name}")
            ok(f"基准时刻：{result.as_of_timestamp}")
            ok(f"预测跨度：{result.horizons_h}")
            ok(f"使用历史行数：{result.data_rows_used}")
            ok(f"预警数量：{result.warnings_count}")
            ok(f"已持久化：{result.persisted}")
            print()
            for m in result.metrics:
                flag = "⚠️" if m.risk_level != "normal" else "  "
                exp_str = f"{m.expected_value:.2f}" if m.expected_value is not None else "N/A"
                dev_str = f"{m.deviation_pct:+.1f}%" if m.deviation_pct is not None else ""
                print(f"    {flag} {m.metric_name:24s} +{m.horizon_h:2d}h → "
                      f"预测={m.predicted_value:10.2f}  期望={exp_str:>10s}  "
                      f"偏差={dev_str:>8s}  风险={m.risk_level}")

        # ── 2. 生产工具：Office 楼 ───────────────────────────
        sec("2. building_kpi_forecast_6h_12h（Office 楼）")
        result2 = await call_tool(
            "building_kpi_forecast_6h_12h",
            {"building_id": "Office"},
            session=session,
        )
        if hasattr(result2, "error"):
            fail(f"错误：{result2.error}")
        else:
            ok(f"预测完成：{result2.warnings_count} 条预警，{len(result2.metrics)} 条指标")

        # ── 3. 生产工具：不存在的楼 → 应返回错误 ──────────────
        sec("3. 不存在的楼应返回 BUILDING_NOT_FOUND")
        result3 = await call_tool(
            "building_kpi_forecast_6h_12h",
            {"building_id": "Hospital"},
            session=session,
        )
        if hasattr(result3, "error") and result3.error_code == "BUILDING_NOT_FOUND":
            ok(f"正确拦截：{result3.error_code}")
        else:
            fail(f"预期 BUILDING_NOT_FOUND，实际：{result3}")

    # ── 4. 调试工具：直传特征 ─────────────────────────────
    sec("4. building_kpi_forecast_from_features（调试工具）")
    from app.services.forecast_service import _get_artifact, _build_features
    import app.services.forecast_service as mod
    import numpy as np
    import pandas as pd

    mod._ARTIFACT = None
    mod._LOAD_ERROR = None
    artifact = _get_artifact()
    if artifact is None:
        fail(f"模型加载失败：{mod._LOAD_ERROR}")
    else:
        np.random.seed(42)
        n = 30
        df = pd.DataFrame({
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="h"),
            "water_m3": np.random.uniform(50, 200, n),
            "electricity_kwh": np.random.uniform(20, 80, n),
            "sim_supply_temp_c": np.random.uniform(6, 10, n),
            "sim_return_temp_c": np.random.uniform(10, 15, n),
            "hac_energy": np.random.uniform(10, 50, n),
            "air_temp_c": np.random.uniform(5, 25, n),
            "dew_temp_c": np.random.uniform(0, 15, n),
            "humidity_rh_pct": np.random.uniform(30, 90, n),
        })
        X = _build_features(df, artifact["feature_cols"])
        features_dict = {col: float(X[col].iloc[0]) for col in artifact["feature_cols"]}

        result4 = await call_tool(
            "building_kpi_forecast_from_features",
            {"features": features_dict},
        )
        if hasattr(result4, "error"):
            fail(f"错误：{result4.error}")
        else:
            ok(f"模型：{result4.model_name}")
            ok(f"接收特征数：{result4.feature_count_received} / 期望：{result4.feature_count_expected}")
            ok(f"预测输出 {len(result4.predictions)} 个目标列：")
            for col, val in result4.predictions.items():
                print(f"      {col:30s} → {val:.4f}")

    await engine.dispose()
    print(f"\n{'='*60}\n  全部验证完成 🎉\n{'='*60}\n")


asyncio.run(main())
