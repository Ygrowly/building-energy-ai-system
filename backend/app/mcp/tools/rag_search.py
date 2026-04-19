"""
阶段二：原子能力库 —— 混合检索工具（Tool 5）
=============================================
MCP 工具薄包装层，实际检索逻辑委托给 app.services.rag_engine。
"""
from __future__ import annotations

from app.schemas.mcp_schemas import (
    MCPError,
    RAGHybridSearchInput,
    RAGHybridSearchOutput,
)
from app.services.rag_engine import search_ragflow


async def rag_hybrid_search(
    inp: RAGHybridSearchInput,
) -> RAGHybridSearchOutput | MCPError:
    """
    调用 RAG 引擎进行混合检索。

    Pipeline（与 MCP 设计文档一致）：
      1. 元数据硬过滤 (Hard Filter)：device_id / building_type 过滤无关文档
      2. 向量召回 Top-20 候选
      3. BGE-Reranker 语义重排序 -> 保留 Top-K（默认 3）
      4. 父子索引补充：返回段落的同时带上父章节标题

    降级策略：RAGFlow 不可用时返回本地知识库结果，系统不崩溃。
    """
    metadata_filter = {}
    if inp.metadata_filter.device_id:
        metadata_filter["device_id"] = inp.metadata_filter.device_id
    if inp.metadata_filter.building_type:
        metadata_filter["building_type"] = inp.metadata_filter.building_type
    if inp.metadata_filter.doc_category:
        metadata_filter["doc_category"] = inp.metadata_filter.doc_category

    return await search_ragflow(
        query=inp.query,
        metadata_filter=metadata_filter or None,
        enable_rerank=inp.enable_rerank,
        top_k=inp.top_k,
    )
