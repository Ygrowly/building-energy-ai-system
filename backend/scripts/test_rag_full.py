#!/usr/bin/env python3
"""
RAG 模块全面测试脚本
=====================
测试内容：
  1. RAGFlow 连通性 & 认证
  2. 知识库文档列表（已上传文档数）
  3. 多类型查询的检索质量（相似度、片段数、来源文档）
  4. 响应速度（每次查询耗时 ms）
  5. Rerank 效果对比（开启 vs 关闭重排序）
  6. 后端 /api/chat RAG 通路（SSE 流）
  7. 汇总评分

用法：
  cd backend
  python scripts/test_rag_full.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path

# Windows GBK 终端兼容：强制 UTF-8 输出
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))
os.chdir(_backend_dir)

import httpx
from dotenv import load_dotenv
load_dotenv(_backend_dir / ".env", override=True)

# ────────────────────────────────────────────────────────────
# 配置
# ────────────────────────────────────────────────────────────
RAGFLOW_API_URL   = os.environ.get("RAGFLOW_API_URL", "").rstrip("/")
RAGFLOW_API_KEY   = os.environ.get("RAGFLOW_API_KEY", "")
RAGFLOW_DATASET_ID = os.environ.get("RAGFLOW_DATASET_ID", "")
RAGFLOW_RERANK_ID = os.environ.get("RAGFLOW_RERANK_ID", "")

BACKEND_BASE = os.environ.get("RAG_TEST_BASE_URL", "http://localhost:8000").rstrip("/")
E2E_USER     = os.environ.get("RAG_E2E_USER", "rag_e2e_test")
E2E_PASSWORD = os.environ.get("RAG_E2E_PASSWORD", "RagE2e1234")

# 测试查询集（模拟实际使用场景，覆盖截图中上传的建筑规范文档）
TEST_QUERIES = [
    {
        "label": "建筑节能-通用规范",
        "query": "建筑节能设计的基本要求和强制性规定是什么？",
        "expected_keywords": ["节能", "建筑", "设计", "规范"],
    },
    {
        "label": "智能化系统维护",
        "query": "建筑智能化系统运行维护的技术规范有哪些要求？",
        "expected_keywords": ["智能", "维护", "系统", "运行"],
    },
    {
        "label": "电气设计标准",
        "query": "建筑电气与智能化通用规范中的用电安全要求",
        "expected_keywords": ["电气", "用电", "安全", "规范"],
    },
    {
        "label": "预测性维护",
        "query": "设备预测性维护的通用要求和实施方法",
        "expected_keywords": ["预测", "维护", "设备", "维修"],
    },
    {
        "label": "暖通空调设计",
        "query": "民用建筑供暖通风与空气调节设计规范的主要内容",
        "expected_keywords": ["供暖", "通风", "空调", "设计"],
    },
    {
        "label": "热泵与冷水机组",
        "query": "冷水机组和热泵能效限定值及能效等级标准",
        "expected_keywords": ["冷水机组", "热泵", "能效", "等级"],
    },
    {
        "label": "设施管理质量",
        "query": "设施管理质量评价指南的关键指标和评估方法",
        "expected_keywords": ["设施管理", "质量", "评价", "指标"],
    },
    {
        "label": "建筑节能基本术语",
        "query": "建筑节能基本术语的定义和分类",
        "expected_keywords": ["节能", "术语", "定义", "建筑"],
    },
]

# ────────────────────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────────────────────
_PASS = "[通过]"
_FAIL = "[失败]"
_WARN = "[警告]"

def _hdr(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _ok(msg: str):   print(f"  [OK] {msg}")
def _err(msg: str):  print(f"  [ERR] {msg}")
def _info(msg: str): print(f"  [>>] {msg}")
def _warn(msg: str): print(f"  [!!] {msg}")


# ────────────────────────────────────────────────────────────
# 1. RAGFlow 连通性测试
# ────────────────────────────────────────────────────────────
async def test_connectivity() -> dict:
    _hdr("1. RAGFlow 连通性 & 认证")
    result = {"ok": False, "latency_ms": None}

    if not RAGFLOW_API_URL:
        _err("RAGFLOW_API_URL 未配置"); return result
    if not RAGFLOW_API_KEY:
        _err("RAGFLOW_API_KEY 未配置"); return result

    _info(f"目标: {RAGFLOW_API_URL}")
    _info(f"Dataset ID: {RAGFLOW_DATASET_ID}")
    _info(f"Rerank ID: {RAGFLOW_RERANK_ID or '未配置'}")

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as c:
            r = await c.get(
                RAGFLOW_API_URL,
                headers={"Authorization": f"Bearer {RAGFLOW_API_KEY}"},
            )
        latency = int((time.perf_counter() - t0) * 1000)
        result["latency_ms"] = latency
        _ok(f"根路径响应: HTTP {r.status_code}  ({latency} ms)")
        result["ok"] = True
    except httpx.ConnectError as e:
        _err(f"连接失败: {e}")
    except httpx.TimeoutException:
        _err("连接超时（>10s）")
    except Exception as e:
        _err(f"异常: {e}")

    return result


# ────────────────────────────────────────────────────────────
# 2. 知识库文档列表
# ────────────────────────────────────────────────────────────
async def test_document_list() -> dict:
    _hdr("2. 知识库文档列表")
    result = {"total": 0, "docs": []}

    if not RAGFLOW_DATASET_ID:
        _warn("未配置 RAGFLOW_DATASET_ID，跳过"); return result

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as c:
            r = await c.get(
                f"{RAGFLOW_API_URL}/api/v1/datasets/{RAGFLOW_DATASET_ID}/documents",
                headers={"Authorization": f"Bearer {RAGFLOW_API_KEY}"},
                params={"page": 1, "page_size": 30},
            )
        if r.status_code != 200:
            _err(f"HTTP {r.status_code}: {r.text[:200]}"); return result

        data = r.json()
        docs_raw = data.get("data", {})
        if isinstance(docs_raw, dict):
            docs_list = docs_raw.get("docs", []) or docs_raw.get("documents", [])
            total = docs_raw.get("total", len(docs_list))
        elif isinstance(docs_raw, list):
            docs_list = docs_raw
            total = len(docs_raw)
        else:
            docs_list = []; total = 0

        result["total"] = total
        result["docs"] = docs_list

        _ok(f"文档总数: {total} 份")
        for i, doc in enumerate(docs_list[:10], 1):
            name  = doc.get("name", doc.get("doc_name", "未知"))
            run   = doc.get("run",  doc.get("parse_status", "?"))
            chunks = doc.get("chunk_count", doc.get("chunk_num", "?"))
            size  = doc.get("size", 0)
            size_kb = f"{size/1024:.1f} KB" if isinstance(size, (int, float)) and size else ""
            _info(f"  [{i:>2}] {name}  状态={run}  chunks={chunks}  {size_kb}")
        if total > 10:
            _info(f"  ... 共 {total} 份，仅展示前 10 份")

    except Exception as e:
        _err(f"获取文档列表失败: {e}")

    return result


# ────────────────────────────────────────────────────────────
# 3. RAG 检索质量 & 响应速度
# ────────────────────────────────────────────────────────────
async def _single_retrieval(
    query: str,
    top_k: int = 5,
    enable_rerank: bool = True,
) -> dict:
    """向 RAGFlow /api/v1/retrieval 发起一次检索，返回结果和耗时。"""
    payload: dict = {
        "question": query,
        "dataset_ids": [RAGFLOW_DATASET_ID],
        "top_k": top_k * 10,
        "page": 1,
        "page_size": top_k,
        "similarity_threshold": 0.1,
        "vector_similarity_weight": 0.3,
        "keyword": True,
        "highlight": False,
    }
    if enable_rerank and RAGFLOW_RERANK_ID:
        payload["rerank_id"] = RAGFLOW_RERANK_ID

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as c:
            r = await c.post(
                f"{RAGFLOW_API_URL}/api/v1/retrieval",
                headers={"Authorization": f"Bearer {RAGFLOW_API_KEY}"},
                json=payload,
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}", "latency_ms": latency_ms}

        data = r.json()
        response_data = data.get("data", {})
        chunks = response_data.get("chunks", [])
        total  = response_data.get("total", len(chunks))

        results = []
        for c_ in chunks:
            sim = float(c_.get("similarity", 0.0))
            doc_name = (
                c_.get("document_keyword")
                or c_.get("document_name")
                or "unknown"
            )
            content_preview = (c_.get("content") or "")[:80].replace("\n", " ")
            results.append({
                "doc_name": doc_name,
                "similarity": round(min(sim, 1.0), 4),
                "content_preview": content_preview,
            })

        return {
            "ok": True,
            "latency_ms": latency_ms,
            "total": total,
            "results": results,
        }
    except httpx.TimeoutException:
        return {"ok": False, "error": "超时(>30s)", "latency_ms": int((time.perf_counter()-t0)*1000)}
    except Exception as e:
        return {"ok": False, "error": str(e), "latency_ms": int((time.perf_counter()-t0)*1000)}


async def test_retrieval_quality() -> dict:
    _hdr("3. 检索质量 & 响应速度")

    summary = {
        "total_queries": len(TEST_QUERIES),
        "success": 0,
        "fail": 0,
        "latencies_ms": [],
        "avg_top1_similarity": [],
        "details": [],
    }

    for item in TEST_QUERIES:
        label = item["label"]
        query = item["query"]
        print(f"\n  ▶ [{label}]")
        print(f"    查询: {query}")

        res = await _single_retrieval(query, top_k=5, enable_rerank=True)

        if not res["ok"]:
            _err(f"    失败: {res.get('error')}  ({res['latency_ms']} ms)")
            summary["fail"] += 1
            summary["details"].append({"label": label, "ok": False})
            continue

        summary["success"] += 1
        summary["latencies_ms"].append(res["latency_ms"])
        results = res["results"]

        top1_sim = results[0]["similarity"] if results else 0.0
        summary["avg_top1_similarity"].append(top1_sim)

        # 检查是否命中期望关键词
        all_content = " ".join(r["content_preview"] + r["doc_name"] for r in results)
        hits = sum(1 for kw in item["expected_keywords"] if kw in all_content)
        hit_rate = hits / len(item["expected_keywords"])

        status = _PASS if top1_sim >= 0.3 else _WARN
        print(f"    耗时: {res['latency_ms']} ms | 召回: {res['total']} 片段 | Top-1 相似度: {top1_sim:.4f} | 关键词命中: {hits}/{len(item['expected_keywords'])}")

        for i, r in enumerate(results[:3], 1):
            print(f"    [{i}] {r['doc_name'][:45]}  sim={r['similarity']:.4f}")
            print(f"        {r['content_preview'][:70]}...")

        summary["details"].append({
            "label": label,
            "ok": True,
            "latency_ms": res["latency_ms"],
            "top1_sim": top1_sim,
            "hit_rate": hit_rate,
            "retrieved": res["total"],
        })

    return summary


# ────────────────────────────────────────────────────────────
# 4. Rerank 对比测试（同一查询，开启 vs 关闭重排序）
# ────────────────────────────────────────────────────────────
async def test_rerank_comparison() -> None:
    _hdr("4. Rerank 重排序效果对比")

    if not RAGFLOW_RERANK_ID:
        _warn("未配置 RAGFLOW_RERANK_ID，跳过对比")
        return

    query = "建筑节能设计标准中关于围护结构传热系数的限值要求"
    print(f"  查询: {query}\n")

    # 关闭 rerank
    r_no  = await _single_retrieval(query, top_k=3, enable_rerank=False)
    # 开启 rerank
    r_yes = await _single_retrieval(query, top_k=3, enable_rerank=True)

    print(f"  {'未启用 Rerank':^40}  {'启用 Rerank':^40}")
    print(f"  耗时: {r_no.get('latency_ms','?')} ms{' ':30}耗时: {r_yes.get('latency_ms','?')} ms")

    res_no  = r_no.get("results",  [])
    res_yes = r_yes.get("results", [])
    max_len = max(len(res_no), len(res_yes))

    for i in range(max_len):
        a = res_no[i]  if i < len(res_no)  else {}
        b = res_yes[i] if i < len(res_yes) else {}
        a_str = f"sim={a.get('similarity','?'):.4f}  {str(a.get('doc_name',''))[:30]}" if a else "(无)"
        b_str = f"sim={b.get('similarity','?'):.4f}  {str(b.get('doc_name',''))[:30]}" if b else "(无)"
        print(f"  [{i+1}] {a_str:<40}  {b_str}")


# ────────────────────────────────────────────────────────────
# 5. 后端 API 通路测试（/api/chat SSE）
# ────────────────────────────────────────────────────────────
async def get_token_for_backend(client: httpx.AsyncClient) -> str | None:
    try:
        r = await client.post(
            f"{BACKEND_BASE}/api/auth/login",
            json={"username": E2E_USER, "password": E2E_PASSWORD},
        )
        if r.status_code == 200:
            return r.json().get("access_token")

        # 尝试注册
        r2 = await client.post(
            f"{BACKEND_BASE}/api/auth/register",
            json={"username": E2E_USER, "password": E2E_PASSWORD, "email": "rag-test@test.local"},
        )
        if r2.status_code in (200, 201):
            return r2.json().get("access_token")

        # 用户已存在，再次登录
        if r2.status_code in (409, 400):
            r3 = await client.post(
                f"{BACKEND_BASE}/api/auth/login",
                json={"username": E2E_USER, "password": E2E_PASSWORD},
            )
            if r3.status_code == 200:
                return r3.json().get("access_token")
    except Exception as e:
        _err(f"获取 token 失败: {e}")
    return None


async def test_backend_rag_api() -> dict:
    _hdr("5. 后端 RAG API 通路测试（SSE 流）")
    result = {"rag_called": False, "latency_ms": None, "ok": False}

    query = "建筑节能通用规范对新建建筑的节能强制性要求是什么？"
    print(f"  查询: {query}")

    try:
        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            # 健康检查
            try:
                hc = await client.get(f"{BACKEND_BASE}/health", timeout=5.0)
                if hc.status_code != 200:
                    _warn(f"后端健康检查返回 {hc.status_code}")
            except Exception:
                _err("后端不可达，跳过此测试"); return result

            token = await get_token_for_backend(client)
            if not token:
                _err("无法获取认证 token，跳过"); return result
            _ok(f"登录成功，token 前 16 字符: {token[:16]}...")

            events = []
            tool_calls: list[str] = []
            final_text = ""
            t0 = time.perf_counter()

            headers = {"Authorization": f"Bearer {token}"}
            async with client.stream(
                "POST",
                f"{BACKEND_BASE}/api/chat",
                json={"message": query},
                headers=headers,
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    _err(f"对话请求失败: HTTP {resp.status_code}"); return result

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        ev = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    events.append(ev)
                    kind = ev.get("type", "")
                    msg  = str(ev.get("message", "") or ev.get("content", ""))

                    if kind == "thinking" and "调用工具：" in msg:
                        tool_name = msg.split("调用工具：", 1)[-1].strip()
                        if tool_name and tool_name not in tool_calls:
                            tool_calls.append(tool_name)
                    if kind == "text" and ev.get("content"):
                        final_text = ev["content"]
                    if "rag_hybrid_search" in msg and "rag_hybrid_search" not in tool_calls:
                        tool_calls.append("rag_hybrid_search")

            latency_ms = int((time.perf_counter() - t0) * 1000)
            result["latency_ms"] = latency_ms

            rag_called = "rag_hybrid_search" in tool_calls
            result["rag_called"] = rag_called
            result["ok"] = True

            _ok(f"SSE 流完成  总耗时: {latency_ms} ms")
            _info(f"工具调用链: {' → '.join(tool_calls) if tool_calls else '(无工具调用记录)'}")
            _info(f"RAG 工具调用: {'是' if rag_called else '否（可能路由到其他 Agent）'}")
            _info(f"回复长度: {len(final_text)} 字符")
            if final_text:
                preview = final_text[:250].replace("\n", " ")
                print(f"\n  --- 回复摘要 ---\n  {preview}...\n  ─────────────────")

    except Exception as e:
        _err(f"SSE 测试异常: {e}")

    return result


# ────────────────────────────────────────────────────────────
# 汇总报告
# ────────────────────────────────────────────────────────────
def print_summary(
    conn: dict,
    docs: dict,
    quality: dict,
    backend: dict,
):
    _hdr("测试汇总报告")

    # 连通性
    conn_str = f"{_PASS}（{conn.get('latency_ms')} ms）" if conn.get("ok") else _FAIL
    print(f"  RAGFlow 连通性:    {conn_str}")

    # 文档数
    total_docs = docs.get("total", 0)
    print(f"  知识库文档数量:    {total_docs} 份")

    # 检索质量
    success = quality.get("success", 0)
    fail    = quality.get("fail",    0)
    lats    = quality.get("latencies_ms", [])
    sims    = quality.get("avg_top1_similarity", [])
    avg_lat = int(sum(lats) / len(lats)) if lats else 0
    max_lat = max(lats) if lats else 0
    min_lat = min(lats) if lats else 0
    avg_sim = round(sum(sims) / len(sims), 4) if sims else 0.0

    print(f"\n  检索测试结果:      {success}/{success+fail} 成功")
    print(f"  平均响应时间:      {avg_lat} ms  (min={min_lat} ms, max={max_lat} ms)")
    print(f"  平均 Top-1 相似度: {avg_sim:.4f}")

    # 速度评级
    if avg_lat < 1000:
        speed_grade = "极快 (< 1s)"
    elif avg_lat < 2000:
        speed_grade = "快速 (1-2s)"
    elif avg_lat < 4000:
        speed_grade = "正常 (2-4s)"
    else:
        speed_grade = "偏慢 (> 4s)"
    print(f"  响应速度评级:      {speed_grade}")

    # 相似度评级
    if avg_sim >= 0.6:
        qual_grade = "优秀 (≥ 0.6)"
    elif avg_sim >= 0.4:
        qual_grade = "良好 (0.4-0.6)"
    elif avg_sim >= 0.2:
        qual_grade = "一般 (0.2-0.4)"
    else:
        qual_grade = "较差 (< 0.2，建议检查向量化状态)"
    print(f"  检索质量评级:      {qual_grade}")

    # 各查询明细
    print("\n  ┌─────────────────────────────┬──────────┬──────────┬────────────┐")
    print("  │ 查询类别                    │ 耗时(ms) │ Top-1 相似度 │ 召回片段 │")
    print("  ├─────────────────────────────┼──────────┼──────────┼────────────┤")
    for d in quality.get("details", []):
        if not d.get("ok"):
            print(f"  │ {d['label']:<27} │   失败   │    -     │     -      │")
        else:
            print(f"  │ {d['label']:<27} │ {d['latency_ms']:>6}   │  {d['top1_sim']:.4f}  │ {d['retrieved']:>6}     │")
    print("  └─────────────────────────────┴──────────┴──────────┴────────────┘")

    # 后端通路
    if backend.get("ok"):
        rag_flag = "是" if backend.get("rag_called") else "否（其他 Agent 处理）"
        print(f"\n  后端 RAG 通路:     OK（{backend.get('latency_ms')} ms）  RAG 工具触发: {rag_flag}")
    else:
        print(f"\n  后端 RAG 通路:     未测试 / 失败")

    # 综合评分
    score = 0
    if conn.get("ok"):       score += 20
    if total_docs > 0:       score += 20
    if success >= len(TEST_QUERIES) * 0.8: score += 20
    if avg_sim >= 0.3:       score += 20
    if avg_lat < 3000:       score += 10
    if backend.get("ok"):    score += 10

    print(f"\n  综合健康得分:      {score}/100")
    if score >= 80:
        print("  → RAG 模块运行良好 ✓")
    elif score >= 50:
        print("  → RAG 模块基本可用，部分功能需关注 ⚠")
    else:
        print("  → RAG 模块存在问题，请检查 RAGFlow 服务和向量化状态 ✗")


# ────────────────────────────────────────────────────────────
# 入口
# ────────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("  RAG 模块全面测试")
    print("=" * 60)
    print(f"  RAGFlow URL: {RAGFLOW_API_URL}")
    print(f"  后端地址:    {BACKEND_BASE}")

    conn    = await test_connectivity()
    if not conn.get("ok"):
        print("\n  RAGFlow 不可达，中止检索测试。")
        print_summary(conn, {}, {"success":0,"fail":0,"latencies_ms":[],"avg_top1_similarity":[],"details":[]}, {})
        return 1

    docs    = await test_document_list()
    quality = await test_retrieval_quality()
    await test_rerank_comparison()
    backend = await test_backend_rag_api()
    print_summary(conn, docs, quality, backend)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
