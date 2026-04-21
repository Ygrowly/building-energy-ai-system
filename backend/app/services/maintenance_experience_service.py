from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import delete_cache_by_prefix, get_or_compute_json
from app.core.person_name import format_person_display_name
from app.db.models import (
    Device,
    MaintenanceExperience,
    MaintenanceExperienceFeedback,
    MaintenanceExperienceUsageLog,
    User,
    WorkOrder,
    WorkOrderAnomalyLink,
)
from app.db.session import AsyncSessionLocal
from app.services.ai_model_provider import get_model_provider, parse_json_object

logger = logging.getLogger(__name__)

SOURCE_TYPES = {"worker_note", "operator_note", "completion_summary", "step_event"}
FEEDBACK_TYPES = {"helpful", "unhelpful", "incorrect"}
READ_ROLES = {"ops", "admin", "manager"}
WRITE_ROLES = {"ops", "admin", "manager"}
DEACTIVATE_ROLES = {"admin", "manager"}
EXPERIENCE_CACHE_PREFIX = "maintenance_experiences:"
SEARCH_CACHE_TTL_SECONDS = 60
MAX_TEXT_LENGTH = 4000
DEMO_SOURCE_CONTRIBUTOR_BY_WORK_ORDER = {
    "WO-20260403-001": "王工",
    "WO-20260403-002": "刘工",
}
UUIDISH_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _as_text(value: Any, *, limit: int = MAX_TEXT_LENGTH) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _as_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _as_text(item, limit=item_limit)
        if text:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _normalize_role(role: str | None) -> str:
    return (role or "").strip().lower()


def _require_read_role(role: str | None) -> None:
    if _normalize_role(role) not in READ_ROLES:
        raise HTTPException(status_code=403, detail="权限不足")


def _require_write_role(role: str | None) -> None:
    if _normalize_role(role) not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="权限不足")


def _require_deactivate_role(role: str | None) -> None:
    if _normalize_role(role) not in DEACTIVATE_ROLES:
        raise HTTPException(status_code=403, detail="权限不足，需要管理员角色")


def _normalize_source_type(source_type: str) -> str:
    normalized = _as_text(source_type, limit=32).lower()
    if normalized not in SOURCE_TYPES:
        raise HTTPException(status_code=400, detail="不支持的经验来源类型")
    return normalized


def _normalize_feedback(feedback: str) -> str:
    normalized = _as_text(feedback, limit=24).lower()
    if normalized not in FEEDBACK_TYPES:
        raise HTTPException(status_code=400, detail="不支持的反馈类型")
    return normalized


def _extract_ascii_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]{2,}", (text or "").lower()) if token}


def _extract_cjk_bigrams(text: str) -> set[str]:
    tokens: set[str] = set()
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", text or ""):
        tokens.add(segment)
        for index in range(len(segment) - 1):
            tokens.add(segment[index : index + 2])
    return tokens


def _tokenize_text(text: str) -> set[str]:
    cleaned = _as_text(text)
    if not cleaned:
        return set()
    return _extract_ascii_tokens(cleaned) | _extract_cjk_bigrams(cleaned)


def _guess_fault_type(text: str, fallback: str | None = None) -> str | None:
    lower = (text or "").lower()
    if "供水温度" in text or "supply temp" in lower:
        return "supply_water_temperature_deviation"
    if "回水温度" in text or "return temp" in lower:
        return "return_water_temperature_deviation"
    if "漏水" in text or "leak" in lower:
        return "water_leak"
    if "cop" in lower or "冷水机" in text or "机组效能" in text:
        return "hvac_efficiency_degradation"
    if "阀门" in text:
        return "valve_operation_issue"
    if "传感器" in text or "读数" in text:
        return "sensor_or_reading_issue"
    return _as_text(fallback, limit=128) or None


def _build_suggested_steps(text: str) -> list[str]:
    normalized = _as_text(text)
    if not normalized:
        return []
    candidates: list[str] = []
    for segment in re.split(r"[。；;\n]", normalized):
        item = segment.strip(" ，,")
        if not item:
            continue
        if any(marker in item for marker in ("先", "再", "然后", "最后", "优先", "其次")):
            candidates.append(item)
    if not candidates:
        for segment in re.split(r"[，,]", normalized):
            item = segment.strip()
            if len(item) >= 6:
                candidates.append(item)
            if len(candidates) >= 3:
                break
    return candidates[:5]


def _build_fault_keywords(text: str, fallback_fault_type: str | None) -> list[str]:
    keywords: list[str] = []
    for token in sorted(_tokenize_text(text), key=len, reverse=True):
        if len(token) < 2:
            continue
        keywords.append(token)
        if len(keywords) >= 8:
            break
    if fallback_fault_type and fallback_fault_type not in keywords:
        keywords.insert(0, fallback_fault_type)
    return keywords[:8]


def _build_symptom_tags(text: str) -> list[str]:
    tags: list[str] = []
    for pattern in (
        "供水温度偏离",
        "回水温度偏离",
        "阀门检查",
        "传感器异常",
        "读数异常",
        "漏水",
        "冷水机效率",
        "报警码",
    ):
        if pattern in text:
            tags.append(pattern)
    if not tags:
        for segment in re.findall(r"[\u4e00-\u9fff]{3,8}", text or ""):
            tags.append(segment)
            if len(tags) >= 4:
                break
    return list(dict.fromkeys(tags))[:6]


def _build_applicable_conditions(
    *,
    building_id: str | None,
    device_type: str | None,
    fault_type: str | None,
) -> list[str]:
    conditions: list[str] = []
    if building_id:
        conditions.append(f"适用于楼宇 {building_id} 的相似场景")
    if device_type:
        conditions.append(f"适用于设备类型 {device_type} 的相似故障")
    if fault_type:
        conditions.append(f"适用于故障类型 {fault_type}")
    return conditions[:4]


def _build_safety_notes(text: str) -> list[str]:
    notes: list[str] = []
    if any(keyword in text for keyword in ("电控柜", "带电", "配电", "断路器", "控制柜")):
        notes.append("涉及电控柜或带电检查时，先完成断电、挂牌和授权确认。")
    if any(keyword in text for keyword in ("压力", "制冷剂", "冷媒", "压缩机")):
        notes.append("涉及压力系统或制冷剂时，必须由具备资质的人员执行。")
    if any(keyword in text for keyword in ("泵", "阀门", "阀", "管路")):
        notes.append("涉及泵、阀门和管路操作前，先确认泄压、隔离和现场许可。")
    return notes[:4]


def _build_conflict_flags(text: str) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    if ("打开电控柜" in text or "带电" in text or "强制运行" in text or "短接" in text) and (
        "断电" not in text and "授权" not in text and "挂牌" not in text
    ):
        conflicts.append(
            {
                "type": "safety_conflict",
                "message": "经验描述涉及高风险操作，但未提及断电、挂牌或授权要求。",
            }
        )
    if "绕过" in text and "联锁" in text:
        conflicts.append(
            {
                "type": "safety_conflict",
                "message": "经验描述出现绕过联锁的风险，引用时必须以现场安全规程为准。",
            }
        )
    if "重启" in text and "直接" in text and "排查" not in text:
        conflicts.append(
            {
                "type": "process_conflict",
                "message": "经验描述倾向直接重启设备，引用时应先核对现场事实和安全边界。",
            }
        )
    return conflicts[:4]


def _fallback_organized_payload(
    source_text: str,
    *,
    building_id: str | None,
    device_type: str | None,
    fault_type: str | None,
) -> dict[str, Any]:
    resolved_fault_type = _guess_fault_type(source_text, fault_type)
    return {
        "organized_text": _as_text(source_text, limit=1200),
        "fault_type": resolved_fault_type,
        "symptom_tags": _build_symptom_tags(source_text),
        "fault_keywords": _build_fault_keywords(source_text, resolved_fault_type),
        "applicable_conditions": _build_applicable_conditions(
            building_id=building_id,
            device_type=device_type,
            fault_type=resolved_fault_type,
        ),
        "suggested_steps": _build_suggested_steps(source_text),
        "safety_notes": _build_safety_notes(source_text),
        "conflict_flags": _build_conflict_flags(source_text),
    }


def _classify_experience_by_rules(source_text: str, *, source_type: str) -> dict[str, Any]:
    text = _as_text(source_text)
    if len(text) < 10:
        return {
            "is_experience": False,
            "experience_type": None,
            "reason": "内容过短，缺少可沉淀的经验信息。",
        }

    positive_patterns = (
        r"以前.*(遇到|处理)",
        r"之前.*(遇到|处理)",
        r"(建议|优先|通常|一般).*(先|再|最后)",
        r"(更快|更稳|更容易)定位",
        r"不要直接",
        r"类似.*问题",
        r"处理.*这个问题",
        r"经验",
    )
    negative_patterns = (
        r"^(我已|已经)?(到场|接单|开始处理|完成)",
        r"^报警码",
        r"^当前",
        r"^现在",
    )

    positive_score = sum(1 for pattern in positive_patterns if re.search(pattern, text))
    negative_score = sum(1 for pattern in negative_patterns if re.search(pattern, text))
    if source_type == "completion_summary" and len(text) >= 20:
        positive_score += 1
    if "先" in text and ("再" in text or "最后" in text):
        positive_score += 1

    is_experience = positive_score >= max(1, negative_score + 1)
    experience_type = "troubleshooting_tip"
    if source_type == "completion_summary":
        experience_type = "completion_summary"
    elif "安全" in text:
        experience_type = "safety_note"

    return {
        "is_experience": is_experience,
        "experience_type": experience_type if is_experience else None,
        "reason": (
            "文本包含相似场景、优先步骤或规避建议，可作为经验沉淀。"
            if is_experience
            else "文本更像状态汇报或现场事实，缺少可复用的经验建议。"
        ),
    }


async def classify_experience_text(source_text: str, *, source_type: str) -> dict[str, Any]:
    fallback = _classify_experience_by_rules(source_text, source_type=source_type)
    provider = get_model_provider()
    if provider is None:
        return fallback

    system_prompt = (
        "你是维修经验识别器。"
        "请判断输入内容是否属于可沉淀的维修经验。"
        "只有包含可复用的排查技巧、适用条件、避坑建议或处理总结时，is_experience 才能为 true。"
        "单纯状态汇报、动作确认、原始读数、无上下文的报警码不算经验。"
        "只输出 JSON。"
    )
    user_prompt = {
        "source_type": source_type,
        "source_text": source_text,
        "schema": {
            "is_experience": "boolean",
            "experience_type": "string|null",
            "reason": "string",
        },
    }
    try:
        raw = await provider.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _json_dumps(user_prompt)},
            ],
            response_schema={"type": "object"},
            temperature=0,
        )
    except Exception as exc:
        logger.info("maintenance experience classify fallback: %s", exc)
        return fallback

    parsed = parse_json_object(raw) or {}
    if not isinstance(parsed.get("is_experience"), bool):
        return fallback
    return {
        "is_experience": bool(parsed.get("is_experience")),
        "experience_type": _as_text(parsed.get("experience_type"), limit=64) or fallback.get("experience_type"),
        "reason": _as_text(parsed.get("reason"), limit=300) or fallback["reason"],
    }


def _normalize_organized_payload(
    payload: dict[str, Any] | None,
    *,
    source_text: str,
    building_id: str | None,
    device_type: str | None,
    fault_type: str | None,
) -> dict[str, Any]:
    fallback = _fallback_organized_payload(
        source_text,
        building_id=building_id,
        device_type=device_type,
        fault_type=fault_type,
    )
    payload = payload or {}
    organized_text = _as_text(payload.get("organized_text"), limit=1200) or fallback["organized_text"]
    resolved_fault_type = _guess_fault_type(
        organized_text or source_text,
        _as_text(payload.get("fault_type"), limit=128) or fault_type,
    )
    return {
        "organized_text": organized_text,
        "fault_type": resolved_fault_type,
        "symptom_tags": _as_list(payload.get("symptom_tags"), limit=6, item_limit=80) or fallback["symptom_tags"],
        "fault_keywords": _as_list(payload.get("fault_keywords"), limit=8, item_limit=80)
        or _build_fault_keywords(organized_text or source_text, resolved_fault_type),
        "applicable_conditions": _as_list(payload.get("applicable_conditions"), limit=4, item_limit=160)
        or _build_applicable_conditions(
            building_id=building_id,
            device_type=device_type,
            fault_type=resolved_fault_type,
        ),
        "suggested_steps": _as_list(payload.get("suggested_steps"), limit=5, item_limit=200)
        or _build_suggested_steps(organized_text or source_text),
        "safety_notes": _as_list(payload.get("safety_notes"), limit=4, item_limit=200)
        or _build_safety_notes(source_text),
        "conflict_flags": payload.get("conflict_flags") if isinstance(payload.get("conflict_flags"), list) else fallback["conflict_flags"],
    }


async def organize_experience_text(
    source_text: str,
    *,
    building_id: str | None,
    device_type: str | None,
    fault_type: str | None,
) -> tuple[dict[str, Any], str, str]:
    fallback = _fallback_organized_payload(
        source_text,
        building_id=building_id,
        device_type=device_type,
        fault_type=fault_type,
    )
    provider = get_model_provider()
    if provider is None:
        return fallback, "local_fallback", "experience_rule_organizer"

    system_prompt = (
        "你是维修经验整理器。"
        "请保持原文语义，不要发明现场事实，不要把经验包装成强制规范。"
        "输出 JSON，字段包括 organized_text、fault_type、symptom_tags、fault_keywords、"
        "applicable_conditions、suggested_steps、safety_notes、conflict_flags。"
        "如果经验涉及高风险操作但缺少断电/授权说明，需要在 conflict_flags 中指出。"
    )
    user_prompt = {
        "source_text": source_text,
        "context": {
            "building_id": building_id,
            "device_type": device_type,
            "fault_type": fault_type,
        },
        "schema": {
            "organized_text": "string",
            "fault_type": "string|null",
            "symptom_tags": ["string"],
            "fault_keywords": ["string"],
            "applicable_conditions": ["string"],
            "suggested_steps": ["string"],
            "safety_notes": ["string"],
            "conflict_flags": [{"type": "string", "message": "string"}],
        },
    }
    try:
        raw = await provider.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _json_dumps(user_prompt)},
            ],
            response_schema={"type": "object"},
            temperature=0.1,
        )
    except Exception as exc:
        logger.info("maintenance experience organize fallback: %s", exc)
        return fallback, "local_fallback", "experience_rule_organizer"

    normalized = _normalize_organized_payload(
        parse_json_object(raw),
        source_text=source_text,
        building_id=building_id,
        device_type=device_type,
        fault_type=fault_type,
    )
    return normalized, "model", "experience_structured_output"


async def _find_work_order_by_ticket_id(db: AsyncSession, ticket_id: str | None) -> WorkOrder | None:
    normalized = _as_text(ticket_id, limit=64)
    if not normalized:
        return None
    result = await db.execute(select(WorkOrder).where(WorkOrder.ticket_id == normalized).limit(1))
    return result.scalar_one_or_none()


async def _resolve_context_metadata(
    db: AsyncSession,
    *,
    source_work_order_id: str | None,
    building_id: str | None,
    device_id: str | None,
    device_type: str | None,
    fault_type: str | None,
) -> tuple[str | None, str | None, str | None, WorkOrder | None]:
    work_order = await _find_work_order_by_ticket_id(db, source_work_order_id)
    resolved_building_id = building_id or getattr(work_order, "building_id", None)
    resolved_device_id = device_id or getattr(work_order, "device_id", None)
    resolved_device_type = device_type
    if not resolved_device_type and resolved_device_id:
        device_result = await db.execute(
            select(Device.device_type).where(Device.device_id == resolved_device_id).limit(1)
        )
        resolved_device_type = device_result.scalar_one_or_none()

    resolved_fault_type = fault_type
    if not resolved_fault_type and work_order is not None:
        link_result = await db.execute(
            select(WorkOrderAnomalyLink)
            .where(WorkOrderAnomalyLink.work_order_id == work_order.id)
            .order_by(WorkOrderAnomalyLink.data_timestamp.desc())
            .limit(1)
        )
        link = link_result.scalar_one_or_none()
        if link is not None:
            resolved_fault_type = _as_text(link.hvac_root_cause, limit=128) or _as_text(link.rule_triggered, limit=128)

    return resolved_building_id, resolved_device_type, resolved_fault_type, work_order


async def _find_duplicate_experience(
    db: AsyncSession,
    *,
    source_type: str,
    source_work_order_id: str | None,
    source_dispatch_id: str | None,
    source_step_plan_id: str | None,
    contributor_user_id: str | None,
    source_text: str,
) -> MaintenanceExperience | None:
    result = await db.execute(
        select(MaintenanceExperience)
        .where(MaintenanceExperience.source_type == source_type)
        .where(MaintenanceExperience.source_work_order_id == source_work_order_id)
        .where(MaintenanceExperience.source_dispatch_id == source_dispatch_id)
        .where(MaintenanceExperience.source_step_plan_id == source_step_plan_id)
        .where(MaintenanceExperience.contributor_user_id == contributor_user_id)
        .where(MaintenanceExperience.source_text == source_text)
        .order_by(MaintenanceExperience.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _build_search_blob(experience: MaintenanceExperience) -> str:
    parts = [
        experience.organized_text,
        experience.source_text,
        experience.fault_type,
        experience.device_type,
        " ".join(_json_loads(experience.fault_keywords_json, [])),
        " ".join(_json_loads(experience.symptom_tags_json, [])),
        " ".join(_json_loads(experience.suggested_steps_json, [])),
        " ".join(_json_loads(experience.applicable_conditions_json, [])),
    ]
    return " ".join(_as_text(part, limit=600) for part in parts if part)


def _build_vector_ref(experience: MaintenanceExperience) -> str:
    tokens = sorted(_tokenize_text(_build_search_blob(experience)))
    return _json_dumps({"tokens": tokens[:256], "indexed_at": _now().isoformat()})


def _get_index_tokens(experience: MaintenanceExperience) -> set[str]:
    parsed = _json_loads(experience.vector_ref, {})
    tokens = parsed.get("tokens") if isinstance(parsed, dict) else None
    if isinstance(tokens, list) and tokens:
        return {str(token) for token in tokens if str(token)}
    return _tokenize_text(_build_search_blob(experience))


def _calculate_experience_score(
    experience: MaintenanceExperience,
    *,
    query_tokens: set[str],
    query_text: str,
    building_id: str | None,
    device_type: str | None,
    fault_type: str | None,
) -> float:
    score = 0.0
    search_blob = _build_search_blob(experience).lower()
    index_tokens = _get_index_tokens(experience)
    if query_tokens:
        overlap = len(query_tokens & index_tokens) / max(len(query_tokens), 1)
        score += overlap * 0.62
        if query_text and query_text.lower() in search_blob:
            score += 0.15
    else:
        score += 0.2
    if building_id and experience.building_id == building_id:
        score += 0.08
    if device_type and experience.device_type == device_type:
        score += 0.08
    if fault_type and experience.fault_type == fault_type:
        score += 0.12
    score += min(int(experience.helpful_count or 0), 5) * 0.03
    score += min(int(experience.usage_count or 0), 8) * 0.01
    score -= min(int(experience.unhelpful_count or 0), 5) * 0.04
    score -= min(int(experience.incorrect_count or 0), 5) * 0.08
    if not experience.is_active:
        score -= 0.2
    return round(max(0.0, min(1.0, score)), 4)


def _serialize_experience(
    experience: MaintenanceExperience,
    *,
    score: float | None = None,
    include_source_text: bool = False,
) -> dict[str, Any]:
    payload = {
        "id": experience.id,
        "source_type": experience.source_type,
        "source_work_order_id": experience.source_work_order_id,
        "source_dispatch_id": experience.source_dispatch_id,
        "source_step_plan_id": experience.source_step_plan_id,
        "contributor_user_id": experience.contributor_user_id,
        "contributor_role": experience.contributor_role,
        "building_id": experience.building_id,
        "device_id": experience.device_id,
        "device_type": experience.device_type,
        "fault_type": experience.fault_type,
        "organized_text": experience.organized_text,
        "fault_keywords": _json_loads(experience.fault_keywords_json, []),
        "symptom_tags": _json_loads(experience.symptom_tags_json, []),
        "suggested_steps": _json_loads(experience.suggested_steps_json, []),
        "safety_notes": _json_loads(experience.safety_notes_json, []),
        "applicable_conditions": _json_loads(experience.applicable_conditions_json, []),
        "conflict_flags": _json_loads(experience.conflict_flags_json, []),
        "vector_index_status": experience.vector_index_status,
        "usage_count": int(experience.usage_count or 0),
        "helpful_count": int(experience.helpful_count or 0),
        "unhelpful_count": int(experience.unhelpful_count or 0),
        "incorrect_count": int(experience.incorrect_count or 0),
        "is_active": bool(experience.is_active),
        "created_at": experience.created_at.isoformat() if experience.created_at else None,
        "updated_at": experience.updated_at.isoformat() if experience.updated_at else None,
    }
    source_contributor_name = resolve_experience_source_contributor_name(payload)
    if source_contributor_name:
        payload["source_contributor_name"] = source_contributor_name
    if include_source_text:
        payload["source_text"] = experience.source_text
    if score is not None:
        payload["score"] = score
    return payload


def resolve_experience_source_contributor_name(item: dict[str, Any]) -> str | None:
    source_work_order_id = _as_text(item.get("source_work_order_id"), limit=64)
    override = DEMO_SOURCE_CONTRIBUTOR_BY_WORK_ORDER.get(source_work_order_id)
    if override:
        return override

    for key in ("source_contributor_name", "contributor_name", "contributor_username", "contributor_user_name"):
        name = _as_text(item.get(key), limit=80)
        if name:
            return format_person_display_name(name) or name

    contributor_user_id = _as_text(item.get("contributor_user_id"), limit=128)
    if contributor_user_id and not UUIDISH_RE.fullmatch(contributor_user_id):
        return format_person_display_name(contributor_user_id) or contributor_user_id
    return None


async def _hydrate_experience_source_contributors(
    db: AsyncSession,
    items: list[dict[str, Any]],
) -> None:
    contributor_ids = {
        _as_text(item.get("contributor_user_id"), limit=128)
        for item in items
        if _as_text(item.get("contributor_user_id"), limit=128)
    }
    if not contributor_ids:
        return

    try:
        result = await db.execute(select(User.id, User.username).where(User.id.in_(contributor_ids)))
        rows = result.all()
    except Exception as exc:  # pragma: no cover - attribution is best-effort metadata
        logger.info("maintenance experience contributor hydrate skipped: %s", exc)
        return

    usernames = {user_id: username for user_id, username in rows}
    for item in items:
        if item.get("source_contributor_name"):
            continue
        username = usernames.get(item.get("contributor_user_id"))
        display_name = format_person_display_name(username) if username else None
        if display_name:
            item["source_contributor_name"] = display_name


async def _search_experiences_uncached(
    db: AsyncSession,
    *,
    query: str | None,
    building_id: str | None,
    device_type: str | None,
    fault_type: str | None,
    limit: int,
    include_inactive: bool,
    sort_by: str,
) -> dict[str, Any]:
    stmt = select(MaintenanceExperience).order_by(MaintenanceExperience.created_at.desc()).limit(250)
    if not include_inactive:
        stmt = stmt.where(MaintenanceExperience.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())
    query_text = _as_text(query, limit=200)
    query_tokens = _tokenize_text(query_text)
    ranked: list[tuple[MaintenanceExperience, float]] = []
    for experience in candidates:
        score = _calculate_experience_score(
            experience,
            query_tokens=query_tokens,
            query_text=query_text,
            building_id=building_id,
            device_type=device_type,
            fault_type=fault_type,
        )
        structure_match = any(
            (
                building_id and experience.building_id == building_id,
                device_type and experience.device_type == device_type,
                fault_type and experience.fault_type == fault_type,
            )
        )
        if sort_by == "score" and query_text and score < 0.12 and not structure_match:
            continue
        ranked.append((experience, score))

    if sort_by == "recent":
        ranked.sort(key=lambda item: (item[0].created_at or _now(), item[1]), reverse=True)
    elif sort_by == "usage":
        ranked.sort(
            key=lambda item: (
                int(item[0].usage_count or 0),
                int(item[0].helpful_count or 0),
                item[1],
                item[0].created_at or _now(),
            ),
            reverse=True,
        )
    else:
        ranked.sort(
            key=lambda item: (
                item[1],
                int(item[0].helpful_count or 0),
                int(item[0].usage_count or 0),
                item[0].created_at or _now(),
            ),
            reverse=True,
        )

    items = [_serialize_experience(experience, score=score) for experience, score in ranked[:limit]]
    await _hydrate_experience_source_contributors(db, items)
    return {
        "query": query_text,
        "items": items,
        "total": len(items),
        "sort_by": sort_by,
    }


async def search_maintenance_experiences(
    db: AsyncSession,
    *,
    actor_role: str | None,
    query: str | None,
    building_id: str | None,
    device_type: str | None,
    fault_type: str | None,
    limit: int = 5,
    include_inactive: bool = False,
    sort_by: str = "score",
) -> dict[str, Any]:
    _require_read_role(actor_role)
    if include_inactive and _normalize_role(actor_role) not in DEACTIVATE_ROLES:
        raise HTTPException(status_code=403, detail="仅管理员可查看停用经验")
    normalized_limit = max(1, min(int(limit or 5), 20))
    normalized_sort = sort_by if sort_by in {"score", "recent", "usage"} else "score"
    cache_key = (
        f"{EXPERIENCE_CACHE_PREFIX}search:"
        f"{normalized_sort}:{include_inactive}:{normalized_limit}:"
        f"{building_id or '-'}:{device_type or '-'}:{fault_type or '-'}:{_as_text(query, limit=200) or '-'}"
    )
    return await get_or_compute_json(
        cache_key,
        ttl_seconds=SEARCH_CACHE_TTL_SECONDS,
        compute=lambda: _search_experiences_uncached(
            db,
            query=query,
            building_id=building_id,
            device_type=device_type,
            fault_type=fault_type,
            limit=normalized_limit,
            include_inactive=include_inactive,
            sort_by=normalized_sort,
        ),
    )


def _schedule_background_task(coro: Any, *, label: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(coro)

    def _log_task_result(done_task: asyncio.Task[Any]) -> None:
        try:
            done_task.result()
        except Exception as exc:  # pragma: no cover
            logger.warning("%s failed: %s", label, exc, exc_info=True)

    task.add_done_callback(_log_task_result)


async def _index_experience_background(experience_id: str) -> None:
    async with AsyncSessionLocal() as db:
        experience = await db.get(MaintenanceExperience, experience_id)
        if experience is None:
            return
        try:
            experience.vector_ref = _build_vector_ref(experience)
            experience.vector_index_status = "indexed"
            experience.updated_at = _now()
            await db.commit()
            await delete_cache_by_prefix(EXPERIENCE_CACHE_PREFIX)
        except Exception:
            await db.rollback()
            experience = await db.get(MaintenanceExperience, experience_id)
            if experience is None:
                return
            experience.vector_index_status = "failed"
            experience.updated_at = _now()
            await db.commit()
            raise


def schedule_experience_index(experience_id: str | None) -> None:
    normalized = _as_text(experience_id, limit=128)
    if not normalized:
        return
    _schedule_background_task(
        _index_experience_background(normalized),
        label=f"maintenance experience index {normalized}",
    )


async def create_maintenance_experience(
    db: AsyncSession,
    *,
    actor_user_id: str | None,
    actor_role: str | None,
    source_type: str,
    source_text: str,
    source_work_order_id: str | None = None,
    source_dispatch_id: str | None = None,
    source_step_plan_id: str | None = None,
    contributor_user_id: str | None = None,
    contributor_role: str | None = None,
    building_id: str | None = None,
    device_id: str | None = None,
    device_type: str | None = None,
    fault_type: str | None = None,
    allow_ignored: bool = False,
    commit: bool = True,
    auto_enqueue: bool = True,
) -> dict[str, Any]:
    _require_write_role(actor_role)
    normalized_source_type = _normalize_source_type(source_type)
    normalized_text = _as_text(source_text, limit=MAX_TEXT_LENGTH)
    if not normalized_text:
        raise HTTPException(status_code=400, detail="经验原文不能为空")

    resolved_building_id, resolved_device_type, resolved_fault_type, _ = await _resolve_context_metadata(
        db,
        source_work_order_id=source_work_order_id,
        building_id=building_id,
        device_id=device_id,
        device_type=device_type,
        fault_type=fault_type,
    )
    classification = await classify_experience_text(normalized_text, source_type=normalized_source_type)
    if not classification.get("is_experience"):
        if allow_ignored:
            return {
                "status": "ignored",
                "is_experience": False,
                "reason": classification.get("reason") or "内容不属于经验类，未入库。",
            }
        raise HTTPException(status_code=422, detail=classification.get("reason") or "内容不属于经验类")

    duplicate = await _find_duplicate_experience(
        db,
        source_type=normalized_source_type,
        source_work_order_id=_as_text(source_work_order_id, limit=64) or None,
        source_dispatch_id=_as_text(source_dispatch_id, limit=128) or None,
        source_step_plan_id=_as_text(source_step_plan_id, limit=128) or None,
        contributor_user_id=_as_text(contributor_user_id or actor_user_id, limit=128) or None,
        source_text=normalized_text,
    )
    if duplicate is not None:
        payload = _serialize_experience(duplicate, include_source_text=True)
        payload["status"] = "existing"
        return payload

    organized, model_provider, model_name = await organize_experience_text(
        normalized_text,
        building_id=resolved_building_id,
        device_type=resolved_device_type,
        fault_type=resolved_fault_type,
    )
    experience = MaintenanceExperience(
        id=str(uuid.uuid4()),
        source_type=normalized_source_type,
        source_work_order_id=_as_text(source_work_order_id, limit=64) or None,
        source_dispatch_id=_as_text(source_dispatch_id, limit=128) or None,
        source_step_plan_id=_as_text(source_step_plan_id, limit=128) or None,
        contributor_user_id=_as_text(contributor_user_id or actor_user_id, limit=128) or None,
        contributor_role=_as_text(contributor_role or actor_role, limit=32) or None,
        building_id=resolved_building_id,
        device_id=_as_text(device_id, limit=128) or None,
        device_type=resolved_device_type,
        fault_type=_as_text(organized.get("fault_type"), limit=128) or resolved_fault_type,
        fault_keywords_json=_json_dumps(organized.get("fault_keywords") or []),
        symptom_tags_json=_json_dumps(organized.get("symptom_tags") or []),
        source_text=normalized_text,
        organized_text=_as_text(organized.get("organized_text"), limit=1200),
        suggested_steps_json=_json_dumps(organized.get("suggested_steps") or []),
        safety_notes_json=_json_dumps(organized.get("safety_notes") or []),
        applicable_conditions_json=_json_dumps(organized.get("applicable_conditions") or []),
        conflict_flags_json=_json_dumps(organized.get("conflict_flags") or []),
        model_provider=model_provider,
        model_name=model_name,
        vector_index_status="pending",
        updated_at=_now(),
    )
    db.add(experience)
    await db.flush()
    if commit:
        await db.commit()
        await delete_cache_by_prefix(EXPERIENCE_CACHE_PREFIX)
    if auto_enqueue:
        schedule_experience_index(experience.id)
    payload = _serialize_experience(experience, include_source_text=True)
    payload["status"] = "created"
    return payload


async def add_maintenance_experience_feedback(
    db: AsyncSession,
    *,
    actor_user_id: str | None,
    actor_role: str | None,
    experience_id: str,
    feedback: str,
    work_order_id: str | None,
    note: str | None,
) -> dict[str, Any]:
    _require_read_role(actor_role)
    normalized_feedback = _normalize_feedback(feedback)
    experience = await db.get(MaintenanceExperience, experience_id)
    if experience is None:
        raise HTTPException(status_code=404, detail="经验不存在")

    db.add(
        MaintenanceExperienceFeedback(
            id=str(uuid.uuid4()),
            experience_id=experience.id,
            user_id=_as_text(actor_user_id, limit=128) or None,
            work_order_id=_as_text(work_order_id, limit=64) or None,
            feedback=normalized_feedback,
            note=_as_text(note, limit=1000) or None,
        )
    )
    if normalized_feedback == "helpful":
        experience.helpful_count = int(experience.helpful_count or 0) + 1
    elif normalized_feedback == "incorrect":
        experience.incorrect_count = int(experience.incorrect_count or 0) + 1
    else:
        experience.unhelpful_count = int(experience.unhelpful_count or 0) + 1
    experience.updated_at = _now()
    await db.commit()
    await delete_cache_by_prefix(EXPERIENCE_CACHE_PREFIX)
    return {
        "ok": True,
        "experience_id": experience.id,
        "feedback": normalized_feedback,
        "helpful_count": int(experience.helpful_count or 0),
        "unhelpful_count": int(experience.unhelpful_count or 0),
        "incorrect_count": int(experience.incorrect_count or 0),
    }


async def deactivate_maintenance_experience(
    db: AsyncSession,
    *,
    actor_user_id: str | None,
    actor_role: str | None,
    experience_id: str,
    reason: str | None,
) -> dict[str, Any]:
    _require_deactivate_role(actor_role)
    experience = await db.get(MaintenanceExperience, experience_id)
    if experience is None:
        raise HTTPException(status_code=404, detail="经验不存在")
    if not experience.is_active:
        return {"ok": True, "status": "already_inactive", "experience_id": experience.id, "is_active": False}
    experience.is_active = False
    experience.deactivated_by = _as_text(actor_user_id, limit=128) or None
    experience.deactivated_reason = _as_text(reason, limit=1000) or None
    experience.deactivated_at = _now()
    experience.updated_at = _now()
    await db.commit()
    await delete_cache_by_prefix(EXPERIENCE_CACHE_PREFIX)
    return {"ok": True, "status": "deactivated", "experience_id": experience.id, "is_active": False}


async def retrieve_experience_recommendations_for_work_order(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    dispatch_id: str | None,
    assistant_session_id: str | None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    building_id, device_type, fault_type, _ = await _resolve_context_metadata(
        db,
        source_work_order_id=work_order.ticket_id,
        building_id=work_order.building_id,
        device_id=work_order.device_id,
        device_type=None,
        fault_type=None,
    )
    result = await _search_experiences_uncached(
        db,
        query=" ".join(
            part
            for part in (
                _as_text(work_order.issue_description, limit=400),
                _as_text(work_order.suggested_action, limit=200),
            )
            if part
        ),
        building_id=building_id,
        device_type=device_type,
        fault_type=fault_type,
        limit=max(1, min(limit, 5)),
        include_inactive=False,
        sort_by="score",
    )
    recommendations: list[dict[str, Any]] = []
    for item in result.get("items") or []:
        recommendations.append(
            {
                "experience_id": item["id"],
                "source_work_order_id": item.get("source_work_order_id"),
                "source_contributor_name": item.get("source_contributor_name"),
                "contributor_user_id": item.get("contributor_user_id"),
                "contributor_role": item.get("contributor_role"),
                "organized_text": item.get("organized_text"),
                "confidence": float(item.get("score") or 0),
                "helpful_count": int(item.get("helpful_count") or 0),
                "safety_notes": item.get("safety_notes") or [],
                "conflict_flags": item.get("conflict_flags") or [],
            }
        )
        experience = await db.get(MaintenanceExperience, item["id"])
        if experience is None:
            continue
        experience.usage_count = int(experience.usage_count or 0) + 1
        experience.updated_at = _now()
        db.add(
            MaintenanceExperienceUsageLog(
                id=str(uuid.uuid4()),
                experience_id=experience.id,
                work_order_id=work_order.ticket_id,
                dispatch_id=_as_text(dispatch_id, limit=128) or None,
                assistant_session_id=_as_text(assistant_session_id, limit=128) or None,
                usage_type="retrieved",
            )
        )
    return recommendations


def looks_like_experience_query(text: str) -> bool:
    normalized = text or ""
    keywords = (
        "经验",
        "历史上大家怎么处理",
        "类似问题怎么处理",
        "最近有哪些",
        "被引用最多",
        "被采纳最多",
        "复用最多",
        "使用最多",
        "无效经验",
        "停用经验",
    )
    return any(keyword in normalized for keyword in keywords)


def _extract_query_hint(text: str, fallback: str | None = None) -> str:
    normalized = _as_text(text, limit=300)
    for phrase in (
        "最近有哪些",
        "这类问题历史上大家怎么处理",
        "历史上大家怎么处理",
        "类似问题怎么处理",
        "被引用最多",
        "被采纳最多",
        "复用最多",
        "使用最多",
        "无效经验",
        "停用经验",
        "经验",
    ):
        normalized = normalized.replace(phrase, " ")
    normalized = " ".join(normalized.split())
    return normalized or _as_text(fallback, limit=200)


async def build_operator_experience_answer(
    db: AsyncSession,
    *,
    actor_role: str | None,
    message: str,
    work_order: WorkOrder | None,
) -> dict[str, Any]:
    _require_read_role(actor_role)
    sort_by = "score"
    if any(token in message for token in ("最近", "最新")):
        sort_by = "recent"
    if any(token in message for token in ("引用最多", "被引用最多", "采纳最多", "被采纳最多", "复用最多", "使用最多")):
        sort_by = "usage"
    include_inactive = any(token in message for token in ("无效", "停用", "incorrect", "错误经验"))

    query = _extract_query_hint(
        message,
        fallback=getattr(work_order, "issue_description", None) if work_order is not None else None,
    )
    building_id = getattr(work_order, "building_id", None) if work_order is not None else None
    device_type = None
    fault_type = None
    if work_order is not None:
        building_id, device_type, fault_type, _ = await _resolve_context_metadata(
            db,
            source_work_order_id=work_order.ticket_id,
            building_id=work_order.building_id,
            device_id=work_order.device_id,
            device_type=None,
            fault_type=None,
        )

    result = await search_maintenance_experiences(
        db,
        actor_role=actor_role,
        query=query,
        building_id=building_id,
        device_type=device_type,
        fault_type=fault_type,
        limit=5,
        include_inactive=include_inactive,
        sort_by=sort_by,
    )
    items = result.get("items") or []
    if not items:
        return {
            "answer": "当前没有符合条件的经验记录。",
            "facts": {"items": []},
            "evidence_refs": ["maintenance_experiences"],
            "suggested_followups": ["换一个更具体的故障描述", "查看当前工单的维修指导记录"],
        }

    header = "已找到以下经验记录："
    if sort_by == "recent":
        header = "最近的相关经验如下："
    elif sort_by == "usage":
        header = "被复用较多的经验如下："
    elif work_order is not None:
        header = f"围绕 {work_order.ticket_id} 的相似经验如下："

    lines = [header]
    for index, item in enumerate(items, start=1):
        source = item.get("source_work_order_id") or item.get("source_type") or "未知来源"
        contributor = resolve_experience_source_contributor_name(item)
        experience_label = f"{contributor}的经验" if contributor else "经验"
        state_label = "停用" if not item.get("is_active", True) else "启用"
        lines.append(
            f"{index}. {experience_label}：{item.get('organized_text') or '经验原文缺失'}"
            f"（来源 {source}，匹配 {float(item.get('score') or 0):.2f}，"
            f"复用 {int(item.get('usage_count') or 0)}，有用 {int(item.get('helpful_count') or 0)}，{state_label}）"
        )
    return {
        "answer": "\n".join(lines),
        "facts": {"items": items},
        "evidence_refs": [
            "maintenance_experiences",
            "maintenance_experience_usage_logs",
            "maintenance_experience_feedback",
        ],
        "suggested_followups": ["查看某条经验的来源工单", "查看当前工单的维修指导记录"],
    }


async def _capture_experience_background(payload: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as db:
        await create_maintenance_experience(
            db,
            actor_user_id=payload.get("actor_user_id"),
            actor_role=payload.get("actor_role"),
            source_type=payload["source_type"],
            source_text=payload["source_text"],
            source_work_order_id=payload.get("source_work_order_id"),
            source_dispatch_id=payload.get("source_dispatch_id"),
            source_step_plan_id=payload.get("source_step_plan_id"),
            contributor_user_id=payload.get("contributor_user_id"),
            contributor_role=payload.get("contributor_role"),
            building_id=payload.get("building_id"),
            device_id=payload.get("device_id"),
            device_type=payload.get("device_type"),
            fault_type=payload.get("fault_type"),
            allow_ignored=True,
            commit=True,
            auto_enqueue=True,
        )


def schedule_experience_capture(
    *,
    actor_user_id: str | None,
    actor_role: str | None,
    source_type: str,
    source_text: str,
    source_work_order_id: str | None,
    source_dispatch_id: str | None = None,
    source_step_plan_id: str | None = None,
    contributor_user_id: str | None = None,
    contributor_role: str | None = None,
    building_id: str | None = None,
    device_id: str | None = None,
    device_type: str | None = None,
    fault_type: str | None = None,
) -> None:
    normalized_text = _as_text(source_text, limit=MAX_TEXT_LENGTH)
    if not normalized_text:
        return
    _schedule_background_task(
        _capture_experience_background(
            {
                "actor_user_id": actor_user_id,
                "actor_role": actor_role,
                "source_type": source_type,
                "source_text": normalized_text,
                "source_work_order_id": source_work_order_id,
                "source_dispatch_id": source_dispatch_id,
                "source_step_plan_id": source_step_plan_id,
                "contributor_user_id": contributor_user_id,
                "contributor_role": contributor_role,
                "building_id": building_id,
                "device_id": device_id,
                "device_type": device_type,
                "fault_type": fault_type,
            }
        ),
        label=f"maintenance experience capture {source_type}",
    )


__all__ = [
    "build_operator_experience_answer",
    "create_maintenance_experience",
    "deactivate_maintenance_experience",
    "looks_like_experience_query",
    "retrieve_experience_recommendations_for_work_order",
    "schedule_experience_capture",
    "schedule_experience_index",
    "search_maintenance_experiences",
]
