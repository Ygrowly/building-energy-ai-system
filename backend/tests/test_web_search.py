"""
联网搜索服务单元测试（app/services/web_search.py）

覆盖范围：
  Part 1 — 纯辅助函数
    · _normalize_url     URL 规范化去重键
    · _truncate          摘要截断
    · _deduplicate       按 URL 去重 + 按分数排序
    · _build_context_block 上下文块格式化

  Part 2 — tavily_search 主函数
    · API Key 未配置 → 直接返回 None
    · 正常调用 → 返回 WebSearchSummary，含去重结果
    · score=None 不崩溃（B1 修复）
    · 长查询自动截断（S2 修复）
    · TTL 缓存命中 → 不发出 HTTP 请求（P3 修复）
    · TTL 缓存过期 → 重新发出 HTTP 请求
    · HTTP 超时 → 返回 None
    · HTTP 4xx 错误 → 返回 None
    · 通用异常 → 返回 None
    · 空结果列表 → 返回 None context_block
    · 模块级 HTTP 客户端复用（P1 修复）

测试策略：
  - 全程 mock _get_http_client，不发真实网络请求
  - 全程 mock get_settings，不依赖 .env 文件
  - 每个测试前后自动清理 TTL 缓存，确保隔离
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.services.web_search as ws_module
from app.services.web_search import (
    SearchResult,
    WebSearchSummary,
    _build_context_block,
    _deduplicate,
    _normalize_url,
    _result_cache,
    _truncate,
    tavily_search,
)

# ===========================================================================
# 公共 Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def clear_cache():
    """每个测试前后清空 TTL 缓存，防止测试间相互污染。"""
    _result_cache.clear()
    yield
    _result_cache.clear()


@pytest.fixture(autouse=True)
def reset_http_singleton():
    """每个测试前后重置模块级 HTTP 客户端单例，确保状态隔离。"""
    original = ws_module._http_client
    ws_module._http_client = None
    yield
    ws_module._http_client = original


def _make_settings(api_key: str = "tvly-test-key") -> MagicMock:
    s = MagicMock()
    s.TAVILY_API_KEY = api_key
    return s


def _make_http_response(results: list[dict] | None = None) -> MagicMock:
    """构造模拟的 Tavily API HTTP 响应。"""
    if results is None:
        results = [
            {"title": "Result A", "url": "https://a.com/page", "content": "Content A", "score": 0.9},
            {"title": "Result B", "url": "https://b.com/page", "content": "Content B", "score": 0.7},
            {"title": "Result C", "url": "https://c.com/page", "content": "Content C", "score": 0.5},
        ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": results}
    mock_resp.raise_for_status = MagicMock()  # 同步方法，正常不抛异常
    return mock_resp


def _make_mock_client(response: MagicMock) -> MagicMock:
    """构造返回指定响应的 httpx 客户端 mock。"""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=response)
    mock_client.is_closed = False
    return mock_client


# ===========================================================================
# Part 1 — 纯辅助函数
# ===========================================================================

class TestNormalizeUrl:
    def test_removes_trailing_slash(self):
        assert _normalize_url("https://example.com/path/") == "example.com/path"

    def test_lowercases(self):
        assert _normalize_url("https://Example.COM/Page") == "example.com/page"

    def test_ignores_query_params(self):
        result = _normalize_url("https://example.com/search?q=hello&page=2")
        assert result == "example.com/search"

    def test_ignores_fragment(self):
        result = _normalize_url("https://example.com/page#section1")
        assert result == "example.com/page"

    def test_same_url_different_trailing_slash(self):
        assert _normalize_url("https://a.com/p") == _normalize_url("https://a.com/p/")

    def test_handles_malformed_url(self):
        """解析失败时不抛异常，降级为小写化原始字符串。"""
        result = _normalize_url("not_a_url")
        assert isinstance(result, str)

    def test_path_included_in_key(self):
        """不同路径的同域名 URL 应生成不同去重键。"""
        assert _normalize_url("https://a.com/p1") != _normalize_url("https://a.com/p2")


class TestTruncate:
    def test_short_text_returned_unchanged(self):
        text = "这是一段短文本。"
        assert _truncate(text, max_chars=200) == text

    def test_truncates_at_chinese_period(self):
        text = "第一句话。" + "x" * 300
        result = _truncate(text, max_chars=50)
        assert result.endswith("…")
        assert "第一句话" in result

    def test_truncates_at_ascii_period(self):
        text = "First sentence. " + "x" * 300
        result = _truncate(text, max_chars=50)
        assert "First sentence" in result

    def test_truncates_at_newline(self):
        text = "第一行\n" + "x" * 300
        result = _truncate(text, max_chars=50)
        assert "第一行" in result

    def test_hard_truncate_when_no_sentence_boundary(self):
        text = "x" * 400
        result = _truncate(text, max_chars=100)
        assert result.endswith("…")
        assert len(result) <= 104  # 100 chars + "…"(3 bytes in UTF-8, but 1 char)

    def test_strips_leading_trailing_whitespace(self):
        text = "  content  "
        assert _truncate(text, max_chars=200) == "content"


class TestDeduplicate:
    def test_empty_list_returns_empty(self):
        assert _deduplicate([]) == []

    def test_keeps_only_highest_score_for_same_url(self):
        low = SearchResult(title="Low", url="https://a.com/p", content="c", score=0.3)
        high = SearchResult(title="High", url="https://a.com/p/", content="c", score=0.9)
        result = _deduplicate([low, high])
        assert len(result) == 1
        assert result[0].score == 0.9
        assert result[0].title == "High"

    def test_different_domains_all_kept(self):
        results = [
            SearchResult(title="A", url="https://a.com/p", content="c", score=0.8),
            SearchResult(title="B", url="https://b.com/p", content="c", score=0.7),
            SearchResult(title="C", url="https://c.com/p", content="c", score=0.6),
        ]
        deduped = _deduplicate(results)
        assert len(deduped) == 3

    def test_results_sorted_by_score_descending(self):
        results = [
            SearchResult(title="C", url="https://c.com/p", content="c", score=0.3),
            SearchResult(title="A", url="https://a.com/p", content="c", score=0.9),
            SearchResult(title="B", url="https://b.com/p", content="c", score=0.6),
        ]
        deduped = _deduplicate(results)
        scores = [r.score for r in deduped]
        assert scores == sorted(scores, reverse=True)

    def test_respects_top_k_limit(self):
        results = [
            SearchResult(title=str(i), url=f"https://site{i}.com/p", content="c", score=float(i) / 10)
            for i in range(10)
        ]
        deduped = _deduplicate(results)
        assert len(deduped) <= 3  # _TOP_K = 3

    def test_url_with_query_params_deduplicated(self):
        r1 = SearchResult(title="A", url="https://a.com/p?utm=x", content="c", score=0.5)
        r2 = SearchResult(title="B", url="https://a.com/p?utm=y", content="c", score=0.8)
        result = _deduplicate([r1, r2])
        assert len(result) == 1
        assert result[0].score == 0.8


class TestBuildContextBlock:
    def test_empty_results_returns_empty_string(self):
        assert _build_context_block("query", []) == ""

    def test_contains_search_markers(self):
        results = [SearchResult(title="T", url="https://t.com", content="Content", score=0.9)]
        block = _build_context_block("test query", results)
        assert "<<<WEB_SEARCH_RESULTS>>>" in block
        assert "<<<WEB_SEARCH_RESULTS_END>>>" in block

    def test_contains_query_text(self):
        results = [SearchResult(title="T", url="https://t.com", content="Content", score=0.9)]
        block = _build_context_block("建筑能耗", results)
        assert "建筑能耗" in block

    def test_contains_result_urls(self):
        results = [
            SearchResult(title="A", url="https://a.com/energy", content="Content A", score=0.9),
            SearchResult(title="B", url="https://b.com/green", content="Content B", score=0.7),
        ]
        block = _build_context_block("query", results)
        assert "https://a.com/energy" in block
        assert "https://b.com/green" in block

    def test_contains_result_titles(self):
        results = [SearchResult(title="绿色建筑标准", url="https://t.com", content="c", score=0.9)]
        block = _build_context_block("query", results)
        assert "绿色建筑标准" in block

    def test_result_content_truncated(self):
        long_content = "摘要内容。" * 100  # 远超 200 字
        results = [SearchResult(title="T", url="https://t.com", content=long_content, score=0.9)]
        block = _build_context_block("query", results)
        # 完整内容不应出现在块中（已被截断）
        assert long_content not in block

    def test_multiple_results_numbered(self):
        results = [
            SearchResult(title="First", url="https://a.com", content="c", score=0.9),
            SearchResult(title="Second", url="https://b.com", content="c", score=0.8),
        ]
        block = _build_context_block("query", results)
        assert "[1]" in block
        assert "[2]" in block


# ===========================================================================
# Part 2 — tavily_search 主函数
# ===========================================================================

class TestTavilySearch:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        """TAVILY_API_KEY 为空时直接返回 None，不发出任何 HTTP 请求。"""
        with patch("app.services.web_search.get_settings", return_value=_make_settings(api_key="")), \
             patch("app.services.web_search._get_http_client") as mock_get_client:
            result = await tavily_search("测试查询")
        assert result is None
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_returns_summary(self):
        """正常调用返回含 3 条结果的 WebSearchSummary。"""
        mock_resp = _make_http_response()
        mock_client = _make_mock_client(mock_resp)

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            result = await tavily_search("光伏发电技术")

        assert result is not None
        assert isinstance(result, WebSearchSummary)
        assert len(result.results) == 3
        assert result.context_block != ""
        assert "<<<WEB_SEARCH_RESULTS>>>" in result.context_block

    @pytest.mark.asyncio
    async def test_score_none_does_not_crash(self):
        """score 字段为 null 时不抛 TypeError（B1 修复）。"""
        mock_resp = _make_http_response(results=[
            {"title": "T", "url": "https://t.com/p", "content": "c", "score": None},
        ])
        mock_client = _make_mock_client(mock_resp)

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            result = await tavily_search("测试 None 分数")

        assert result is not None
        assert result.results[0].score == 0.0

    @pytest.mark.asyncio
    async def test_score_missing_defaults_to_zero(self):
        """score 字段完全缺失时默认为 0.0。"""
        mock_resp = _make_http_response(results=[
            {"title": "T", "url": "https://t.com/p", "content": "c"},  # 无 score 字段
        ])
        mock_client = _make_mock_client(mock_resp)

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            result = await tavily_search("测试缺失分数")

        assert result is not None
        assert result.results[0].score == 0.0

    @pytest.mark.asyncio
    async def test_long_query_truncated_to_200_chars(self):
        """超过 200 字的查询被截断后再传给 Tavily API（S2 修复）。"""
        long_query = "这是一个非常长的查询词，" * 30  # >> 200 chars
        assert len(long_query) > 200

        mock_resp = _make_http_response()
        mock_client = _make_mock_client(mock_resp)

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            await tavily_search(long_query)

        # 检查实际发送给 Tavily 的 payload 中 query 长度已被截断
        call_kwargs = mock_client.post.call_args
        sent_payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json") or call_kwargs[0][1]
        assert len(sent_payload["query"]) <= 200

    @pytest.mark.asyncio
    async def test_cache_hit_no_http_request(self):
        """TTL 缓存命中时不发出任何 HTTP 请求（P3 修复）。"""
        query = "光伏发电缓存测试"
        cached_summary = WebSearchSummary(
            query=query,
            results=[SearchResult(title="T", url="https://t.com", content="c", score=0.9)],
            context_block="cached block",
        )
        # 手动写入新鲜缓存
        _result_cache[query.lower().strip()] = (cached_summary, time.monotonic())

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client") as mock_get_client:
            result = await tavily_search(query)

        assert result is cached_summary
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_cache_triggers_new_request(self):
        """TTL 缓存过期后重新发出 HTTP 请求。"""
        query = "过期缓存测试"
        stale_summary = WebSearchSummary(
            query=query, results=[], context_block="old"
        )
        # 写入已过期的缓存（时间戳设为 600 秒前）
        _result_cache[query.lower().strip()] = (stale_summary, time.monotonic() - 600.0)

        mock_resp = _make_http_response()
        mock_client = _make_mock_client(mock_resp)

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            result = await tavily_search(query)

        mock_client.post.assert_called_once()
        assert result is not stale_summary

    @pytest.mark.asyncio
    async def test_result_written_to_cache_after_success(self):
        """成功调用后结果被写入缓存。"""
        query = "写入缓存测试"
        mock_resp = _make_http_response()
        mock_client = _make_mock_client(mock_resp)

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            result = await tavily_search(query)

        cache_key = query.lower().strip()
        assert cache_key in _result_cache
        cached_result, cached_at = _result_cache[cache_key]
        assert cached_result is result
        assert time.monotonic() - cached_at < 1.0  # 刚写入，应该非常新鲜

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        """HTTP 超时时返回 None，不抛异常。"""
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            result = await tavily_search("超时测试")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_4xx_returns_none(self):
        """Tavily API 返回 4xx 错误时返回 None，不抛异常。"""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)
        )

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            result = await tavily_search("鉴权错误测试")

        assert result is None

    @pytest.mark.asyncio
    async def test_generic_exception_returns_none(self):
        """任意未预期异常时返回 None，不向上传播。"""
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=RuntimeError("意外错误"))

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            result = await tavily_search("通用异常测试")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_results_from_api(self):
        """API 返回空列表时 context_block 为空字符串。"""
        mock_resp = _make_http_response(results=[])
        mock_client = _make_mock_client(mock_resp)

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            result = await tavily_search("空结果测试")

        assert result is not None
        assert result.context_block == ""
        assert result.results == []

    @pytest.mark.asyncio
    async def test_deduplication_applied_to_results(self):
        """相同域名的多条结果只保留一条（URL 去重）。"""
        # 3 条结果来自同一 URL（不同 query params）
        mock_resp = _make_http_response(results=[
            {"title": "A", "url": "https://same.com/page?v=1", "content": "c", "score": 0.9},
            {"title": "B", "url": "https://same.com/page?v=2", "content": "c", "score": 0.7},
            {"title": "C", "url": "https://other.com/page", "content": "c", "score": 0.5},
        ])
        mock_client = _make_mock_client(mock_resp)

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client", return_value=mock_client):
            result = await tavily_search("去重测试")

        # same.com/page 只保留一条（score=0.9 的那条）
        urls = [r.url for r in result.results]
        same_com_results = [u for u in urls if "same.com" in u]
        assert len(same_com_results) == 1
        assert result.results[0].score == 0.9  # 高分优先

    @pytest.mark.asyncio
    async def test_http_client_singleton_reused(self):
        """连续两次调用复用同一个 HTTP 客户端实例（P1 修复）。"""
        mock_resp = _make_http_response()
        mock_client = _make_mock_client(mock_resp)

        with patch("app.services.web_search.get_settings", return_value=_make_settings()):
            # 预先注入一个"未关闭"的单例客户端
            ws_module._http_client = mock_client

            # 第一次调用
            mock_resp2 = _make_http_response()
            mock_client.post = AsyncMock(return_value=mock_resp2)
            await tavily_search("第一次调用")

            # 第二次调用（用不同 query 绕过缓存）
            mock_resp3 = _make_http_response()
            mock_client.post = AsyncMock(return_value=mock_resp3)
            await tavily_search("第二次调用不同词")

        # 两次调用都通过同一个 mock_client，而非创建新实例
        assert ws_module._http_client is mock_client

    @pytest.mark.asyncio
    async def test_query_used_as_cache_key_case_insensitive(self):
        """查询词大小写不同时命中同一缓存条目。"""
        query_lower = "光伏 energy"
        query_upper = "光伏 ENERGY"

        cached_summary = WebSearchSummary(
            query=query_lower,
            results=[SearchResult(title="T", url="https://t.com", content="c", score=0.9)],
            context_block="cached",
        )
        _result_cache[query_lower.lower().strip()] = (cached_summary, time.monotonic())

        with patch("app.services.web_search.get_settings", return_value=_make_settings()), \
             patch("app.services.web_search._get_http_client") as mock_get_client:
            result = await tavily_search(query_upper)

        assert result is cached_summary
        mock_get_client.assert_not_called()
