"""
预测模块单元测试
================
测试 forecast_service 的各个子模块：
  1. 绝对湿度计算
  2. 预警阈值判定
  3. 特征构造（41 维）
  4. Schema 序列化
  5. 模型加载与推理（需 pkl 存在）
  6. MCP 工具注册
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

pd = pytest.importorskip("pandas", exc_type=ImportError)


# ---------------------------------------------------------------------------
# 1. 绝对湿度计算
# ---------------------------------------------------------------------------
class TestAbsoluteHumidity:
    def test_normal_values(self):
        from app.services.forecast_service import _absolute_humidity
        result = _absolute_humidity(20.0, 10.0)
        assert result > 0
        assert isinstance(result, float)

    def test_zero_temperature(self):
        from app.services.forecast_service import _absolute_humidity
        result = _absolute_humidity(0.0, 0.0)
        assert result > 0

    def test_nan_returns_zero(self):
        from app.services.forecast_service import _absolute_humidity
        assert _absolute_humidity(float("nan"), 10.0) == 0.0
        assert _absolute_humidity(10.0, float("nan")) == 0.0

    def test_none_returns_zero(self):
        from app.services.forecast_service import _absolute_humidity
        assert _absolute_humidity(None, 10.0) == 0.0
        assert _absolute_humidity(10.0, None) == 0.0

    def test_hot_humid_higher_than_cold_dry(self):
        from app.services.forecast_service import _absolute_humidity
        hot = _absolute_humidity(35.0, 25.0)
        cold = _absolute_humidity(5.0, -5.0)
        assert hot > cold


# ---------------------------------------------------------------------------
# 2. 预警阈值判定
# ---------------------------------------------------------------------------
class TestAssessRisk:
    def test_normal_when_below_threshold(self):
        from app.services.forecast_service import _assess_risk
        risk, rule, dev = _assess_risk("electricity_kwh", 55.0, 50.0)
        assert risk == "normal"
        assert rule is None
        assert dev is not None

    def test_warning_when_above_threshold(self):
        from app.services.forecast_service import _assess_risk
        risk, rule, dev = _assess_risk("electricity_kwh", 100.0, 50.0)
        assert risk == "warning"
        assert rule == "electricity_overload"
        assert dev == 100.0

    def test_water_leak_warning(self):
        from app.services.forecast_service import _assess_risk
        risk, rule, dev = _assess_risk("water_l", 5000.0, 2000.0)
        assert risk == "warning"
        assert rule == "water_leak"

    def test_hvac_overconsumption_warning(self):
        from app.services.forecast_service import _assess_risk
        risk, rule, dev = _assess_risk("hac_energy", 100.0, 50.0)
        assert risk == "warning"
        assert rule == "hvac_overconsumption"

    def test_none_expected_returns_normal(self):
        from app.services.forecast_service import _assess_risk
        risk, rule, dev = _assess_risk("electricity_kwh", 100.0, None)
        assert risk == "normal"
        assert dev is None

    def test_zero_expected_returns_normal(self):
        from app.services.forecast_service import _assess_risk
        risk, rule, dev = _assess_risk("electricity_kwh", 100.0, 0.0)
        assert risk == "normal"

    def test_temperature_never_triggers_warning(self):
        from app.services.forecast_service import _assess_risk
        risk, rule, dev = _assess_risk("sim_supply_temp_c", 50.0, 7.0)
        assert risk == "normal"
        assert rule is None

    def test_only_relative_exceeded_not_enough(self):
        """相对偏差超标但绝对偏差不足，不应触发预警。"""
        from app.services.forecast_service import _assess_risk
        risk, rule, dev = _assess_risk("electricity_kwh", 6.0, 5.0)
        assert risk == "normal"


# ---------------------------------------------------------------------------
# 3. 特征构造
# ---------------------------------------------------------------------------
def _make_fake_df(n: int = 30) -> pd.DataFrame:
    """构造模拟 energy_data 的 DataFrame。"""
    np.random.seed(42)
    return pd.DataFrame({
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


class TestBuildFeatures:
    def test_output_shape(self):
        from app.services.forecast_service import _build_features
        feature_cols = [
            "water_l_lag1", "water_l_lag2", "water_l_lag3",
            "water_l_lag6", "water_l_lag12", "water_l_lag24",
            "electricity_kwh_lag1", "electricity_kwh_lag2", "electricity_kwh_lag3",
            "electricity_kwh_lag6", "electricity_kwh_lag12", "electricity_kwh_lag24",
            "sim_supply_temp_c_lag1", "sim_supply_temp_c_lag2", "sim_supply_temp_c_lag3",
            "sim_supply_temp_c_lag6", "sim_supply_temp_c_lag12", "sim_supply_temp_c_lag24",
            "sim_return_temp_c_lag1", "sim_return_temp_c_lag2", "sim_return_temp_c_lag3",
            "sim_return_temp_c_lag6", "sim_return_temp_c_lag12", "sim_return_temp_c_lag24",
            "hac_energy_lag1", "hac_energy_lag2", "hac_energy_lag3",
            "hac_energy_lag6", "hac_energy_lag12", "hac_energy_lag24",
            "w_mean24", "e_mean24", "hac_mean24", "e_std24",
            "hour", "dow", "month",
            "Ta", "Tdew", "hum", "rh",
        ]
        df = _make_fake_df(30)
        X = _build_features(df, feature_cols)
        assert X.shape == (1, 41)
        assert list(X.columns) == feature_cols

    def test_does_not_mutate_input(self):
        from app.services.forecast_service import _build_features
        df = _make_fake_df(30)
        original_cols = list(df.columns)
        feature_cols = ["water_l_lag1", "hour", "Ta", "rh", "hum",
                        "w_mean24", "e_mean24", "hac_mean24", "e_std24",
                        "electricity_kwh_lag1", "sim_supply_temp_c_lag1",
                        "sim_return_temp_c_lag1", "hac_energy_lag1",
                        "water_l_lag2", "water_l_lag3", "water_l_lag6",
                        "water_l_lag12", "water_l_lag24",
                        "electricity_kwh_lag2", "electricity_kwh_lag3",
                        "electricity_kwh_lag6", "electricity_kwh_lag12",
                        "electricity_kwh_lag24",
                        "sim_supply_temp_c_lag2", "sim_supply_temp_c_lag3",
                        "sim_supply_temp_c_lag6", "sim_supply_temp_c_lag12",
                        "sim_supply_temp_c_lag24",
                        "sim_return_temp_c_lag2", "sim_return_temp_c_lag3",
                        "sim_return_temp_c_lag6", "sim_return_temp_c_lag12",
                        "sim_return_temp_c_lag24",
                        "hac_energy_lag2", "hac_energy_lag3",
                        "hac_energy_lag6", "hac_energy_lag12",
                        "hac_energy_lag24",
                        "dow", "month", "Tdew"]
        _build_features(df, feature_cols)
        assert list(df.columns) == original_cols

    def test_missing_feature_raises(self):
        from app.services.forecast_service import _build_features
        df = _make_fake_df(30)
        with pytest.raises(ValueError, match="无法构造的特征列"):
            _build_features(df, ["nonexistent_col_xyz"])

    def test_too_few_rows_has_nan_in_lag24(self):
        """不足 25 行时，lag24 会含 NaN（调用方负责提前拦截）。"""
        from app.services.forecast_service import _build_features
        df = _make_fake_df(10)
        feature_cols = ["water_l_lag24", "hour", "Ta", "rh", "hum"]
        X = _build_features(df, feature_cols)
        assert pd.isna(X["water_l_lag24"].iloc[0])

    def test_time_features_correct(self):
        from app.services.forecast_service import _build_features
        df = _make_fake_df(30)
        X = _build_features(df, ["hour", "dow", "month"])
        last_ts = pd.Timestamp("2025-01-02 05:00:00")
        assert int(X["hour"].iloc[0]) == last_ts.hour
        assert int(X["dow"].iloc[0]) == last_ts.dayofweek
        assert int(X["month"].iloc[0]) == last_ts.month

    def test_weather_mapping(self):
        from app.services.forecast_service import _build_features
        df = _make_fake_df(30)
        X = _build_features(df, ["Ta", "Tdew", "rh", "hum"])
        assert X["Ta"].iloc[0] == df["air_temp_c"].iloc[-1]
        assert X["Tdew"].iloc[0] == df["dew_temp_c"].iloc[-1]
        assert X["rh"].iloc[0] == df["humidity_rh_pct"].iloc[-1]
        assert X["hum"].iloc[0] > 0


# ---------------------------------------------------------------------------
# 4. Schema 序列化
# ---------------------------------------------------------------------------
class TestSchemas:
    def test_forecast_kpi_input_defaults(self):
        from app.schemas.mcp_schemas import ForecastKPIInput
        inp = ForecastKPIInput(building_id="Education")
        assert inp.as_of is None
        assert inp.include_expected_comparison is True

    def test_forecast_kpi_input_with_as_of(self):
        from app.schemas.mcp_schemas import ForecastKPIInput
        ts = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        inp = ForecastKPIInput(building_id="Office", as_of=ts)
        assert inp.as_of == ts

    def test_forecasted_metric_serialization(self):
        from app.schemas.mcp_schemas import ForecastedMetric
        m = ForecastedMetric(
            metric_name="electricity_kwh",
            horizon_h=6,
            predicted_value=55.1234,
            expected_value=50.0,
            deviation_pct=10.25,
            risk_level="normal",
            rule_triggered=None,
        )
        d = m.model_dump()
        assert d["metric_name"] == "electricity_kwh"
        assert d["horizon_h"] == 6
        assert d["predicted_value"] == 55.1234

    def test_forecast_kpi_output_serialization(self):
        from app.schemas.mcp_schemas import ForecastKPIOutput, ForecastedMetric
        ts = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        output = ForecastKPIOutput(
            building_id="Education",
            as_of_timestamp=ts,
            model_name="test_model",
            horizons_h=[6, 12],
            metrics=[
                ForecastedMetric(
                    metric_name="electricity_kwh",
                    horizon_h=6,
                    predicted_value=55.0,
                    risk_level="normal",
                ),
            ],
            warnings_count=0,
            data_rows_used=30,
            persisted=False,
        )
        d = output.model_dump()
        assert d["building_id"] == "Education"
        assert len(d["metrics"]) == 1


# ---------------------------------------------------------------------------
# 5. 模型加载与推理（需要 pkl 文件）
# ---------------------------------------------------------------------------
class TestModelLoadAndPredict:
    def test_artifact_loads(self):
        """验证模型元数据可通过子进程加载并包含必要字段。"""
        from app.services.forecast_service import _load_metadata, _METADATA_ERROR, _PKL_PATH
        import app.services.forecast_service as mod
        mod._METADATA = None
        mod._METADATA_ERROR = None
        meta = _load_metadata()
        if meta is None:
            pytest.skip(f"pkl not loadable at {_PKL_PATH}: {mod._METADATA_ERROR}")
        assert "feature_cols" in meta
        assert "target_cols" in meta
        assert "horizons_h" in meta
        assert "target_kpis" in meta
        assert "model_name" in meta
        assert len(meta["feature_cols"]) == 41
        assert len(meta["target_cols"]) == 10

    def test_predict_with_fake_data(self):
        """用假数据验证完整的特征构造 + 子进程推理链路。"""
        from app.services.forecast_service import _load_metadata, _predict, _build_features
        import app.services.forecast_service as mod
        mod._METADATA = None
        mod._METADATA_ERROR = None
        meta = _load_metadata()
        if meta is None:
            pytest.skip("pkl not loadable")

        df = _make_fake_df(30)
        X = _build_features(df, meta["feature_cols"])
        assert X.shape == (1, 41)

        feature_row = {col: float(X[col].iloc[0]) for col in meta["feature_cols"]}
        y_hat = _predict(feature_row, meta["feature_cols"])
        assert len(y_hat) == 10
        for val in y_hat:
            assert isinstance(val, float)
            assert not math.isnan(val)


# ---------------------------------------------------------------------------
# 6. MCP 工具注册
# ---------------------------------------------------------------------------
class TestMCPRegistration:
    def test_forecast_tool_registered(self):
        from app.mcp.server import _REGISTRY
        assert "building_kpi_forecast_6h_12h" in _REGISTRY

    def test_forecast_tool_metadata(self):
        from app.mcp.server import _REGISTRY
        defn = _REGISTRY["building_kpi_forecast_6h_12h"]
        assert defn.requires_db is True
        assert defn.input_schema is not None
        assert "预测" in defn.description or "ML" in defn.description

    def test_debug_tool_registered(self):
        from app.mcp.server import _REGISTRY
        assert "building_kpi_forecast_from_features" in _REGISTRY

    def test_debug_tool_metadata(self):
        from app.mcp.server import _REGISTRY
        defn = _REGISTRY["building_kpi_forecast_from_features"]
        assert defn.requires_db is False
        assert defn.input_schema is not None
        assert "调试" in defn.description

    def test_list_tools_includes_forecast(self):
        from app.mcp.server import list_tools
        tools = list_tools()
        names = [t["name"] for t in tools]
        assert "building_kpi_forecast_6h_12h" in names
        assert "building_kpi_forecast_from_features" in names


# ---------------------------------------------------------------------------
# 7. 调试工具直传推理
# ---------------------------------------------------------------------------
class TestForecastFromFeatures:
    def test_missing_features_returns_error(self):
        from app.services.forecast_service import forecast_from_raw_features
        from app.schemas.mcp_schemas import MCPError
        import app.services.forecast_service as mod
        mod._METADATA = None
        mod._METADATA_ERROR = None
        result = forecast_from_raw_features({"hour": 12.0})
        if isinstance(result, MCPError) and result.error_code == "MODEL_LOAD_FAILED":
            pytest.skip("pkl not loadable")
        assert isinstance(result, MCPError)
        assert result.error_code == "FEATURE_MISMATCH"

    def test_full_features_returns_predictions(self):
        from app.services.forecast_service import forecast_from_raw_features, _load_metadata, _build_features
        from app.schemas.mcp_schemas import ForecastFromFeaturesOutput, MCPError
        import app.services.forecast_service as mod
        mod._METADATA = None
        mod._METADATA_ERROR = None
        meta = _load_metadata()
        if meta is None:
            pytest.skip("pkl not loadable")

        df = _make_fake_df(30)
        X = _build_features(df, meta["feature_cols"])
        features_dict = {col: float(X[col].iloc[0]) for col in meta["feature_cols"]}
        result = forecast_from_raw_features(features_dict)
        assert isinstance(result, ForecastFromFeaturesOutput)
        assert len(result.predictions) == 10
        assert result.feature_count_expected == 41
        assert result.feature_count_received == 41

    def test_schema_serialization(self):
        from app.schemas.mcp_schemas import ForecastFromFeaturesInput, ForecastFromFeaturesOutput
        inp = ForecastFromFeaturesInput(features={"a": 1.0, "b": 2.0})
        assert len(inp.features) == 2
        out = ForecastFromFeaturesOutput(
            model_name="test",
            horizons_h=[6, 12],
            target_cols=["y_a", "y_b"],
            predictions={"y_a": 1.0, "y_b": 2.0},
            feature_count_received=2,
            feature_count_expected=41,
        )
        d = out.model_dump()
        assert d["model_name"] == "test"
        assert len(d["predictions"]) == 2


# ---------------------------------------------------------------------------
# 8. 严格基线匹配策略
# ---------------------------------------------------------------------------
class TestStrictBaselineMatching:
    """验证第一版基线对齐策略：仅当 future_ts == kpi_expected_hourly.timestamp 时才返回期望值。"""

    def test_no_expected_returns_normal(self):
        """expected_value=None 时，risk_level 必须为 normal，不报错不补值。"""
        from app.services.forecast_service import _assess_risk
        risk, rule, dev = _assess_risk("electricity_kwh", 999.0, None)
        assert risk == "normal"
        assert rule is None
        assert dev is None

    def test_exact_match_returns_expected(self):
        """精确匹配到基线时，返回期望值和偏差。"""
        from app.services.forecast_service import _assess_risk
        risk, rule, dev = _assess_risk("electricity_kwh", 100.0, 50.0)
        assert risk == "warning"
        assert dev == 100.0
        assert rule == "electricity_overload"

    def test_all_kpi_none_expected_stays_normal(self):
        """所有 KPI 在未匹配基线时均返回 normal。"""
        from app.services.forecast_service import _assess_risk, _KPI_NAMES
        for kpi in _KPI_NAMES:
            risk, rule, dev = _assess_risk(kpi, 9999.0, None)
            assert risk == "normal", f"{kpi} should be normal when expected=None"
            assert dev is None

    def test_metric_output_without_baseline(self):
        """模拟完整 ForecastedMetric 组装：无基线时字段正确。"""
        from app.schemas.mcp_schemas import ForecastedMetric
        m = ForecastedMetric(
            metric_name="water_l",
            horizon_h=6,
            predicted_value=1500.0,
            expected_value=None,
            deviation_pct=None,
            risk_level="normal",
            rule_triggered=None,
        )
        assert m.expected_value is None
        assert m.deviation_pct is None
        assert m.risk_level == "normal"

    def test_metric_output_with_baseline(self):
        """模拟完整 ForecastedMetric 组装：有基线且超标时字段正确。"""
        from app.schemas.mcp_schemas import ForecastedMetric
        m = ForecastedMetric(
            metric_name="water_l",
            horizon_h=12,
            predicted_value=5000.0,
            expected_value=2000.0,
            deviation_pct=150.0,
            risk_level="warning",
            rule_triggered="water_leak",
        )
        assert m.expected_value == 2000.0
        assert m.risk_level == "warning"
        assert m.rule_triggered == "water_leak"


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeBuildingInfoSession:
    def __init__(self, rows_per_call: list[list[tuple]]):
        self._rows_per_call = rows_per_call
        self.calls = 0

    async def execute(self, _stmt):
        if self.calls >= len(self._rows_per_call):
            raise AssertionError("unexpected execute call")
        rows = self._rows_per_call[self.calls]
        self.calls += 1
        return _FakeResult(rows)


@pytest.mark.asyncio
async def test_get_building_info_accepts_actual_building_id():
    from app.mcp.tools.data_query import get_building_info

    session = _FakeBuildingInfoSession([
        [("Fox_office_Alice",)],
        [("EM_ELE_Fox_office_Alice",)],
    ])

    meter_id, actual_bid = await get_building_info(session, "Fox_office_Alice")

    assert meter_id == "EM_ELE_Fox_office_Alice"
    assert actual_bid == "Fox_office_Alice"
    assert session.calls == 2


@pytest.mark.asyncio
async def test_get_building_info_falls_back_to_primary_space_usage():
    from app.mcp.tools.data_query import get_building_info

    session = _FakeBuildingInfoSession([
        [],
        [("Fox_office_Alice",)],
        [("EM_ELE_Fox_office_Alice",)],
    ])

    meter_id, actual_bid = await get_building_info(session, "Office")

    assert meter_id == "EM_ELE_Fox_office_Alice"
    assert actual_bid == "Fox_office_Alice"
    assert session.calls == 3


@pytest.mark.asyncio
async def test_forecast_persists_resolved_building_id(monkeypatch: pytest.MonkeyPatch):
    import app.services.forecast_service as mod
    from app.schemas.mcp_schemas import ForecastKPIOutput

    async def fake_get_building_info(_session, _building_ref):
        return "EM_ELE_Fox_office_Alice", "Fox_office_Alice"

    async def fake_build_features_async(_df, _feature_cols):
        return pd.DataFrame([{"f1": 1.0}])

    async def fake_predict_async(_feature_row, _feature_cols):
        return [100.0]

    persisted_args: dict[str, object] = {}

    async def fake_persist_predictions(*, building_id, as_of, metrics, model_name, session):
        persisted_args["building_id"] = building_id
        persisted_args["as_of"] = as_of
        persisted_args["metrics"] = metrics
        persisted_args["model_name"] = model_name
        persisted_args["session"] = session
        return 1

    class FakeForecastSession:
        def __init__(self):
            self._energy_rows = self._make_energy_rows()
            self._expected_rows = [
                (self._energy_rows[0][0] + timedelta(hours=6), None, 50.0, None, None, None),
            ]
            self.calls = 0

        def _make_energy_rows(self):
            latest = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
            rows = []
            for offset in range(25):
                ts = latest - timedelta(hours=offset)
                rows.append((ts, 10.0, 20.0, 7.0, 12.0, 15.0, 26.0, 18.0, 60.0))
            return rows

        async def execute(self, _stmt):
            self.calls += 1
            if self.calls == 1:
                return _FakeResult(self._energy_rows)
            if self.calls == 2:
                return _FakeResult(self._expected_rows)
            raise AssertionError("unexpected execute call")

    monkeypatch.setattr("app.mcp.tools.data_query.get_building_info", fake_get_building_info)
    monkeypatch.setattr(mod, "_load_metadata", lambda: {
        "feature_cols": ["f1"],
        "target_cols": ["y_electricity_kwh_tplus6h"],
        "target_kpis": ["electricity_kwh"],
        "model_name": "test-model",
        "horizons_h": [6],
    })
    monkeypatch.setattr(mod, "_build_features_async", fake_build_features_async)
    monkeypatch.setattr(mod, "_predict_async", fake_predict_async)
    monkeypatch.setattr(mod, "_persist_predictions", fake_persist_predictions)

    result = await mod.forecast_building_kpi(
        building_id="Office",
        session=FakeForecastSession(),
    )

    assert isinstance(result, ForecastKPIOutput)
    assert result.persisted is True
    assert result.warnings_count == 1
    assert persisted_args["building_id"] == "Fox_office_Alice"
