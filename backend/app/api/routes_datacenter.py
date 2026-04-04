"""
数据中心路由模块。

提供两类端点：
  1. /datacenter/datasets/*        — CSV/Excel 数据集上传、预览、AI 分析
  2. /datacenter/datasets/import   — 将数据集导入 energy_data 表
  3. /datacenter/energy-data/*     — energy_data 表 CRUD（增删改查）
  4. /datacenter/documents/*       — PDF/Word 知识库文档管理（代理 RAGFlow API）
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import get_current_active_user
from app.db.models import DatasetFile, EnergyData, User
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


def _build_import_batch_params(
    df_sub: pd.DataFrame,
    mapped_fields: list[str],
    batch_start: int,
    batch_size: int,
) -> tuple[list[dict[str, Any]], set[str], datetime | None, datetime | None, int, list[str]]:
    """把 DataFrame 分块转换为 executemany 参数，避免一次性展开整表 records。"""
    batch_df = df_sub.iloc[batch_start: batch_start + batch_size]
    batch_params: list[dict[str, Any]] = []
    imported_bids: set[str] = set()
    min_ts: datetime | None = None
    max_ts: datetime | None = None
    failed = 0
    errors: list[str] = []

    for row in batch_df.itertuples(index=False):
        row_dict = row._asdict()
        try:
            ts_raw = row_dict["timestamp"]
            ts = ts_raw.to_pydatetime() if hasattr(ts_raw, "to_pydatetime") else ts_raw
            bid = str(row_dict["building_id"])
            row_p: dict[str, Any] = {"ts": ts, "bid": bid}
            for field in mapped_fields:
                raw = row_dict.get(field)
                try:
                    row_p[field] = None if (raw is None or pd.isna(raw)) else float(raw)
                except (TypeError, ValueError):
                    row_p[field] = None
            batch_params.append(row_p)
            imported_bids.add(bid)
            if min_ts is None or ts < min_ts:
                min_ts = ts
            if max_ts is None or ts > max_ts:
                max_ts = ts
        except Exception as exc:
            failed += 1
            if len(errors) < 5:
                errors.append(str(exc))

    return batch_params, imported_bids, min_ts, max_ts, failed, errors


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
    await asyncio.to_thread(save_path.write_bytes, content)

    try:
        result = await asyncio.to_thread(data_analyzer.analyze_file, str(save_path))
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
        analysis = await asyncio.to_thread(data_analyzer.analyze_file, record.file_path)
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
    delete_energy_data: bool = Query(
        True,
        description="是否同时删除已导入到 energy_data 的对应记录（默认 True）",
    ),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    删除数据集文件记录及磁盘文件。

    当 `delete_energy_data=true`（默认）时，如果该数据集曾导入过 energy_data，
    则同时删除导入的 energy_data 记录（按楼宇 ID + 时间范围精确匹配）。
    """
    record = await _get_dataset_or_404(dataset_id, current_user.id, db)

    log.info("删除数据集 %s (delete_energy_data=%s)", dataset_id, delete_energy_data)

    # ── 尝试获取导入元信息 ──────────────────────────────────────
    deleted_energy_rows = 0
    import_meta: dict | None = None
    try:
        stats = json.loads(record.stats_json or "{}")
        import_meta = stats.get("_import")
    except Exception:
        pass

    if import_meta and not delete_energy_data:
        log.info("数据集 %s 有 energy_data 导入记录，但 delete_energy_data=False，跳过清除", dataset_id)

    # ── 删除对应的 energy_data 记录 ─────────────────────────────
    if delete_energy_data and import_meta:
        building_ids: list[str] = import_meta.get("building_ids") or []
        min_ts_str: str | None = import_meta.get("min_ts")
        max_ts_str: str | None = import_meta.get("max_ts")

        if building_ids and min_ts_str and max_ts_str:
            try:
                min_ts = datetime.fromisoformat(min_ts_str.replace("Z", "+00:00"))
                max_ts = datetime.fromisoformat(max_ts_str.replace("Z", "+00:00"))
                result = await db.execute(
                    text("""
                        DELETE FROM energy_data
                        WHERE building_id = ANY(:bids)
                          AND timestamp >= :t0
                          AND timestamp <= :t1
                    """),
                    {"bids": building_ids, "t0": min_ts, "t1": max_ts},
                )
                deleted_energy_rows = result.rowcount or 0
                log.info(
                    "数据集 %s 删除时同步删除 energy_data %d 条 (buildings=%s, %s ~ %s)",
                    dataset_id, deleted_energy_rows, building_ids, min_ts_str, max_ts_str,
                )
            except Exception as exc:
                log.warning("删除 energy_data 失败：%s", exc)

    # ── 删除磁盘文件 ──────────────────────────────────────────────
    Path(record.file_path).unlink(missing_ok=True)

    # ── 删除数据集记录 ────────────────────────────────────────────
    await db.execute(
        delete(DatasetFile).where(DatasetFile.id == dataset_id)
    )
    await db.commit()

    msg = "数据集已删除"
    if deleted_energy_rows > 0:
        msg += f"，同时清除了 {deleted_energy_rows:,} 条 energy_data 记录"
    return {"message": msg, "deleted_energy_rows": deleted_energy_rows}


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
        analysis = await asyncio.to_thread(data_analyzer.analyze_file, record.file_path)
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
# energy_data 字段列别名映射（CSV 列名 → energy_data 字段名）
# ---------------------------------------------------------------------------

_ENERGY_COL_ALIASES: dict[str, list[str]] = {
    "timestamp": [
        "timestamp", "time", "datetime", "date_time", "ts", "日期时间", "时间",
    ],
    "building_id": [
        "building_id", "building", "buildingid", "building_name", "楼宇id", "楼宇",
    ],
    "electricity_kwh": [
        "electricity_kwh", "electricity", "elec_kwh", "electricity(kwh)",
        "electricity_energy", "用电量", "电耗",
    ],
    "water_m3": [
        "water_m3", "water", "water(m3)", "water_consumption",
        # 注意：water_l 是升，直接映射不做单位转换（用户需自行核实）
        "water_l", "waterconsumption", "用水量", "水耗",
    ],
    "hac_energy": [
        "hac_energy", "hvac_energy", "hac", "hvac", "hac_kwh",
        "ac_energy", "空调能耗",
    ],
    "sim_supply_temp_c": [
        "sim_supply_temp_c", "supply_temp", "supply_temp_c", "supply_temperature",
        "supplytemp", "供水温度",
    ],
    "sim_return_temp_c": [
        "sim_return_temp_c", "return_temp", "return_temp_c", "return_temperature",
        "returntemp", "回水温度",
    ],
    "air_temp_c": [
        "air_temp_c", "air_temp", "ambient_temp", "temperature", "temp_c",
        "airtemperature", "air_temperature", "室外温度", "气温",
    ],
    "dew_temp_c": [
        "dew_temp_c", "dew_temp", "dew_point", "dew_point_c",
        "dewtemperature", "dew_temperature", "露点温度",
    ],
    "humidity_rh_pct": [
        "humidity_rh_pct", "humidity", "humidity_pct", "rh_pct",
        "relative_humidity", "relativehumidity", "湿度",
    ],
}

_ENERGY_FLOAT_FIELDS = [
    "electricity_kwh", "water_m3", "hac_energy",
    "sim_supply_temp_c", "sim_return_temp_c",
    "air_temp_c", "dew_temp_c", "humidity_rh_pct",
]

# 批量导入分批大小
_IMPORT_BATCH_SIZE = 500


def _detect_column_mapping(csv_columns: list[str]) -> dict[str, str]:
    """
    自动检测 CSV 列名 → energy_data 字段名的映射。
    返回 {energy_field: csv_column_name}，只包含能匹配上的字段。
    """
    lower_cols = {c.lower().strip(): c for c in csv_columns}
    mapping: dict[str, str] = {}
    for field, aliases in _ENERGY_COL_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lower_cols:
                mapping[field] = lower_cols[alias.lower()]
                break
    return mapping


# ---------------------------------------------------------------------------
# Pydantic 请求体模型
# ---------------------------------------------------------------------------

class EnergyDataUpdate(BaseModel):
    timestamp: str
    building_id: str
    electricity_kwh: float | None = None
    water_m3: float | None = None
    hac_energy: float | None = None
    sim_supply_temp_c: float | None = None
    sim_return_temp_c: float | None = None
    air_temp_c: float | None = None
    dew_temp_c: float | None = None
    humidity_rh_pct: float | None = None


class EnergyDataCreate(BaseModel):
    timestamp: str
    building_id: str
    electricity_kwh: float | None = None
    water_m3: float | None = None
    hac_energy: float | None = None
    sim_supply_temp_c: float | None = None
    sim_return_temp_c: float | None = None
    air_temp_c: float | None = None
    dew_temp_c: float | None = None
    humidity_rh_pct: float | None = None


# ---------------------------------------------------------------------------
# 数据集导入到 energy_data（SSE 流式 + 批量 upsert）
# ---------------------------------------------------------------------------

@router.post(
    "/datasets/{dataset_id}/import-to-energy-data",
    summary="将数据集流式导入 energy_data 表（SSE 进度推送）",
)
async def import_dataset_to_energy_data(
    dataset_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    SSE 流式导入：
      - 每批（500 行）推送一次进度事件
      - 事件格式：data: {"stage":"importing","progress":0.45,"imported":500,"total":1100}
      - 完成事件：data: {"done":true,"imported":1000,"failed":5,"col_map":{...},...}
      - 结束标记：data: [DONE]

    列名自动映射（不区分大小写）：
      - airTemperature / air_temperature → air_temp_c
      - dewTemperature / dew_temperature → dew_temp_c
      - humidity → humidity_rh_pct
      - water_l / water_m3 → water_m3
      - 以及其他常见别名（详见 _ENERGY_COL_ALIASES）
    """
    # 前置校验（用请求 session）
    record = await _get_dataset_or_404(dataset_id, current_user.id, db)
    file_path = record.file_path
    saved_id = record.id

    async def _stream():  # noqa: C901
        _emit = lambda obj: f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"  # noqa: E731

        async with AsyncSessionLocal() as sdb:
            try:
                # ── 阶段 1：解析文件 ──────────────────────────────────────
                yield _emit({"stage": "parsing", "progress": 0.0, "msg": "正在解析文件..."})

                try:
                    df, _ = await asyncio.to_thread(data_analyzer.parse_file, file_path)
                except Exception as exc:
                    yield _emit({"error": f"文件解析失败：{exc}"})
                    yield "data: [DONE]\n\n"
                    return

                col_map = _detect_column_mapping(df.columns.tolist())
                missing = []
                if "timestamp" not in col_map:
                    missing.append("timestamp（或 time/datetime）")
                if "building_id" not in col_map:
                    missing.append("building_id（或 building）")
                if missing:
                    yield _emit({"error": f"CSV 缺少必要列：{', '.join(missing)}。当前列：{df.columns.tolist()[:15]}"})
                    yield "data: [DONE]\n\n"
                    return

                # ── 阶段 2：验证楼宇 ID ─────────────────────────────────
                yield _emit({"stage": "validating", "progress": 0.02, "msg": "校验楼宇 ID..."})

                bids_in_csv = (
                    df[col_map["building_id"]].dropna().astype(str).str.strip().unique().tolist()
                )
                valid_bids_res = await sdb.execute(
                    text("SELECT building_id FROM buildings WHERE building_id = ANY(:bids)"),
                    {"bids": bids_in_csv},
                )
                valid_bids: set[str] = {r[0] for r in valid_bids_res.fetchall()}
                invalid_bids = [b for b in bids_in_csv if b not in valid_bids]

                if not valid_bids:
                    yield _emit({
                        "error": f"所有楼宇 ID 均不存在于 buildings 表：{bids_in_csv[:5]}",
                    })
                    yield "data: [DONE]\n\n"
                    return

                # ── 阶段 3：准备数据 ─────────────────────────────────────
                yield _emit({"stage": "preparing", "progress": 0.05, "msg": "预处理数据..."})

                # 只保留已映射的列并重命名
                keep_cols = {v: k for k, v in col_map.items()}  # csv_col → field
                df_sub = df[list(col_map.values())].copy()
                df_sub = df_sub.rename(columns=keep_cols)

                # 过滤无效楼宇
                df_sub["building_id"] = df_sub["building_id"].astype(str).str.strip()
                df_sub = df_sub[df_sub["building_id"].isin(valid_bids)]

                # 解析时间戳（向量化，比行循环快 10-50x）
                df_sub["timestamp"] = pd.to_datetime(df_sub["timestamp"], utc=True)
                df_sub = df_sub.dropna(subset=["timestamp", "building_id"])

                total = len(df_sub)
                if total == 0:
                    yield _emit({"error": "没有有效数据行可导入"})
                    yield "data: [DONE]\n\n"
                    return

                # ── 阶段 4：确定 upsert SQL（一次性构建） ────────────────
                mapped_fields = [f for f in _ENERGY_FLOAT_FIELDS if f in col_map]
                if mapped_fields:
                    cols_sql = "timestamp, building_id, " + ", ".join(mapped_fields)
                    vals_sql = ":ts, :bid, " + ", ".join(f":{f}" for f in mapped_fields)
                    set_sql  = ", ".join(f"{f} = EXCLUDED.{f}" for f in mapped_fields)
                    upsert_sql = text(f"""
                        INSERT INTO energy_data ({cols_sql})
                        VALUES ({vals_sql})
                        ON CONFLICT (timestamp, building_id) DO UPDATE SET {set_sql}
                    """)
                else:
                    upsert_sql = text("""
                        INSERT INTO energy_data (timestamp, building_id)
                        VALUES (:ts, :bid)
                        ON CONFLICT (timestamp, building_id) DO NOTHING
                    """)

                # ── 阶段 5：批量 upsert ───────────────────────────────────
                imported = 0
                failed = 0
                errors: list[str] = []
                min_ts: datetime | None = None
                max_ts: datetime | None = None
                imported_bids: set[str] = set()

                for batch_start in range(0, total, _IMPORT_BATCH_SIZE):
                    batch_params, batch_bids, batch_min_ts, batch_max_ts, batch_failed, batch_errors = (
                        await asyncio.to_thread(
                            _build_import_batch_params,
                            df_sub,
                            mapped_fields,
                            batch_start,
                            _IMPORT_BATCH_SIZE,
                        )
                    )
                    imported_bids.update(batch_bids)
                    failed += batch_failed
                    for err in batch_errors:
                        if len(errors) >= 5:
                            break
                        errors.append(err)
                    if batch_min_ts is not None and (min_ts is None or batch_min_ts < min_ts):
                        min_ts = batch_min_ts
                    if batch_max_ts is not None and (max_ts is None or batch_max_ts > max_ts):
                        max_ts = batch_max_ts

                    if batch_params:
                        try:
                            await sdb.execute(upsert_sql, batch_params)
                            await sdb.commit()
                            imported += len(batch_params)
                        except Exception as exc:
                            await sdb.rollback()
                            failed += len(batch_params)
                            imported -= len(batch_params)  # 回滚已计数
                            if len(errors) < 5:
                                errors.append(f"批次 {batch_start} 写入失败：{exc}")

                    processed = min(batch_start + _IMPORT_BATCH_SIZE, total)
                    progress = min(0.99, processed / total * 0.95 + 0.05)
                    yield _emit({
                        "stage": "importing",
                        "progress": round(progress, 3),
                        "imported": imported,
                        "total": total,
                    })

                # ── 阶段 6：保存导入元信息回 dataset_files ───────────────
                import_meta = {
                    "imported_rows": imported,
                    "building_ids": list(imported_bids),
                    "min_ts": min_ts.isoformat() if min_ts else None,
                    "max_ts": max_ts.isoformat() if max_ts else None,
                    "col_map": col_map,
                }
                try:
                    meta_res = await sdb.execute(
                        select(DatasetFile).where(DatasetFile.id == saved_id)
                    )
                    saved_rec = meta_res.scalar_one_or_none()
                    if saved_rec:
                        existing_stats = json.loads(saved_rec.stats_json or "{}")
                        existing_stats["_import"] = import_meta
                        saved_rec.stats_json = json.dumps(existing_stats, ensure_ascii=False)
                        await sdb.commit()
                except Exception as exc:
                    log.warning("保存导入元信息失败：%s", exc)

                yield _emit({
                    "done": True,
                    "imported_rows": imported,
                    "failed_rows": failed,
                    "errors": errors,
                    "col_map": col_map,
                    "invalid_building_ids": invalid_bids,
                    "building_ids": list(imported_bids),
                    "min_ts": min_ts.isoformat() if min_ts else None,
                    "max_ts": max_ts.isoformat() if max_ts else None,
                })

            except Exception as exc:
                log.exception("导入流异常")
                yield _emit({"error": f"导入失败：{exc}"})
            finally:
                yield "data: [DONE]\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# energy_data CRUD 端点
# ---------------------------------------------------------------------------

@router.get("/energy-data", summary="分页查询 energy_data 记录")
async def list_energy_data(
    building_ids: str = Query(..., description="逗号分隔的楼宇 ID 列表"),
    start_ts: str = Query(..., description="开始时间 ISO8601"),
    end_ts: str = Query(..., description="结束时间 ISO8601"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """分页返回指定楼宇和时间范围内的 energy_data 记录。"""
    bid_list = [b.strip() for b in building_ids.split(",") if b.strip()]
    try:
        t0 = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"时间格式错误：{exc}") from exc

    offset = (page - 1) * page_size

    count_result = await db.execute(
        text("""
            SELECT COUNT(*) FROM energy_data
            WHERE building_id = ANY(:bids)
              AND timestamp >= :t0
              AND timestamp <= :t1
        """),
        {"bids": bid_list, "t0": t0, "t1": t1},
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text("""
            SELECT timestamp, building_id,
                   electricity_kwh, water_m3, hac_energy,
                   sim_supply_temp_c, sim_return_temp_c,
                   air_temp_c, dew_temp_c, humidity_rh_pct
            FROM energy_data
            WHERE building_id = ANY(:bids)
              AND timestamp >= :t0
              AND timestamp <= :t1
            ORDER BY timestamp DESC, building_id
            LIMIT :lim OFFSET :off
        """),
        {"bids": bid_list, "t0": t0, "t1": t1, "lim": page_size, "off": offset},
    )

    records = []
    for row in rows_result.fetchall():
        ts, bid, elec, water, hac, sup_t, ret_t, air_t, dew_t, hum = row
        records.append({
            "timestamp": ts.isoformat() if ts else None,
            "building_id": bid,
            "electricity_kwh": _fv(elec),
            "water_m3": _fv(water),
            "hac_energy": _fv(hac),
            "sim_supply_temp_c": _fv(sup_t),
            "sim_return_temp_c": _fv(ret_t),
            "air_temp_c": _fv(air_t),
            "dew_temp_c": _fv(dew_t),
            "humidity_rh_pct": _fv(hum),
        })

    return {"records": records, "total": total, "page": page, "page_size": page_size}


@router.post("/energy-data/row", summary="新增一条 energy_data 记录")
async def create_energy_data_record(
    body: EnergyDataCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新增一条 energy_data 记录（如已存在则更新）。"""
    try:
        ts = datetime.fromisoformat(body.timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"时间格式错误：{exc}") from exc

    # 验证 building_id 存在
    bid_check = await db.execute(
        text("SELECT 1 FROM buildings WHERE building_id = :bid"),
        {"bid": body.building_id},
    )
    if not bid_check.scalar():
        raise HTTPException(status_code=400, detail=f"楼宇 '{body.building_id}' 不存在")

    fields = {f: getattr(body, f) for f in _ENERGY_FLOAT_FIELDS}
    non_null = {k: v for k, v in fields.items() if v is not None}

    if non_null:
        cols = ", ".join(non_null.keys())
        vals = ", ".join(f":{k}" for k in non_null.keys())
        sets = ", ".join(f"{k} = :{k}" for k in non_null.keys())
        params = {"ts": ts, "bid": body.building_id, **non_null}
        await db.execute(
            text(f"""
                INSERT INTO energy_data (timestamp, building_id, {cols})
                VALUES (:ts, :bid, {vals})
                ON CONFLICT (timestamp, building_id) DO UPDATE SET {sets}
            """),
            params,
        )
    else:
        await db.execute(
            text("""
                INSERT INTO energy_data (timestamp, building_id)
                VALUES (:ts, :bid)
                ON CONFLICT (timestamp, building_id) DO NOTHING
            """),
            {"ts": ts, "bid": body.building_id},
        )

    await db.commit()
    return {"message": "记录已创建", "timestamp": ts.isoformat(), "building_id": body.building_id}


@router.put("/energy-data/row", summary="更新一条 energy_data 记录")
async def update_energy_data_record(
    body: EnergyDataUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """按 (timestamp, building_id) 主键更新 energy_data 记录的数值字段。"""
    try:
        ts = datetime.fromisoformat(body.timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"时间格式错误：{exc}") from exc

    fields = {f: getattr(body, f) for f in _ENERGY_FLOAT_FIELDS}
    non_null = {k: v for k, v in fields.items() if v is not None}
    if not non_null:
        raise HTTPException(status_code=400, detail="没有可更新的字段")

    sets = ", ".join(f"{k} = :{k}" for k in non_null.keys())
    params = {"ts": ts, "bid": body.building_id, **non_null}
    result = await db.execute(
        text(f"""
            UPDATE energy_data
            SET {sets}
            WHERE timestamp = :ts AND building_id = :bid
        """),
        params,
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="记录不存在")
    await db.commit()
    return {"message": "记录已更新"}


@router.delete("/energy-data/row", summary="删除一条 energy_data 记录")
async def delete_energy_data_record(
    timestamp: str = Query(..., description="时间戳 ISO8601"),
    building_id: str = Query(..., description="楼宇 ID"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """按 (timestamp, building_id) 主键删除一条 energy_data 记录。"""
    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"时间格式错误：{exc}") from exc

    result = await db.execute(
        text("DELETE FROM energy_data WHERE timestamp = :ts AND building_id = :bid"),
        {"ts": ts, "bid": building_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="记录不存在")
    await db.commit()
    return {"message": "记录已删除"}


def _fv(val: Any) -> float | None:
    """安全转换为 float，None 或 NaN 返回 None。"""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    except (TypeError, ValueError):
        return None


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
