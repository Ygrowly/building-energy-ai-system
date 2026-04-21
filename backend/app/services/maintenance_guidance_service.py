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
from app.services.worker_ai_service import (
    _append_message,
    _assert_worker_permission,
    _ensure_session,
    _humanize_worker_reply_text,
    _resolve_work_order,
)

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


def _step_status_prompt_label(status: Any) -> str:
    normalized = str(status or "").strip().lower()
    return {
        "completed": "前面已看过",
        "skipped": "暂时跳过",
        "needs_support": "需要协同",
        "uncertain": "还待核实",
        "pending": "眼下更该继续看",
    }.get(normalized, "待继续判断")


def _build_steps_for_guidance_model(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_steps: list[dict[str, Any]] = []
    for step in steps[:8]:
        if not isinstance(step, dict):
            continue
        normalized_steps.append(
            {
                "title": _as_text(step.get("title"), limit=80),
                "instruction": _as_text(step.get("instruction"), limit=500),
                "reason": _as_text(step.get("reason"), limit=240),
                "expected_result": _as_text(step.get("expected_result"), limit=240),
                "risk_note": _as_text(step.get("risk_note"), limit=240),
                "progress_hint": _step_status_prompt_label(step.get("status")),
                "worker_note": _as_text(step.get("note"), limit=240) or None,
            }
        )
    return normalized_steps


def _build_current_step_for_guidance_model(current_step: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(current_step, dict):
        return None
    return {
        "title": _as_text(current_step.get("title"), limit=80),
        "instruction": _as_text(current_step.get("instruction"), limit=500),
        "reason": _as_text(current_step.get("reason"), limit=240),
        "expected_result": _as_text(current_step.get("expected_result"), limit=240),
        "risk_note": _as_text(current_step.get("risk_note"), limit=240),
        "progress_hint": _step_status_prompt_label(current_step.get("status")),
        "worker_note": _as_text(current_step.get("note"), limit=240) or None,
    }


def _summarize_recent_guidance_progress(recent_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    event_summary_map = {
        "completed": "维修人员觉得这一步前面的检查已经做过了",
        "skipped": "维修人员暂时跳过了这一步",
        "needs_support": "维修人员倾向于请求协同",
        "uncertain": "维修人员觉得这一步还有待核实",
        "note": "维修人员补充了备注",
        "worker_observation": "维修人员补充了现场观察",
        "generate": "已生成过维修建议",
    }
    summaries: list[dict[str, Any]] = []
    for event in recent_events[:5]:
        if not isinstance(event, dict):
            continue
        event_type = _as_text(event.get("event_type"), limit=64)
        note = _as_text(event.get("note"), limit=240)
        summary = event_summary_map.get(event_type, "维修人员补充了新的现场信息")
        summaries.append(
            {
                "summary": summary,
                "note": note or None,
                "created_at": event.get("created_at"),
            }
        )
    return summaries


def _sanitize_guidance_reply(reply: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(reply, dict):
        return reply
    return {
        **reply,
        "answer": _humanize_worker_reply_text(reply.get("answer")),
        "suggested_next_message": _humanize_worker_reply_text(reply.get("suggested_next_message")),
        "suggested_followups": [
            _humanize_worker_reply_text(item)
            for item in (reply.get("suggested_followups") or [])
            if _humanize_worker_reply_text(item)
        ][:3],
    }


def _looks_like_ddc_help_request(message: str) -> bool:
    text = _as_text(message, limit=500).lower()
    patterns = (
        "不会查ddc",
        "不会看ddc",
        "不懂ddc",
        "查不到ddc",
        "不会查点位",
        "查不到点位",
        "不会看点位",
        "不会查bms",
        "不会看bms",
        "不懂bms",
        "不会看自控",
        "不会查自控",
    )
    return any(pattern in text for pattern in patterns)


def _build_ddc_help_reply(current_step: dict[str, Any] | None) -> dict[str, Any]:
    step_title = _as_text((current_step or {}).get("title"), limit=80)
    prefix = f"没关系，{step_title}里不一定非得你去查 DDC。" if step_title else "没关系，不一定非得你去查 DDC。"
    return {
        "answer": (
            f"{prefix} 先别碰登录、点位和参数，先做眼前能看到的三件事："
            "先看设备就地面板、温度表或报警灯；再记下现在看到的供回水温度、运行/停机状态和有没有报警；"
            "最后拍一张屏幕或设备铭牌发我。你把这些现场事实补给我，我先帮你判断是设备本体问题，还是再请自控同事一起看。"
        ),
        "suggested_step_status": "pending",
        "suggested_next_message": "把你眼前能看到的温度、运行状态、报警灯或屏幕照片发我。",
        "suggested_followups": [
            "现场现在能看到哪些读数？",
            "设备面板上有没有报警灯或报警码？",
            "方便拍一张就地面板或铭牌给我吗？",
        ],
        "safety_level": "normal",
    }


def _build_rag_query(work_order: WorkOrder) -> str:
    parts = [
        work_order.issue_description,
        work_order.suggested_action,
        work_order.building_id,
        work_order.device_id,
        "维修步骤 排查 安全 注意事项",
    ]
    return " ".join(str(item) for item in parts if item)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _build_workflow_profile_text(
    work_order: WorkOrder,
    *,
    context: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = [
        _as_text(work_order.issue_description, limit=300),
        _as_text(work_order.suggested_action, limit=300),
        _as_text(work_order.building_id, limit=120),
        _as_text(work_order.device_id, limit=160),
    ]
    for item in (context or {}).get("anomaly_evidence", [])[:5]:
        if not isinstance(item, dict):
            continue
        parts.append(_as_text(item.get("rule_triggered"), limit=240))
        parts.append(_as_text(item.get("hvac_root_cause"), limit=240))
    return " ".join(part for part in parts if part).lower()


def _build_workflow_profile(
    work_order: WorkOrder,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = _build_workflow_profile_text(work_order, context=context)
    sensor_keywords = (
        "传感器",
        "sensor",
        "计量",
        "显示异常",
        "显示不准",
        "读数异常",
        "读数不准",
        "信号",
        "通讯",
        "通信",
        "离线",
        "点位",
        "映射",
        "漂移",
        "偏差",
        "失准",
        "温度偏离",
        "数据异常",
    )

    if _is_hvac_chiller_issue(work_order) and not _contains_any(text, sensor_keywords):
        return {
            "profile_key": "hvac_chiller",
            "label": "暖通冷机效能/水系统异常",
            "primary_goal": "先确认机组实际工况与关键读数，再判断是效率下降、换热问题，还是数据采集/运行模式异常。",
            "onsite_focus": [
                "先确认目标机组和现场安全边界",
                "记录供回水、冷冻水/冷却水和报警等关键读数",
                "再判断换热、制冷剂或调度问题",
            ],
            "avoid": [
                "不要先让维修人员做制冷剂、压力、电气高风险操作",
                "不要在缺少现场读数时直接下结论",
            ],
            "generation_rules": [
                "这是暖通冷机/水系统相关异常，步骤应围绕机组、换热、水侧和关键读数组织。",
                "先让维修人员记录机组面板或就地读数，不要先进入抽象的系统推理。",
            ],
        }

    if _contains_any(
        text,
        (
            "夜间",
            "深夜",
            "下班后",
            "非工作时间",
            "无人",
            "空耗",
            "未关",
            "未关闭",
            "长明灯",
            "照明",
            "灯光",
            "灯未关",
            "设备未关",
            "持续运行",
            "夜间能耗",
            "夜间用电",
            "插座",
            "加班",
        ),
    ):
        return {
            "profile_key": "night_energy",
            "label": "夜间空耗/未关灯/未关设备",
            "primary_goal": "先确认现场是否仍在实际使用，再确认哪些负载仍开启，最后判断能现场关闭还是需要物业/自控/值班侧协同。",
            "onsite_focus": [
                "先核实现场是否有人在用或有临时活动",
                "确认照明、空调末端、插座或其他负载哪些还开着",
                "按岗位边界做现场关闭或发起协同",
            ],
            "avoid": [
                "不要把它写成拆机修设备的流程",
                "不要让维修人员先去查节假日日历或 BA/DDC 参数",
            ],
            "generation_rules": [
                "这是夜间空耗/未关设备类异常，流程重点应是现场占用核实、负载确认、记录取证和处置/协同。",
                "先确认现场是否真实在使用，不要把第一步写成查排程、节假日或点位表。",
            ],
        }

    if _contains_any(
        text,
        (
            "排程",
            "日历",
            "节假日",
            "holiday",
            "schedule",
            "occupied",
            "unoccupied",
            "night setback",
            "模式",
            "模式识别",
            "时间同步",
            "时钟",
            "运行模式",
        ),
    ):
        return {
            "profile_key": "schedule_mode",
            "label": "模式/排程/状态识别异常",
            "primary_goal": "先确认现场真实使用状态和就地运行状态，再判断是不是系统模式、排程、时间同步或状态识别异常。",
            "onsite_focus": [
                "先看现场是否真的在使用、设备是否真的在运行",
                "记录就地面板、状态灯、时间和现场状态",
                "若现场正常而系统异常，再转自控/管理侧核验排程与映射",
            ],
            "avoid": [
                "不要让维修人员一上来登录 BA/DDC 查表",
                "不要把“今天是不是节假日”写成维修人员自己必须判断的任务",
            ],
            "generation_rules": [
                "这是模式/排程/状态识别类异常，第一步必须是现场核实真实使用状态，而不是系统侧查表。",
                "更深的节假日表、排程配置、时间同步核验应表述为后续协同或自控侧处理。",
            ],
        }

    if _contains_any(text, sensor_keywords):
        return {
            "profile_key": "sensor_display",
            "label": "传感器/显示/计量偏差",
            "primary_goal": "先确认现场真实现象和就地读数，再判断是传感器本体、安装接线、通信链路，还是系统显示/映射异常。",
            "onsite_focus": [
                "先确认现场是否真的异常",
                "对比就地读数、面板读数和工单异常描述",
                "检查传感器外观、安装、接线和通信迹象",
            ],
            "avoid": [
                "不要在没有现场读数时直接认定点位错误",
                "不要让维修人员先去翻系统参数表",
            ],
            "generation_rules": [
                "这是传感器/显示/计量偏差类异常，步骤重点应是现场实测、读数对比、传感器外观和信号链路。",
                "如果怀疑系统显示或映射异常，应在现场核实后再写成协同事项。",
            ],
        }

    if _contains_any(
        text,
        (
            "报警",
            "故障",
            "异响",
            "漏水",
            "漏液",
            "漏油",
            "阀门",
            "水泵",
            "风机",
            "压缩机",
            "跳停",
            "不启动",
            "过载",
            "过热",
            "堵塞",
            "卡滞",
        ),
    ):
        return {
            "profile_key": "equipment_fault",
            "label": "现场设备运行异常",
            "primary_goal": "先确认设备对象与现场异常，再做岗位内可执行的非侵入式排查，最后决定是否需要升级协同。",
            "onsite_focus": [
                "先核对目标设备和现场安全",
                "观察异响、异味、泄漏、报警和状态灯",
                "优先做岗位内的非侵入式检查",
            ],
            "avoid": [
                "不要跳过现场现象确认直接做系统推理",
                "不要把高风险拆检动作写成普通步骤",
            ],
            "generation_rules": [
                "这是设备运行异常类工单，流程要围绕现场现象、就地状态、非侵入式检查和安全升级组织。",
            ],
        }

    return {
        "profile_key": "general",
        "label": "通用现场异常",
        "primary_goal": "先确认现场真实异常与影响范围，再收集关键事实，最后判断是设备问题、传感器问题还是系统侧问题。",
        "onsite_focus": [
            "确认工单对象和异常是否真实存在",
            "记录现场读数、状态、报警和照片",
            "根据现场事实决定继续排查还是请求协同",
        ],
        "avoid": [
            "不要凭抽象推理替代现场事实",
            "不要让维修人员一开始就做系统侧深度核验",
        ],
        "generation_rules": [
            "流程主线应先围绕现场确认和事实采集，再决定后续分流。",
        ],
    }


def _fallback_general_step_plan(
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


def _fallback_night_energy_step_plan(
    *,
    work_order: WorkOrder,
    rag_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issue = _as_text(work_order.issue_description, limit=160) or "夜间空耗/未关设备异常"
    return {
        "guide_version": 1,
        "summary": f"这张工单更像夜间空耗/未关灯/未关设备类异常：{issue}。流程重点不是拆机维修，而是先确认现场是否仍在使用，再确认哪些负载仍开启，并按岗位边界做现场处置或协同。",
        "root_cause_candidates": [
            {
                "name": "现场仍在实际使用或存在临时活动",
                "confidence": "medium",
                "evidence": ["夜间异常未必等于故障，需先区分加班、保洁、安保或临时活动等正常占用"],
            },
            {
                "name": "照明/空调/插座等负载未关闭",
                "confidence": "medium",
                "evidence": ["若现场无人使用但负载持续开启，更接近现场处置或管理问题而非设备故障"],
            },
            {
                "name": "系统状态识别、排程或计量映射异常",
                "confidence": "low",
                "evidence": ["如果现场其实已关闭而系统仍报异常，需要转系统侧继续核验"],
            },
        ],
        "steps": [
            {
                "id": "step_1",
                "title": "确认现场是否仍在实际使用",
                "instruction": "先到对应楼层、房间或区域确认是否有人在用，是否有加班、保洁、安保、临时活动或施工，不要一开始就查系统排程。",
                "reason": "夜间异常先要分清是真空耗，还是合理占用。",
                "expected_result": "明确现场是仍在使用，还是已无人使用。",
                "risk_note": "涉及办公区、教室或管制区域时，注意按现场要求沟通和进入，不要影响正常活动。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_2",
                "title": "确认哪些负载仍处于开启状态",
                "instruction": "记录哪些设备还在运行，例如照明、空调末端、新风机、插座设备或整层公共负载，能拍照时记录范围和状态。",
                "reason": "只有先明确是哪类负载未关闭，后面才能判断能否现场处理。",
                "expected_result": "得到具体的区域、设备类别和开启状态。",
                "risk_note": "不要凭远处观察下结论，尽量确认到具体区域或设备类别。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_3",
                "title": "判断属于合理占用还是异常空耗",
                "instruction": "结合现场是否有人、活动是否正常、设备开启范围和持续状态，判断这是临时使用、忘关设备，还是明显与现场状态不一致。",
                "reason": "夜间工单的关键不是先修，而是先确认这张单有没有真实处置对象。",
                "expected_result": "形成一句结论：合理占用、现场未关闭，或现场与系统信息不一致。",
                "risk_note": "不要因为“夜里”就默认一定是异常，先以现场事实为准。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_4",
                "title": "按岗位边界做现场处置或发起协同",
                "instruction": "对你岗位内可安全关闭、且按现场规程允许处理的负载再处置；若涉及办公使用、租户区域、集中控制或无权操作的设备，改为请求物业、值班或自控侧协同。",
                "reason": "夜间异常很多时候是处置边界问题，不一定需要维修员单独完成。",
                "expected_result": "明确哪些可以现场处理，哪些需要协同。",
                "risk_note": "不要为追求关停效果擅自拉闸、断电或越权操作集中控制设备。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_5",
                "title": "若现场已正常则转系统侧核验",
                "instruction": "如果现场其实已关闭、无人使用，但系统仍报夜间异常，把现场事实、照片、时间和区域发给维小修，再转自控/管理侧核验排程、状态识别或计量映射。",
                "reason": "这类情况下问题重点转成系统识别，而不是现场设备维修。",
                "expected_result": "形成可提交的现场核实结论和后续协同依据。",
                "risk_note": "维修人员不需要自己先去查节假日日历、排程表或 BA/DDC 点位。",
                "requires_photo": True,
                "status": "pending",
            },
        ],
        "safety_notes": [
            "夜间异常先确认现场使用状态，再决定是否处置，不要默认都是故障。",
            "涉及配电、集中控制或租户区域权限时，按现场规程和管理边界协同处理。",
        ],
        "rag_refs": rag_refs or [],
    }


def _fallback_schedule_mode_step_plan(
    *,
    work_order: WorkOrder,
    rag_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issue = _as_text(work_order.issue_description, limit=160) or "模式/排程疑似异常"
    return {
        "guide_version": 1,
        "summary": f"这张工单更像模式/排程/状态识别类异常：{issue}。流程重点是先确认现场真实使用状态和设备状态，再决定是否把问题转给自控/管理侧继续核验。",
        "root_cause_candidates": [
            {
                "name": "现场真实使用状态与系统模式不一致",
                "confidence": "medium",
                "evidence": ["很多模式类工单需要先核实现场到底在不在用、设备到底在不在运行"],
            },
            {
                "name": "排程、日历或时间同步异常",
                "confidence": "low",
                "evidence": ["若现场正常而系统异常持续存在，更像系统侧配置或识别问题"],
            },
        ],
        "steps": [
            {
                "id": "step_1",
                "title": "确认现场真实使用状态",
                "instruction": "先到现场确认区域是否真实在使用、设备是否真实在运行，先看人、灯光、温度体感、末端运行和现场活动，不要先去系统查表。",
                "reason": "模式/排程异常最怕离开现场事实只看系统显示。",
                "expected_result": "明确现场是正在使用，还是实际上已停止使用。",
                "risk_note": "不要把“今天是不是节假日”当成第一现场动作，先看现场真实状态。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_2",
                "title": "记录就地状态和时间信息",
                "instruction": "记录就地面板、状态灯、当前运行/停机状态，以及现场核实的时间、区域和现象，方便后续和系统异常对照。",
                "reason": "要判断是不是系统模式识别错误，必须先保留现场事实。",
                "expected_result": "得到可对照的现场状态、时间和照片。",
                "risk_note": "先留痕再下判断，不要只凭口头印象。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_3",
                "title": "判断是现场问题还是系统识别问题",
                "instruction": "如果现场确实在使用或设备确实在运行，继续按现场问题处理；如果现场已正常但系统仍报异常，把“不一致”这个事实明确记录下来。",
                "reason": "这一步是把维修处置和系统协同分开，避免走错方向。",
                "expected_result": "形成一句结论：现场确有问题，或现场与系统信息不一致。",
                "risk_note": "不要因为系统显示异常就默认一定是现场设备故障。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_4",
                "title": "把系统侧深度核验转为协同事项",
                "instruction": "如果现场正常而系统仍异常，把现场照片、时间、区域和就地状态交给维小修，再请自控/管理侧核验排程、日历、时间同步或状态映射。",
                "reason": "更深的模式/排程核验通常不该作为维修人员的一线操作任务。",
                "expected_result": "形成清晰的协同请求和现场依据。",
                "risk_note": "不要要求维修人员先登录 BA/DDC 查点位、日历或排程表。",
                "requires_photo": True,
                "status": "pending",
            },
        ],
        "safety_notes": [
            "先以现场真实状态为准，再决定是否转系统侧核验。",
            "模式/排程问题的系统深查应优先写成协同事项，而不是一线维修动作。",
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


def _fallback_sensor_display_step_plan(
    *,
    work_order: WorkOrder,
    rag_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issue = _as_text(work_order.issue_description, limit=160) or "传感器/显示偏差异常"
    return {
        "guide_version": 1,
        "summary": f"这张工单更像传感器/显示/计量偏差类异常：{issue}。先确认现场真实现象和就地读数，再判断是传感器本体、安装接线、通信链路，还是系统显示/映射问题。",
        "root_cause_candidates": [
            {
                "name": "现场读数与系统显示不一致",
                "confidence": "medium",
                "evidence": ["这类工单的第一步通常是就地核读数，而不是先改参数"],
            },
            {
                "name": "传感器外观、安装或接线异常",
                "confidence": "medium",
                "evidence": ["传感器偏差常见于松动、污染、安装位置不当、保温破损或接线异常"],
            },
            {
                "name": "通信链路或点位映射异常",
                "confidence": "low",
                "evidence": ["如果现场读数和传感器状态正常，但系统仍不一致，需要转系统侧核验信号链路或映射"],
            },
        ],
        "steps": [
            {
                "id": "step_1",
                "title": "确认现场真实现象和就地读数",
                "instruction": "先到现场确认实际温度、压力、流量或状态是否真的异常，优先看就地温度表、设备面板或明显现象，不要先信系统显示。",
                "reason": "这类工单先要分清是现场真异常，还是系统读数不可信。",
                "expected_result": "得到现场实测或就地可见读数，并判断异常是否真实存在。",
                "risk_note": "在还没核清现场读数前，不要先调参数或直接更换部件。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_2",
                "title": "记录现场与系统的差异",
                "instruction": "把现场读数、系统显示值、查看时间和位置一起记录下来，方便后续判断差异是持续的还是偶发的。",
                "reason": "只有把差异记录清楚，后面才能判断是传感器、通信还是显示映射问题。",
                "expected_result": "形成一组可比对的现场事实和系统信息。",
                "risk_note": "记录时尽量注明位置、设备和时间，避免后面混淆对象。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_3",
                "title": "检查传感器外观、安装和接线迹象",
                "instruction": "检查传感器是否松动、污染、遮挡、保温破损、安装位置异常或接线明显松脱，查看有没有离线、断线或供电异常的直接迹象。",
                "reason": "这一步可以快速发现很多不需要深度拆检的基础问题。",
                "expected_result": "发现直接可见的安装/接线问题，或确认外观未见明显异常。",
                "risk_note": "涉及开盖、拆线或电气测量时，先按现场授权和规程执行。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_4",
                "title": "判断是否需要系统侧协同核验",
                "instruction": "如果现场读数正常、传感器外观也正常，但系统仍显示异常，把差异事实和照片发给维小修，再请自控侧核验通信链路、点位映射或采集配置。",
                "reason": "这时问题重点很可能已经不在现场传感器本体，而在系统侧。",
                "expected_result": "形成清晰的继续维修或协同核验结论。",
                "risk_note": "不要让一线维修人员先自己去查 DDC 点位或改采集参数。",
                "requires_photo": True,
                "status": "pending",
            },
        ],
        "safety_notes": [
            "先核实现场读数，再决定是不是系统显示问题。",
            "传感器拆装、校准、电气测量等动作按现场规程和授权执行。",
        ],
        "rag_refs": rag_refs or [],
    }


def _fallback_equipment_fault_step_plan(
    *,
    work_order: WorkOrder,
    rag_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issue = _as_text(work_order.issue_description, limit=120) or "设备运行异常"
    device = work_order.device_id or "相关设备"
    return {
        "guide_version": 1,
        "summary": f"这张工单更像现场设备运行异常：{issue}。建议先确认 {device} 的现场现象、就地状态和报警，再做岗位内可执行的非侵入式检查，最后决定是否需要协同。",
        "root_cause_candidates": [
            {
                "name": "设备本体或执行机构异常",
                "confidence": "medium",
                "evidence": [f"需先结合 {device} 的运行状态、报警、异响、漏水或卡滞现象判断设备是否真实异常"],
            },
            {
                "name": "现场现象与系统信息不一致",
                "confidence": "low",
                "evidence": ["如果现场未见同类异常，仍需保留系统显示或工单触发可能有偏差的分支"],
            },
        ],
        "steps": [
            {
                "id": "step_1",
                "title": "确认设备对象与作业安全",
                "instruction": "到达现场后先确认工单对应设备、区域和安全边界，确认当前没有明显的人身或设备风险再继续。",
                "reason": "先查对对象并控制风险，避免误操作。",
                "expected_result": "确认目标设备正确，现场具备继续观察和记录的条件。",
                "risk_note": "涉及电控柜、带压管路、旋转部件或高处作业时先按现场安全规范执行。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_2",
                "title": "观察现场直接异常现象",
                "instruction": "先看设备有没有异响、异味、漏水、漏油、结露、振动、报警灯或明显不运行的现象，能拍照时先拍照。",
                "reason": "维修动作先从最直接的现场异常征象开始，比抽象分析更可靠。",
                "expected_result": "确认现场是否存在可见异常，以及异常出现在哪个部位。",
                "risk_note": "发现持续泄漏、冒烟、焦味或明显危险时，先按现场规程上报和隔离，不要继续尝试运行。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_3",
                "title": "核对就地状态和报警信息",
                "instruction": "记录设备就地面板、运行/停机状态、状态灯、报警码和关键读数，把最关键的现场事实补给维小修。",
                "reason": "后续判断需要知道设备当前到底在运行、停机还是带报警运行。",
                "expected_result": "得到可支撑下一步判断的状态、读数和报警信息。",
                "risk_note": "先记录现状，不要一上来就复位报警或强行重启。",
                "requires_photo": True,
                "status": "pending",
            },
            {
                "id": "step_4",
                "title": "做岗位内的非侵入式基础检查",
                "instruction": "在不拆卸、不绕过保护的前提下，检查阀位、滤网、接线外观、固定件、外部堵塞、明显松动或冷却/通风条件等基础问题。",
                "reason": "很多设备问题在这一层就能发现明显线索，不需要先做高风险动作。",
                "expected_result": "发现可见问题，或确认当前岗位内未见明显异常。",
                "risk_note": "高风险拆检、电气测量、压力系统处理和制冷剂相关操作必须由有资质人员或按规程执行。",
                "requires_photo": False,
                "status": "pending",
            },
            {
                "id": "step_5",
                "title": "汇总现场事实并决定下一步",
                "instruction": "把异常现象、报警、读数、照片和基础检查结果汇总起来，再决定是继续设备维修，还是请求电工、自控或其他班组协同。",
                "reason": "让后续维修和升级协同都有明确的现场依据。",
                "expected_result": "形成可提交的维修备注或协同请求。",
                "risk_note": "不要让 AI 自动替你确认工单完成，最终结论仍需维修人员确认。",
                "requires_photo": False,
                "status": "pending",
            },
        ],
        "safety_notes": [
            "优先观察现场征象和就地状态，再决定是否继续拆检或升级协同。",
            "AI 步骤是辅助建议，不替代现场安全规程和设备维保要求。",
        ],
        "rag_refs": rag_refs or [],
    }


def _fallback_step_plan(
    *,
    work_order: WorkOrder,
    rag_refs: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = _build_workflow_profile(work_order, context=context)
    if profile["profile_key"] == "hvac_chiller":
        return _fallback_hvac_chiller_step_plan(work_order=work_order, rag_refs=rag_refs)
    if profile["profile_key"] == "night_energy":
        return _fallback_night_energy_step_plan(work_order=work_order, rag_refs=rag_refs)
    if profile["profile_key"] == "schedule_mode":
        return _fallback_schedule_mode_step_plan(work_order=work_order, rag_refs=rag_refs)
    if profile["profile_key"] == "sensor_display":
        return _fallback_sensor_display_step_plan(work_order=work_order, rag_refs=rag_refs)
    if profile["profile_key"] == "equipment_fault":
        return _fallback_equipment_fault_step_plan(work_order=work_order, rag_refs=rag_refs)
    return _fallback_general_step_plan(work_order=work_order, rag_refs=rag_refs)


def _normalize_step_plan(
    raw: dict[str, Any] | None,
    *,
    work_order: WorkOrder,
    rag_refs: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not raw:
        return _fallback_step_plan(work_order=work_order, rag_refs=rag_refs, context=context)

    fallback = _fallback_step_plan(work_order=work_order, rag_refs=rag_refs, context=context)
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
    workflow_profile = context.get("workflow_profile") if isinstance(context.get("workflow_profile"), dict) else {}
    profile_label = _as_text(workflow_profile.get("label"), limit=80)
    profile_goal = _as_text(workflow_profile.get("primary_goal"), limit=240)
    profile_generation_rules = (
        workflow_profile.get("generation_rules") if isinstance(workflow_profile.get("generation_rules"), list) else []
    )
    system_prompt = (
        "你是维修端 AI 维小修，任务是给现场维修人员生成可执行的辅助维修步骤。"
        "必须只输出合法 JSON 对象，不要输出 Markdown，不要输出思考过程。"
        "步骤必须基于工单上下文、异常证据、相似工单和可用知识库内容自主判断，不要套用固定模板。"
        "优先给非侵入式、可观察、可记录的现场检查步骤。"
        "第一步优先确认现场是否真的存在异常，再判断是设备问题、传感器问题，还是系统显示/排程问题。"
        "不要让维修人员一上来就去查 BA/DDC 点位、节假日日历、排程表或模式参数；"
        "如果怀疑排程/日历/模式识别异常，先让维修人员确认现场是否真的在使用，再把更深的系统核验表述为请自控/管理侧协助。"
        "涉及断电挂牌、开柜、拆卸、制冷剂充注、压力系统、电气测量、化学清洗等高风险动作时，"
        "只能建议联系具备资质的人员或按现场规程执行，不能把它写成普通维修人员直接操作的步骤。"
        "不能自动替维修人员确认工单完成，不能要求绕过安全规范。"
        "不要编造维保记录、历史结论、资质证书名称/编号、法规标准编号、设备铭牌参数或固定阈值。"
        "如果需要阈值或资质要求，只能写“按机组手册/现场规程/具备资质人员确认”。"
        f"{f'当前工单更接近“{profile_label}”场景，流程主线应围绕：{profile_goal}' if profile_label and profile_goal else ''}"
    )
    user_prompt = {
        "context": context,
        "workflow_profile": workflow_profile,
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
            "第一步先写维修人员到现场如何确认真实异常，不要第一步就让他查节假日、排程表、BA 登录界面或 DDC 点位。",
            "如果怀疑模式/排程问题，维修人员只需要确认现场是否真的在使用；更深的节假日表、时间同步、排程配置核验，应写成后续协同或自控侧检查。",
            "不要把“今天是不是节假日”写成维修人员自己要判断的任务；可以写成“确认现场是否在正常使用”。",
            "每个步骤都要说明为什么这样查，以及完成后维修人员应该告诉 AI 什么事实。",
            "高风险操作必须表述为升级/协同/由有资质人员执行。",
            "不要使用“唯一可靠依据”“必须拆开检查”这类绝对化表述。",
            *[_as_text(item, limit=240) for item in profile_generation_rules if _as_text(item, limit=240)],
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
    answer = _humanize_worker_reply_text(_as_text(raw.get("answer"), limit=1200))
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
        "suggested_next_message": _humanize_worker_reply_text(_as_text(raw.get("suggested_next_message"), limit=300)),
        "suggested_followups": [
            _humanize_worker_reply_text(_as_text(item, limit=120))
            for item in followups[:3]
            if _humanize_worker_reply_text(_as_text(item, limit=120))
        ],
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
        "输入里会带内部元数据和步骤进度，它们只用于你理解现场，不允许在 answer 里原样复述。"
        "绝对不要输出或复述 step_1、step_2、completed、pending、needs_support、uncertain、event_type、plan_id、dispatch_id、系统里只确认、闭环、命中规则 这些实现层表达。"
        "如果维修人员问“做到哪一步了”，不要回答内部步骤编号；改用自然说法，例如“前面外观看过了，眼下更该核对读数和显示链路”。"
        "除非安全风险很高，answer 不要堆长清单；优先用 1 段判断加最多 3 个下一步要点。"
        "如果用户描述漏液、外流、冒烟、异味、异常噪声、带电风险、压力系统或制冷剂风险，先给安全优先建议。"
        "可以建议调整步骤顺序，但不能自动替用户完成步骤或改变工单状态。"
        "不要编造未提供的读数、阈值、维保记录、证书、法规编号或设备铭牌参数。"
        "不要编造教室号、房间号、楼层、BA 工作站位置、百分比、时间差、温度值、运行画面细节或具体控制点名称，除非这些信息已在输入里明确给出。"
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
            "steps": _build_steps_for_guidance_model(steps),
        },
        "current_step": _build_current_step_for_guidance_model(current_step),
        "recent_progress": _summarize_recent_guidance_progress(recent_events),
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
            "就算输入里带步骤编号或原始状态，也不要在 answer 原样复述；改成“前面外观看过了”“这一步还差读数”“接下来先看控制屏”这种说法。",
            "不要说“系统里只确认”“闭环”“命中规则”“当前状态”这类系统实现词。",
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
    normalized = _normalize_step_plan(model_plan, work_order=work_order, rag_refs=rag_refs, context=context)
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
    context["workflow_profile"] = _build_workflow_profile(work_order, context=context)
    fallback = _fallback_guidance_reply(message=text, work_order=work_order, current_step=current_step)
    if _looks_like_ddc_help_request(text):
        model_reply = None
        reply = _sanitize_guidance_reply(_build_ddc_help_reply(current_step))
    else:
        model_reply = await _generate_guidance_reply_with_model(
            message=text,
            context=context,
            plan=plan,
            steps=steps,
            current_step=current_step,
            recent_events=recent_events,
        )
        reply = _sanitize_guidance_reply(_normalize_guidance_reply(model_reply, fallback=fallback))
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
