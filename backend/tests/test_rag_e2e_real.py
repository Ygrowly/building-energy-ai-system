"""
RAG 模块端到端集成测试（使用真实 PDF：dataset/raw_knowledge/数据集使用方案.pdf）。

覆盖：上传 → 触发向量化 → 对话触发 rag_hybrid_search → 校验回复引用知识库。

运行前提：
  - 后端已启动（默认 http://localhost:8000）
  - RAGFlow 已启动且 .env 中 RAGFLOW_* 已配置
  - 数据库可用

默认跳过（避免 CI 依赖外部服务）。显式运行方式：
  RAG_E2E_RUN=1 pytest tests/test_rag_e2e_real.py -v -s
  或：pytest tests/test_rag_e2e_real.py -v -s -m e2e
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

# 项目根、backend 目录
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
PDF_PATH = PROJECT_ROOT / "dataset" / "raw_knowledge" / "数据集使用方案.pdf"

BASE_URL = os.environ.get("RAG_E2E_BASE_URL", "http://localhost:8000").rstrip("/")
PARSE_WAIT = int(os.environ.get("RAG_E2E_PARSE_WAIT", "25"))
E2E_USER = os.environ.get("RAG_E2E_USER", "rag_e2e_test")
E2E_PASSWORD = os.environ.get("RAG_E2E_PASSWORD", "RagE2e1234")

CHAT_QUESTION = "办公楼凌晨能耗异常，请根据运维知识库诊断可能原因并引用文档依据。"


def _skip_if_not_e2e():
    if not os.environ.get("RAG_E2E_RUN"):
        pytest.skip("需要 RAG_E2E_RUN=1 或 -m e2e 才运行真实 E2E")
    if not PDF_PATH.exists():
        pytest.skip(f"真实 PDF 不存在: {PDF_PATH}")


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _e2e_login_payload():
    return {"username": E2E_USER.lower(), "password": E2E_PASSWORD}


@pytest.fixture(scope="module")
async def token():
    _skip_if_not_e2e()
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{BASE_URL}/health")
        if r.status_code != 200:
            pytest.skip(f"后端不可达: {BASE_URL}")
        login = await client.post(
            f"{BASE_URL}/api/auth/login",
            json=_e2e_login_payload(),
        )
        if login.status_code == 200:
            yield login.json()["access_token"]
            return
        reg = await client.post(
            f"{BASE_URL}/api/auth/register",
            json={"username": E2E_USER, "password": E2E_PASSWORD, "email": "e2e@test.local"},
        )
        if reg.status_code in (200, 201):
            yield reg.json()["access_token"]
            return
        if reg.status_code in (409, 400):
            login2 = await client.post(
                f"{BASE_URL}/api/auth/login",
                json=_e2e_login_payload(),
            )
            if login2.status_code == 200:
                yield login2.json()["access_token"]
                return
        pytest.fail(f"无法获取 token: login={login.status_code}, register={reg.status_code}")


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_rag_e2e_upload_parse_and_chat_calls_rag(token):
    """完整流程：上传真实 PDF → 向量化 → 对话 → 校验 RAG 被调用且回复引用知识库。"""
    _skip_if_not_e2e()
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. 上传
        with open(PDF_PATH, "rb") as f:
            content = f.read()
        upload_resp = await client.post(
            f"{BASE_URL}/api/datacenter/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (PDF_PATH.name, content, "application/pdf")},
        )
        assert upload_resp.status_code == 200, upload_resp.text
        data = upload_resp.json()
        doc_id = None
        if isinstance(data.get("data"), list) and data["data"]:
            doc_id = data["data"][0].get("id")
        elif isinstance(data.get("data"), dict):
            doc_id = data["data"].get("id")
        if not doc_id:
            doc_id = data.get("id")
        assert doc_id, f"未找到 doc_id: {data}"

        # 2. 触发解析
        parse_resp = await client.post(
            f"{BASE_URL}/api/datacenter/documents/{doc_id}/parse",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert parse_resp.status_code == 200, parse_resp.text

        # 3. 等待向量化
        await asyncio.sleep(PARSE_WAIT)

        # 4. 对话并收集 SSE
        tool_calls = []
        final_text = ""
        events = []
        async with client.stream(
            "POST",
            f"{BASE_URL}/api/chat",
            json={"message": CHAT_QUESTION},
            timeout=120.0,
        ) as resp:
            assert resp.status_code == 200, resp.text
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    continue
                try:
                    ev = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                events.append(ev)
                msg = str(ev.get("message", "") or ev.get("content", ""))
                if ev.get("type") == "thinking" and "调用工具：" in msg:
                    name = msg.split("调用工具：", 1)[-1].strip()
                    if name and name not in tool_calls:
                        tool_calls.append(name)
                if ev.get("type") == "text":
                    content = ev.get("content", "")
                    if content:
                        final_text = content

        for ev in events:
            msg = str(ev.get("message", "") or ev.get("content", "") or "")
            if "rag_hybrid_search" in msg and "rag_hybrid_search" not in tool_calls:
                tool_calls.append("rag_hybrid_search")
                break

        # 5. 断言
        assert "rag_hybrid_search" in tool_calls, (
            f"未检测到 RAG 调用。工具调用列表: {tool_calls}"
        )
        assert len(final_text) > 50, "回复过短，可能未正常返回"
        # 回复中应出现知识库/文档/依据等表述之一
        assert any(
            k in final_text for k in ("知识库", "手册", "依据", "文档", "检索")
        ), f"回复中未明显引用知识库: {final_text[:300]}..."
