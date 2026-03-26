"""
联网搜索 MCP 工具 —— 包装 Tavily 搜索服务供 Agent ReAct 循环调用。

Agent 在知识库（RAG）不足时自主决定调用此工具，
无需 API 层预注入，上下文更精简、响应更快。
"""
from __future__ import annotations

import logging

from app.schemas.mcp_schemas import WebSearchInput
from app.services.web_search import tavily_search

logger = logging.getLogger(__name__)


async def web_search(inp: WebSearchInput) -> str:
    """
    调用 Tavily 联网搜索并返回格式化结果字符串。

    返回值直接作为 ToolMessage content 供 Agent 参考。
    """
    summary = await tavily_search(inp.query)

    if summary is None or not summary.results:
        return f"联网搜索「{inp.query}」未找到相关结果，请基于已有知识回答。"

    lines = [f"联网搜索「{inp.query}」找到 {len(summary.results)} 条参考资料：\n"]
    for i, r in enumerate(summary.results, 1):
        lines.append(f"[{i}] {r.title}")
        lines.append(f"    来源: {r.url}")
        lines.append(f"    摘要: {r.content}")
        lines.append("")

    return "\n".join(lines)
