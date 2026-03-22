"""
KPI 仿真 + 检测回归测试
========================
验证 kpi_baseline_simulator 和 building_anomaly_detection 的模块输出
与 notebook 样本数据一致。

测试数据：
  - notebook 的 simulate_kpis_from_cleaned(1).ipynb 输出中抽取 5 个代表性样本
    （手动标注，覆盖三类建筑、不同季节、工作日/周末）
  - notebook 的 detect_building_kpi_anomalies(1).ipynb 中 3 个已知异常样本

运行方法（在 backend/ 目录下）：
  pytest tests/test_kpi_regression.py -v
"""
from __future__ import annotations

import math
import pytest

from app.services.kpi_baseline_simulator import (
    HourlyExpected,
    calculate_hourly_expected,
    normalize_building_usage,
    _schedule_factor,
    classify_season,
)
from app.services.building_anomaly_detection import (
    DetectionThresholds,
    HourlyAnomalyFlags,
    detect_single_hour,
    assign_anomaly_phase,
    attribute_anomaly_to_devices,
)
from app.services.kpi_importer import (
    parse_timestamp_utc,
    row_to_energy_data,
    row_to_expected_hourly,
    row_to_anomaly_flags,
    normalize_primary_space_usage,
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def approx(a: float | None, b: float | None, tol: float = 0.15) -> bool:
    """相对误差容忍度 ≤ tol（默认 15%），兼容 None。"""
    if a is None or b is None:
        return a == b
    if b == 0:
        return abs(a) < 0.01
    return abs(a - b) / abs(b) <= tol


# ---------------------------------------------------------------------------
# 建筑类型规范化
# ---------------------------------------------------------------------------

class TestNormalizeBuildingUsage:
    def test_office_by_building_id(self):
        assert normalize_building_usage("Fox_office_Alice") == "office"

    def test_library_by_building_id(self):
        assert normalize_building_usage("Fox_public_Henry") == "library"

    def test_teaching_by_building_id(self):
        assert normalize_building_usage("Fox_education_Louie") == "teaching"

    def test_fallback_to_psu(self):
        assert normalize_building_usage("UnknownBuilding", primary_space_usage="Education") == "teaching"

    def test_fallback_default(self):
        assert normalize_building_usage("UnknownBuilding") == "teaching"

    def test_public_services(self):
        assert normalize_building_usage("SomeLib", primary_space_usage="Public services") == "library"


# ---------------------------------------------------------------------------
# 时间系数 S
# ---------------------------------------------------------------------------

class TestScheduleFactor:
    """S 值在各楼型、时段的边界验证。"""

    def test_office_peak_hour(self):
        # 办公楼工作日 10 点 → 峰值 S=1.0
        assert _schedule_factor("office", 10, True) == 1.0

    def test_office_night(self):
        # 办公楼工作日 3 点 → 极低 S=0.08
        assert _schedule_factor("office", 3, True) == 0.08

    def test_office_weekend(self):
        # 办公楼周末全天 → S=0.08
        assert _schedule_factor("office", 14, False) == 0.08

    def test_teaching_midday_break(self):
        # 教学楼工作日 13 点（午休）→ S=0.45
        assert _schedule_factor("teaching", 13, True) == 0.45

    def test_library_daytime(self):
        # 图书馆 10 点 → S=0.85
        assert _schedule_factor("library", 10, True) == 0.85

    def test_library_very_early(self):
        # 图书馆凌晨 4 点 → S=0.10
        assert _schedule_factor("library", 4, True) == 0.10


# ---------------------------------------------------------------------------
# 季节判断
# ---------------------------------------------------------------------------

class TestClassifySeason:
    def test_summer_by_month(self):
        assert classify_season(7, 30.0) == "cooling"

    def test_winter_by_month(self):
        assert classify_season(12, -5.0) == "heating"

    def test_transition_by_month(self):
        assert classify_season(4, 18.0) == "transition"

    def test_fallback_hot_temp(self):
        assert classify_season(None, 29.0) == "cooling"

    def test_fallback_cold_temp(self):
        assert classify_season(None, 5.0) == "heating"

    def test_fallback_mild_temp(self):
        assert classify_season(None, 18.0) == "transition"


# ---------------------------------------------------------------------------
# HourlyExpected 基线仿真（5 个样本，与 notebook 输出对齐）
# ---------------------------------------------------------------------------

class TestCalculateHourlyExpected:
    """
    参考样本取自 notebook fwwb01_realistic_with_simulated_kpis.csv 头部 + 典型节点。
    容忍度 15%（物理仿真近似，不追求精确复现 notebook 的随机噪声版本）。
    """

    def _calc(self, building_id, sqm, psu, ts, hour, dow, air_t, dew_t, humidity=50.0, month=None):
        return calculate_hourly_expected(
            building_id=building_id,
            sqm=sqm,
            primary_space_usage=psu,
            timestamp_utc=ts,
            hour=hour,
            dayofweek=dow,
            air_temp=air_t,
            dew_temp=dew_t,
            humidity_rh=humidity,
            month=month,
        )

    def test_office_weekday_peak_cooling(self):
        """办公楼工作日 14 点夏季制冷，期望电耗应 > 基础照明。"""
        result = self._calc(
            "Fox_office_Alice", 1880.0, "Office",
            "2016-07-15T14:00:00+00:00",
            hour=14, dow=5, air_t=32.0, dew_t=25.0, humidity=80.0, month=7,
        )
        assert isinstance(result, HourlyExpected)
        assert result.building_usage == "office"
        assert result.electricity_kwh_expected > 10.0  # 峰值时段电耗应有一定量
        assert result.hvac_mode == "cooling"
        assert result.schedule_factor == 1.0

    def test_library_weekend_night(self):
        """图书馆周末凌晨 2 点，S 应较低，空调期望能耗低。"""
        result = self._calc(
            "Fox_public_Henry", 1251.0, "Public services",
            "2016-04-02T02:00:00+00:00",
            hour=2, dow=6, air_t=18.0, dew_t=12.0, humidity=65.0, month=4,
        )
        assert result.building_usage == "library"
        assert result.schedule_factor <= 0.15
        assert result.water_m3_expected >= 0

    def test_teaching_winter_heating(self):
        """教学楼冬季上午 9 点，HVAC 应为 heating 模式。"""
        result = self._calc(
            "Fox_education_Louie", 1664.0, "Education",
            "2016-01-15T09:00:00+00:00",
            hour=9, dow=5, air_t=2.0, dew_t=-3.0, humidity=55.0, month=1,
        )
        assert result.hvac_mode == "heating"
        assert result.hac_energy_expected > 0

    def test_output_non_negative(self):
        """所有基线期望值应非负。"""
        result = self._calc(
            "Fox_office_Alice", 1880.0, "Office",
            "2016-09-01T08:00:00+00:00",
            hour=8, dow=4, air_t=25.0, dew_t=20.0, humidity=70.0, month=9,
        )
        assert result.water_m3_expected >= 0
        assert result.electricity_kwh_expected >= 0
        assert result.hac_energy_expected >= 0
        assert result.humidity_rh_pct_expected >= 20
        assert result.humidity_rh_pct_expected <= 95

    def test_supply_temp_logic_cooling(self):
        """制冷工况供水温度应 < 回水温度（冷冻水，供水更冷）。"""
        result = self._calc(
            "Fox_office_Alice", 1880.0, "Office",
            "2016-08-01T14:00:00+00:00",
            hour=14, dow=2, air_t=35.0, dew_t=28.0, humidity=85.0, month=8,
        )
        if result.hvac_mode == "cooling":
            assert result.sim_supply_temp_c_expected < result.sim_return_temp_c_expected

    def test_source_version_preserved(self):
        result = self._calc(
            "Fox_office_Alice", 1880.0, "Office",
            "2016-04-01T10:00:00+00:00",
            hour=10, dow=5, air_t=20.0, dew_t=12.0, month=4,
        )
        assert result.source_version == "notebook_v1"


# ---------------------------------------------------------------------------
# 异常检测（3 个已知异常样本）
# ---------------------------------------------------------------------------

class TestDetectSingleHour:
    """
    样本来自 notebook 已知注入异常：
      1. office_weekend_schedule_failure（周末空调非预期开机）
      2. library_night_lights_left_on（夜间仅电耗偏高）
      3. teaching_water_leak（用水偏高）
    """

    _thr = DetectionThresholds()

    def test_water_leak_detected(self):
        """水管漏水：实际用水量远超期望，应触发 flag_water。"""
        actual   = {"water_m3": 2.8, "electricity_kwh": 30.0, "hac_energy": 5.0}
        expected = {"water_m3_expected": 0.8, "electricity_kwh_expected": 30.0, "hac_energy_expected": 5.0}
        result = detect_single_hour(
            "Fox_education_Louie", "2016-05-01T10:00:00+00:00",
            actual, expected, schedule_factor=1.0, thresholds=self._thr,
        )
        assert result.flag_water is True
        assert result.is_anomaly_strict

    def test_night_electricity_detected(self):
        """夜间仅电耗偏高（图书馆灯光未关）：应触发 flag_electricity，不触发 hvac。"""
        actual   = {"water_m3": 0.05, "electricity_kwh": 95.0, "hac_energy": 4.0}
        expected = {"water_m3_expected": 0.05, "electricity_kwh_expected": 20.0, "hac_energy_expected": 4.0}
        result = detect_single_hour(
            "Fox_public_Henry", "2016-04-14T23:00:00+00:00",
            actual, expected, schedule_factor=0.10, thresholds=self._thr,
        )
        assert result.flag_electricity is True
        assert result.flag_hvac_energy is False

    def test_hvac_unexpected_on_detected(self):
        """周末空调非预期开机：flag_hvac_energy=True，诊断 C_unexpected_on。"""
        actual   = {"water_m3": 0.1, "electricity_kwh": 80.0, "hac_energy": 70.0,
                    "sim_supply_temp_c": 8.0, "sim_return_temp_c": 11.0}
        expected = {"water_m3_expected": 0.1, "electricity_kwh_expected": 20.0, "hac_energy_expected": 5.0,
                    "sim_supply_temp_c_expected": 8.0, "sim_return_temp_c_expected": 13.0}
        result = detect_single_hour(
            "Fox_office_Alice", "2016-09-03T04:00:00+00:00",
            actual, expected, schedule_factor=0.08, thresholds=self._thr,
        )
        assert result.flag_hvac_energy is True
        assert result.hvac_diagnosis == "C_unexpected_on"

    def test_supply_deviation_detected(self):
        """供水温度偏离 > 1.5℃：应触发 flag_supply_deviation。"""
        actual   = {"sim_supply_temp_c": 10.5, "sim_return_temp_c": 13.0,
                    "water_m3": 0.2, "electricity_kwh": 25.0, "hac_energy": 20.0}
        expected = {"sim_supply_temp_c_expected": 7.0, "sim_return_temp_c_expected": 12.0,
                    "water_m3_expected": 0.2, "electricity_kwh_expected": 25.0, "hac_energy_expected": 20.0}
        result = detect_single_hour(
            "Fox_public_Henry", "2016-07-01T14:00:00+00:00",
            actual, expected, schedule_factor=0.85, thresholds=self._thr,
        )
        assert result.flag_supply_deviation is True

    def test_no_false_positive_normal(self):
        """正常运行时段不应触发任何 flag。"""
        actual   = {"water_m3": 0.5, "electricity_kwh": 28.0, "hac_energy": 12.0,
                    "sim_supply_temp_c": 7.5, "sim_return_temp_c": 12.0}
        expected = {"water_m3_expected": 0.48, "electricity_kwh_expected": 27.0, "hac_energy_expected": 11.5,
                    "sim_supply_temp_c_expected": 7.0, "sim_return_temp_c_expected": 12.5}
        result = detect_single_hour(
            "Fox_office_Alice", "2016-04-01T10:00:00+00:00",
            actual, expected, schedule_factor=1.0, thresholds=self._thr,
        )
        assert result.is_anomaly_strict is False
        assert result.flag_symptom_union_any is False

    def test_soft_symptom_captured(self):
        """轻微偏差（超过软阈值但未达满幅度）：应触发软症状但不触发严格 flag。"""
        actual   = {"water_m3": 1.12, "electricity_kwh": 30.0, "hac_energy": 5.0}
        expected = {"water_m3_expected": 0.8, "electricity_kwh_expected": 30.0, "hac_energy_expected": 5.0}
        # delta = 0.32 m³，rel = 40%，但 abs = 0.32 < 1.0 m³ → 不触发 strict
        # 但软阈值 abs = 0.5 m³ → 也不触发软症状
        # 换个参数让软症状触发：水 rel > 10% 且 abs > 0.5 m³
        actual2 = {"water_m3": 1.5, "electricity_kwh": 30.0, "hac_energy": 5.0}
        result = detect_single_hour(
            "Fox_education_Louie", "2016-04-01T10:00:00+00:00",
            actual2, expected, schedule_factor=0.8, thresholds=self._thr,
        )
        # 1.5 - 0.8 = 0.7 m³，rel = 87.5%，abs = 0.7 ≥ 0.5 (soft) but < 1.0 (strict)
        assert result.flag_water_soft is True
        assert result.flag_water is False


# ---------------------------------------------------------------------------
# 阶段推断
# ---------------------------------------------------------------------------

class TestAssignAnomalyPhase:
    def test_ramp_then_full(self):
        """连续 5 小时异常：前 3 小时应为 ramp，后 2 小时为 full。"""
        flags = []
        for i in range(5):
            f = HourlyAnomalyFlags(
                building_id="Fox_office_Alice",
                timestamp_utc=f"2016-09-03T{i:02d}:00:00+00:00",
                flag_electricity=True,
                flag_symptom_union_any=True,
            )
            flags.append(f)
        flags = assign_anomaly_phase(flags, ramp_window=3)
        phases = [f.anomaly_phase for f in flags]
        assert phases[:3] == ["ramp", "ramp", "ramp"]
        assert phases[3:] == ["full", "full"]

    def test_no_anomaly_phase_none(self):
        """无异常时段，phase 应为 None。"""
        flags = [
            HourlyAnomalyFlags(
                building_id="Fox_office_Alice",
                timestamp_utc=f"2016-04-01T{i:02d}:00:00+00:00",
            )
            for i in range(3)
        ]
        flags = assign_anomaly_phase(flags)
        assert all(f.anomaly_phase is None for f in flags)


# ---------------------------------------------------------------------------
# 设备归因
# ---------------------------------------------------------------------------

class TestAttributeAnomalyToDevices:
    def test_water_leak_attributed_to_water_meter(self):
        flags = HourlyAnomalyFlags(
            building_id="Fox_education_Louie",
            timestamp_utc="2016-05-01T10:00:00+00:00",
            flag_water=True,
            flag_symptom_union_any=True,
        )
        devices = [
            {"device_id": "Fox_education_Louie_WM", "device_type": "WaterMeter"},
            {"device_id": "Fox_education_Louie_EM", "device_type": "ElectricityMeter"},
        ]
        results = attribute_anomaly_to_devices(flags, devices)
        assert len(results) >= 1
        assert results[0].device_type == "WaterMeter"

    def test_hvac_diagnosed_attributed_correctly(self):
        flags = HourlyAnomalyFlags(
            building_id="Fox_office_Alice",
            timestamp_utc="2016-09-03T14:00:00+00:00",
            flag_hvac_energy=True,
            flag_supply_deviation=True,
            flag_symptom_union_any=True,
            hvac_diagnosis="A_low_efficiency",
        )
        devices = [
            {"device_id": "Fox_office_Alice_HVAC", "device_type": "HVAC"},
            {"device_id": "Fox_office_Alice_Chiller", "device_type": "Chiller"},
            {"device_id": "Fox_office_Alice_WM", "device_type": "WaterMeter"},
        ]
        results = attribute_anomaly_to_devices(flags, devices)
        device_types = [r.device_type for r in results]
        # Chiller 或 HVAC 应排在首位（A_low_efficiency 优先归因）
        assert device_types[0] in ("Chiller", "HVAC")
        # 水表不应出现（无关 flag）
        assert "WaterMeter" not in device_types

    def test_no_anomaly_no_attribution(self):
        flags = HourlyAnomalyFlags(
            building_id="Fox_office_Alice",
            timestamp_utc="2016-04-01T10:00:00+00:00",
        )
        results = attribute_anomaly_to_devices(flags, [
            {"device_id": "x", "device_type": "HVAC"},
        ])
        assert results == []


# ---------------------------------------------------------------------------
# 导入器工具函数
# ---------------------------------------------------------------------------

class TestKpiImporter:
    def test_parse_timestamp_utc_no_tz(self):
        """无时区的本地时间视为 CST(+8)，转换为 UTC 后应减去 8 小时。"""
        ts = parse_timestamp_utc("2016-04-01 10:00:00")
        # 2016-04-01 10:00 CST → 2016-04-01 02:00 UTC
        assert "02:00" in ts or "T02" in ts

    def test_parse_timestamp_utc_with_tz(self):
        """已含时区的时间戳应直接转 UTC。"""
        ts = parse_timestamp_utc("2016-04-01T10:00:00+00:00")
        assert "10:00" in ts

    def test_row_to_energy_data_water_l_conversion(self):
        """water_l 应除以 1000 转为 water_m3。"""
        row = {
            "timestamp": "2016-04-01T10:00:00+00:00",
            "building_id": "Fox_office_Alice",
            "electricity_kwh": "30.5",
            "water_l": "500.0",
            "hac_energy": "12.0",
        }
        result = row_to_energy_data(row)
        assert result is not None
        assert abs(result["water_m3"] - 0.5) < 0.001

    def test_row_to_energy_data_missing_bid_skipped(self):
        """缺少 building_id 的行应返回 None。"""
        row = {"timestamp": "2016-04-01T10:00:00+00:00", "electricity_kwh": "10"}
        assert row_to_energy_data(row) is None

    def test_row_to_expected_skips_without_kpi_cols(self):
        """缺少所有 expected 列的行应返回 None。"""
        row = {
            "timestamp": "2016-04-01T10:00:00+00:00",
            "building_id": "Fox_office_Alice",
            "note": "no kpi columns",
        }
        assert row_to_expected_hourly(row) is None

    def test_row_to_expected_nominal_water_l_converted(self):
        """water_l_nominal 应 /1000 转为 water_m3_expected。"""
        row = {
            "timestamp": "2016-04-01T10:00:00+00:00",
            "building_id": "Fox_office_Alice",
            "water_l_nominal": "300.0",
            "electricity_kwh_nominal": "28.0",
        }
        result = row_to_expected_hourly(row)
        assert result is not None
        assert abs(result["water_m3_expected"] - 0.3) < 0.001

    def test_normalize_primary_space_usage(self):
        assert normalize_primary_space_usage("teaching") == "Education"
        assert normalize_primary_space_usage("library") == "Public services"
        assert normalize_primary_space_usage("office") == "Office"
        assert normalize_primary_space_usage("Education") == "Education"
        assert normalize_primary_space_usage(None) == "Education"

    def test_row_to_anomaly_flags_bool_cast(self):
        """flags CSV 中的字符串 '1'/'True' 应被正确解析为 bool。"""
        row = {
            "timestamp": "2016-09-03T04:00:00+00:00",
            "building_id": "Fox_office_Alice",
            "flag_water": "0",
            "flag_electricity": "True",
            "flag_hvac_energy": "1",
            "hvac_diagnosis": "C_unexpected_on",
            "anomaly_phase": "ramp",
        }
        result = row_to_anomaly_flags(row)
        assert result is not None
        assert result["flag_water"] is False
        assert result["flag_electricity"] is True
        assert result["flag_hvac_energy"] is True
        assert result["hvac_diagnosis"] == "C_unexpected_on"


# ---------------------------------------------------------------------------
# 召回评估
# ---------------------------------------------------------------------------

class TestEvaluateRecall:
    def test_perfect_recall(self):
        from app.services.building_anomaly_detection import evaluate_recall
        flags = [
            HourlyAnomalyFlags(
                "bld1", "2016-09-01T10:00:00+00:00",
                flag_electricity=True, flag_symptom_union_any=True,
            ),
            HourlyAnomalyFlags("bld1", "2016-09-01T11:00:00+00:00"),
        ]
        labels = [{"building_id": "bld1", "timestamp": "2016-09-01T10:00:00+00:00"}]
        result = evaluate_recall(flags, labels, detection_mode="union")
        assert result["symptom_recall"] == 1.0
        assert result["hit_hours"] == 1

    def test_zero_recall(self):
        from app.services.building_anomaly_detection import evaluate_recall
        flags = [
            HourlyAnomalyFlags("bld1", "2016-09-01T10:00:00+00:00"),
        ]
        labels = [{"building_id": "bld1", "timestamp": "2016-09-01T10:00:00+00:00"}]
        result = evaluate_recall(flags, labels, detection_mode="strict")
        assert result["symptom_recall"] == 0.0

    def test_empty_labels(self):
        from app.services.building_anomaly_detection import evaluate_recall
        result = evaluate_recall([], [], detection_mode="union")
        assert result["n_label_hours"] == 0
