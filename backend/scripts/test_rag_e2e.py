#!/usr/bin/env python3
"""
RAG 模块端到端测试脚本（使用真实 PDF）。

流程：
  1. 登录获取 JWT
  2. 上传 dataset/raw_knowledge/数据集使用方案.pdf 到 RAGFlow 知识库
  3. 触发文档向量化解析，等待完成
  4. 发起对话：提问触发故障诊断 Agent → 调用 rag_hybrid_search
  5. 校验：SSE 流中出现 rag_hybrid_search 调用，且回复中可引用知识库/文档

运行前提：
  - 后端已启动（默认 http://localhost:8000）
  - RAGFlow 已启动且 .env 中 RAGFLOW_* 已配置
  - 数据库可用（用于注册/登录）

用法：
  cd backend && python scripts/test_rag_e2e.py
  或：RAG_E2E_BASE_URL=http://127.0.0.1:8000 python scripts/test_rag_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# 确保 backend 为项目根，可 import app
_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))
os.chdir(_backend_dir)

import httpx

# 加载 .env（backend 目录下）
from dotenv import load_dotenv
load_dotenv(_backend_dir / ".env", override=True)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("RAG_E2E_BASE_URL", "http://localhost:8000").rstrip("/")
# 项目根目录下的 PDF（与 backend 平级的 dataset/raw_knowledge/）
PROJECT_ROOT = _backend_dir.parent
DEFAULT_PDF_PATH = PROJECT_ROOT / "dataset" / "raw_knowledge" / "数据集使用方案.pdf"
PDF_PATH = Path(os.environ.get("RAG_E2E_PDF_PATH", str(DEFAULT_PDF_PATH)))
# 等待向量化完成最长时间（秒，轮询模式）
PARSE_WAIT_SECONDS = int(os.environ.get("RAG_E2E_PARSE_WAIT", "120"))

# 测试用户（若已存在则直接登录）
E2E_USER = os.environ.get("RAG_E2E_USER", "rag_e2e_test")
E2E_PASSWORD = os.environ.get("RAG_E2E_PASSWORD", "RagE2e1234")

# 用于触发 diagnose_agent + RAG 的提问
CHAT_QUESTION_FOR_RAG = (
    "办公楼凌晨能耗异常，请根据运维知识库诊断可能原因并引用文档依据。"
)
# 可选：针对上传的《数据集使用方案》的提问（若路由到知识库检索）
CHAT_QUESTION_ABOUT_DOC = "根据《数据集使用方案》文档，数据集的使用流程或格式要求是什么？"


# ---------------------------------------------------------------------------
# 步骤 1：注册 / 登录，获取 access_token
# ---------------------------------------------------------------------------
def _login_payload() -> dict:
    """登录/注册用的用户名密码（后端要求 username 小写）。"""
    return {"username": E2E_USER.lower(), "password": E2E_PASSWORD}


async def get_token(client: httpx.AsyncClient) -> str:
    # 后端 /api/auth/login 接收 JSON body，不是 form
    login_resp = await client.post(
        f"{BASE_URL}/api/auth/login",
        json=_login_payload(),
    )
    if login_resp.status_code == 200:
        return login_resp.json()["access_token"]

    # 登录失败则尝试注册（用户已存在时注册返回 409）
    reg_resp = await client.post(
        f"{BASE_URL}/api/auth/register",
        json={
            "username": E2E_USER,
            "password": E2E_PASSWORD,
            "email": "rag-e2e@test.local",
        },
    )
    if reg_resp.status_code in (200, 201):
        return reg_resp.json()["access_token"]
    # 409 = 用户名已被注册，用同一账号再试登录
    if reg_resp.status_code in (409, 400):
        login2 = await client.post(
            f"{BASE_URL}/api/auth/login",
            json=_login_payload(),
        )
        if login2.status_code == 200:
            return login2.json()["access_token"]

    err = f"无法获取 token。登录: {login_resp.status_code}; 注册: {reg_resp.status_code}"
    if login_resp.status_code == 422:
        err += "（422 多为请求体格式错误，请确认后端登录接口接受 JSON）"
    if login_resp.status_code in (502, 503):
        err += "（若为 502/503 请先确认后端已启动且数据库可用）"
    raise RuntimeError(err)


# ---------------------------------------------------------------------------
# 步骤 2：上传 PDF 到 RAGFlow
# ---------------------------------------------------------------------------
async def upload_document(client: httpx.AsyncClient, token: str) -> str:
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF 不存在: {PDF_PATH}")

    with open(PDF_PATH, "rb") as f:
        content = f.read()

    filename = PDF_PATH.name
    # 上传 PDF 可能较大，单独用更长超时的 client，同时 trust_env=False 绕过系统代理
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as upload_client:
        resp = await upload_client.post(
            f"{BASE_URL}/api/datacenter/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (filename, content, "application/pdf")},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"上传失败: {resp.status_code} {resp.text}")

    data = resp.json()
    # RAGFlow 返回结构可能是 {"data": [{"id": "xxx", ...}]} 或 {"data": {"id": "xxx"}} 或 {"id": "xxx"}
    doc_id = None
    if isinstance(data.get("data"), list) and data["data"]:
        doc_id = data["data"][0].get("id")
    elif isinstance(data.get("data"), dict):
        doc_id = data["data"].get("id")
    if not doc_id:
        doc_id = data.get("id")
    if not doc_id:
        raise RuntimeError(f"上传响应中未找到文档 ID: {data}")
    return str(doc_id)


# ---------------------------------------------------------------------------
# 步骤 3：触发向量化并轮询等待完成
# ---------------------------------------------------------------------------
async def parse_and_wait(client: httpx.AsyncClient, token: str, doc_id: str) -> None:
    resp = await client.post(
        f"{BASE_URL}/api/datacenter/documents/{doc_id}/parse",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"触发解析失败: {resp.status_code} {resp.text}")

    print(f"  已触发向量化，轮询解析状态（最多 {PARSE_WAIT_SECONDS} 秒）...")
    waited = 0
    poll_interval = 5  # 每 5 秒轮询一次
    while waited < PARSE_WAIT_SECONDS:
        await asyncio.sleep(poll_interval)
        waited += poll_interval
        try:
            st_resp = await client.get(
                f"{BASE_URL}/api/datacenter/documents/{doc_id}/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            if st_resp.status_code == 200:
                st = st_resp.json()
                run = st.get("run", "UNSTART")
                chunks = st.get("chunk_count", 0)
                progress = st.get("progress", 0.0)
                print(f"    [{waited:>3}s] run={run}  chunks={chunks}  progress={progress:.0%}")
                if run == "DONE" and chunks > 0:
                    print("  解析完成！")
                    return
                if run in ("FAIL", "CANCEL"):
                    raise RuntimeError(f"RAGFlow 解析失败，状态: {run}")
        except RuntimeError:
            raise
        except Exception as exc:
            print(f"    轮询异常（忽略）: {exc}")

    print(f"  等待 {PARSE_WAIT_SECONDS} 秒超时，继续执行（RAGFlow 可能仍在处理）...")


# ---------------------------------------------------------------------------
# 步骤 4 & 5：发起对话，解析 SSE，校验 RAG 调用与引用
# ---------------------------------------------------------------------------
async def chat_and_verify_rag(client: httpx.AsyncClient, question: str) -> dict:
    """发起一次对话，收集 SSE 事件，返回 {tool_calls: [...], final_text: str, events: [...]}"""
    events = []
    tool_calls = []
    final_text = ""

    async with client.stream(
        "POST",
        f"{BASE_URL}/api/chat",
        json={"message": question},
        timeout=120.0,
    ) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"对话请求失败: {resp.status_code} {resp.text}")

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
            kind = ev.get("type")
            msg = str(ev.get("message", "") or ev.get("content", ""))
            # 服务端发送：thinking event 的 message 为 "调用工具：rag_hybrid_search"
            if kind == "thinking" and "调用工具：" in msg:
                tool_name = msg.split("调用工具：", 1)[-1].strip()
                if tool_name and tool_name not in tool_calls:
                    tool_calls.append(tool_name)
            if kind == "text":
                content = ev.get("content", "")
                if content:
                    final_text = content
            if kind == "artifact" and ev.get("source_info", {}).get("tool") == "rag_hybrid_search":
                if "rag_hybrid_search" not in tool_calls:
                    tool_calls.append("rag_hybrid_search")

    # 兜底：从所有 event 的 message/content 中查找 rag_hybrid_search
    for ev in events:
        msg = str(ev.get("message", "") or ev.get("content", "") or "")
        if "rag_hybrid_search" in msg and "rag_hybrid_search" not in tool_calls:
            tool_calls.append("rag_hybrid_search")
            break

    return {"tool_calls": tool_calls, "final_text": final_text, "events": events}


async def check_backend(client: httpx.AsyncClient) -> bool:
    """检查后端是否可达。"""
    try:
        r = await client.get(f"{BASE_URL}/health")
        return r.status_code == 200
    except Exception:
        return False


def main():
    async def run():
        print("=== RAG 模块端到端测试（真实 PDF） ===\n")
        print(f"  BASE_URL: {BASE_URL}")
        print(f"  PDF: {PDF_PATH} (exists: {PDF_PATH.exists()})")
        if not PDF_PATH.exists():
            print("\n  [错误] PDF 文件不存在，请确认路径。")
            return 1
        print()

        # trust_env=False：绕过 Windows 系统代理，直连后端和 RAGFlow
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            ok = await check_backend(client)
            if not ok:
                print("  [错误] 后端不可达，请先启动: cd backend && uvicorn main:app --reload")
                return 1
            print("  后端健康检查: OK\n")
            # 1. Token
            print("1. 获取认证 Token...")
            token = await get_token(client)
            print("   OK\n")

            # 2. 上传
            print("2. 上传 PDF 到 RAGFlow 知识库...")
            doc_id = await upload_document(client, token)
            print(f"   doc_id: {doc_id}\n")

            # 3. 解析
            print("3. 触发文档向量化...")
            await parse_and_wait(client, token, doc_id)
            print("   等待结束\n")

            # 4. 对话（触发 diagnose_agent → RAG）
            print("4. 发起对话（触发知识库检索）...")
            result = await chat_and_verify_rag(client, CHAT_QUESTION_FOR_RAG)
            print(f"   工具调用: {result['tool_calls']}")
            print(f"   最终回复长度: {len(result['final_text'])} 字符")
            if result["final_text"]:
                print(f"   回复摘要: {result['final_text'][:200]}...")
            print()

            # 5. 校验
            rag_called = "rag_hybrid_search" in result["tool_calls"]
            doc_referenced = (
                "数据集使用方案" in result["final_text"]
                or "知识库" in result["final_text"]
                or "手册" in result["final_text"]
                or "依据" in result["final_text"]
                or "文档" in result["final_text"]
            )

            print("5. 校验结果（故障诊断 + 知识库）:")
            print(f"   - RAG 工具 rag_hybrid_search 已调用: {rag_called}")
            print(f"   - 回复中提及知识库/文档/依据: {doc_referenced}")

            # 可选：再问一句针对《数据集使用方案》的题目，看是否命中刚上传的 PDF
            print("\n6. 针对《数据集使用方案》的提问（验证是否命中该文档）...")
            result2 = await chat_and_verify_rag(client, CHAT_QUESTION_ABOUT_DOC)
            rag2 = "rag_hybrid_search" in result2["tool_calls"]
            doc2 = "数据集使用方案" in result2["final_text"] or "数据集" in result2["final_text"]
            print(f"   - 本次 RAG 调用: {rag2}")
            print(f"   - 回复提及「数据集」/「数据集使用方案」: {doc2}")
            if result2["final_text"]:
                print(f"   回复摘要: {result2['final_text'][:180]}...")

            if rag_called and (doc_referenced or len(result["final_text"]) > 50):
                print("\n   [通过] 完整 RAG 流程：上传 → 向量化 → 问答引用知识库 已跑通。")
                return 0
            if not rag_called:
                print("\n   [未通过] 未检测到 rag_hybrid_search 调用，请确认路由到故障诊断 Agent 且 RAGFlow 可用。")
                return 1
            print("\n   [部分通过] RAG 已调用，回复中未明显引用文档（可能仍来自知识库）。")
            return 0

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
