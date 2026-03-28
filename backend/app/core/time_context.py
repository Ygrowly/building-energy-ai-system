"""
统一时间上下文工具（全链路唯一时间源）。

职责：
1. 提供系统当前日期/时间（不依赖数据库）
2. 结合数据库有效范围 + 用户指定时间，计算有效查询范围
3. 生成标准化的时间上下文注入文本，供所有 Agent 节点使用
4. 为预测功能提供精确的 UTC 时间戳

设计原则：
- 当前日期永远来自系统时钟（date.today()）
- 数据库范围仅作为"数据可用性"参考，不决定"今天是哪天"
- 所有 Agent 通过本模块获取时间，禁止自行获取或硬编码
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 基础时间获取
# ---------------------------------------------------------------------------

def get_today() -> date:
    """系统当前日期（唯一时间源，所有模块统一使用）。"""
    return date.today()


def get_now_utc() -> datetime:
    """系统当前 UTC 时间戳（预测功能等需要精确时间时使用）。"""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 查询范围计算
# ---------------------------------------------------------------------------

def resolve_query_range(
    *,
    data_min: str | None = None,
    data_max: str | None = None,
    user_start: str | None = None,
    user_end: str | None = None,
    lookback_days: int = 30,
) -> tuple[str, str]:
    """
    计算有效查询范围，返回 (start_date, end_date) 字符串。

    优先级：
    1. 用户明确指定的时间范围
    2. 数据库最新数据往前推 lookback_days 天
    3. 从今天往前推 lookback_days 天（兜底）
    """
    if user_start and user_end:
        return user_start, user_end

    today = get_today()

    if data_max:
        try:
            anchor = date.fromisoformat(data_max)
        except ValueError:
            anchor = today
    else:
        anchor = today

    eff_end = anchor
    eff_start = anchor - timedelta(days=lookback_days - 1)

    if data_min:
        try:
            min_d = date.fromisoformat(data_min)
            eff_start = max(eff_start, min_d)
        except ValueError:
            pass

    return str(eff_start), str(eff_end)


# ---------------------------------------------------------------------------
# Agent 上下文注入
# ---------------------------------------------------------------------------

def build_time_context(
    *,
    data_range: dict | None = None,
    user_time_context: dict | None = None,
    label: str = "查询时间范围",
) -> list[str]:
    """
    构建标准化的时间上下文注入文本，供 Agent SystemMessage 使用。

    Args:
        data_range: get_data_range() 返回的 dict（可选，含 min_date/max_date）
        user_time_context: Router 提取的 time_context（可选，含 start/end）
        label: 标签名（"查询时间范围"/"诊断时间范围"）

    Returns:
        list[str]: 每行一条注入文本
    """
    today = get_today()
    lines: list[str] = [f"【今天日期】: {today}"]

    # 提取各参数
    data_min = data_range.get("min_date") if data_range else None
    data_max = data_range.get("max_date") if data_range else None
    user_start = None
    user_end = None
    if isinstance(user_time_context, dict):
        user_start = user_time_context.get("start")
        user_end = user_time_context.get("end")

    # 计算有效范围
    eff_start, eff_end = resolve_query_range(
        data_min=data_min,
        data_max=data_max,
        user_start=user_start,
        user_end=user_end,
    )

    lines.append(
        f"【{label}（所有工具调用必须使用此范围）】: {eff_start} ~ {eff_end}"
    )

    if data_min and data_max:
        lines.append(f"【数据库有效数据范围】: {data_min} ~ {data_max}")

    lines.append("**严禁自行编造日期，必须使用上述时间范围**")

    return lines


def clamp_date_to_range(
    dt_str: str,
    data_min: str | None = None,
    data_max: str | None = None,
) -> str:
    """
    将日期字符串钳位到数据有效范围内。

    超出范围时自动修正到最近的边界，供 MCP 工具层防御性使用。
    """
    try:
        d = date.fromisoformat(dt_str)
    except ValueError:
        return dt_str

    if data_min:
        try:
            d = max(d, date.fromisoformat(data_min))
        except ValueError:
            pass
    if data_max:
        try:
            d = min(d, date.fromisoformat(data_max))
        except ValueError:
            pass

    return str(d)
