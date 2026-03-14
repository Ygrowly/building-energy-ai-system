"""
RAG 模块综合测试
================

覆盖范围：
  Part 1 — RAG Engine 服务层（app/services/rag_engine.py）
    · local_search()      本地知识库关键词检索
    · search_ragflow()    RAGFlow API 混合检索（含 fallback、HTTP 错误、重排）

  Part 2 — RAG MCP 工具层（app/mcp/tools/rag_search.py）
    · rag_hybrid_search() 元数据过滤 + 委托 search_ragflow

  Part 3 — 文档管理 API（app/api/routes_datacenter.py）
    · POST /api/datacenter/documents/upload    上传 PDF/Word 到 RAGFlow 知识库
    · GET  /api/datacenter/documents           获取 RAGFlow 文档列表
    · DELETE /api/datacenter/documents/{id}    删除知识库文档
    · POST /api/datacenter/documents/{id}/parse  触发文档向量化解析

测试策略：
  - 全程 mock httpx.AsyncClient，不发真实网络请求
  - 通过 FastAPI dependency_overrides 绕过 JWT 鉴权
  - 使用 patch 替换 get_settings 来模拟配置变体（有/无 RAGFlow 配置）
"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.schemas.mcp_schemas import (
    MCPError,
    MetadataFilter,
    RAGHybridSearchInput,
    RAGHybridSearchOutput,
    RAGSearchResult,
)
from app.services.rag_engine import local_search, search_ragflow
from app.mcp.tools.rag_search import rag_hybrid_search
from main import app


# ===========================================================================
# 公共 fixture
# ===========================================================================

@pytest.fixture
async def client():
    """带认证绕过的 AsyncClient，所有文档 API 测试共用。"""
    from app.core.security import get_current_active_user
    from app.db.models import User

    mock_user = MagicMock(spec=User)
    mock_user.id = "test-user-id"
    mock_user.username = "testuser"
    mock_user.is_active = True

    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


def _make_settings(
    *,
    api_key: str = "ragflow-test-key",
    dataset_id: str = "dataset-test-id",
    api_url: str = "http://ragflow.test:9380",
    rerank_id: str = "gte-rerank@test",
):
    """构造模拟的 settings 对象。"""
    s = MagicMock()
    s.RAGFLOW_API_KEY = api_key
    s.RAGFLOW_DATASET_ID = dataset_id
    s.RAGFLOW_API_URL = api_url
    s.RAGFLOW_RERANK_ID = rerank_id
    return s


def _make_ragflow_response(chunks: list[dict], total: int = None, doc_aggs: list[dict] = None):
    """构造 RAGFlow /api/v1/retrieval 的标准响应体。"""
    return {
        "data": {
            "chunks": chunks,
            "total": total if total is not None else len(chunks),
            "doc_aggs": doc_aggs or [],
        }
    }


# ===========================================================================
# Part 1：RAG Engine 服务层
# ===========================================================================

class TestLocalSearch:
    """local_search() — 本地关键词知识库检索（RAGFlow 不可用时的 fallback）。"""

    def test_cop_query_returns_result(self):
        """查询 COP 相关关键词能命中本地知识库。"""
        results = local_search("空调COP能效比下降是什么原因")
        assert len(results) >= 1
        assert isinstance(results[0], RAGSearchResult)
        assert results[0].similarity > 0
        assert "COP" in results[0].content or "能效" in results[0].content

    def test_energy_anomaly_query(self):
        """能耗异常查询命中相关条目。"""
        results = local_search("凌晨能耗高，夜间用电异常原因")
        assert len(results) >= 1
        assert results[0].similarity > 0
        # 相似度最高的应该在前面
        similarities = [r.similarity for r in results]
        assert similarities == sorted(similarities, reverse=True)

    def test_maintenance_query(self):
        """设备维护查询命中运维规程。"""
        results = local_search("设备巡检维修工单流程")
        assert len(results) >= 1
        assert results[0].source_doc  # 来源文档不为空

    def test_water_query(self):
        """水耗查询命中水耗管理章节。"""
        results = local_search("用水量异常，水耗管理")
        assert len(results) >= 1
        assert any("水" in r.content for r in results)

    def test_energy_trend_query(self):
        """能耗趋势查询命中对应章节。"""
        results = local_search("月度用电趋势节能分析")
        assert len(results) >= 1

    def test_unrelated_query_returns_fallback(self):
        """完全无关的查询返回通用提示，similarity=0。"""
        # 使用不含任何领域关键词的查询
        results = local_search("莎士比亚戏剧鉴赏与文学批评")
        assert len(results) == 1
        assert results[0].similarity == 0.0
        assert results[0].source_doc == "本地知识库"
        assert results[0].rerank_score is None

    def test_top_k_limits_results(self):
        """top_k 参数控制返回条数上限。"""
        results_1 = local_search("能耗异常COP设备维护水耗趋势", top_k=1)
        results_2 = local_search("能耗异常COP设备维护水耗趋势", top_k=2)
        assert len(results_1) <= 1
        assert len(results_2) <= 2

    def test_result_fields_complete(self):
        """返回结果包含所有必需字段。"""
        results = local_search("COP能效比空调")
        r = results[0]
        assert r.content
        assert r.parent_section
        assert r.source_doc
        assert r.page == 1
        assert 0.0 <= r.similarity <= 1.0

    def test_default_top_k_is_3(self):
        """默认 top_k=3，最多返回 3 条。"""
        results = local_search("能耗 COP 设备 水耗 趋势 工单 维修 巡检")
        assert len(results) <= 3


class TestSearchRagflow:
    """search_ragflow() — 调用 RAGFlow API 的混合检索。"""

    @pytest.mark.asyncio
    async def test_fallback_when_no_api_key(self):
        """未配置 RAGFLOW_API_KEY 时自动降级到本地知识库。"""
        mock_settings = _make_settings(api_key="", dataset_id="")
        with patch("app.services.rag_engine.get_settings", return_value=mock_settings):
            result = await search_ragflow("COP能效比", top_k=2)
        assert isinstance(result, RAGHybridSearchOutput)
        assert result.reranked is False
        assert len(result.results) <= 2

    @pytest.mark.asyncio
    async def test_fallback_when_no_dataset_id(self):
        """未配置 RAGFLOW_DATASET_ID 时降级。"""
        mock_settings = _make_settings(api_key="some-key", dataset_id="")
        with patch("app.services.rag_engine.get_settings", return_value=mock_settings):
            result = await search_ragflow("设备故障")
        assert isinstance(result, RAGHybridSearchOutput)

    @pytest.mark.asyncio
    async def test_success_with_chunks(self):
        """正常返回 chunks，结果列表不为空，字段映射正确。"""
        mock_settings = _make_settings()
        chunks = [
            {
                "document_id": "doc-001",
                "content": "冷却塔结垢导致COP下降0.5~1.0。",
                "similarity": 0.85,
                "vector_similarity": 0.80,
                "document_keyword": "楼宇运维手册.pdf",
            },
            {
                "document_id": "doc-002",
                "content": "制冷剂泄漏会降低系统制冷能力。",
                "similarity": 0.72,
                "vector_similarity": 0.68,
                "document_keyword": "楼宇运维手册.pdf",
            },
        ]
        doc_aggs = [
            {"doc_id": "doc-001", "doc_name": "楼宇运维手册.pdf"},
            {"doc_id": "doc-002", "doc_name": "楼宇运维手册.pdf"},
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_ragflow_response(chunks, doc_aggs=doc_aggs)
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.services.rag_engine.get_settings", return_value=mock_settings),
            patch("app.services.rag_engine.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await search_ragflow("COP能效比下降原因", top_k=2)

        assert isinstance(result, RAGHybridSearchOutput)
        assert len(result.results) == 2
        assert result.results[0].similarity == 0.85
        assert result.results[0].source_doc == "楼宇运维手册.pdf"
        assert result.results[0].content == "冷却塔结垢导致COP下降0.5~1.0。"
        assert result.reranked is True  # 配置了 rerank_id
        assert result.query == "COP能效比下降原因"

    @pytest.mark.asyncio
    async def test_rerank_score_populated_when_reranked(self):
        """启用重排时 rerank_score 从 vector_similarity 填充。"""
        mock_settings = _make_settings(rerank_id="gte-rerank@test")
        chunks = [{
            "document_id": "doc-001",
            "content": "空调能效比说明。",
            "similarity": 0.9,
            "vector_similarity": 0.75,
            "document_keyword": "手册.pdf",
        }]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_ragflow_response(chunks)
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.services.rag_engine.get_settings", return_value=mock_settings),
            patch("app.services.rag_engine.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await search_ragflow("能效比", enable_rerank=True)

        assert result.results[0].rerank_score == 0.75
        assert result.reranked is True

    @pytest.mark.asyncio
    async def test_rerank_disabled_rerank_score_is_none(self):
        """禁用重排时 rerank_score=None。"""
        mock_settings = _make_settings(rerank_id="gte-rerank@test")
        chunks = [{
            "document_id": "doc-001",
            "content": "测试内容。",
            "similarity": 0.7,
            "vector_similarity": 0.65,
            "document_keyword": "手册.pdf",
        }]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_ragflow_response(chunks)
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.services.rag_engine.get_settings", return_value=mock_settings),
            patch("app.services.rag_engine.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await search_ragflow("测试", enable_rerank=False)

        assert result.results[0].rerank_score is None
        assert result.reranked is False

    @pytest.mark.asyncio
    async def test_http_error_returns_mcp_error(self):
        """RAGFlow 返回 HTTP 错误时，返回 MCPError 而不是抛异常。"""
        mock_settings = _make_settings()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("连接被拒绝")
        )

        with (
            patch("app.services.rag_engine.get_settings", return_value=mock_settings),
            patch("app.services.rag_engine.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await search_ragflow("任意查询")

        assert isinstance(result, MCPError)
        assert result.error_code == "RAGFLOW_UNAVAILABLE"
        assert result.tool_name == "rag_hybrid_search"
        assert "RAGFlow" in result.error

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_empty_results(self):
        """RAGFlow 返回空 chunks 时，结果列表为空。"""
        mock_settings = _make_settings()
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_ragflow_response([])
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.services.rag_engine.get_settings", return_value=mock_settings),
            patch("app.services.rag_engine.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await search_ragflow("极罕见的查询词")

        assert isinstance(result, RAGHybridSearchOutput)
        assert result.results == []
        assert result.total_retrieved == 0

    @pytest.mark.asyncio
    async def test_similarity_clamped_to_1(self):
        """相似度超过 1.0 时被截断到 1.0（防御 RAGFlow 偶发数据异常）。"""
        mock_settings = _make_settings()
        chunks = [{
            "document_id": "doc-001",
            "content": "测试内容。",
            "similarity": 1.5,   # 异常值 > 1.0
            "vector_similarity": 1.2,
            "document_keyword": "手册.pdf",
        }]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_ragflow_response(chunks)
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.services.rag_engine.get_settings", return_value=mock_settings),
            patch("app.services.rag_engine.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await search_ragflow("测试")

        assert result.results[0].similarity == 1.0
        assert result.results[0].rerank_score == 1.0

    @pytest.mark.asyncio
    async def test_doc_name_from_aggs(self):
        """优先从 doc_aggs 获取文件名（比 document_keyword 更准确）。"""
        mock_settings = _make_settings()
        chunks = [{
            "document_id": "doc-abc",
            "content": "内容。",
            "similarity": 0.6,
            "document_keyword": "旧名称.pdf",  # 应被 doc_aggs 覆盖
        }]
        doc_aggs = [{"doc_id": "doc-abc", "doc_name": "楼宇运维手册2024版.pdf"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_ragflow_response(chunks, doc_aggs=doc_aggs)
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.services.rag_engine.get_settings", return_value=mock_settings),
            patch("app.services.rag_engine.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await search_ragflow("测试")

        assert result.results[0].source_doc == "楼宇运维手册2024版.pdf"

    @pytest.mark.asyncio
    async def test_request_payload_includes_rerank_id(self):
        """启用重排时，请求 payload 中包含 rerank_id 字段。"""
        mock_settings = _make_settings(rerank_id="gte-rerank@Tongyi-Qianwen")
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_ragflow_response([])
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.services.rag_engine.get_settings", return_value=mock_settings),
            patch("app.services.rag_engine.httpx.AsyncClient", return_value=mock_client),
        ):
            await search_ragflow("查询", enable_rerank=True)

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
        assert "rerank_id" in payload
        assert payload["rerank_id"] == "gte-rerank@Tongyi-Qianwen"

    @pytest.mark.asyncio
    async def test_request_payload_no_rerank_id_when_disabled(self):
        """禁用重排时，payload 中不包含 rerank_id。"""
        mock_settings = _make_settings(rerank_id="gte-rerank@test")
        mock_resp = MagicMock()
        mock_resp.json.return_value = _make_ragflow_response([])
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.services.rag_engine.get_settings", return_value=mock_settings),
            patch("app.services.rag_engine.httpx.AsyncClient", return_value=mock_client),
        ):
            await search_ragflow("查询", enable_rerank=False)

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json", {})
        assert "rerank_id" not in payload


# ===========================================================================
# Part 2：RAG MCP 工具层
# ===========================================================================

class TestRAGHybridSearchTool:
    """rag_hybrid_search() — MCP 工具薄包装层。"""

    def _make_inp(
        self,
        query: str = "设备故障诊断",
        top_k: int = 3,
        device_id: str = "",
        building_type: str = "",
        enable_rerank: bool = True,
    ) -> RAGHybridSearchInput:
        return RAGHybridSearchInput(
            query=query,
            top_k=top_k,
            metadata_filter=MetadataFilter(
                device_id=device_id,
                building_type=building_type,
            ),
            enable_rerank=enable_rerank,
        )

    @pytest.mark.asyncio
    async def test_delegates_to_search_ragflow(self):
        """rag_hybrid_search 正确委托给 search_ragflow。"""
        expected = RAGHybridSearchOutput(
            results=[],
            query="设备故障诊断",
            total_retrieved=0,
            reranked=False,
        )
        with patch(
            "app.mcp.tools.rag_search.search_ragflow",
            AsyncMock(return_value=expected),
        ) as mock_search:
            result = await rag_hybrid_search(self._make_inp())

        assert result is expected
        mock_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_metadata_filter_device_id_passed(self):
        """有 device_id 时传入 metadata_filter。"""
        expected = RAGHybridSearchOutput(results=[], query="查询", total_retrieved=0, reranked=False)
        with patch(
            "app.mcp.tools.rag_search.search_ragflow",
            AsyncMock(return_value=expected),
        ) as mock_search:
            await rag_hybrid_search(self._make_inp(device_id="M-OFF-001"))

        _, call_kwargs = mock_search.call_args
        assert call_kwargs.get("metadata_filter") == {"device_id": "M-OFF-001"}

    @pytest.mark.asyncio
    async def test_empty_metadata_filter_passes_none(self):
        """device_id 和 building_type 均为空时 metadata_filter=None。"""
        expected = RAGHybridSearchOutput(results=[], query="查询", total_retrieved=0, reranked=False)
        with patch(
            "app.mcp.tools.rag_search.search_ragflow",
            AsyncMock(return_value=expected),
        ) as mock_search:
            await rag_hybrid_search(self._make_inp())

        _, call_kwargs = mock_search.call_args
        assert call_kwargs.get("metadata_filter") is None

    @pytest.mark.asyncio
    async def test_building_type_filter_passed(self):
        """有 building_type 时传入 metadata_filter。"""
        expected = RAGHybridSearchOutput(results=[], query="查询", total_retrieved=0, reranked=False)
        with patch(
            "app.mcp.tools.rag_search.search_ragflow",
            AsyncMock(return_value=expected),
        ) as mock_search:
            await rag_hybrid_search(self._make_inp(building_type="Office"))

        _, call_kwargs = mock_search.call_args
        assert call_kwargs.get("metadata_filter") == {"building_type": "Office"}

    @pytest.mark.asyncio
    async def test_both_filters_combined(self):
        """device_id 和 building_type 同时存在时合并传入。"""
        expected = RAGHybridSearchOutput(results=[], query="查询", total_retrieved=0, reranked=False)
        with patch(
            "app.mcp.tools.rag_search.search_ragflow",
            AsyncMock(return_value=expected),
        ) as mock_search:
            await rag_hybrid_search(
                self._make_inp(device_id="M-OFF-001", building_type="Office")
            )

        _, call_kwargs = mock_search.call_args
        mf = call_kwargs.get("metadata_filter")
        assert mf == {"device_id": "M-OFF-001", "building_type": "Office"}

    @pytest.mark.asyncio
    async def test_enable_rerank_passed_through(self):
        """enable_rerank 参数正确透传。"""
        expected = RAGHybridSearchOutput(results=[], query="查询", total_retrieved=0, reranked=False)
        with patch(
            "app.mcp.tools.rag_search.search_ragflow",
            AsyncMock(return_value=expected),
        ) as mock_search:
            await rag_hybrid_search(self._make_inp(enable_rerank=False))

        _, call_kwargs = mock_search.call_args
        assert call_kwargs.get("enable_rerank") is False

    @pytest.mark.asyncio
    async def test_top_k_passed_through(self):
        """top_k 参数正确透传。"""
        expected = RAGHybridSearchOutput(results=[], query="查询", total_retrieved=0, reranked=False)
        with patch(
            "app.mcp.tools.rag_search.search_ragflow",
            AsyncMock(return_value=expected),
        ) as mock_search:
            await rag_hybrid_search(self._make_inp(top_k=5))

        _, call_kwargs = mock_search.call_args
        assert call_kwargs.get("top_k") == 5

    @pytest.mark.asyncio
    async def test_mcp_error_propagated(self):
        """search_ragflow 返回 MCPError 时透传给调用方。"""
        error = MCPError(
            error="RAGFlow 不可用",
            error_code="RAGFLOW_UNAVAILABLE",
            tool_name="rag_hybrid_search",
        )
        with patch(
            "app.mcp.tools.rag_search.search_ragflow",
            AsyncMock(return_value=error),
        ):
            result = await rag_hybrid_search(self._make_inp())

        assert isinstance(result, MCPError)
        assert result.error_code == "RAGFLOW_UNAVAILABLE"


# ===========================================================================
# Part 3：文档管理 API 端点
# ===========================================================================

def _make_ragflow_http_response(body: dict, status_code: int = 200):
    """构造 mock httpx.Response 对象。"""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = str(body)
    resp.raise_for_status = MagicMock()
    return resp


def _make_failing_ragflow_response(status_code: int = 500, message: str = "内部错误"):
    """构造会触发 raise_for_status 的 mock 响应。"""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = {"message": message}
    resp.text = message
    exc = httpx.HTTPStatusError(
        message=message,
        request=MagicMock(),
        response=resp,
    )
    resp.raise_for_status = MagicMock(side_effect=exc)
    return resp


class TestDocumentUploadAPI:
    """POST /api/datacenter/documents/upload"""

    @pytest.mark.asyncio
    async def test_upload_pdf_success(self, client):
        """上传 PDF 文件成功，返回 RAGFlow 响应。"""
        ragflow_resp_body = {
            "code": 0,
            "data": [{"id": "doc-new-001", "name": "test.pdf", "status": "1"}]
        }
        mock_resp = _make_ragflow_http_response(ragflow_resp_body)
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.post(
                "/api/datacenter/documents/upload",
                files={"file": ("test.pdf", b"%PDF-1.4 fake pdf content", "application/pdf")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    @pytest.mark.asyncio
    async def test_upload_docx_success(self, client):
        """上传 .docx 文件成功。"""
        ragflow_resp_body = {"code": 0, "data": [{"id": "doc-002", "name": "report.docx"}]}
        mock_resp = _make_ragflow_http_response(ragflow_resp_body)
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.post(
                "/api/datacenter/documents/upload",
                files={"file": ("report.docx", b"PK fake docx content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_upload_txt_success(self, client):
        """上传 .txt 文件成功。"""
        mock_resp = _make_ragflow_http_response({"code": 0, "data": []})
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.post(
                "/api/datacenter/documents/upload",
                files={"file": ("notes.txt", b"plain text content", "text/plain")},
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_upload_invalid_format_rejected(self, client):
        """上传非白名单格式（如 .jpg）返回 415。"""
        resp = await client.post(
            "/api/datacenter/documents/upload",
            files={"file": ("image.jpg", b"fake image bytes", "image/jpeg")},
        )
        assert resp.status_code == 415
        assert "不支持" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_excel_rejected_for_documents(self, client):
        """文档端点拒绝 .xlsx（属于数据集格式，非知识库文档格式）。"""
        resp = await client.post(
            "/api/datacenter/documents/upload",
            files={"file": ("data.xlsx", b"fake excel", "application/vnd.ms-excel")},
        )
        assert resp.status_code == 415

    @pytest.mark.asyncio
    async def test_upload_file_too_large_rejected(self, client):
        """文件超过 50MB 返回 413。"""
        large_content = b"x" * (51 * 1024 * 1024)  # 51 MB
        resp = await client.post(
            "/api/datacenter/documents/upload",
            files={"file": ("huge.pdf", large_content, "application/pdf")},
        )
        assert resp.status_code == 413
        assert "50 MB" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_ragflow_not_configured_returns_503(self, client):
        """未配置 RAGFlow 时返回 503。"""
        mock_settings = MagicMock()
        mock_settings.RAGFLOW_API_KEY = ""
        mock_settings.RAGFLOW_DATASET_ID = ""
        mock_settings.RAGFLOW_API_URL = ""
        mock_settings.RAGFLOW_RERANK_ID = ""

        with patch("app.api.routes_datacenter.settings", mock_settings):
            resp = await client.post(
                "/api/datacenter/documents/upload",
                files={"file": ("test.pdf", b"fake pdf", "application/pdf")},
            )

        assert resp.status_code == 503
        assert "RAGFlow" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_ragflow_connection_error_returns_502(self, client):
        """RAGFlow 连接失败返回 502。"""
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.post = AsyncMock(
            side_effect=httpx.ConnectError("连接被拒绝")
        )

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.post(
                "/api/datacenter/documents/upload",
                files={"file": ("test.pdf", b"fake pdf", "application/pdf")},
            )

        assert resp.status_code == 502
        assert "连接失败" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_ragflow_http_error_propagated(self, client):
        """RAGFlow 返回 HTTP 错误时，转换并透传给客户端。"""
        mock_resp = _make_failing_ragflow_response(400, "文件格式错误")
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.post(
                "/api/datacenter/documents/upload",
                files={"file": ("test.pdf", b"fake pdf", "application/pdf")},
            )

        assert resp.status_code == 400
        assert "RAGFlow" in resp.json()["detail"]


class TestDocumentListAPI:
    """GET /api/datacenter/documents"""

    @pytest.mark.asyncio
    async def test_list_documents_success(self, client):
        """成功获取文档列表。"""
        ragflow_resp = {
            "code": 0,
            "data": {
                "docs": [
                    {"id": "doc-001", "name": "楼宇运维手册.pdf", "status": "1", "size": 1024000},
                    {"id": "doc-002", "name": "能耗数据字典.pdf", "status": "1", "size": 512000},
                ],
                "total": 2,
            }
        }
        mock_resp = _make_ragflow_http_response(ragflow_resp)
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.get("/api/datacenter/documents")

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    @pytest.mark.asyncio
    async def test_list_documents_with_pagination(self, client):
        """分页参数正确传递给 RAGFlow。"""
        mock_resp = _make_ragflow_http_response({"code": 0, "data": {"docs": [], "total": 0}})
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.get(
                "/api/datacenter/documents",
                params={"page": 2, "page_size": 10},
            )

        assert resp.status_code == 200
        call_kwargs = mock_http_client.get.call_args
        params = call_kwargs.kwargs.get("params", {})
        assert params.get("page") == 2
        assert params.get("page_size") == 10

    @pytest.mark.asyncio
    async def test_list_not_configured_returns_503(self, client):
        """未配置 RAGFlow 时返回 503。"""
        mock_settings = MagicMock()
        mock_settings.RAGFLOW_API_KEY = ""
        mock_settings.RAGFLOW_DATASET_ID = ""
        mock_settings.RAGFLOW_API_URL = ""
        mock_settings.RAGFLOW_RERANK_ID = ""

        with patch("app.api.routes_datacenter.settings", mock_settings):
            resp = await client.get("/api/datacenter/documents")

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_list_ragflow_connection_error(self, client):
        """RAGFlow 连接超时返回 502。"""
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.get = AsyncMock(
            side_effect=httpx.TimeoutException("请求超时")
        )

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.get("/api/datacenter/documents")

        assert resp.status_code == 502


class TestDocumentDeleteAPI:
    """DELETE /api/datacenter/documents/{doc_id}"""

    @pytest.mark.asyncio
    async def test_delete_document_success(self, client):
        """成功删除文档，RAGFlow 返回 code=0。"""
        ragflow_resp = {"code": 0, "message": "文档已删除"}
        mock_resp = _make_ragflow_http_response(ragflow_resp)
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.delete = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.delete("/api/datacenter/documents/doc-001")

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    @pytest.mark.asyncio
    async def test_delete_sends_correct_doc_id(self, client):
        """删除请求 body 中包含正确的文档 ID。"""
        mock_resp = _make_ragflow_http_response({"code": 0})
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.delete = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            await client.delete("/api/datacenter/documents/target-doc-xyz")

        call_kwargs = mock_http_client.delete.call_args
        content = call_kwargs.kwargs.get("content", b"")
        import json
        body = json.loads(content)
        assert "target-doc-xyz" in body["ids"]

    @pytest.mark.asyncio
    async def test_delete_not_configured_returns_503(self, client):
        """RAGFlow 未配置时删除返回 503。"""
        mock_settings = MagicMock()
        mock_settings.RAGFLOW_API_KEY = ""
        mock_settings.RAGFLOW_DATASET_ID = ""
        mock_settings.RAGFLOW_API_URL = ""

        with patch("app.api.routes_datacenter.settings", mock_settings):
            resp = await client.delete("/api/datacenter/documents/some-doc")

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_delete_ragflow_error_propagated(self, client):
        """RAGFlow 返回 404 错误时透传。"""
        mock_resp = _make_failing_ragflow_response(404, "文档不存在")
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.delete = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.delete("/api/datacenter/documents/nonexistent-doc")

        assert resp.status_code == 404


class TestDocumentParseAPI:
    """POST /api/datacenter/documents/{doc_id}/parse — 触发文档向量化解析"""

    @pytest.mark.asyncio
    async def test_parse_trigger_success(self, client):
        """成功触发向量化解析，RAGFlow 返回成功响应。"""
        ragflow_resp = {"code": 0, "message": "解析任务已提交"}
        mock_resp = _make_ragflow_http_response(ragflow_resp)
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.post("/api/datacenter/documents/doc-001/parse")

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    @pytest.mark.asyncio
    async def test_parse_sends_correct_document_id(self, client):
        """解析请求 payload 中包含正确的文档 ID。"""
        mock_resp = _make_ragflow_http_response({"code": 0})
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            await client.post("/api/datacenter/documents/parse-target-doc/parse")

        call_kwargs = mock_http_client.post.call_args
        payload = call_kwargs.kwargs.get("json", {})
        assert "parse-target-doc" in payload.get("document_ids", [])

    @pytest.mark.asyncio
    async def test_parse_not_configured_returns_503(self, client):
        """RAGFlow 未配置时返回 503。"""
        mock_settings = MagicMock()
        mock_settings.RAGFLOW_API_KEY = ""
        mock_settings.RAGFLOW_DATASET_ID = ""
        mock_settings.RAGFLOW_API_URL = ""

        with patch("app.api.routes_datacenter.settings", mock_settings):
            resp = await client.post("/api/datacenter/documents/doc-001/parse")

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_parse_ragflow_connection_error(self, client):
        """RAGFlow 连接失败时返回 502。"""
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.post = AsyncMock(
            side_effect=httpx.ConnectError("无法连接到 RAGFlow")
        )

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.post("/api/datacenter/documents/doc-001/parse")

        assert resp.status_code == 502
        assert "连接失败" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_parse_ragflow_http_error_propagated(self, client):
        """RAGFlow 返回 HTTP 错误时转换并透传。"""
        mock_resp = _make_failing_ragflow_response(500, "解析服务内部错误")
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            resp = await client.post("/api/datacenter/documents/doc-001/parse")

        assert resp.status_code == 500
        assert "RAGFlow" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_parse_calls_correct_ragflow_endpoint(self, client):
        """验证调用了正确的 RAGFlow /documents/run 端点。"""
        mock_resp = _make_ragflow_http_response({"code": 0})
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.api.routes_datacenter.httpx.AsyncClient", return_value=mock_http_client):
            await client.post("/api/datacenter/documents/doc-001/parse")

        call_args = mock_http_client.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "/documents/run" in url
