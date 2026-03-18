"""
Tavily 联网搜索服务。

功能：
- 调用 Tavily Search API，每次获取 top 3 结果
- 查询词自动截断到 _QUERY_MAX_CHARS（避免 API 报错，减少日志中的敏感信息暴露）
- 按 URL 去重（相同域名下的重复结果只保留得分最高的一条）
- 内置 5 分钟 TTL 内存缓存（节省 API credit，同一问题不重复调用）
- 模块级 httpx 单例（复用连接池，避免每次重建 TLS 握手）
- 搜索结果用明确标记块包裹（降低间接 Prompt Injection 风险）
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TOP_K = 3
_SNIPPET_MAX_CHARS = 200   # 限制摘要长度，同时降低 Prompt Injection 攻击面
_QUERY_MAX_CHARS = 200     # Tavily API query 长度上限，防止超长请求报错

# ── 模块级 HTTP 客户端（复用连接池，避免每次请求重建 TLS 握手）───────────────
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """懒初始化单例 httpx 客户端，连接关闭后自动重建。"""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


# ── TTL 内存缓存（相同 query 5 分钟内不重复调用 Tavily）──────────────────────
_CACHE_TTL = 300.0
_result_cache: dict[str, tuple["WebSearchSummary", float]] = {}


@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: float


@dataclass
class WebSearchSummary:
    query: str
    results: list[SearchResult]
    context_block: str   # 格式化后供 LLM 使用的上下文字符串


def _normalize_url(url: str) -> str:
    """提取 URL 的域名+路径作为去重键（忽略查询参数和 fragment）。"""
    try:
        p = urlparse(url)
        return f"{p.netloc}{p.path}".rstrip("/").lower()
    except Exception:
        return url.lower()


def _truncate(text: str, max_chars: int = _SNIPPET_MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for sep in ("。", ".", "\n", "！", "？", "!", "?"):
        idx = cut.rfind(sep)
        if idx > max_chars // 2:
            return cut[: idx + 1] + "…"
    return cut + "…"


def _deduplicate(results: list[SearchResult]) -> list[SearchResult]:
    """按规范化 URL 去重，保留分数最高的那条，结果按得分降序取 top K。"""
    seen: dict[str, SearchResult] = {}
    for r in results:
        key = _normalize_url(r.url)
        if key not in seen or r.score > seen[key].score:
            seen[key] = r
    return sorted(seen.values(), key=lambda x: x.score, reverse=True)[:_TOP_K]


def _build_context_block(query: str, results: list[SearchResult]) -> str:
    """
    将搜索结果格式化为 LLM 可读的上下文块。

    使用 <<<MARKER>>> 边界标记明确隔离外部数据与用户指令，
    降低恶意网页内容触发间接 Prompt Injection 的风险。
    """
    if not results:
        return ""

    lines = [
        "<<<WEB_SEARCH_RESULTS>>>",
        f"查询词：{query}",
        "以下是来自互联网的最新参考资料，请基于这些内容回答；若内容不足请如实说明，不要编造：",
        "",
    ]
    for i, r in enumerate(results, 1):
        snippet = _truncate(r.content)
        lines.append(f"[{i}] 标题：{r.title}")
        lines.append(f"    来源：{r.url}")
        lines.append(f"    摘要：{snippet}")
        lines.append("")

    lines.append("<<<WEB_SEARCH_RESULTS_END>>>")
    return "\n".join(lines)


async def tavily_search(query: str) -> Optional[WebSearchSummary]:
    """
    异步调用 Tavily 搜索，返回去重+摘要后的结构化结果。

    - 所有异常均被捕获并返回 None，由调用方决定降级策略
    - TAVILY_API_KEY 未配置时直接返回 None，不发出网络请求
    """
    settings = get_settings()
    api_key = settings.TAVILY_API_KEY
    if not api_key:
        logger.warning("TAVILY_API_KEY 未配置，跳过联网搜索")
        return None

    # 截断过长的 query，防止 API 报错，并减少日志中的敏感信息
    safe_query = query[:_QUERY_MAX_CHARS] if len(query) > _QUERY_MAX_CHARS else query

    # TTL 缓存命中检查
    cache_key = safe_query.lower().strip()
    if cache_key in _result_cache:
        cached_result, cached_at = _result_cache[cache_key]
        if time.monotonic() - cached_at < _CACHE_TTL:
            logger.info("Tavily 缓存命中: query_prefix=%s", safe_query[:40])
            return cached_result

    payload = {
        "api_key": api_key,
        "query": safe_query,
        "search_depth": "basic",
        "max_results": _TOP_K + 2,   # 多取几条，去重后保留 top K
        "include_answer": False,
        "include_raw_content": False,
    }

    try:
        client = _get_http_client()
        resp = await client.post(_TAVILY_SEARCH_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Tavily 搜索超时: query_prefix=%s", safe_query[:40])
        return None
    except httpx.HTTPStatusError as e:
        logger.warning("Tavily API 错误: status=%s", e.response.status_code)
        return None
    except Exception as e:
        logger.warning("Tavily 搜索异常: %s", type(e).__name__)
        return None

    raw_results: list[SearchResult] = []
    for item in data.get("results", []):
        content = item.get("content", "") or item.get("snippet", "")
        raw_results.append(SearchResult(
            title=item.get("title", "无标题"),
            url=item.get("url", ""),
            content=content,
            score=float(item.get("score") or 0.0),  # 修复: or 0.0 防止 None → float 崩溃
        ))

    deduped = _deduplicate(raw_results)
    context = _build_context_block(safe_query, deduped)

    summary = WebSearchSummary(query=safe_query, results=deduped, context_block=context)

    # 写入 TTL 缓存
    _result_cache[cache_key] = (summary, time.monotonic())

    logger.info(
        "Tavily 搜索完成: 原始=%d 去重后=%d",
        len(raw_results), len(deduped),
    )
    return summary
