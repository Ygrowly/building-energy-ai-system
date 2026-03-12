"""临时脚本：测试 RAGFlow /api/v1/retrieval 接口连通性"""
import asyncio
import httpx

RAGFLOW_API_URL = "http://localhost:9380"
RAGFLOW_API_KEY = "ragflow-jnCVt29S_excBlC1UPvpilfIhOzmp_B06fU36M2Iv6M"
RAGFLOW_DATASET_ID = "b7f9fd9a1d1411f19580178d9b889381"


async def main():
    payload = {
        "question": "能耗异常怎么排查",
        "dataset_ids": [RAGFLOW_DATASET_ID],
        "top_k": 10,
        "page": 1,
        "page_size": 3,
        "similarity_threshold": 0.2,
        "vector_similarity_weight": 0.3,
        "keyword": True,
        "highlight": False,
    }
    headers = {"Authorization": f"Bearer {RAGFLOW_API_KEY}"}
    print(f">>> POST {RAGFLOW_API_URL}/api/v1/retrieval")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{RAGFLOW_API_URL}/api/v1/retrieval",
                headers=headers,
                json=payload,
            )
            print(f"HTTP Status: {resp.status_code}")
            data = resp.json()
            print(f"code: {data.get('code')}")
            print(f"message: {data.get('message', '')}")
            chunks = data.get("data", {}).get("chunks", [])
            total = data.get("data", {}).get("total", 0)
            print(f"total chunks in kb: {total}, returned: {len(chunks)}")
            # 构建 doc_id → doc_name 查找表
            doc_id_map = {
                a["doc_id"]: a["doc_name"]
                for a in data.get("data", {}).get("doc_aggs", [])
                if "doc_id" in a
            }
            for i, c in enumerate(chunks):
                doc_id = c.get("document_id", "")
                doc_name = doc_id_map.get(doc_id) or c.get("document_keyword") or c.get("document_name", "?")
                print(f"\n--- Chunk {i+1} ---")
                print(f"  doc: {doc_name}")
                print(f"  similarity: {c.get('similarity')}  vector_similarity: {c.get('vector_similarity')}")
                print(f"  content[:120]: {str(c.get('content', ''))[:120]}")
    except httpx.ConnectError as e:
        print(f"[连接失败] RAGFlow 服务未启动或地址不对: {e}")
    except Exception as e:
        print(f"[错误] {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
