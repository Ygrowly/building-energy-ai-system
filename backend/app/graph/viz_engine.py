"""
可视化引擎 —— 确定性后处理模块。

根据 Data Agent ReAct 链中的工具调用结果，自动决定是否生成可视化，
以及生成什么类型的可视化。LLM 不参与任何可视化决策。

规则：
  query_daily_energy_summary  →  多天=折线图, 单天=数值卡片
  compare_metric_across_buildings  →  柱状图
  calculate_system_cop  →  仪表盘
  query_energy_metrics  →  多于5条=折线图, 否则不画
  compare_time_periods  →  对比卡片
  detect_energy_anomalies / get_device_live_status  →  不画
  generate_report  →  透传（已有 component_type）
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
BUILDING_ZH: dict[str, str] = {
    "Education": "教学楼",
    "Office": "办公楼",
    "Public services": "公共楼",
}

METRIC_ZH: dict[str, str] = {
    "electricity_kwh": "用电量",
    "water_m3": "用水量",
    "hac_energy": "空调能耗",
    "sim_supply_temp_c": "供水温度",
    "sim_return_temp_c": "回水温度",
    "air_temp_c": "气温",
    "dew_temp_c": "露点温度",
    "humidity_rh_pct": "湿度",
}

UNIT_MAP: dict[str, str] = {
    "electricity_kwh": "kWh",
    "water_m3": "m³",
    "hac_energy": "kWh",
    "sim_supply_temp_c": "°C",
    "sim_return_temp_c": "°C",
    "air_temp_c": "°C",
    "dew_temp_c": "°C",
    "humidity_rh_pct": "%",
}

AGG_ZH: dict[str, str] = {
    "avg": "平均",
    "sum": "总",
    "max": "峰值",
    "min": "最低",
}


# ---------------------------------------------------------------------------
# 工具结果提取
# ---------------------------------------------------------------------------
def _extract_tool_triples(
    messages: list[BaseMessage],
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """
    从 ReAct 消息链中提取 (tool_name, tool_args, tool_result) 三元组。
    """
    # 建立 tool_call_id → args 的查找表
    call_args: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in getattr(msg, "tool_calls", None) or []:
                call_args[tc["id"]] = tc.get("args", {})

    triples: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        tool_name = getattr(msg, "name", "") or ""
        try:
            result = json.loads(msg.content)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(result, dict):
            continue
        # 跳过错误结果
        if "error" in result and "error_code" in result:
            continue
        args = call_args.get(getattr(msg, "tool_call_id", ""), {})
        triples.append((tool_name, args, result))

    return triples


# ---------------------------------------------------------------------------
# Artifact 构造辅助
# ---------------------------------------------------------------------------
def _make_artifact(
    component_type: str,
    widget: str,
    title: str,
    data_payload: dict[str, Any] | list[Any],
    source_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "artifact_id": f"artifact_{uuid.uuid4().hex[:8]}",
        "component_type": component_type,
        "widget": widget,
        "title": title,
        "data_payload": data_payload,
        "source_info": source_info,
    }


def _bname(building_id: str) -> str:
    """building_id → 中文名"""
    return BUILDING_ZH.get(building_id, building_id)


# ---------------------------------------------------------------------------
# 各工具的可视化规则
# ---------------------------------------------------------------------------
def _viz_daily_summary(
    calls: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """query_daily_energy_summary → LineChart / ValueCard"""
    # 过滤掉空结果
    valid_calls = [
        (args, result)
        for args, result in calls
        if result.get("records") and len(result["records"]) > 0
    ]
    if not valid_calls:
        return []

    # 多次调用（多楼对比） → 合并成多系列折线图
    if len(valid_calls) > 1:
        series = []
        for args, result in valid_calls:
            records = result["records"]
            if len(records) <= 1:
                continue
            bid = result.get("building_id") or args.get("building_id", "")
            series.append({
                "name": _bname(bid),
                "data": [r.get("total_electricity_kwh", 0) for r in records],
                "timestamps": [r.get("day", "") for r in records],
            })
        if series:
            return [_make_artifact(
                "LineChart", "line-chart",
                "楼宇每日用电趋势对比",
                {"series": series},
                {"source_view": "daily_energy_summary", "base_table": "energy_data"},
            )]

    # 单次调用
    args, result = valid_calls[0]
    records = result["records"]
    bid = result.get("building_id") or args.get("building_id", "")
    building = _bname(bid)

    if len(records) == 1:
        # 单天 → 数值卡片
        r = records[0]
        return [_make_artifact(
            "ValueCard", "value-card",
            f"{building} {r.get('day', '')} 用电量",
            {
                "mode": "simple",
                "value": r.get("total_electricity_kwh", 0),
                "unit": "kWh",
                "label": f"{building} {r.get('day', '')} 用电量",
            },
            {
                "building_id": building,
                "source_view": "daily_energy_summary",
                "date": r.get("day", ""),
            },
        )]

    # 多天 → 折线图
    return [_make_artifact(
        "LineChart", "line-chart",
        f"{building}每日用电趋势",
        {
            "series": [{
                "name": building,
                "data": [r.get("total_electricity_kwh", 0) for r in records],
                "timestamps": [r.get("day", "") for r in records],
            }],
        },
        {
            "building_id": building,
            "source_view": "daily_energy_summary",
            "base_table": "energy_data",
        },
    )]


def _viz_compare_buildings(
    calls: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """compare_metric_across_buildings → BarChart"""
    artifacts = []
    for args, result in calls:
        results_list = result.get("results", [])
        if len(results_list) <= 1:
            continue
        metric = result.get("metric", "")
        agg = result.get("aggregation", "sum")
        metric_zh = METRIC_ZH.get(metric, metric)
        agg_zh = AGG_ZH.get(agg, agg)
        unit = results_list[0].get("unit", "") if results_list else ""

        artifacts.append(_make_artifact(
            "BarChart", "bar-chart",
            f"楼宇{agg_zh}{metric_zh}对比",
            [{
                "label": _bname(r.get("building_type", "")),
                "value": r.get("aggregated_value", 0),
            } for r in results_list],
            {
                "source_table": "energy_data",
                "aggregation": agg,
                "unit": unit,
            },
        ))
    return artifacts


def _viz_cop(
    calls: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """calculate_system_cop → Gauge"""
    artifacts = []
    for args, result in calls:
        cop = result.get("cop_mean", 0)
        bid = result.get("building_id") or args.get("building_id", "")
        building = _bname(bid)
        # COP 仪表盘：低值=红（差）, 高值=绿（好），与默认色反转
        artifacts.append(_make_artifact(
            "Gauge", "gauge",
            f"{building} 空调系统 COP",
            {
                "value": round(cop, 2),
                "unit": "COP",
                "min": 0,
                "max": 6,
                "colorStops": [[0.4, "#f87171"], [0.7, "#fbbf24"], [1, "#4ade80"]],
            },
            {
                "building_id": building,
                "hvac_mode": result.get("hvac_mode", ""),
                "gb_baseline": result.get("gb_baseline", ""),
                "source_table": "energy_data",
            },
        ))
    return artifacts


# 用户问题中暗示需要可视化趋势的关键词
_TREND_KEYWORDS = (
    "趋势", "变化", "走势", "波动", "时段", "各时", "逐时", "逐小时",
    "小时", "曲线", "图", "画", "可视化", "对比", "分布",
)


def _wants_trend(user_question: str) -> bool:
    """用户问题是否明确要求看趋势/图表？"""
    return any(kw in user_question for kw in _TREND_KEYWORDS)


def _is_single_day(args: dict[str, Any], records: list[dict]) -> bool:
    """判断查询是否只涉及单天（不值得画时序图）。"""
    # 方法 1：从查询参数的 time_range 判断
    tr = args.get("time_range", {})
    if isinstance(tr, dict):
        start = str(tr.get("start", ""))[:10]
        end = str(tr.get("end", ""))[:10]
        if start and end and start == end:
            return True
    # 方法 2：从实际数据的首尾时间戳判断
    if records:
        first_ts = str(records[0].get("timestamp", ""))[:10]
        last_ts = str(records[-1].get("timestamp", ""))[:10]
        if first_ts and last_ts and first_ts == last_ts:
            return True
    return False


def _viz_energy_metrics(
    calls: list[tuple[dict[str, Any], dict[str, Any]]],
    user_question: str = "",
) -> list[dict[str, Any]]:
    """
    query_energy_metrics → LineChart。
    - 跨多天 → 始终画图
    - 单天 + 用户要看趋势 → 画图
    - 单天 + 用户只问数值 → 不画图
    """
    artifacts = []
    for args, result in calls:
        records = result.get("records", [])
        if len(records) <= 5:
            continue

        # 单天查询：只有用户明确要求看趋势时才画图
        if _is_single_day(args, records) and not _wants_trend(user_question):
            logger.debug("viz_engine: 跳过单天 query_energy_metrics（%d 条，非趋势问题）", len(records))
            continue

        bid = result.get("building_id") or args.get("building_id", "")
        building = _bname(bid)

        # 按 metric 分组（一次查询可能包含多个指标，单位不同不能混在一张图）
        single_day = _is_single_day(args, records)
        metric_groups: dict[str, list[dict]] = {}
        for r in records:
            m = r.get("metric", "unknown")
            metric_groups.setdefault(m, []).append(r)

        for metric, metric_records in metric_groups.items():
            if len(metric_records) <= 3:
                continue
            # ★ 按时间排序，确保 x 轴从 00:00 开始
            metric_records.sort(key=lambda r: str(r.get("timestamp", "")))

            unit = metric_records[0].get("unit", "") if metric_records else ""
            metric_zh = METRIC_ZH.get(metric, metric)

            # 提取并格式化时间标签
            # 单天 → "15:00"; 多天 → "04-15 15:00"
            def _fmt_ts(ts_raw: str) -> str:
                s = str(ts_raw).replace("T", " ")  # 兼容 ISO 格式
                if single_day:
                    return s[11:16] if len(s) >= 16 else s
                return s[5:16] if len(s) >= 16 else s

            timestamps = [_fmt_ts(r.get("timestamp", "")) for r in metric_records]

            artifacts.append(_make_artifact(
                "LineChart", "line-chart",
                f"{building} {metric_zh}趋势",
                {
                    "series": [{
                        "name": metric_zh,
                        "data": [r.get("value", 0) for r in metric_records],
                        "timestamps": timestamps,
                    }],
                },
                {
                    "building_id": building,
                    "source_table": "energy_data",
                    "data_points": len(metric_records),
                    "unit": unit,
                },
            ))
    return artifacts


def _viz_compare_periods(
    calls: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """compare_time_periods → ValueCard（对比模式）"""
    artifacts = []
    for args, result in calls:
        bid = result.get("building_id") or args.get("building_id", "")
        building = _bname(bid)
        metric = result.get("metric", "")
        metric_zh = METRIC_ZH.get(metric, metric)
        unit = result.get("unit", "")

        artifacts.append(_make_artifact(
            "ValueCard", "value-card",
            f"{building} {metric_zh}同环比",
            {
                "mode": "comparison",
                "period_a": {
                    "label": result.get("period_a_label", ""),
                    "value": result.get("period_a_value", 0),
                },
                "period_b": {
                    "label": result.get("period_b_label", ""),
                    "value": result.get("period_b_value", 0),
                },
                "delta": result.get("delta", 0),
                "delta_pct": result.get("delta_pct"),
                "unit": unit,
            },
            {
                "building_id": building,
                "source_table": "energy_data",
            },
        ))
    return artifacts


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def generate_viz_artifacts(
    new_messages: list[BaseMessage],
    user_question: str = "",
) -> list[dict[str, Any]]:
    """
    扫描 ReAct 链消息，根据工具调用结果自动生成可视化 artifact。

    user_question: 用户原始问题，用于判断是否需要趋势可视化（如"变化趋势"）。
    返回 0~N 个 artifact dict，可直接通过 SSE 推送给前端。
    """
    triples = _extract_tool_triples(new_messages)
    if not triples:
        return []

    # 按工具名分组
    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for tool_name, tool_args, tool_result in triples:
        groups.setdefault(tool_name, []).append((tool_args, tool_result))

    artifacts: list[dict[str, Any]] = []

    # 透传已有 component_type 的结果（generate_report 等）
    for _tool_name, calls in groups.items():
        for _args, result in calls:
            ct = result.get("component_type", "")
            if ct in ("ReportDownload", "WorkOrderCard"):
                artifacts.append(result)

    # 规则引擎
    if "query_daily_energy_summary" in groups:
        artifacts.extend(_viz_daily_summary(groups["query_daily_energy_summary"]))

    if "compare_metric_across_buildings" in groups:
        artifacts.extend(_viz_compare_buildings(groups["compare_metric_across_buildings"]))

    if "calculate_system_cop" in groups:
        artifacts.extend(_viz_cop(groups["calculate_system_cop"]))

    if "query_energy_metrics" in groups:
        artifacts.extend(_viz_energy_metrics(groups["query_energy_metrics"], user_question))

    if "compare_time_periods" in groups:
        artifacts.extend(_viz_compare_periods(groups["compare_time_periods"]))

    # detect_energy_anomalies / get_device_live_status / list_available_buildings → 不画

    logger.info("viz_engine 生成 %d 个 artifact", len(artifacts))
    return artifacts
