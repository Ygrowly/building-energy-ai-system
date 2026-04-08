"""
可视化引擎 —— 确定性后处理模块 v2。

改进点（相对 v1）：
  1. 跨调用智能合并：同指标 × 多楼 → 合并为一张多系列图（Layer 1）
  2. 多指标完整提取：daily_summary 同时生成用电/用水/空调图表（Layer 2）
  3. 用户意图驱动筛选：解析用户问题关心的指标，过滤无关图表（Layer 3）
  4. chart_manifest 构建：为 Synthesis LLM 提供精确的图表清单（Layer 4）

规则：
  query_daily_energy_summary  →  每个指标独立生成折线图（多楼合并为多系列）
  compare_metric_across_buildings  →  柱状图
  calculate_system_cop  →  仪表盘
  query_energy_metrics  →  同指标多楼合并为多系列折线图
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

from app.core.buildings import get_building_label

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
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

METRIC_ANCHOR: dict[str, str] = {
    "electricity_kwh": "用电",
    "water_m3": "用水",
    "hac_energy": "空调",
    "gas_m3": "燃气",
    "sim_supply_temp_c": "供水温度",
    "sim_return_temp_c": "回水温度",
    "air_temp_c": "气温",
    "dew_temp_c": "露点",
    "humidity_rh_pct": "湿度",
    "cop": "COP",
    "total_electricity_kwh": "用电",
    "total_water_m3": "用水",
    "total_hac_energy": "空调",
}

GRAN_LABEL: dict[str, str] = {
    "day": "每日",
    "week": "每周",
    "month": "每月",
}

GRAN_UNIT: dict[str, str] = {
    "day": "天",
    "week": "周",
    "month": "月",
}


def _detect_granularity(args: dict[str, Any], result: dict[str, Any]) -> str:
    """从工具返回结果或参数中推断实际粒度。"""
    if result.get("granularity"):
        return result["granularity"]
    return args.get("granularity", "day")


def _format_x_labels(timestamps: list[str], gran: str) -> list[str]:
    """根据粒度格式化 X 轴标签。"""
    if not timestamps:
        return timestamps
    if gran == "month":
        # "2026-01" or "2026-01-01 ..." -> "2026-01"
        return [t[:7] if len(t) >= 7 else t for t in timestamps]
    elif gran == "week":
        # "2026-01-06" -> "01-06"
        return [t[5:10] if len(t) >= 10 else t for t in timestamps]
    else:
        # day: "2026-01-15" -> "01-15"
        return [t[5:10] if len(t) >= 10 else t for t in timestamps]


# daily_summary 记录中可提取为图表的指标字段
DAILY_SUMMARY_METRICS: dict[str, tuple[str, str, str]] = {
    "total_electricity_kwh": ("用电量", "kWh", "electricity_kwh"),
    "total_water_m3":        ("用水量", "m³",  "water_m3"),
    "total_hac_energy":      ("空调能耗", "kWh", "hac_energy"),
}

# 用户意图 → 相关指标映射
INTENT_METRIC_MAP: dict[str, list[str]] = {
    "用电": ["electricity_kwh", "total_electricity_kwh"],
    "电量": ["electricity_kwh", "total_electricity_kwh"],
    "用水": ["water_m3", "total_water_m3"],
    "水量": ["water_m3", "total_water_m3"],
    "空调": ["hac_energy", "total_hac_energy"],
    "暖通": ["hac_energy", "total_hac_energy"],
    "温度": ["air_temp_c", "sim_supply_temp_c", "sim_return_temp_c"],
    "湿度": ["humidity_rh_pct"],
    "COP":  ["cop"],
    "能效": ["cop"],
}


# ---------------------------------------------------------------------------
# 工具结果提取
# ---------------------------------------------------------------------------
def _extract_tool_triples(
    messages: list[BaseMessage],
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """从 ReAct 消息链中提取 (tool_name, tool_args, tool_result) 三元组。"""
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
    anchor: str | None = None,
) -> dict[str, Any]:
    art: dict[str, Any] = {
        "artifact_id": f"artifact_{uuid.uuid4().hex[:8]}",
        "component_type": component_type,
        "widget": widget,
        "title": title,
        "data_payload": data_payload,
        "source_info": source_info,
    }
    if anchor:
        art["anchor"] = anchor
    return art


def _bname(building_id: str) -> str:
    """building_id → 中文名"""
    return get_building_label(building_id, building_id)


# ---------------------------------------------------------------------------
# Layer 3: 用户意图解析
# ---------------------------------------------------------------------------
def _extract_user_metrics(question: str) -> set[str] | None:
    """
    从用户问题中提取关心的指标集合。
    返回 None 表示不限制（用户未明确提及指标）。
    """
    found: set[str] = set()
    for keyword, metrics in INTENT_METRIC_MAP.items():
        if keyword in question:
            found.update(metrics)
    return found if found else None


def _artifact_matches_metrics(artifact: dict[str, Any], user_metrics: set[str]) -> bool:
    """检查 artifact 的 anchor 是否与用户关心的指标匹配。"""
    anchor = artifact.get("anchor", "")
    if not anchor:
        return True
    for metric, metric_anchor in METRIC_ANCHOR.items():
        if metric_anchor == anchor and metric in user_metrics:
            return True
    return False


# ---------------------------------------------------------------------------
# 趋势判断辅助
# ---------------------------------------------------------------------------
_TREND_KEYWORDS = (
    "趋势", "变化", "走势", "波动", "时段", "各时", "逐时", "逐小时",
    "小时", "曲线", "图", "画", "可视化", "对比", "分布",
)


def _wants_trend(user_question: str) -> bool:
    """用户问题是否明确要求看趋势/图表？"""
    return any(kw in user_question for kw in _TREND_KEYWORDS)


def _is_single_day(args: dict[str, Any], records: list[dict]) -> bool:
    """判断查询是否只涉及单天。"""
    tr = args.get("time_range", {})
    if isinstance(tr, dict):
        start = str(tr.get("start", ""))[:10]
        end = str(tr.get("end", ""))[:10]
        if start and end and start == end:
            return True
    if records:
        first_ts = str(records[0].get("timestamp", ""))[:10]
        last_ts = str(records[-1].get("timestamp", ""))[:10]
        if first_ts and last_ts and first_ts == last_ts:
            return True
    return False


# ---------------------------------------------------------------------------
# 各工具的可视化规则（Layer 1 + 2 改造）
# ---------------------------------------------------------------------------
def _viz_daily_summary(
    calls: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """
    query_daily_energy_summary → 自适应图表生成。
    - 多栋楼同一指标 → 合并为多系列图（Layer 1）
    - 提取 electricity + water + hac_energy 三个指标（Layer 2）
    - 根据粒度自适应标题（每日/每周/每月）
    - 根据数据点数量自适应图表类型（LineChart/BarChart/ValueCard）
    """
    valid_calls = [
        (args, result)
        for args, result in calls
        if result.get("records") and len(result["records"]) > 0
    ]
    if not valid_calls:
        return []

    # 从第一个有效调用推断粒度（同一批查询粒度一致）
    gran = _detect_granularity(valid_calls[0][0], valid_calls[0][1])
    gran_zh = GRAN_LABEL.get(gran, "每日")

    artifacts: list[dict[str, Any]] = []

    for field, (label, unit, anchor_key) in DAILY_SUMMARY_METRICS.items():
        if len(valid_calls) > 1:
            # 多楼对比
            series = []
            for args, result in valid_calls:
                records = result["records"]
                if len(records) <= 1:
                    continue
                values = [r.get(field, 0) for r in records]
                if all(v == 0 for v in values):
                    continue
                bid = result.get("building_id") or args.get("building_id", "")
                raw_ts = [r.get("day", "") for r in records]
                series.append({
                    "name": _bname(bid),
                    "data": values,
                    "timestamps": _format_x_labels(raw_ts, gran),
                })
            if not series:
                continue
            max_points = max(len(s["data"]) for s in series)
            chart_type, widget = _pick_chart_type(max_points)
            artifacts.append(_make_artifact(
                chart_type, widget,
                f"楼宇{gran_zh}{label}趋势对比",
                {"series": series} if chart_type == "LineChart" else _series_to_bar(series, label, unit),
                {"source_view": "daily_energy_summary", "base_table": "energy_data", "unit": unit},
                anchor=METRIC_ANCHOR.get(anchor_key),
            ))
        else:
            # 单栋楼
            args, result = valid_calls[0]
            records = result["records"]
            bid = result.get("building_id") or args.get("building_id", "")
            building = _bname(bid)
            values = [r.get(field, 0) for r in records]

            if all(v == 0 for v in values):
                continue

            n = len(records)
            if n <= 2:
                for r in records:
                    artifacts.append(_make_artifact(
                        "ValueCard", "value-card",
                        f"{building} {r.get('day', '')} {label}",
                        {
                            "mode": "simple",
                            "value": r.get(field, 0),
                            "unit": unit,
                            "label": f"{building} {r.get('day', '')} {label}",
                        },
                        {"building_id": building, "source_view": "daily_energy_summary", "date": r.get("day", "")},
                        anchor=METRIC_ANCHOR.get(anchor_key),
                    ))
            else:
                raw_ts = [r.get("day", "") for r in records]
                formatted_ts = _format_x_labels(raw_ts, gran)
                chart_type, widget = _pick_chart_type(n)
                if chart_type == "LineChart":
                    artifacts.append(_make_artifact(
                        "LineChart", "line-chart",
                        f"{building}{gran_zh}{label}趋势",
                        {
                            "series": [{
                                "name": building,
                                "data": values,
                                "timestamps": formatted_ts,
                            }],
                        },
                        {"building_id": building, "source_view": "daily_energy_summary", "unit": unit},
                        anchor=METRIC_ANCHOR.get(anchor_key),
                    ))
                else:
                    artifacts.append(_make_artifact(
                        "BarChart", "bar-chart",
                        f"{building}{gran_zh}{label}",
                        [{"label": t, "value": v} for t, v in zip(formatted_ts, values)],
                        {"building_id": building, "source_view": "daily_energy_summary", "unit": unit},
                        anchor=METRIC_ANCHOR.get(anchor_key),
                    ))

    return artifacts


def _pick_chart_type(n_points: int) -> tuple[str, str]:
    """根据数据点数量选择最合适的图表类型。"""
    if n_points >= 7:
        return "LineChart", "line-chart"
    return "BarChart", "bar-chart"


def _series_to_bar(
    series: list[dict[str, Any]], label: str, unit: str,
) -> list[dict[str, Any]]:
    """将多系列数据转为柱状图格式（用每个楼宇的总值）。"""
    return [
        {"label": s["name"], "value": sum(s["data"])}
        for s in series
    ]


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
            anchor=METRIC_ANCHOR.get(metric),
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
            anchor=METRIC_ANCHOR.get("cop"),
        ))
    return artifacts


def _viz_energy_metrics(
    calls: list[tuple[dict[str, Any], dict[str, Any]]],
    user_question: str = "",
) -> list[dict[str, Any]]:
    """
    query_energy_metrics → LineChart（Layer 1 跨调用合并）。

    核心改进：按 metric 分组，同一 metric 多个楼宇 → 合并为一张多系列图。
    """
    # Phase 1: 提取所有 (building, metric, records) 并按 metric 分组
    MetricGroup = dict[str, list[tuple[str, list[dict]]]]
    metric_building_groups: MetricGroup = {}

    for args, result in calls:
        records = result.get("records", [])
        if len(records) <= 5:
            continue

        single_day = _is_single_day(args, records)
        if single_day and not _wants_trend(user_question):
            logger.debug("viz_engine: 跳过单天 query_energy_metrics（%d 条，非趋势问题）", len(records))
            continue

        bid = result.get("building_id") or args.get("building_id", "")

        # 按 metric 分组（一次查询可能包含多个指标）
        per_metric: dict[str, list[dict]] = {}
        for r in records:
            m = r.get("metric", "unknown")
            per_metric.setdefault(m, []).append(r)

        for metric, metric_records in per_metric.items():
            if len(metric_records) <= 3:
                continue
            metric_records.sort(key=lambda r: str(r.get("timestamp", "")))
            metric_building_groups.setdefault(metric, []).append((bid, metric_records))

    # Phase 2: 每个 metric 组生成一张图（多楼 → 多系列）
    artifacts: list[dict[str, Any]] = []

    for metric, buildings in metric_building_groups.items():
        metric_zh = METRIC_ZH.get(metric, metric)
        unit = ""
        single_day_any = False

        if len(buildings) > 1:
            # 多楼同指标 → 多系列对比折线图
            series = []
            for bid, metric_records in buildings:
                if not unit:
                    unit = metric_records[0].get("unit", "") if metric_records else ""
                single_day_any = single_day_any or _is_single_day({}, metric_records)

                def _fmt_ts(ts_raw: str, is_single: bool) -> str:
                    s = str(ts_raw).replace("T", " ")
                    if is_single:
                        return s[11:16] if len(s) >= 16 else s
                    return s[5:16] if len(s) >= 16 else s

                timestamps = [_fmt_ts(r.get("timestamp", ""), single_day_any) for r in metric_records]
                series.append({
                    "name": _bname(bid),
                    "data": [r.get("value", 0) for r in metric_records],
                    "timestamps": timestamps,
                })

            artifacts.append(_make_artifact(
                "LineChart", "line-chart",
                f"楼宇{metric_zh}趋势对比",
                {"series": series},
                {"source_table": "energy_data", "unit": unit},
                anchor=METRIC_ANCHOR.get(metric),
            ))
        else:
            # 单楼 → 单系列折线图
            bid, metric_records = buildings[0]
            building = _bname(bid)
            unit = metric_records[0].get("unit", "") if metric_records else ""
            single_day = _is_single_day({}, metric_records)

            def _fmt_ts(ts_raw: str) -> str:
                s = str(ts_raw).replace("T", " ")
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
                anchor=METRIC_ANCHOR.get(metric),
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
            anchor=METRIC_ANCHOR.get(metric),
        ))
    return artifacts


# ---------------------------------------------------------------------------
# chart_manifest 构建（Layer 4）
# ---------------------------------------------------------------------------
WIDGET_ZH: dict[str, str] = {
    "line-chart": "折线图",
    "bar-chart": "柱状图",
    "gauge": "仪表盘",
    "value-card": "数值卡片",
}


def build_chart_manifest(artifacts: list[dict[str, Any]]) -> str:
    """
    将 artifact 列表转化为人类可读的图表清单，供 Synthesis LLM 精确引用。
    """
    chart_artifacts = [
        a for a in artifacts
        if a.get("component_type") not in ("ReportDownload", "WorkOrderCard")
        and a.get("artifact_id")
    ]
    if not chart_artifacts:
        return "本次查询未生成可视化图表。请仅使用文字和数据进行分析。"

    lines = [f"已生成 {len(chart_artifacts)} 张图表："]
    for i, art in enumerate(chart_artifacts, 1):
        title = art.get("title", "未命名")
        widget = art.get("widget", "")
        widget_zh = WIDGET_ZH.get(widget, widget)
        anchor = art.get("anchor", "")

        # 提取 series 信息
        series_names = ""
        dp = art.get("data_payload", {})
        if isinstance(dp, dict) and "series" in dp:
            names = [s.get("name", "") for s in dp["series"] if s.get("name")]
            if names:
                series_names = "，".join(names)

        desc = f"{i}. 「{title}」（{widget_zh}"
        if series_names:
            desc += f"，{series_names}"
        desc += "）"
        if anchor:
            desc += f" — 锚点关键词：{anchor}"
        lines.append(desc)

    lines.append("")
    lines.append("图表会自动嵌入到包含其「锚点关键词」的最后一个段落之后。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 数据摘要提取（供 Synthesis LLM 使用）
# ---------------------------------------------------------------------------
def build_data_summary(messages: list[BaseMessage]) -> str:
    """从 ReAct 消息链中程序化提取工具调用结果的简要摘要。"""
    triples = _extract_tool_triples(messages)
    if not triples:
        return "（未执行工具调用）"

    summaries: list[str] = []
    for tool_name, args, result in triples:
        if tool_name == "query_daily_energy_summary":
            bid = result.get("building_id", "")
            records = result.get("records", [])
            if records:
                gran = result.get("granularity", args.get("granularity", "day"))
                gran_unit = GRAN_UNIT.get(gran, "条")
                date_range_days = result.get("date_range_days", 0)

                total_elec = sum(r.get("total_electricity_kwh", 0) for r in records)
                total_water = sum(r.get("total_water_m3", 0) for r in records)
                total_hac = sum(r.get("total_hac_energy", 0) for r in records)
                parts = [f"{len(records)}条{gran_unit}级数据"]
                if date_range_days > 0:
                    parts.append(f"跨度{date_range_days}天")
                if total_elec > 0:
                    parts.append(f"总用电{total_elec:.0f}kWh")
                if total_water > 0:
                    parts.append(f"总用水{total_water:.1f}m³")
                if total_hac > 0:
                    parts.append(f"空调总能耗{total_hac:.0f}kWh")
                summaries.append(f"  {_bname(bid)}: {', '.join(parts)}")

        elif tool_name == "query_energy_metrics":
            bid = result.get("building_id", "")
            records = result.get("records", [])
            metrics: dict[str, list[float]] = {}
            for r in records:
                m = r.get("metric", "")
                metrics.setdefault(m, []).append(r.get("value", 0))
            for m, values in metrics.items():
                avg_val = sum(values) / len(values) if values else 0
                max_val = max(values) if values else 0
                min_val = min(values) if values else 0
                summaries.append(
                    f"  {_bname(bid)} {METRIC_ZH.get(m, m)}: "
                    f"{len(values)}条, 均值{avg_val:.1f}, 峰值{max_val:.1f}, 谷值{min_val:.1f} {UNIT_MAP.get(m, '')}"
                )

        elif tool_name == "compare_metric_across_buildings":
            metric = result.get("metric", "")
            results_list = result.get("results", [])
            for r in results_list:
                bt = r.get("building_type", "")
                val = r.get("aggregated_value", 0)
                unit = r.get("unit", "")
                summaries.append(f"  {_bname(bt)} {METRIC_ZH.get(metric, metric)}: {val:.1f}{unit}")

        elif tool_name == "calculate_system_cop":
            bid = result.get("building_id", "")
            cop = result.get("cop_mean", 0)
            summaries.append(f"  {_bname(bid)} COP: {cop:.2f}")

        elif tool_name == "compare_time_periods":
            bid = result.get("building_id", "")
            metric = result.get("metric", "")
            delta_pct = result.get("delta_pct")
            summaries.append(
                f"  {_bname(bid)} {METRIC_ZH.get(metric, metric)} 变化率: "
                f"{'+' if (delta_pct or 0) > 0 else ''}{delta_pct}%"
            )

    return "工具调用结果摘要：\n" + "\n".join(summaries) if summaries else "（工具返回结果为空）"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def generate_viz_artifacts(
    new_messages: list[BaseMessage],
    user_question: str = "",
) -> list[dict[str, Any]]:
    """
    扫描 ReAct 链消息，根据工具调用结果自动生成可视化 artifact。

    user_question: 用户原始问题，用于 Layer 3 意图筛选。
    返回 0~N 个 artifact dict，可直接通过 SSE 推送给前端。
    """
    triples = _extract_tool_triples(new_messages)
    if not triples:
        logger.info("viz_engine: 未提取到任何工具调用三元组（消息数=%d）", len(new_messages))
        return []

    # 按工具名分组
    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for tool_name, tool_args, tool_result in triples:
        groups.setdefault(tool_name, []).append((tool_args, tool_result))

    logger.info("viz_engine: 工具组=%s", {k: len(v) for k, v in groups.items()})

    artifacts: list[dict[str, Any]] = []

    # 透传已有 component_type 的结果（generate_report 等）
    for _tool_name, calls in groups.items():
        for _args, result in calls:
            ct = result.get("component_type", "")
            if ct in ("ReportDownload", "WorkOrderCard"):
                artifacts.append(result)

    # 规则引擎
    if "query_daily_energy_summary" in groups:
        daily_calls = groups["query_daily_energy_summary"]
        for i, (args, result) in enumerate(daily_calls):
            bid = result.get("building_id", "?")
            recs = result.get("records", [])
            logger.info("viz_engine: daily_summary[%d] building=%s records=%d", i, bid, len(recs))
        artifacts.extend(_viz_daily_summary(daily_calls))

    if "compare_metric_across_buildings" in groups:
        artifacts.extend(_viz_compare_buildings(groups["compare_metric_across_buildings"]))

    if "calculate_system_cop" in groups:
        artifacts.extend(_viz_cop(groups["calculate_system_cop"]))

    if "query_energy_metrics" in groups:
        artifacts.extend(_viz_energy_metrics(groups["query_energy_metrics"], user_question))

    if "compare_time_periods" in groups:
        artifacts.extend(_viz_compare_periods(groups["compare_time_periods"]))

    # Layer 3: 用户意图驱动筛选
    user_metrics = _extract_user_metrics(user_question)
    if user_metrics:
        filtered = [a for a in artifacts if _artifact_matches_metrics(a, user_metrics)]
        if filtered:
            artifacts = filtered

    logger.info("viz_engine 生成 %d 个 artifact", len(artifacts))
    return artifacts
