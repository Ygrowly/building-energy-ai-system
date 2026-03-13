"""
数据分析服务层。

负责解析用户上传的 CSV / Excel 文件，提取统计信息，
并调用 LLM 对数据内容进行 AI 洞察分析（流式输出）。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, AsyncGenerator

import pandas as pd

from app.core.config import get_settings

settings = get_settings()


# ---------------------------------------------------------------------------
# 类型别名
# ---------------------------------------------------------------------------

ColumnInfo = dict[str, Any]   # {name, dtype, null_count, unique_count}
StatsInfo = dict[str, Any]    # {col: {min, max, mean, std, ...}}


# ---------------------------------------------------------------------------
# 文件解析
# ---------------------------------------------------------------------------

def parse_file(file_path: str) -> tuple[pd.DataFrame, str]:
    """
    读取 CSV 或 Excel 文件，返回 (DataFrame, 文件类型字符串)。
    文件类型以后缀名判断：.csv → 'csv'，.xlsx/.xls → 'xlsx'。
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(file_path, encoding_errors="replace")
        return df, "csv"
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(file_path, engine="openpyxl" if suffix == ".xlsx" else None)
        return df, "xlsx"
    else:
        raise ValueError(f"不支持的文件格式：{suffix}，仅支持 .csv / .xlsx / .xls")


def extract_column_info(df: pd.DataFrame) -> list[ColumnInfo]:
    """提取每列的元信息：名称、数据类型、空值数量、唯一值数量。"""
    result: list[ColumnInfo] = []
    for col in df.columns:
        series = df[col]
        result.append({
            "name": str(col),
            "dtype": _simplify_dtype(str(series.dtype)),
            "null_count": int(series.isna().sum()),
            "unique_count": int(series.nunique()),
        })
    return result


def extract_stats(df: pd.DataFrame) -> StatsInfo:
    """对所有数值列计算基础统计量，非数值列跳过。返回 JSON 可序列化的字典。"""
    stats: StatsInfo = {}
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    for col in numeric_cols:
        series = df[col].dropna()
        if series.empty:
            continue
        stats[str(col)] = {
            "min": _safe_float(series.min()),
            "max": _safe_float(series.max()),
            "mean": _safe_float(series.mean()),
            "std": _safe_float(series.std()),
            "median": _safe_float(series.median()),
        }
    return stats


def get_sample_rows(df: pd.DataFrame, n: int = 10) -> list[dict[str, Any]]:
    """返回前 n 行数据，转换为 JSON 可序列化格式（NaN → None）。"""
    sample = df.head(n).where(pd.notna(df.head(n)), other=None)
    return sample.to_dict(orient="records")


def analyze_file(file_path: str) -> dict[str, Any]:
    """
    一次性解析文件，返回包含完整分析结果的字典：
    {
        file_type, row_count, column_count,
        columns: [...],
        stats: {...},
        sample_rows: [...],
        columns_json: str,    # JSON 序列化后的字符串（存 DB 用）
        stats_json: str,
    }
    """
    df, file_type = parse_file(file_path)
    columns = extract_column_info(df)
    stats = extract_stats(df)
    sample = get_sample_rows(df)

    return {
        "file_type": file_type,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": columns,
        "stats": stats,
        "sample_rows": sample,
        "columns_json": json.dumps(columns, ensure_ascii=False),
        "stats_json": json.dumps(stats, ensure_ascii=False),
    }


# ---------------------------------------------------------------------------
# AI 分析（流式 LLM 调用）
# ---------------------------------------------------------------------------

async def ai_analyze_stream(
    original_name: str,
    row_count: int,
    column_count: int,
    columns: list[ColumnInfo],
    stats: StatsInfo,
    sample_rows: list[dict],
) -> AsyncGenerator[str, None]:
    """
    调用 LLM 对数据集进行 AI 洞察分析，以流式方式逐段 yield 文本。
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=0.3,
        streaming=True,
    )

    col_summary = "\n".join(
        f"  - {c['name']}（{c['dtype']}，空值 {c['null_count']} 个，唯一值 {c['unique_count']} 个）"
        for c in columns
    )
    stats_summary = ""
    if stats:
        stats_lines = []
        for col, s in stats.items():
            stats_lines.append(
                f"  - {col}：最小={s['min']:.3g}，最大={s['max']:.3g}，"
                f"均值={s['mean']:.3g}，标准差={s['std']:.3g}，中位数={s['median']:.3g}"
            )
        stats_summary = "数值统计：\n" + "\n".join(stats_lines)

    sample_text = ""
    if sample_rows:
        sample_text = "前3行样本数据：\n"
        for i, row in enumerate(sample_rows[:3], 1):
            sample_text += f"  行{i}: {json.dumps(row, ensure_ascii=False)}\n"

    prompt = f"""你是一位数据分析专家。请对以下数据集进行深度洞察分析。

文件名：{original_name}
数据规模：{row_count} 行 × {column_count} 列

列信息：
{col_summary}

{stats_summary}

{sample_text}

请从以下角度进行分析（用 Markdown 格式输出）：
1. **数据概览**：描述数据集的整体情况和可能的业务场景
2. **数据质量**：评估空值、异常值、数据完整性问题
3. **关键发现**：基于统计数据发现有价值的规律或特征
4. **分析建议**：提出具体可行的后续分析方向
"""

    messages = [
        SystemMessage(content="你是一位专业的数据分析师，善于从数据中发现业务价值。请用简洁、专业的中文回答。"),
        HumanMessage(content=prompt),
    ]

    async for chunk in llm.astream(messages):
        if chunk.content:
            yield str(chunk.content)


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _simplify_dtype(dtype_str: str) -> str:
    """将 pandas dtype 字符串简化为可读标签。"""
    if "int" in dtype_str:
        return "整数"
    if "float" in dtype_str:
        return "浮点数"
    if "bool" in dtype_str:
        return "布尔值"
    if "datetime" in dtype_str:
        return "日期时间"
    return "文本"


def _safe_float(val: Any) -> float | None:
    """将可能含 NaN/Inf 的值转换为 JSON 安全的 float 或 None。"""
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 6)
    except (TypeError, ValueError):
        return None
