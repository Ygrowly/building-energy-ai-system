"""
数据中心路由模块。

提供两类端点：
  1. /datacenter/datasets/*   — CSV/Excel 数据集上传、预览、AI 分析
  2. /datacenter/documents/*  — PDF/Word 知识库文档管理（代理 RAGFlow API）
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import get_current_active_user
from app.db.models import DatasetFile, User
from app.db.session import AsyncSessionLocal
from app.services import data_analyzer

log = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/datacenter", tags=["数据中心"])

# 上传文件存储目录（相对于进程 cwd，即 backend/）
UPLOAD_DIR = Path("uploads/datasets")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_DATASET_TYPES = {".csv", ".xlsx", ".xls"}
ALLOWED_DOC_TYPES = {".pdf", ".docx", ".doc", ".txt", ".md"}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# ---------------------------------------------------------------------------
# 公共依赖
# ---------------------------------------------------------------------------

async def get_db() -> AsyncSession:  # type: ignore[override]
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# 数据集端点
# ---------------------------------------------------------------------------

@router.post("/datasets/upload", summary="上传数据集文件（CSV/Excel）")
async def upload_dataset(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    接受 CSV / XLSX / XLS 文件，解析后存储文件元信息到数据库。
    返回解析后的列信息和统计摘要，可直接用于前端预览。
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_DATASET_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"不支持的文件格式 '{suffix}'，请上传 .csv / .xlsx / .xls 文件",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="文件大小超过 50 MB 限制",
        )

    file_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{file_id}{suffix}"
    save_path.write_bytes(content)

    try:
        result = data_analyzer.analyze_file(str(save_path))
    except Exception as exc:
        save_path.unlink(missing_ok=True)
        log.exception("文件解析失败：%s", file.filename)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"文件解析失败：{exc}",
        ) from exc

    record = DatasetFile(
        id=file_id,
        original_name=file.filename or save_path.name,
        file_path=str(save_path),
        file_type=result["file_type"],
        row_count=result["row_count"],
        column_count=result["column_count"],
        columns_json=result["columns_json"],
        stats_json=result["stats_json"],
        uploader_id=current_user.id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return {
        "id": record.id,
        "original_name": record.original_name,
        "file_type": record.file_type,
        "row_count": record.row_count,
        "column_count": record.column_count,
        "uploaded_at": record.uploaded_at.isoformat(),
        "columns": result["columns"],
        "stats": result["stats"],
        "sample_rows": result["sample_rows"],
    }


@router.get("/datasets", summary="获取当前用户的数据集列表")
async def list_datasets(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(DatasetFile)
        .where(DatasetFile.uploader_id == current_user.id)
        .order_by(DatasetFile.uploaded_at.desc())
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "original_name": r.original_name,
            "file_type": r.file_type,
            "row_count": r.row_count,
            "column_count": r.column_count,
            "uploaded_at": r.uploaded_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/datasets/{dataset_id}", summary="获取数据集详情（含列信息、统计、样本数据）")
async def get_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    record = await _get_dataset_or_404(dataset_id, current_user.id, db)

    columns = json.loads(record.columns_json or "[]")
    stats = json.loads(record.stats_json or "{}")

    # 实时重新读取样本数据（避免存储大量行数据在 DB 中）
    try:
        analysis = data_analyzer.analyze_file(record.file_path)
        sample_rows = analysis["sample_rows"]
    except Exception:
        sample_rows = []

    return {
        "id": record.id,
        "original_name": record.original_name,
        "file_type": record.file_type,
        "row_count": record.row_count,
        "column_count": record.column_count,
        "uploaded_at": record.uploaded_at.isoformat(),
        "columns": columns,
        "stats": stats,
        "sample_rows": sample_rows,
    }


@router.delete("/datasets/{dataset_id}", summary="删除数据集")
async def delete_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    record = await _get_dataset_or_404(dataset_id, current_user.id, db)

    Path(record.file_path).unlink(missing_ok=True)

    await db.execute(
        delete(DatasetFile).where(DatasetFile.id == dataset_id)
    )
    await db.commit()
    return {"message": "数据集已删除"}


@router.post("/datasets/{dataset_id}/analyze", summary="对数据集进行 AI 洞察分析（SSE 流式输出）")
async def analyze_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    record = await _get_dataset_or_404(dataset_id, current_user.id, db)

    columns = json.loads(record.columns_json or "[]")
    stats = json.loads(record.stats_json or "{}")

    try:
        analysis = data_analyzer.analyze_file(record.file_path)
        sample_rows = analysis["sample_rows"]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"读取文件失败：{exc}",
        ) from exc

    async def _stream():
        try:
            async for chunk in data_analyzer.ai_analyze_stream(
                original_name=record.original_name,
                row_count=record.row_count or 0,
                column_count=record.column_count or 0,
                columns=columns,
                stats=stats,
                sample_rows=sample_rows,
            ):
                yield f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            log.exception("AI 分析流异常")
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 知识库端点（代理 RAGFlow API）
# ---------------------------------------------------------------------------

def _ragflow_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.RAGFLOW_API_KEY}"}


def _ragflow_url(path: str) -> str:
    return f"{settings.RAGFLOW_API_URL.rstrip('/')}{path}"


@router.post("/documents/upload", summary="上传文档到 RAGFlow 知识库（PDF/Word/TXT）")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_DOC_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"不支持的文件格式 '{suffix}'，请上传 .pdf / .docx / .doc / .txt / .md 文件",
        )

    if not settings.RAGFLOW_API_KEY or not settings.RAGFLOW_DATASET_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAGFlow 未配置，请检查 RAGFLOW_API_KEY 和 RAGFLOW_DATASET_ID",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="文件大小超过 50 MB 限制",
        )

    url = _ragflow_url(f"/api/v1/datasets/{settings.RAGFLOW_DATASET_ID}/documents")
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        try:
            resp = await client.post(
                url,
                headers=_ragflow_headers(),
                files={"file": (file.filename, content, file.content_type or "application/octet-stream")},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            _raise_ragflow_error(exc)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"RAGFlow 连接失败：{exc}") from exc


@router.get("/documents", summary="获取 RAGFlow 知识库文档列表")
async def list_documents(
    page: int = 1,
    page_size: int = 30,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    if not settings.RAGFLOW_API_KEY or not settings.RAGFLOW_DATASET_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAGFlow 未配置",
        )

    url = _ragflow_url(f"/api/v1/datasets/{settings.RAGFLOW_DATASET_ID}/documents")
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        try:
            resp = await client.get(
                url,
                headers=_ragflow_headers(),
                params={"page": page, "page_size": page_size},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            _raise_ragflow_error(exc)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"RAGFlow 连接失败：{exc}") from exc


@router.delete("/documents/{doc_id}", summary="从 RAGFlow 知识库删除文档")
async def delete_document(
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    if not settings.RAGFLOW_API_KEY or not settings.RAGFLOW_DATASET_ID:
        raise HTTPException(status_code=503, detail="RAGFlow 未配置")

    url = _ragflow_url(f"/api/v1/datasets/{settings.RAGFLOW_DATASET_ID}/documents")
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        try:
            # 注意：当前 httpx.AsyncClient.delete 在部分版本里不支持 content 参数。
            # 使用 request + json 发送请求体，兼容性更好。
            resp = await client.request(
                "DELETE",
                url,
                headers={**_ragflow_headers(), "Content-Type": "application/json"},
                json={"ids": [doc_id]},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            _raise_ragflow_error(exc)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"RAGFlow 连接失败：{exc}") from exc


@router.get("/documents/{doc_id}/status", summary="查询 RAGFlow 文档解析状态")
async def get_document_status(
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """
    返回 RAGFlow 中指定文档的解析状态。
    关键字段：
      - run: "UNSTART" | "RUNNING" | "DONE" | "CANCEL" | "FAIL"
      - chunk_count: 已生成的 chunk 数量（>0 表示解析完成）
      - progress: 0.0 ~ 1.0
    """
    if not settings.RAGFLOW_API_KEY or not settings.RAGFLOW_DATASET_ID:
        raise HTTPException(status_code=503, detail="RAGFlow 未配置")

    url = _ragflow_url(
        f"/api/v1/datasets/{settings.RAGFLOW_DATASET_ID}/documents/{doc_id}"
    )
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        try:
            resp = await client.get(url, headers=_ragflow_headers())
            resp.raise_for_status()
            try:
                body = resp.json()
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                # RAGFlow 在某些异常/兼容场景下可能返回非 UTF-8 或非 JSON，
                # 这里不要让轮询直接 500。
                try:
                    preview = resp.text[:300]
                except Exception:
                    preview = "<unavailable>"
                log.warning("RAGFlow 文档状态解析失败 doc_id=%s: %s preview=%s", doc_id, exc, preview)
                body = {}

            doc = body.get("data", body) if isinstance(body, dict) else {}
            return {
                "id": doc_id,
                "run": doc.get("run", "UNSTART"),
                "chunk_count": doc.get("chunk_count", 0),
                "progress": doc.get("progress", 0.0),
                "progress_msg": doc.get("progress_msg", []),
                # RAGFlow 文档列表里一般会带 update_time；轮询状态时也返回，便于前端刷新“更新时间”列
                "update_time": doc.get("update_time"),
            }
        except httpx.HTTPStatusError as exc:
            _raise_ragflow_error(exc)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"RAGFlow 连接失败：{exc}") from exc


@router.post("/documents/{doc_id}/parse", summary="触发 RAGFlow 文档解析（向量化）")
async def parse_document(
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    if not settings.RAGFLOW_API_KEY or not settings.RAGFLOW_DATASET_ID:
        raise HTTPException(status_code=503, detail="RAGFlow 未配置")

    # v0.24 Parse API: POST /api/v1/datasets/{dataset_id}/chunks
    url = _ragflow_url(f"/api/v1/datasets/{settings.RAGFLOW_DATASET_ID}/chunks")
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        try:
            resp = await client.post(
                url,
                headers={**_ragflow_headers(), "Content-Type": "application/json"},
                json={"document_ids": [doc_id]},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            _raise_ragflow_error(exc)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"RAGFlow 连接失败：{exc}") from exc


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

async def _get_dataset_or_404(
    dataset_id: str, user_id: str, db: AsyncSession
) -> DatasetFile:
    result = await db.execute(
        select(DatasetFile).where(
            DatasetFile.id == dataset_id,
            DatasetFile.uploader_id == user_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在或无权访问",
        )
    return record


def _raise_ragflow_error(exc: httpx.HTTPStatusError) -> None:
    """将 RAGFlow HTTP 错误转换为 FastAPI HTTPException，尽量保留原始错误信息。"""
    detail = ""
    try:
        body = exc.response.json()
        if isinstance(body, dict):
            detail = (
                body.get("message")
                or body.get("msg")
                or body.get("error")
                or body.get("detail")
                or ""
            )
    except Exception:
        pass
    if not detail:
        detail = exc.response.text or f"HTTP {exc.response.status_code}"
    if exc.response.status_code in (502, 503):
        detail = f"{detail}（请确认 RAGFlow 服务已启动且 RAGFLOW_API_URL 可访问）"
    raise HTTPException(
        status_code=exc.response.status_code,
        detail=f"RAGFlow 返回错误：{detail}",
    ) from exc
