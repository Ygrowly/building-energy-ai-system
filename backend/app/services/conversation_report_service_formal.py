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
_MARKDOWN_TOKEN_RE = re.compile(r"[#>*`_~\-]+")
_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?")
_SAME_YEAR_RANGE_RE = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日?\s*(?:至|到|~|-)\s*(\d{1,2})月(\d{1,2})日?"
)
_QUESTION_MARK_RE = re.compile(r"[?？]$")
_RAW_TITLE_HINT_RE = re.compile(r"^(我|请|帮我|现在|想|需要|分析一下|看一下)")
_BUILDING_TOKEN_RE = re.compile(
    r"(教学楼|办公楼|实验楼|宿舍楼|行政楼|食堂|图书馆|商业楼|医院|园区|校区|机房|数据中心|"
    r"[A-Za-z0-9_-]{2,20}(?:楼|馆|中心|园区|校区|Office|Education|Building))"
)

_METRIC_RULES: list[tuple[tuple[str, ...], str]] = [
    (("平均日总用电量", "平均日耗电"), "平均日总用电量"),
    (("总用电量", "总耗电量"), "总用电量"),
    (("日均用电", "日均耗电"), "日均用电量"),
    (("用电量", "耗电量", "电量"), "用电量"),
    (("用水量", "水量"), "用水量"),
    (("COP", "cop"), "COP"),
    (("冷量", "制冷量"), "冷量"),
    (("能耗",), "能耗"),
]

_ANALYSIS_TYPE_RULES: list[tuple[tuple[str, ...], str]] = [
    (("对比", "比较", "vs", "VS"), "对比分析"),
    (("趋势", "变化", "走势"), "趋势分析"),
    (("异常", "诊断", "排查"), "诊断分析"),
    (("原因", "为什么"), "原因分析"),
]


class ConversationReportDraft(BaseModel):
    report_title: str = Field(description="正式报告标题，必须是名词短语，不能直接复述用户问题。")
    report_summary: str = Field(description="一句话摘要，30到60字，不要使用问句。")
    executive_summary: str = Field(description="执行摘要，使用 markdown，可包含列表，但不要写标题。")
    key_findings: str = Field(description="关键结论，使用 markdown，可包含列表，但不要写标题。")
    recommendations: str = Field(description="建议行动，使用 markdown，可包含列表，但不要写标题。")
    risks_and_open_questions: str = Field(
        description="风险与待确认项，使用 markdown，可包含列表，但不要写标题。"
    )


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
                    max_tokens=2400,
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
                max_tokens=2000,
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
    return clean[: limit - 3].rstrip() + "..."


def _plain_text(text: str) -> str:
    clean = sanitize_report_markdown(text)
    clean = _MARKDOWN_TOKEN_RE.sub(" ", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _first_sentence(text: str, limit: int = 64) -> str:
    plain = _plain_text(text)
    if not plain:
        return ""
    parts = re.split(r"[。；;.!?？\n]", plain)
    for part in parts:
        candidate = part.strip(" -:：")
        if candidate:
            return _truncate(candidate, limit)
    return _truncate(plain, limit)


def _stable_unique_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        key = str(
            artifact.get("artifact_id")
            or f"{artifact.get('component_type')}|{artifact.get('widget')}|{artifact.get('title')}"
        )
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(artifact)
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
        if content and not content.startswith("[Router]"):
            turns.append(("ai", content))
    return turns


def _extract_last_by_role(turns: list[tuple[str, str]], role: str) -> str:
    for current_role, content in reversed(turns):
        if current_role == role and content:
            return content
    return ""


def _markdown_bullets(items: list[str], fallback: str) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return fallback
    return "\n".join(f"- {item}" for item in cleaned)


def _looks_like_raw_question(text: str) -> bool:
    plain = _plain_text(text)
    if not plain:
        return True
    return bool(_QUESTION_MARK_RE.search(plain) or _RAW_TITLE_HINT_RE.search(plain))


def _normalize_date(year: str, month: str, day: str) -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _extract_dates_from_text(text: str) -> list[str]:
    results: list[str] = []
    for year, month, day in _DATE_RE.findall(text):
        results.append(_normalize_date(year, month, day))
    for year, start_month, start_day, end_month, end_day in _SAME_YEAR_RANGE_RE.findall(text):
        results.append(_normalize_date(year, start_month, start_day))
        results.append(_normalize_date(year, end_month, end_day))
    return results


def _extract_date_range(context: dict[str, Any]) -> dict[str, str] | None:
    candidates: list[str] = []

    for text in (
        context["latest_user_question"],
        context["latest_ai_answer"],
        context["context_summary"],
        context["react_data_summary"],
    ):
        candidates.extend(_extract_dates_from_text(text))

    for artifact in context["artifacts"]:
        source_info = artifact.get("source_info")
        if not isinstance(source_info, dict):
            continue
        start = source_info.get("start_date") or source_info.get("date_start")
        end = source_info.get("end_date") or source_info.get("date_end")
        if start and end:
            return {"start": str(start), "end": str(end)}
        for value in source_info.values():
            if isinstance(value, str):
                candidates.extend(_extract_dates_from_text(value))

    unique_dates = sorted({item for item in candidates if item})
    if len(unique_dates) >= 2:
        return {"start": unique_dates[0], "end": unique_dates[-1]}
    return None


def _extract_targets(context: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for text in (
        context["session_title"],
        context["latest_user_question"],
        context["latest_ai_answer"],
        context["context_summary"],
        " ".join(context["artifact_titles"]),
    ):
        candidates.extend(match.group(1) for match in _BUILDING_TOKEN_RE.finditer(text))

    session_building = str(context.get("session_building") or "").strip()
    if session_building:
        candidates.append(session_building)

    unique: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        cleaned = item.strip("（）()[]【】,，。 ")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)
    return unique[:4]


def _detect_metric(context: dict[str, Any]) -> str:
    corpus = " ".join(
        [
            context["session_title"],
            context["latest_user_question"],
            context["latest_ai_answer"],
            context["context_summary"],
            context["react_data_summary"],
        ]
    )
    for keywords, label in _METRIC_RULES:
        if any(keyword in corpus for keyword in keywords):
            return label
    return "能耗指标"


def _detect_analysis_type(context: dict[str, Any]) -> str:
    corpus = " ".join(
        [
            context["session_title"],
            context["latest_user_question"],
            context["latest_ai_answer"],
            context["context_summary"],
        ]
    )
    for keywords, label in _ANALYSIS_TYPE_RULES:
        if any(keyword in corpus for keyword in keywords):
            return label
    return "分析"


def _extract_data_sources(artifacts: list[dict[str, Any]]) -> list[str]:
    sources: list[str] = []
    for artifact in artifacts:
        source_info = artifact.get("source_info")
        if not isinstance(source_info, dict):
            continue
        for key in ("source_table", "base_table", "source_view"):
            value = source_info.get(key)
            if value:
                sources.append(str(value))

    unique: list[str] = []
    seen: set[str] = set()
    for item in sources:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique[:3]


def _build_heuristic_title(context: dict[str, Any]) -> str:
    targets = context["targets"]
    metric = context["metric"]
    analysis_type = context["analysis_type"]

    if len(targets) >= 2 and analysis_type == "对比分析":
        return f"{targets[0]}与{targets[1]}{metric}对比分析报告"
    if len(targets) >= 2 and analysis_type == "原因分析":
        return f"{targets[0]}与{targets[1]}{metric}差异原因分析报告"
    if targets:
        return f"{targets[0]}{metric}{analysis_type}报告"
    return f"{metric}{analysis_type}报告"


def _build_heuristic_summary(context: dict[str, Any], finding: str = "") -> str:
    if finding:
        return _truncate(finding, 72)
    targets = "、".join(context["targets"][:2]) or "相关楼宇"
    metric = context["metric"]
    analysis_type = context["analysis_type"]
    return f"本报告围绕{targets}的{metric}进行{analysis_type}，提炼关键结论、建议行动与待确认风险。"


def _resolve_report_title(context: dict[str, Any], draft: ConversationReportDraft) -> str:
    candidate = _plain_text(draft.report_title)
    if not candidate or _looks_like_raw_question(candidate):
        candidate = _build_heuristic_title(context)
    if not candidate.endswith("报告"):
        candidate = candidate.rstrip("。") + "报告"
    return _truncate(candidate, 48)


def _resolve_report_summary(context: dict[str, Any], draft: ConversationReportDraft) -> str:
    candidate = _first_sentence(draft.report_summary, 72)
    if not candidate or _looks_like_raw_question(candidate):
        candidate = _first_sentence(draft.key_findings, 72)
    if not candidate:
        candidate = _first_sentence(draft.executive_summary, 72)
    if not candidate:
        candidate = _build_heuristic_summary(context, _first_sentence(context["latest_ai_answer"], 72))
    return candidate


def _build_fallback_sections(context: dict[str, Any]) -> ConversationReportDraft:
    summary_lines: list[str] = []
    if context["context_summary"]:
        summary_lines.extend(
            _truncate(line, 180)
            for line in str(context["context_summary"]).splitlines()
            if line.strip()
        )
    if context["latest_ai_answer"]:
        summary_lines.append(_truncate(_first_sentence(context["latest_ai_answer"], 140), 140))
    if context["react_data_summary"] and context["react_data_summary"] != "（未执行工具调用）":
        summary_lines.append(_truncate(_first_sentence(context["react_data_summary"], 140), 140))

    findings: list[str] = []
    if context["react_data_summary"] and context["react_data_summary"] != "（未执行工具调用）":
        findings.append(_truncate(_first_sentence(context["react_data_summary"], 180), 180))
    if context["artifact_titles"]:
        findings.append(f"本次会话生成的关键工件包括：{'、'.join(context['artifact_titles'])}。")
    if context["latest_ai_answer"]:
        findings.append(_truncate(_first_sentence(context["latest_ai_answer"], 180), 180))

    recommendations: list[str] = []
    pending_action = context["pending_action"]
    if isinstance(pending_action, dict) and pending_action.get("ticket_id"):
        recommendations.append(
            f"优先确认待审批事项 {pending_action['ticket_id']}，再决定是否进入现场执行。"
        )
    if context["artifact_titles"]:
        recommendations.append("结合已生成图表复核关键指标，再执行下一步排查或汇报动作。")
    recommendations.append("对结论涉及的关键数据保留人工复核，避免直接基于单轮对话形成最终决策。")

    risks: list[str] = []
    if not context["artifact_titles"]:
        risks.append("本次会话未生成可视化工件，部分判断缺少图表佐证。")
    if not context["react_data_summary"] or context["react_data_summary"] == "（未执行工具调用）":
        risks.append("结构化数据摘要不足，部分结论依赖文本归纳。")
    if not context["context_summary"]:
        risks.append("历史滚动摘要缺失，跨轮上下文可能不完整。")
    if isinstance(pending_action, dict) and pending_action.get("ticket_id"):
        risks.append("存在待审批动作，执行前需要确认工单内容与优先级。")

    heuristic_finding = (
        _first_sentence(context["latest_ai_answer"], 72)
        or _first_sentence(context["context_summary"], 72)
        or _first_sentence("\n".join(findings), 72)
    )
    return ConversationReportDraft(
        report_title=_build_heuristic_title(context),
        report_summary=_build_heuristic_summary(context, heuristic_finding),
        executive_summary=_markdown_bullets(
            summary_lines[:4],
            "- 本次会话已生成正式总结报表，但当前可用摘要信息有限。",
        ),
        key_findings=_markdown_bullets(
            findings[:4],
            "- 当前会话缺少足够的结构化结论。",
        ),
        recommendations=_markdown_bullets(
            recommendations[:4],
            "- 建议先复核关键数据，再继续下一步操作。",
        ),
        risks_and_open_questions=_markdown_bullets(
            risks[:4],
            "- 当前未发现额外风险，但仍建议保留人工复核。",
        ),
    )


def _build_llm_context(context: dict[str, Any]) -> str:
    transcript_lines: list[str] = []
    for role, content in context["turns"][-8:]:
        prefix = "用户" if role == "user" else "AI"
        transcript_lines.append(f"{prefix}: {_truncate(content, 240)}")

    artifact_lines = [f"- {title}" for title in context["artifact_titles"]] or ["- 无"]
    pending_action = context["pending_action"]
    if isinstance(pending_action, dict) and pending_action:
        pending_summary = (
            f"ticket_id={pending_action.get('ticket_id')}, "
            f"building_id={pending_action.get('building_id')}, "
            f"priority={pending_action.get('priority')}, "
            f"issue={pending_action.get('issue_description')}"
        )
    else:
        pending_summary = "无"

    date_range = context["date_range"]
    date_range_label = f"{date_range['start']} ~ {date_range['end']}" if date_range else "未明确"

    return "\n".join(
        [
            f"会话标题：{context['session_title']}",
            f"分析对象：{'、'.join(context['targets']) or '未明确'}",
            f"核心指标：{context['metric']}",
            f"分析类型：{context['analysis_type']}",
            f"时间范围：{date_range_label}",
            f"会话楼宇：{context['session_building'] or '未标注'}",
            f"用户轮次：{context['user_turn_count']}",
            f"AI 轮次：{context['ai_turn_count']}",
            f"最新用户问题：{_truncate(context['latest_user_question'], 260) or '无'}",
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
            "数据来源：",
            "、".join(context["data_sources"]) or "未明确",
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
        "你是楼宇能耗管理系统的报告编辑器。"
        "请基于给定会话状态生成一份正式分析报告所需的结构化内容。\n"
        "要求：\n"
        "1. report_title 必须是正式报告标题，禁止直接复述用户问句，禁止使用第一人称。\n"
        "2. report_summary 必须是一句话摘要，突出主要结论或分析重点，不能是问句。\n"
        "3. executive_summary、key_findings、recommendations、risks_and_open_questions 都使用 markdown，可用列表，但不要再写标题。\n"
        "4. 只能依据输入事实，不得编造数据，不得输出原始逐条问答，不得输出代码块或图表占位符。\n"
        "5. recommendations 必须是可执行动作；risks_and_open_questions 必须包含待确认项或核验点。"
    )
    return await llm.ainvoke(prompt + "\n\n" + _build_llm_context(context))


def _build_overview_items(
    context: dict[str, Any],
    report_summary: str,
    report_draft: ConversationReportDraft,
) -> list[ReportSummaryItem]:
    pending_action = context["pending_action"]
    pending_label = "无"
    if isinstance(pending_action, dict) and pending_action.get("ticket_id"):
        pending_label = str(pending_action.get("ticket_id"))

    date_range = context["date_range"]
    date_range_label = f"{date_range['start']} ~ {date_range['end']}" if date_range else "未明确"
    data_sources = "、".join(context["data_sources"]) if context["data_sources"] else "对话分析结果"
    key_judgement = (
        _first_sentence(context["latest_ai_answer"], 72)
        or _first_sentence(context["context_summary"], 72)
        or _first_sentence(report_draft.key_findings, 72)
        or report_summary
    )

    return [
        ReportSummaryItem(label="分析对象", value="、".join(context["targets"]) or "未明确"),
        ReportSummaryItem(label="核心指标", value=context["metric"]),
        ReportSummaryItem(label="分析方式", value=context["analysis_type"]),
        ReportSummaryItem(label="时间范围", value=date_range_label),
        ReportSummaryItem(label="数据来源", value=data_sources),
        ReportSummaryItem(label="工件产出", value=f"{len(context['artifacts'])} 个"),
        ReportSummaryItem(label="待审批事项", value=pending_label),
        ReportSummaryItem(label="核心判断", value=key_judgement or "待结合正文进一步确认"),
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

    context: dict[str, Any] = {
        "session_id": session_id,
        "session_title": session_title or "AI 对话总结报表",
        "session_building": state.get("building_id"),
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
        "artifact_titles": [
            str(artifact.get("title") or artifact.get("component_type") or artifact.get("widget") or "未命名工件")
            for artifact in artifacts
        ],
    }
    context["targets"] = _extract_targets(context)
    context["metric"] = _detect_metric(context)
    context["analysis_type"] = _detect_analysis_type(context)
    context["data_sources"] = _extract_data_sources(artifacts)
    context["date_range"] = _extract_date_range(context)

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

    report_title = _resolve_report_title(context, report_draft)
    report_summary = _resolve_report_summary(context, report_draft)
    overview_items = _build_overview_items(context, report_summary, report_draft)

    sections: list[ReportSection] = [
        ReportSection(
            id="conversation-overview",
            namespace="conversation-report",
            title="分析概览",
            description=report_summary,
            type="summary",
            summaryItems=overview_items,
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
                title=str(artifact.get("title") or f"关键图表 {index}"),
                type="artifact",
                artifact=artifact,
                order=100 + index,
            )
        )

    cover_subject = "、".join(context["targets"][:2]) or str(context.get("session_building") or "")
    return ConversationReportPayload(
        title=report_title,
        subtitle=report_summary,
        generatedAt=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        buildingName=cover_subject or None,
        dateRange=context["date_range"],
        sections=sections,
        mode=req.mode,
        generatedBy="AI 正式分析报告",
    )
