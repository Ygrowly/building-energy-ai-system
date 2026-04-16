from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import (
    DispatchHallEntry,
    DispatchTask,
    User,
    WorkOrder,
    WorkOrderAnomalyLink,
    WorkerAiStepEvent,
    WorkerAiStepPlan,
)
from app.schemas.mcp_schemas import MCPError
from app.services.ai_model_provider import get_model_provider, parse_json_object
from app.services.maintenance_experience_service import (
    retrieve_experience_recommendations_for_work_order,
    schedule_experience_capture,
)
from app.services.rag_engine import search_ragflow
from app.services.worker_ai_service import _append_message, _assert_worker_permission, _ensure_session, _resolve_work_order

logger = logging.getLogger(__name__)

STEP_STATUSES = {"pending", "completed", "skipped", "needs_support", "uncertain"}
ACTIVE_PLAN_STATUS = "active"


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _as_text(value: Any, *, limit: int = 2000) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _select_current_step(steps: list[dict[str, Any]], step_id: str | None = None) -> dict[str, Any] | None:
    if step_id:
        for step in steps:
            if step.get("id") == step_id:
                return step
    return (
        next((step for step in steps if step.get("status") in {"pending", "uncertain"}), None)
        or next((step for step in steps if step.get("status") == "needs_support"), None)
        or next((step for step in steps if step.get("status") not in {"completed", "skipped"}), None)
    )


def _build_rag_query(work_order: WorkOrder) -> str:
    parts = [
        work_order.issue_description,
        work_order.suggested_action,
        work_order.building_id,
        work_order.device_id,
        "维修步骤 排查 安全 注意事项",
    ]
    return " ".join(str(item) for item in parts if item)


def _fallback_step_plan(
    *,
    work_order: WorkOrder,
    rag_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if _is_hvac_chiller_issue(work_order):
        return _fallback_hvac_chiller_step_plan(work_order=work_order, rag_refs=rag_refs)

    issue = _as_text(work_order.issue_description, limit=120) or "当前异常"
    device = work_order.device_id or "相关设备"
    return {
        "guide_version": 1,
        "summary": f"维小修已根据工单“{issue}”生成基础排查步骤。当前如果知识库或模型不可用，请按安全确认、读数核对、设备检查、协同判断的顺序推进。",
        "root_cause_candidates": [
            {
                "name": "现场读数或传感器链路异常",
                "confidence": "medium",
                "evidence": ["工单描述存在指标偏离或设备异常，需要先核对现场事实"],
            },
            {
                "name": "设备执行机构或运行工况异常",
                "confidence": "medium",
                "evidence": [f"需检查 {device} 及其关联阀门、泵、电控或通信状态"],
            },
        ],
        "steps": [
            {
                "id": "step_1",
                "title": "确认现场安全与工单对象",
                "instruction": "到达现场后先确认作业环境、安全授权和设备位置，核对工单中的楼宇、设备与异常描述。",
                "reason": "避免走错设备或在未确认安全条件下操作。",
                "expected_result": "确认现场可安全排查，工单对象与现场设备一致。",
                "risk_note": "涉及电控柜、泵房或高处区域时先按现场安全规范执行。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_2",
                "title": "核对现场读数",
                "instruction": "查看就地仪表、控制屏或设备状态灯，并记录关键读数。能拍照时上传现场照片给维小修辅助判断。",
                "reason": "先确认系统异常是否与现场读数一致。",
                "expected_result": "得到现场读数或状态，与系统记录可对比。",
                "risk_note": "不要在未记录现状前重置设备或清除报警。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_3",
                "title": "检查传感器与通信链路",
                "instruction": "检查传感器外观、接线、供电和通信状态，确认是否存在松动、污染、遮挡或离线。",
                "reason": "偏差类工单常见原因是传感器或通信链路异常。",
                "expected_result": "确认传感器链路正常，或发现需要校准/更换/恢复通信的问题。",
                "risk_note": "拆接线前先确认断电和授权。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_4",
                "title": "检查执行设备运行状态",
                "instruction": "检查阀门、泵、风机、过滤网、控制柜或相关执行机构的运行状态和报警信息。",
                "reason": "如果读数可信，下一步需要判断系统实际工况是否异常。",
                "expected_result": "确认执行设备是否正常运行，是否存在卡滞、漏水、堵塞、跳停或报警。",
                "risk_note": "不要绕过联锁保护或强制运行存在故障风险的设备。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_5",
                "title": "汇总结论并决定下一步",
                "instruction": "把发现、读数、照片和处理动作记录下来；若超出个人能力或需要其他班组，向维小修说“请求协同，因为...”。",
                "reason": "保证后续完成、协同或升级都有清晰依据。",
                "expected_result": "形成可提交的维修备注或协同原因。",
                "risk_note": "不要让 AI 自动替你判定完成，最终仍由维修人员确认。",
                "requires_photo": False,
                "status": "pending",
            },
        ],
        "safety_notes": [
            "涉及带电、压力管路、泵房、阀门拆卸时先遵守现场安全规范。",
            "AI 步骤是辅助建议，不替代维修人员的专业判断。",
        ],
        "rag_refs": rag_refs or [],
    }


def _is_hvac_chiller_issue(work_order: WorkOrder) -> bool:
    text = f"{work_order.issue_description} {work_order.suggested_action} {work_order.device_id or ''}".lower()
    keywords = ("暖通", "hvac", "冷水机", "冷机", "cop", "冷凝器", "蒸发器", "制冷剂", "冷冻水", "冷却水")
    return any(keyword in text for keyword in keywords)


def _fallback_hvac_chiller_step_plan(
    *,
    work_order: WorkOrder,
    rag_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issue = _as_text(work_order.issue_description, limit=160) or "暖通能耗异常"
    return {
        "guide_version": 1,
        "summary": f"这张工单指向暖通能耗异常/冷水机组效能衰退：{issue}。建议先确认机组实际运行与负荷，再核算 COP，随后排查换热、冷却水/冷冻水侧和制冷剂状态。",
        "root_cause_candidates": [
            {
                "name": "冷水机组 COP 降低",
                "confidence": "high",
                "evidence": ["工单根因已指向冷水机组效能衰退", "暖通能耗实际值显著高于预期值"],
            },
            {
                "name": "冷凝器/蒸发器换热效率下降",
                "confidence": "medium",
                "evidence": ["建议动作包含清洗冷凝器/蒸发器", "换热恶化会导致压缩机功耗上升"],
            },
            {
                "name": "制冷剂充注量或冷却水侧工况异常",
                "confidence": "medium",
                "evidence": ["建议动作包含检查制冷剂充注量", "冷却水流量/温度异常会拉低机组效率"],
            },
        ],
        "steps": [
            {
                "id": "step_1",
                "title": "确认冷水机组与作业安全",
                "instruction": "到机房后先核对工单对应的冷水机组、控制柜和运行编号，确认现场无漏水、异响、异味和电气告警后再继续。",
                "reason": "先确认对象和安全边界，避免误查非目标机组或带风险操作。",
                "expected_result": "确认目标机组、当前运行/停机状态和现场安全条件。",
                "risk_note": "涉及电控柜、压力管路和旋转设备时，不要擅自开柜或解除联锁。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_2",
                "title": "核对 BMS 与机组面板关键读数",
                "instruction": "记录机组面板或 BMS 上的供回水温度、冷冻水/冷却水进出水温度、负荷率、电流或功率、报警码和运行模式。",
                "reason": "这一步用于确认能耗异常是真实运行效率问题，还是数据采集或运行模式异常。",
                "expected_result": "得到可用于核算 COP 和判断换热状态的关键读数。",
                "risk_note": "不要先复位报警；先拍照或记录当前状态。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_3",
                "title": "复核冷水机组 COP 和负荷匹配",
                "instruction": "结合当前冷量、功率、供回水温差和负荷率，判断 COP 是否明显低于正常范围，并确认是否存在低负荷长时间运行或多台机组分配不合理。",
                "reason": "工单根因是效能衰退，COP 与负荷匹配是最直接的判断入口。",
                "expected_result": "明确是效率降低、负荷调度不合理，还是数据读数异常。",
                "risk_note": "如果缺少流量或冷量数据，先记录缺项，不要用猜测结论替代现场事实。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_4",
                "title": "检查冷凝器、蒸发器和水侧换热",
                "instruction": "检查冷凝器/蒸发器是否存在结垢、堵塞、过滤器压差异常、冷却水温偏高、冷却塔或水泵运行异常。",
                "reason": "换热变差会推高冷凝压力或降低蒸发效率，导致机组耗电升高。",
                "expected_result": "判断是否需要清洗换热器、处理过滤器或检查冷却水系统。",
                "risk_note": "涉及拆洗、排污或水泵操作时按现场检修规程执行。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_5",
                "title": "检查制冷剂与压缩机运行迹象",
                "instruction": "查看是否有低压/高压报警、结霜、油位异常、异常噪声或制冷剂泄漏迹象；必要时请有资质人员检查充注量和压力参数。",
                "reason": "制冷剂不足或压缩机异常会直接造成冷量不足和能耗升高。",
                "expected_result": "形成是否需要制冷专业人员介入的判断。",
                "risk_note": "制冷剂和压力系统检查需要资质，不能凭 AI 建议直接拆卸或充注。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_6",
                "title": "形成处理结论或请求协同",
                "instruction": "把 COP、关键读数、报警、照片和初步判断记录下来；如果需要清洗、制冷剂检查或电气协助，直接告诉我“请求协同，因为...”。",
                "reason": "让后续完成、协同或升级有明确依据。",
                "expected_result": "得到可提交的维修备注、协同原因或升级建议。",
                "risk_note": "不要让 AI 自动替你判定工单完成，最终由维修人员确认。",
                "requires_photo": False,
                "status": "pending",
            },
        ],
        "safety_notes": [
            "冷水机组涉及电气、压力和旋转部件，先确认现场安全和授权。",
            "制冷剂、压力系统和电控柜操作必须由具备资质的人员执行。",
            "AI 步骤是辅助建议，不替代现场维修规程和专业判断。",
        ],
        "rag_refs": rag_refs or [],
    }


def _normalize_step_plan(raw: dict[str, Any] | None, *, work_order: WorkOrder, rag_refs: list[dict[str, Any]]) -> dict[str, Any]:
    if not raw:
        return _fallback_step_plan(work_order=work_order, rag_refs=rag_refs)

    fallback = _fallback_step_plan(work_order=work_order, rag_refs=rag_refs)
    steps = raw.get("steps") if isinstance(raw.get("steps"), list) else []
    normalized_steps: list[dict[str, Any]] = []
    for index, step in enumerate(steps[:8], start=1):
        if not isinstance(step, dict):
            continue
        title = _as_text(step.get("title"), limit=80)
        instruction = _as_text(step.get("instruction"), limit=500)
        if not title or not instruction:
            continue
        status = step.get("status") if step.get("status") in STEP_STATUSES else "pending"
        normalized_steps.append(
            {
                "id": _as_text(step.get("id"), limit=64) or f"step_{index}",
                "title": title,
                "instruction": instruction,
                "reason": _as_text(step.get("reason"), limit=400),
                "expected_result": _as_text(step.get("expected_result"), limit=400),
                "risk_note": _as_text(step.get("risk_note"), limit=300),
                "requires_photo": bool(step.get("requires_photo", False)),
                "status": status,
                "note": _as_text(step.get("note"), limit=300),
            }
        )
    if not normalized_steps:
        normalized_steps = fallback["steps"]

    root_causes = raw.get("root_cause_candidates")
    if not isinstance(root_causes, list) or not root_causes:
        root_causes = fallback["root_cause_candidates"]

    safety_notes = raw.get("safety_notes")
    if not isinstance(safety_notes, list) or not safety_notes:
        safety_notes = fallback["safety_notes"]

    return {
        "guide_version": int(raw.get("guide_version") or 1),
        "summary": _as_text(raw.get("summary"), limit=800) or fallback["summary"],
        "root_cause_candidates": root_causes[:5],
        "steps": normalized_steps,
        "safety_notes": [_as_text(item, limit=240) for item in safety_notes[:5] if _as_text(item, limit=240)],
        "rag_refs": rag_refs,
    }


async def _load_context(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
) -> dict[str, Any]:
    anomaly_result = await db.execute(
        select(WorkOrderAnomalyLink)
        .where(WorkOrderAnomalyLink.work_order_id == work_order.id)
        .order_by(WorkOrderAnomalyLink.data_timestamp.desc())
        .limit(5)
    )
    anomalies = []
    for item in anomaly_result.scalars().all():
        anomalies.append(
            {
                "rule_triggered": item.rule_triggered,
                "hvac_root_cause": item.hvac_root_cause,
                "actual_value": item.actual_value,
                "expected_value": item.expected_value,
                "deviation_pct": item.deviation_pct,
                "data_timestamp": item.data_timestamp.isoformat() if item.data_timestamp else None,
            }
        )

    predicates = [WorkOrder.building_id == work_order.building_id]
    if work_order.device_id:
        predicates.append(WorkOrder.device_id == work_order.device_id)
    similar_result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.id != work_order.id)
        .where(or_(*predicates))
        .order_by(WorkOrder.created_at.desc())
        .limit(5)
    )
    similar = []
    for item in similar_result.scalars().all():
        similar.append(
            {
                "ticket_id": item.ticket_id,
                "status": item.status,
                "issue_description": item.issue_description,
                "worker_result": item.worker_result,
                "worker_notes": item.worker_notes,
            }
        )

    return {
        "work_order": {
            "ticket_id": work_order.ticket_id,
            "building_id": work_order.building_id,
            "device_id": work_order.device_id,
            "issue_description": work_order.issue_description,
            "suggested_action": work_order.suggested_action,
            "priority": work_order.priority,
            "status": work_order.status,
            "processing_started_at": work_order.processing_started_at.isoformat() if work_order.processing_started_at else None,
        },
        "anomaly_evidence": anomalies,
        "similar_work_orders": similar,
    }


async def _retrieve_manual_context(work_order: WorkOrder) -> tuple[list[dict[str, Any]], bool, str | None]:
    rag_output = await search_ragflow(_build_rag_query(work_order), top_k=3)
    if isinstance(rag_output, MCPError):
        return [], False, rag_output.error
    refs = [
        {
            "content": result.content[:600],
            "source_doc": result.source_doc,
            "parent_section": result.parent_section,
            "similarity": result.similarity,
        }
        for result in rag_output.results
    ]
    return refs, rag_output.reranked, None


async def _generate_plan_with_model(
    *,
    context: dict[str, Any],
    rag_refs: list[dict[str, Any]],
    experience_recommendations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    provider = get_model_provider()
    if provider is None:
        return None
    settings = get_settings()
    system_prompt = (
        "你是维修端 AI 维小修，任务是给现场维修人员生成可执行的辅助维修步骤。"
        "必须只输出合法 JSON 对象，不要输出 Markdown，不要输出思考过程。"
        "步骤必须基于工单上下文、异常证据、相似工单和可用知识库内容自主判断，不要套用固定模板。"
        "优先给非侵入式、可观察、可记录的现场检查步骤。"
        "涉及断电挂牌、开柜、拆卸、制冷剂充注、压力系统、电气测量、化学清洗等高风险动作时，"
        "只能建议联系具备资质的人员或按现场规程执行，不能把它写成普通维修人员直接操作的步骤。"
        "不能自动替维修人员确认工单完成，不能要求绕过安全规范。"
        "不要编造维保记录、历史结论、资质证书名称/编号、法规标准编号、设备铭牌参数或固定阈值。"
        "如果需要阈值或资质要求，只能写“按机组手册/现场规程/具备资质人员确认”。"
    )
    user_prompt = {
        "context": context,
        "rag_refs": rag_refs,
        "experience_recommendations": experience_recommendations,
        "schema": {
            "guide_version": 1,
            "summary": "string",
            "root_cause_candidates": [
                {"name": "string", "confidence": "low|medium|high", "evidence": ["string"]}
            ],
            "steps": [
                {
                    "id": "step_1",
                    "title": "string",
                    "instruction": "string",
                    "reason": "string",
                    "expected_result": "string",
                    "risk_note": "string",
                    "requires_photo": "boolean",
                    "status": "pending",
                }
            ],
            "safety_notes": ["string"],
        },
        "generation_rules": [
            "不要编造未提供的实时读数、维保记录、历史工单编号、法规阈值、资质证书名称或设备铭牌参数。",
            "如果证据不足，写成需要现场确认，不要下定论。",
            "每个步骤都要说明为什么这样查，以及完成后维修人员应该告诉 AI 什么事实。",
            "高风险操作必须表述为升级/协同/由有资质人员执行。",
            "不要使用“唯一可靠依据”“必须拆开检查”这类绝对化表述。",
        ],
    }
    try:
        raw = await provider.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False, default=str)},
            ],
            response_schema={"type": "object"},
            temperature=0.2,
        )
    except Exception as exc:
        logger.info("维小修维修步骤生成降级为本地模板: %s", exc)
        return None
    return parse_json_object(raw)


def _normalize_guidance_reply(raw: dict[str, Any] | None, *, fallback: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return fallback
    answer = _as_text(raw.get("answer"), limit=1200)
    if not answer:
        return fallback
    suggested_status = raw.get("suggested_step_status")
    if suggested_status not in {"pending", "uncertain", "needs_support"}:
        suggested_status = None
    followups = raw.get("suggested_followups")
    if not isinstance(followups, list):
        followups = []
    return {
        "answer": answer,
        "suggested_step_status": suggested_status,
        "suggested_next_message": _as_text(raw.get("suggested_next_message"), limit=300),
        "suggested_followups": [_as_text(item, limit=120) for item in followups[:3] if _as_text(item, limit=120)],
        "safety_level": raw.get("safety_level") if raw.get("safety_level") in {"normal", "caution", "danger"} else "normal",
    }


def _fallback_guidance_reply(
    *,
    message: str,
    work_order: WorkOrder,
    current_step: dict[str, Any] | None,
) -> dict[str, Any]:
    text = _as_text(message, limit=500)
    step_title = _as_text((current_step or {}).get("title"), limit=80) or "当前步骤"
    leak_like = any(token in text for token in ("泄漏", "漏水", "漏油", "漏液", "外流", "流出", "往外流", "渗", "滴", "喷出"))
    compressor_like = "压缩机" in text
    if leak_like:
        target = "压缩机附近" if compressor_like else "异常位置"
        return {
            "answer": (
                f"这条情况要先按现场安全异常处理：{target}出现不明介质外流时，先不要复位、拆动或强行继续运行。"
                "请先确认外流的是水、油、冷凝水还是疑似制冷剂，记录外流位置、颜色、气味、是否伴随结霜/异响/报警，能拍照就先上传照片。"
                f"这比“{step_title}”更优先；如果无法判断介质来源、外流持续扩大，或涉及制冷剂/油路/电气部位，请直接说“请求协同，因为压缩机附近有不明介质持续外流”。"
            ),
            "suggested_step_status": "uncertain",
            "suggested_next_message": "请拍一张外流位置和机组面板报警，再补充外流物看起来像水、油还是雾状冷媒。",
            "suggested_followups": ["外流位置在哪里？", "机组面板有没有报警？", "外流物像水、油还是雾状冷媒？"],
            "safety_level": "danger",
        }

    if any(token in text for token in ("报警", "故障码", "告警")):
        return {
            "answer": (
                f"我先把这条现场信息归到“{step_title}”里。请先不要复位报警，记录报警码、发生时间和当前运行状态；"
                "如果有面板照片可以上传，我会结合工单和当前步骤继续判断下一步。"
            ),
            "suggested_step_status": "pending",
            "suggested_next_message": "请补充报警码或上传面板照片。",
            "suggested_followups": ["报警码是什么？", "报警前后机组运行状态有没有变化？"],
            "safety_level": "caution",
        }

    return {
        "answer": (
            f"我收到这个现场情况，会先结合“{step_title}”判断。请把关键事实补全：当前读数/状态、看到的位置、是否有报警、"
            "是否能拍照。信息不足时先不要直接判定完成，我会根据你补充的现场事实调整下一步。"
        ),
        "suggested_step_status": "pending",
        "suggested_next_message": "请补充关键读数、报警或现场照片。",
        "suggested_followups": ["有哪些关键读数？", "现场有没有报警或异响？"],
        "safety_level": "normal",
    }


async def _generate_guidance_reply_with_model(
    *,
    message: str,
    context: dict[str, Any],
    plan: WorkerAiStepPlan,
    steps: list[dict[str, Any]],
    current_step: dict[str, Any] | None,
    recent_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    provider = get_model_provider()
    if provider is None:
        return None
    system_prompt = (
        "你是维修端 AI 维小修，现在处于维修指导阶段。"
        "你要根据当前工单、维修步骤计划、当前步骤和维修人员刚描述的现场情况，给出下一步诊断建议。"
        "不要回答接单、到场、开始处理、请求协同、完成等工单动作菜单；这些由另一个动作执行器处理。"
        "你的口吻要像正在陪现场师傅排查，不要像规章制度或状态机。"
        "除非安全风险很高，answer 不要堆长清单；优先用 1 段判断加最多 3 个下一步要点。"
        "如果用户描述漏液、外流、冒烟、异味、异常噪声、带电风险、压力系统或制冷剂风险，先给安全优先建议。"
        "可以建议调整步骤顺序，但不能自动替用户完成步骤或改变工单状态。"
        "不要编造未提供的读数、阈值、维保记录、证书、法规编号或设备铭牌参数。"
        "必须只输出合法 JSON 对象，不要输出 Markdown，不要输出思考过程。"
    )
    user_prompt = {
        "worker_message": message,
        "context": context,
        "step_plan": {
            "plan_id": plan.id,
            "summary": plan.summary,
            "root_cause_candidates": _json_loads(plan.root_cause_candidates_json, []),
            "safety_notes": _json_loads(plan.safety_notes_json, []),
            "steps": steps,
        },
        "current_step": current_step,
        "recent_events": recent_events,
        "output_schema": {
            "answer": "string",
            "suggested_step_status": "pending|uncertain|needs_support|null",
            "suggested_next_message": "string|null",
            "suggested_followups": ["string"],
            "safety_level": "normal|caution|danger",
        },
        "rules": [
            "answer 要直接面向维修人员，先回应他刚说的现场情况，再说明下一步该观察什么。",
            "少用“必须、禁止、流程、状态机、规则”等口吻；需要安全提醒时也要说清楚原因。",
            "如果现场描述明显比当前步骤更紧急，可以说明先临时切到更安全/更相关的检查。",
            "需要协同时只建议维修人员说“请求协同，因为...”，不要替他提交。",
            "如果信息不足，问 1 到 3 个关键澄清问题。",
        ],
    }
    try:
        raw = await provider.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False, default=str)},
            ],
            response_schema={"type": "object"},
            temperature=0.2,
        )
    except Exception as exc:
        logger.info("维小修指导对话降级为本地回复: %s", exc)
        return None
    return parse_json_object(raw)


def _is_guidance_ready(work_order: WorkOrder, dispatch_task: DispatchTask | None) -> bool:
    dispatch_status = getattr(dispatch_task, "dispatch_status", None)
    dispatch_started_at = getattr(dispatch_task, "processing_started_at", None)
    return bool(
        work_order.processing_started_at
        or dispatch_started_at
        or dispatch_status in {"processing", "waiting_support", "supporting"}
    )


def serialize_step_plan(plan: WorkerAiStepPlan, *, guidance_ready: bool = True) -> dict[str, Any]:
    generated_from = _json_loads(plan.generated_from_json, {})
    return {
        "plan_id": plan.id,
        "ticket_id": None,
        "dispatch_id": plan.dispatch_id,
        "status": plan.status,
        "plan_version": plan.version,
        "summary": plan.summary,
        "root_cause_candidates": _json_loads(plan.root_cause_candidates_json, []),
        "steps": _json_loads(plan.steps_json, []),
        "safety_notes": _json_loads(plan.safety_notes_json, []),
        "experience_recommendations": generated_from.get("experience_recommendations", []),
        "model_provider": plan.model_provider,
        "model_name": plan.model_name,
        "guidance_ready": guidance_ready,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


async def get_or_create_worker_step_plan(
    db: AsyncSession,
    *,
    ticket_id: str,
    dispatch_id: str | None,
    auto_generate: bool,
    user: User,
) -> dict[str, Any]:
    work_order, dispatch_task, hall_entry = await _resolve_work_order(
        db,
        ticket_id=ticket_id,
        dispatch_id=dispatch_id,
        hall_entry_id=None,
    )
    if work_order is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _assert_worker_permission(user, work_order, dispatch_task, hall_entry)

    existing_result = await db.execute(
        select(WorkerAiStepPlan)
        .where(WorkerAiStepPlan.work_order_id == work_order.id)
        .where(WorkerAiStepPlan.status == ACTIVE_PLAN_STATUS)
        .order_by(WorkerAiStepPlan.updated_at.desc())
        .limit(1)
    )
    existing = existing_result.scalar_one_or_none()
    guidance_ready = _is_guidance_ready(work_order, dispatch_task)
    if existing is not None or not auto_generate:
        if existing is None:
            return {
                "ticket_id": work_order.ticket_id,
                "dispatch_id": getattr(dispatch_task, "id", dispatch_id),
                "plan_id": None,
                "status": "not_generated",
                "plan_version": 0,
                "summary": "开始处理后，维小修会接入现场维修指导。",
                "root_cause_candidates": [],
                "steps": [],
                "safety_notes": [],
                "experience_recommendations": [],
                "guidance_ready": guidance_ready,
            }
        serialized = serialize_step_plan(existing, guidance_ready=guidance_ready)
        serialized["ticket_id"] = work_order.ticket_id
        return serialized

    if not guidance_ready:
        return {
            "ticket_id": work_order.ticket_id,
            "dispatch_id": getattr(dispatch_task, "id", dispatch_id),
            "plan_id": None,
            "status": "not_ready",
            "plan_version": 0,
            "summary": "当前工单还未进入处理阶段。请先在工单详情页完成接单、到场和开始处理，开始处理后维小修再接入现场指导。",
            "root_cause_candidates": [],
            "steps": [],
            "safety_notes": ["正式动手前请先确认现场安全和作业授权。"],
            "experience_recommendations": [],
            "guidance_ready": False,
        }

    context = await _load_context(db, work_order=work_order)
    rag_refs, rag_reranked, rag_error = await _retrieve_manual_context(work_order)
    experience_recommendations = await retrieve_experience_recommendations_for_work_order(
        db,
        work_order=work_order,
        dispatch_id=getattr(dispatch_task, "id", dispatch_id),
        assistant_session_id=None,
        limit=3,
    )
    model_plan = await _generate_plan_with_model(
        context=context,
        rag_refs=rag_refs,
        experience_recommendations=experience_recommendations,
    )
    normalized = _normalize_step_plan(model_plan, work_order=work_order, rag_refs=rag_refs)
    if rag_error:
        normalized["safety_notes"].append("当前 RAGFlow 检索不可用，本次步骤包含本地通用排查建议。")

    settings = get_settings()
    plan = WorkerAiStepPlan(
        id=str(uuid.uuid4()),
        work_order_id=work_order.id,
        dispatch_id=getattr(dispatch_task, "id", dispatch_id),
        generated_from_json=json.dumps(
            {
                "context": context,
                "rag_refs": rag_refs,
                "experience_recommendations": experience_recommendations,
                "rag_reranked": rag_reranked,
                "rag_error": rag_error,
            },
            ensure_ascii=False,
            default=str,
        ),
        root_cause_candidates_json=json.dumps(normalized["root_cause_candidates"], ensure_ascii=False, default=str),
        summary=normalized["summary"],
        steps_json=json.dumps(normalized["steps"], ensure_ascii=False, default=str),
        safety_notes_json=json.dumps(normalized["safety_notes"], ensure_ascii=False, default=str),
        status=ACTIVE_PLAN_STATUS,
        version=1,
        model_provider=settings.AI_PROVIDER if model_plan else "local_fallback",
        model_name=settings.AI_TEXT_MODEL if model_plan else "local_template",
        created_by=user.id,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(plan)
    await db.flush()
    db.add(
        WorkerAiStepEvent(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            step_id="plan",
            user_id=user.id,
            event_type="generate",
            payload_json=json.dumps({"source": plan.model_provider}, ensure_ascii=False),
        )
    )
    await db.commit()
    serialized = serialize_step_plan(plan, guidance_ready=guidance_ready)
    serialized["ticket_id"] = work_order.ticket_id
    return serialized


async def handle_worker_guidance_chat(
    db: AsyncSession,
    *,
    message: str,
    session_id: str | None,
    ticket_id: str,
    dispatch_id: str | None,
    plan_id: str | None,
    step_id: str | None,
    client_context: dict[str, Any] | None,
    user: User,
) -> dict[str, Any]:
    text = _as_text(message, limit=1000)
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")

    work_order, dispatch_task, hall_entry = await _resolve_work_order(
        db,
        ticket_id=ticket_id,
        dispatch_id=dispatch_id,
        hall_entry_id=None,
    )
    if work_order is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _assert_worker_permission(user, work_order, dispatch_task, hall_entry)
    if not _is_guidance_ready(work_order, dispatch_task):
        raise HTTPException(status_code=409, detail="当前工单还未进入处理阶段，请先完成接单、到场和开始处理")

    plan: WorkerAiStepPlan | None = None
    if plan_id:
        plan = await db.get(WorkerAiStepPlan, plan_id)
        if plan is None or plan.work_order_id != work_order.id or plan.status != ACTIVE_PLAN_STATUS:
            raise HTTPException(status_code=404, detail="步骤计划不存在")
    else:
        result = await db.execute(
            select(WorkerAiStepPlan)
            .where(WorkerAiStepPlan.work_order_id == work_order.id)
            .where(WorkerAiStepPlan.status == ACTIVE_PLAN_STATUS)
            .order_by(WorkerAiStepPlan.updated_at.desc())
            .limit(1)
        )
        plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="维修指导步骤尚未生成")

    steps = _json_loads(plan.steps_json, [])
    if not isinstance(steps, list):
        steps = []
    current_step = _select_current_step(steps, step_id)
    if current_step is None:
        raise HTTPException(status_code=404, detail="当前维修步骤不存在")

    event_result = await db.execute(
        select(WorkerAiStepEvent)
        .where(WorkerAiStepEvent.plan_id == plan.id)
        .where(WorkerAiStepEvent.step_id == current_step.get("id"))
        .order_by(WorkerAiStepEvent.created_at.desc())
        .limit(5)
    )
    recent_events = [
        {
            "event_type": event.event_type,
            "note": event.note,
            "payload": _json_loads(event.payload_json, {}),
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in event_result.scalars().all()
    ]

    session_id = session_id or str(uuid.uuid4())
    await _ensure_session(
        db,
        session_id=session_id,
        user=user,
        work_order=work_order,
        state={
            "mode": "worker_guidance",
            "plan_id": plan.id,
            "step_id": current_step.get("id"),
        },
    )
    await _append_message(db, session_id=session_id, role="user", content=text, content_type="guidance_observation")

    context = await _load_context(db, work_order=work_order)
    fallback = _fallback_guidance_reply(message=text, work_order=work_order, current_step=current_step)
    model_reply = await _generate_guidance_reply_with_model(
        message=text,
        context=context,
        plan=plan,
        steps=steps,
        current_step=current_step,
        recent_events=recent_events,
    )
    reply = _normalize_guidance_reply(model_reply, fallback=fallback)
    settings = get_settings()
    model_provider = settings.AI_PROVIDER if model_reply else "local_fallback"
    model_name = settings.AI_TEXT_MODEL if model_reply else "local_guidance"

    db.add(
        WorkerAiStepEvent(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            step_id=str(current_step.get("id") or step_id or "current"),
            user_id=user.id,
            event_type="worker_observation",
            note=text,
            payload_json=json.dumps(
                {
                    "client_context": client_context or {},
                    "reply": reply,
                    "model_provider": model_provider,
                    "model_name": model_name,
                },
                ensure_ascii=False,
                default=str,
            ),
        )
    )
    await _append_message(
        db,
        session_id=session_id,
        role="assistant",
        content=reply["answer"],
        content_type="guidance_reply",
        model_provider=model_provider,
        model_name=model_name,
    )
    await db.commit()
    schedule_experience_capture(
        actor_user_id=user.id,
        actor_role=user.role,
        source_type="worker_note",
        source_text=text,
        source_work_order_id=work_order.ticket_id,
        source_dispatch_id=getattr(dispatch_task, "id", dispatch_id),
        source_step_plan_id=plan.id,
        contributor_user_id=user.id,
        contributor_role=user.role,
        building_id=work_order.building_id,
        device_id=work_order.device_id,
    )

    return {
        "assistant": "维小修",
        "session_id": session_id,
        "message_type": "guidance_chat",
        "answer": reply["answer"],
        "executed": False,
        "plan_id": plan.id,
        "step_id": current_step.get("id"),
        "suggested_step_status": reply.get("suggested_step_status"),
        "suggested_next_message": reply.get("suggested_next_message"),
        "suggested_followups": reply.get("suggested_followups", []),
        "safety_level": reply.get("safety_level", "normal"),
    }


async def update_worker_step_status(
    db: AsyncSession,
    *,
    ticket_id: str,
    step_id: str,
    plan_id: str,
    status: str,
    note: str | None,
    client_version: int | None,
    user: User,
) -> dict[str, Any]:
    if status not in STEP_STATUSES:
        raise HTTPException(status_code=400, detail="不支持的步骤状态")
    work_order, dispatch_task, hall_entry = await _resolve_work_order(
        db,
        ticket_id=ticket_id,
        dispatch_id=None,
        hall_entry_id=None,
    )
    if work_order is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _assert_worker_permission(user, work_order, dispatch_task, hall_entry)

    plan = await db.get(WorkerAiStepPlan, plan_id)
    if plan is None or plan.work_order_id != work_order.id:
        raise HTTPException(status_code=404, detail="步骤计划不存在")
    if client_version is not None and client_version < plan.version:
        logger.info("维小修步骤版本落后: client=%s server=%s", client_version, plan.version)

    steps = _json_loads(plan.steps_json, [])
    found = False
    current_status: str | None = None
    event_type = status
    for step in steps:
        if step.get("id") == step_id:
            current_status = str(step.get("status") or "pending")
            step["status"] = status
            if note:
                step["note"] = note
            if note and status == current_status:
                event_type = "note"
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="步骤不存在")

    plan.steps_json = json.dumps(steps, ensure_ascii=False, default=str)
    plan.version += 1
    plan.updated_at = datetime.now(timezone.utc)
    db.add(
        WorkerAiStepEvent(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            step_id=step_id,
            user_id=user.id,
            event_type=event_type,
            note=note,
            payload_json=json.dumps({"client_version": client_version}, ensure_ascii=False),
        )
    )
    await db.commit()

    next_step = next((step for step in steps if step.get("status") == "pending"), None)
    if event_type == "note":
        next_suggestion = "已记录这一步的备注。你可以继续当前步骤，或继续告诉我新的现场情况。"
    elif status == "needs_support":
        next_suggestion = "这一步已标记为需要协同。你可以直接对维小修说“请求协同，因为...”来走原后端流程。"
    elif next_step:
        next_suggestion = f"下一步建议：{next_step.get('title')}。{next_step.get('instruction')}"
    else:
        next_suggestion = "现场步骤已经走完。请回到工单详情页提交维修结果，我可以继续帮你整理现场备注。"

    return {
        "ok": True,
        "plan_id": plan.id,
        "plan_version": plan.version,
        "steps": steps,
        "next_suggestion": next_suggestion,
    }


async def record_step_media_event(
    db: AsyncSession,
    *,
    work_order: WorkOrder,
    step_id: str | None,
    user: User,
    asset_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    if not step_id:
        return
    result = await db.execute(
        select(WorkerAiStepPlan)
        .where(WorkerAiStepPlan.work_order_id == work_order.id)
        .where(WorkerAiStepPlan.status == ACTIVE_PLAN_STATUS)
        .order_by(WorkerAiStepPlan.updated_at.desc())
        .limit(1)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        return
    db.add(
        WorkerAiStepEvent(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            step_id=step_id,
            user_id=user.id,
            event_type=event_type,
            payload_json=json.dumps({"asset_id": asset_id, **payload}, ensure_ascii=False, default=str),
        )
    )
