#!/usr/bin/env python3
"""
RAGFlow 连通性诊断脚本（用于排查 502 / 连接失败）。

在后端所在机器上运行，检查：
  1. .env 中的 RAGFLOW_API_URL 是否可解析、可连接
  2. 对 RAGFlow 根路径和文档列表 API 的请求结果（状态码、响应体）

用法：cd backend && python scripts/check_ragflow_connection.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_dir))
os.chdir(_backend_dir)

from dotenv import load_dotenv
load_dotenv(_backend_dir / ".env", override=True)

import httpx

RAGFLOW_API_URL = os.environ.get("RAGFLOW_API_URL", "").rstrip("/")
RAGFLOW_API_KEY = os.environ.get("RAGFLOW_API_KEY", "")
RAGFLOW_DATASET_ID = os.environ.get("RAGFLOW_DATASET_ID", "")


def main():
    print("=== RAGFlow 连通性诊断 ===\n")
    print(f"  RAGFLOW_API_URL:      {RAGFLOW_API_URL or '(未设置)'}")
    print(f"  RAGFLOW_API_KEY:      {'已设置' if RAGFLOW_API_KEY else '(未设置)'}")
    print(f"  RAGFLOW_DATASET_ID:   {RAGFLOW_DATASET_ID or '(未设置)'}\n")

    if not RAGFLOW_API_URL:
        print("  [失败] 未配置 RAGFLOW_API_URL")
        return 1

    headers = {}
    if RAGFLOW_API_KEY:
        headers["Authorization"] = f"Bearer {RAGFLOW_API_KEY}"

    # 1) 请求根路径或常见健康路径（部分 RAGFlow 部署有 /health 或根路径返回 200/404）
    print("1. 请求 RAGFlow 根路径 GET", RAGFLOW_API_URL, "...")
    try:
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            r = client.get(RAGFLOW_API_URL, headers=headers)
        print(f"   状态码: {r.status_code}")
        if r.headers.get("content-type", "").startswith("application/json"):
            try:
                body = r.json()
                print(f"   响应(JSON): {body}")
            except Exception:
                print(f"   响应体(前200字): {r.text[:200]}")
        else:
            print(f"   响应体(前200字): {r.text[:200]}")
    except httpx.ConnectError as e:
        print(f"   [连接失败] {e}")
        print("   → 可能原因: 目标机器未开 RAGFlow、Tailscale 未连上、防火墙拦截、URL 或端口错误")
        return 1
    except httpx.TimeoutException as e:
        print(f"   [超时] {e}")
        print("   → 可能原因: 对端响应慢、网络不稳定、Tailscale 延迟高")
        return 1
    except Exception as e:
        print(f"   [异常] {type(e).__name__}: {e}")
        return 1

    # 2) 请求文档列表 API（上传时用的同一 base，可确认认证与 dataset 是否有效）
    if not RAGFLOW_DATASET_ID:
        print("\n2. 跳过文档列表检查（未配置 RAGFLOW_DATASET_ID）")
        return 0

    doc_list_url = f"{RAGFLOW_API_URL}/api/v1/datasets/{RAGFLOW_DATASET_ID}/documents"
    print("\n2. 请求文档列表 GET", doc_list_url, "...")
    try:
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            r = client.get(doc_list_url, headers=headers, params={"page": 1, "page_size": 1})
        print(f"   状态码: {r.status_code}")
        if r.status_code == 200:
            try:
                data = r.json()
                print(f"   响应: code={data.get('code')}, message={data.get('message', '')}")
                if "data" in data:
                    print(f"   data 键: {list(data['data'].keys()) if isinstance(data['data'], dict) else type(data['data'])}")
            except Exception:
                print(f"   响应体(前300字): {r.text[:300]}")
        else:
            print(f"   响应体: {r.text[:400]}")
            if r.status_code == 502:
                print("   → 502 通常表示: 对端网关/反向代理无法从上游拿到正常响应（RAGFlow 未监听对、崩溃或超时）")
            if r.status_code == 401:
                print("   → 401 表示: API Key 错误或未传")
    except httpx.ConnectError as e:
        print(f"   [连接失败] {e}")
        return 1
    except httpx.TimeoutException as e:
        print(f"   [超时] {e}")
        return 1
    except Exception as e:
        print(f"   [异常] {type(e).__name__}: {e}")
        return 1

    print("\n诊断结束。若根路径可通但文档 API 返回 502，请到 RAGFlow 所在机器检查服务是否监听 0.0.0.0、是否被 nginx 正确代理。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
