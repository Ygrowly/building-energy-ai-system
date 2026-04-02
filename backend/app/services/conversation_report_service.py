from __future__ import annotations

import re
import threading
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.graph.viz_engine import build_chart_manifest, build_data_summary
from app.schemas.report_schemas import (
    ConversationReportPayload,
    ConversationReportRequest,
    ReportSection,
    ReportSummaryItem,
)

_PLACEHOLDER_RE = re.compile(r"<<CHART:[^>]*>>")
_TOOL_CALL_RE = re.compile(
    r"\b(render_ui_component|create_work_order_draft|generate_report)\s*\([\s\S]*?\)\s*"
)
_BLANK_LINE_RE = re.compile(r"\n{3,}")


class ConversationReportDraft(BaseModel):
    executive_summary: str = Field(description="执行摘要，使用 markdown，可用列表，不要写标题。")
    key_findings: str = Field(description="关键结论，使用 markdown，可用列表，不要写标题。")
    recommendations: str = Field(description="建议行动，使用 markdown，可用列表，不要写标题。")
    risks_and_open_questions: str = Field(description="风险与待确认项，使用 markdown，可用列表，不要写标题。")


_cached_report_llm_fast: Any = None
_cached_report_llm_deep: Any = None
_report_llm_lock: threading.RLock | None = None


def _get_report_llm_lock() -> threading.RLock:
    global _report_llm_lock
    if _report_llm_lock is None:
        _report_llm_lock = threading.RLock()
    return _report_llm_lock


def _build_report_llm(thinking_mode: str = "fast") -> Any:
    global _cached_report_llm_fast, _cached_report_llm_deep
    settings = get_settings()
    with _get_report_llm_lock():
        if thinking_mode == "deep" and settings.LLM_MODEL_DEEP:
            if _cached_report_llm_deep is None:
                base_llm = ChatOpenAI(
                    model=settings.LLM_MODEL_DEEP,
                    api_key=settings.LLM_API_KEY or "placeholder",
                    base_url=settings.LLM_BASE_URL,
                    temperature=0.2,
                    max_tokens=2200,
                    request_timeout=90,
                )
                _cached_report_llm_deep = base_llm.with_structured_output(ConversationReportDraft)
            return _cached_report_llm_deep

        if _cached_report_llm_fast is None:
            base_llm = ChatOpenAI(
                model=settings.LLM_MODEL_SYNTHESIS or settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY or "placeholder",
                base_url=settings.LLM_BASE_URL,
                temperature=0.2,
                max_tokens=1800,
                request_timeout=60,
            )
            _cached_report_llm_fast = base_llm.with_structured_output(ConversationReportDraft)
        return _cached_report_llm_fast


def sanitize_report_markdown(text: str) -> str:
    clean = _PLACEHOLDER_RE.sub("", text or "")
    clean = _TOOL_CALL_RE.sub("", clean)
    clean = clean.replace("\r\n", "\n").strip()
    clean = _BLANK_LINE_RE.sub("\n\n", clean)
    return clean


def _truncate(text: str, limit: int) -> str:
    clean = sanitize_report_markdown(text)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _stable_unique_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        key = str(
            art.get("artifact_id")
            or f"{art.get('component_type')}|{art.get('widget')}|{art.get('title')}"
        )
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(art)
        normalized.setdefault("type", "artifact")
        unique.append(normalized)
    return unique


def _extract_conversation_turns(messages: list[BaseMessage]) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    for msg in messages:
        if isinstance(msg, HumanMessage) and msg.content:
            turns.append(("user", sanitize_report_markdown(str(msg.content))))
            continue
        if not isinstance(msg, AIMessage):
            continue
        if getattr(msg, "tool_calls", None):
            continue
        content = sanitize_report_markdown(str(msg.content or ""))
        if not content or content.startswith("[Router]"):
            continue
        turns.append(("ai", content))
    return turns


def _extract_last_by_role(turns: list[tuple[str, str]], role: str) -> str:
    for item_role, content in reversed(turns):
        if item_role == role and content:
            return content
    return ""


def _markdown_bullets(items: list[str], fallback: str) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return fallback
    return "\n".join(f"- {item}" for item in cleaned)


def _build_fallback_sections(context: dict[str, Any]) -> ConversationReportDraft:
    summary_lines: list[str] = []
    if context["context_summary"]:
        summary_lines.extend(
            _truncate(line, 180)
            for line in str(context["context_summary"]).splitlines()
            if line.strip()
        )
    if context["latest_ai_answer"]:
        summary_lines.append(_truncate(context["latest_ai_answer"], 320))
    if context["react_data_summary"] and not str(context["react_data_summary"]).startswith("（"):
        summary_lines.append(_truncate(context["react_data_summary"], 320))

    findings: list[str] = []
    if context["react_data_summary"] and not str(context["react_data_summary"]).startswith("（"):
        findings.append(_truncate(context["react_data_summary"], 360))
    if context["artifact_titles"]:
        findings.append(f"会话产出工件：{'、'.join(context['artifact_titles'])}")
    if context["latest_ai_answer"]:
        findings.append(_truncate(context["latest_ai_answer"], 240))

    recommendations: list[str] = []
    pending_action = context["pending_action"]
    if isinstance(pending_action, dict) and pending_action.get("ticket_id"):
        recommendations.append(
            f"优先处理待审批事项 {pending_action['ticket_id']}，目标楼宇 {pending_action.get('building_id') or '未标注'}。"
        )
    if context["artifact_titles"]:
        recommendations.append("结合已生成图表与卡片复核关键指标，再执行现场动作。")
    recommendations.append("对异常结论保留数据复核步骤，避免直接依据单轮对话做最终决策。")

    risks: list[str] = []
    if not context["artifact_titles"]:
        risks.append("本次会话未生成可视化工件，部分判断缺少图表佐证。")
    if not context["react_data_summary"] or str(context["react_data_summary"]).startswith("（"):
        risks.append("结构化数据摘要不足，部分结论依赖最终回答文本整理。")
    if not context["context_summary"]:
        risks.append("历史滚动摘要缺失，跨轮上下文可能不完整。")
    if isinstance(pending_action, dict) and pending_action.get("ticket_id"):
        risks.append("存在待审批动作，执行前需确认工单内容与优先级。")

    return ConversationReportDraft(
        executive_summary=_markdown_bullets(summary_lines[:4], "- 本次会话已完成总结导出，但未获取到足够摘要内容。"),
        key_findings=_markdown_bullets(findings[:4], "- 当前会话缺少可提炼的结构化结论。"),
        recommendations=_markdown_bullets(recommendations[:4], "- 建议复核关键数据后再继续下一步操作。"),
        risks_and_open_questions=_markdown_bullets(risks[:4], "- 当前未发现额外风险，但建议保留人工复核。"),
    )


def _build_llm_context(turns: list[tuple[str, str]], context: dict[str, Any]) -> str:
    transcript_lines: list[str] = []
    for role, content in turns[-8:]:
        prefix = "用户" if role == "user" else "AI"
        transcript_lines.append(f"{prefix}: {_truncate(content, 220)}")

    artifact_lines = [f"- {title}" for title in context["artifact_titles"]] or ["- 无"]
    pending_action = context["pending_action"]
    pending_summary = "无"
    if isinstance(pending_action, dict) and pending_action:
        pending_summary = (
            f"ticket_id={pending_action.get('ticket_id')}, "
            f"building_id={pending_action.get('building_id')}, "
            f"priority={pending_action.get('priority')}, "
            f"issue={pending_action.get('issue_description')}"
        )

    return "\n".join(
        [
            f"会话标题：{context['title']}",
            f"楼宇：{context['building_name'] or '未标注'}",
            f"用户轮次：{context['user_turn_count']}",
            f"AI 轮次：{context['ai_turn_count']}",
            f"最新用户问题：{_truncate(context['latest_user_question'], 240) or '无'}",
            f"最新 AI 回答：{_truncate(context['latest_ai_answer'], 320) or '无'}",
            "",
            "历史滚动摘要：",
            context["context_summary"] or "无",
            "",
            "结构化数据摘要：",
            context["react_data_summary"] or "无",
            "",
            "图表清单：",
            context["chart_manifest"] or "无",
            "",
            "待审批事项：",
            pending_summary,
            "",
            "会话工件：",
            "\n".join(artifact_lines),
            "",
            "最近对话摘录：",
            "\n".join(transcript_lines) or "无",
        ]
    )


async def _generate_ai_sections(context: dict[str, Any], thinking_mode: str) -> ConversationReportDraft:
    llm = _build_report_llm(thinking_mode)
    prompt = (
        "你是建筑能源智能管理系统的报表编辑器。"
        "请基于给定会话状态生成正式总结报表的四个正文块。"
        "要求：\n"
        "1. 只依据输入事实，不编造新数据。\n"
        "2. 使用简洁专业中文。\n"
        "3. 每个字段使用 markdown，可包含项目列表，但不要写标题。\n"
        "4. 不要输出原始逐条问答，不要输出图表占位符，不要输出代码块。\n"
        "5. recommendations 必须是可执行动作，risks_and_open_questions 必须包含不确定项或核验点。"
    )
    return await llm.ainvoke(prompt + "\n\n" + _build_llm_context(context["turns"], context))


def _build_overview_items(context: dict[str, Any]) -> list[ReportSummaryItem]:
    pending_action = context["pending_action"]
    pending_label = "无"
    if isinstance(pending_action, dict) and pending_action.get("ticket_id"):
        pending_label = str(pending_action.get("ticket_id"))
    return [
        ReportSummaryItem(label="会话标题", value=context["title"]),
        ReportSummaryItem(label="楼宇", value=context["building_name"] or "未标注"),
        ReportSummaryItem(label="用户轮次", value=str(context["user_turn_count"])),
        ReportSummaryItem(label="AI 轮次", value=str(context["ai_turn_count"])),
        ReportSummaryItem(label="工件数量", value=str(len(context["artifacts"]))),
        ReportSummaryItem(label="待审批事项", value=pending_label),
    ]


def _build_appendix_content(turns: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    for index, (role, content) in enumerate(turns, start=1):
        title = "用户" if role == "user" else "AI"
        lines.append(f"{index}. **{title}**：{_truncate(content, 500)}")
    return "\n".join(lines)


async def generate_conversation_report_payload(
    *,
    session_id: str,
    session_title: str,
    state: dict[str, Any],
    req: ConversationReportRequest,
) -> ConversationReportPayload:
    messages = list(state.get("messages", []))
    turns = _extract_conversation_turns(messages)
    user_turn_count = sum(1 for role, _ in turns if role == "user")
    ai_turn_count = sum(1 for role, _ in turns if role == "ai")
    if user_turn_count == 0 and ai_turn_count == 0:
        raise ValueError("当前会话暂无可导出的有效内容")

    raw_artifacts = list(state.get("artifacts", [])) if req.artifact_policy == "all" else []
    artifacts = _stable_unique_artifacts(raw_artifacts)
    react_data_summary = state.get("react_data_summary") or build_data_summary(messages)
    chart_manifest = state.get("chart_manifest") or build_chart_manifest(raw_artifacts)

    context = {
        "session_id": session_id,
        "title": session_title or "AI 对话总结报表",
        "building_name": state.get("building_id"),
        "turns": turns,
        "user_turn_count": user_turn_count,
        "ai_turn_count": ai_turn_count,
        "latest_user_question": _extract_last_by_role(turns, "user"),
        "latest_ai_answer": _extract_last_by_role(turns, "ai"),
        "context_summary": sanitize_report_markdown(str(state.get("context_summary") or "")),
        "react_data_summary": sanitize_report_markdown(str(react_data_summary or "")),
        "chart_manifest": sanitize_report_markdown(str(chart_manifest or "")),
        "pending_action": state.get("pending_action"),
        "artifacts": artifacts,
        "artifact_titles": [str(art.get("title") or art.get("component_type") or art.get("widget")) for art in artifacts],
    }

    report_draft: ConversationReportDraft
    if req.generation_mode == "rules":
        report_draft = _build_fallback_sections(context)
    else:
        try:
            thinking_mode = str(state.get("thinking_mode") or "fast")
            report_draft = await _generate_ai_sections(context, thinking_mode)
        except Exception:
            if req.generation_mode == "backend_ai":
                raise
            report_draft = _build_fallback_sections(context)

    sections: list[ReportSection] = [
        ReportSection(
            id="conversation-overview",
            namespace="conversation-report",
            title="会话概览",
            type="summary",
            summaryItems=_build_overview_items(context),
            order=10,
        ),
        ReportSection(
            id="conversation-executive-summary",
            namespace="conversation-report",
            title="执行摘要",
            type="text",
            content=sanitize_report_markdown(report_draft.executive_summary),
            contentFormat="markdown",
            order=20,
        ),
        ReportSection(
            id="conversation-key-findings",
            namespace="conversation-report",
            title="关键结论",
            type="text",
            content=sanitize_report_markdown(report_draft.key_findings),
            contentFormat="markdown",
            order=30,
        ),
        ReportSection(
            id="conversation-recommendations",
            namespace="conversation-report",
            title="建议行动",
            type="text",
            content=sanitize_report_markdown(report_draft.recommendations),
            contentFormat="markdown",
            order=40,
        ),
        ReportSection(
            id="conversation-risks",
            namespace="conversation-report",
            title="风险与待确认项",
            type="text",
            content=sanitize_report_markdown(report_draft.risks_and_open_questions),
            contentFormat="markdown",
            order=50,
        ),
    ]

    if req.include_appendix:
        sections.append(
            ReportSection(
                id="conversation-appendix",
                namespace="conversation-report",
                title="原始对话附录",
                type="text",
                content=_build_appendix_content(turns),
                contentFormat="markdown",
                order=60,
            )
        )

    for index, artifact in enumerate(artifacts, start=1):
        sections.append(
            ReportSection(
                id=f"conversation-artifact-{index}",
                namespace="conversation-report",
                title=str(artifact.get("title") or f"会话工件 {index}"),
                type="artifact",
                artifact=artifact,
                order=100 + index,
            )
        )

    subtitle = f"共 {user_turn_count} 轮用户提问，导出为正式总结报表"
    return ConversationReportPayload(
        title=context["title"],
        subtitle=subtitle,
        generatedAt=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        buildingName=context["building_name"],
        sections=sections,
        mode=req.mode,
        generatedBy="AI 对话总结报表",
    )
