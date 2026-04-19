from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.core.chat_message_utils import get_human_display_content
from app.core.buildings import BUILDING_ID_TO_TYPE, BUILDING_TYPE_LABELS
from app.core.config import get_settings
from app.graph.viz_engine import build_chart_manifest, build_data_summary
from app.schemas.report_schemas import (
    ConversationReportPayload,
    ConversationReportRequest,
    FormalReportMeta,
    ReportSection,
    ReportSummaryItem,
)

DEFAULT_REPORT_TEMPLATE_ID = "formal-management-brief"

_BUILDING_DISPLAY = {
    **BUILDING_TYPE_LABELS,
    "Public": BUILDING_TYPE_LABELS["Public services"],
    **{
        building_id: BUILDING_TYPE_LABELS[building_type]
        for building_id, building_type in BUILDING_ID_TO_TYPE.items()
    },
}

_PLACEHOLDER_RE = re.compile(r"<<CHART:[^>]*>>")
_TOOL_CALL_RE = re.compile(
    r"\b(render_ui_component|create_work_order_draft|generate_report)\s*\([\s\S]*?\)\s*"
)
_BLANK_LINE_RE = re.compile(r"\n{3,}")
_MARKDOWN_TOKEN_RE = re.compile(r"[#>*`_~\-]+")
_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(m3/h|m³/h|kWh|kW|吨|℃)")
_MONEY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|万元|RMB|CNY)", re.IGNORECASE)
_CARBON_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:tCO2e|kgCO2e|吨二氧化碳当量|千克二氧化碳当量)",
    re.IGNORECASE,
)

_TARGET_PATTERNS = (
    "教学楼",
    "办公楼",
    "实验楼",
    "宿舍楼",
    "行政楼",
    "食堂",
    "公共楼",
    "图书馆",
    "数据中心",
    "园区",
    "校区",
)

_METRIC_RULES: list[tuple[tuple[str, ...], str]] = [
    (("用水", "水量", "漏水"), "用水量"),
    (("用电", "电量", "耗电"), "用电量"),
    (("COP", "cop"), "COP"),
    (("冷量", "制冷"), "冷量"),
]

_ANALYSIS_TYPE_RULES: list[tuple[tuple[str, ...], str]] = [
    (("对比", "比较", "vs", "VS"), "对比分析"),
    (("趋势", "变化", "走势"), "趋势分析"),
    (("异常", "诊断", "排查"), "诊断分析"),
    (("原因", "根因"), "原因分析"),
]

_cached_report_llm_fast: Any = None
_cached_report_llm_deep: Any = None
_report_llm_lock: threading.RLock | None = None


class ConversationReportDraft(BaseModel):
    report_title: str = Field(description="正式报告标题，不要复述用户问题。")
    report_summary: str = Field(description="一句话总结，突出结论。")
    executive_summary: str = Field(description="执行摘要，markdown 列表。")
    key_findings: str = Field(description="关键发现，markdown 列表。")
    recommendations: str = Field(description="建议动作，markdown 列表。")
    risks_and_open_questions: str = Field(description="风险与待确认项，markdown 列表。")


@dataclass(frozen=True)
class ReportTemplateDefinition:
    id: str
    label: str
    description: str
    audience: str
    build_payload: Callable[[dict[str, Any], ConversationReportRequest, ConversationReportDraft], ConversationReportPayload]


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


def _first_sentence(text: str, limit: int = 72) -> str:
    plain = _plain_text(text)
    if not plain:
        return ""
    for part in re.split(r"[。；;.!?\n]", plain):
        candidate = part.strip()
        if candidate:
            return _truncate(candidate, limit)
    return _truncate(plain, limit)


def _markdown_bullets(items: list[str], fallback: str) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return fallback
    return "\n".join(f"- {item}" for item in cleaned)


def _extract_markdown_bullets(text: str, limit: int = 3) -> list[str]:
    items: list[str] = []
    for line in sanitize_report_markdown(text).splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        candidate = re.sub(r"^[-*]\s*", "", candidate)
        candidate = re.sub(r"^\d+\.\s*", "", candidate)
        candidate = candidate.strip()
        if candidate:
            items.append(_truncate(candidate, 120))
        if len(items) >= limit:
            break
    return items


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
            turns.append(("user", sanitize_report_markdown(get_human_display_content(msg))))
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


def _normalize_date(year: str, month: str, day: str) -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _extract_dates_from_text(text: str) -> list[str]:
    return [_normalize_date(year, month, day) for year, month, day in _DATE_RE.findall(text or "")]


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
    for raw in (
        str(context.get("session_building") or ""),
        context["session_title"],
        context["latest_user_question"],
        context["latest_ai_answer"],
        " ".join(context["artifact_titles"]),
    ):
        if not raw:
            continue
        for token in _TARGET_PATTERNS:
            if token in raw:
                candidates.append(token)
        for match in re.findall(r"[A-Za-z0-9_-]{2,24}", raw):
            if any(ch.isalpha() for ch in match):
                candidates.append(_BUILDING_DISPLAY.get(match, match))

    unique: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        cleaned = _BUILDING_DISPLAY.get(item.strip(), item.strip())
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
        for key in ("source_table", "base_table", "source_view", "dataset"):
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
        return f"{targets[0]}与{targets[1]}{metric}{analysis_type}报告"
    if targets:
        return f"{targets[0]}{metric}{analysis_type}报告"
    return f"{metric}{analysis_type}报告"


def _build_heuristic_summary(context: dict[str, Any], finding: str = "") -> str:
    if finding:
        return _truncate(finding, 72)
    targets = "、".join(context["targets"][:2]) or "相关对象"
    return f"本报告围绕{targets}的{context['metric']}开展{context['analysis_type']}，提炼结论、证据和建议动作。"


def _resolve_report_title(context: dict[str, Any], draft: ConversationReportDraft) -> str:
    candidate = _plain_text(draft.report_title)
    if not candidate:
        candidate = _build_heuristic_title(context)
    if not candidate.endswith("报告"):
        candidate = candidate.rstrip("。") + "报告"
    return _truncate(candidate, 48)


def _resolve_report_summary(context: dict[str, Any], draft: ConversationReportDraft) -> str:
    candidate = _first_sentence(draft.report_summary, 72)
    if not candidate:
        candidate = _first_sentence(draft.key_findings, 72)
    if not candidate:
        candidate = _first_sentence(draft.executive_summary, 72)
    if not candidate:
        candidate = _build_heuristic_summary(context, _first_sentence(context["latest_ai_answer"], 72))
    return candidate


def _build_fallback_sections(context: dict[str, Any]) -> ConversationReportDraft:
    summary_lines: list[str] = []
    for source in (
        context["context_summary"],
        context["latest_ai_answer"],
        context["react_data_summary"],
    ):
        sentence = _first_sentence(source, 160)
        if sentence:
            summary_lines.append(sentence)

    findings = [
        _first_sentence(context["latest_ai_answer"], 160),
        _first_sentence(context["react_data_summary"], 160),
        f"本次会话涉及对象：{'、'.join(context['targets'])}" if context["targets"] else "",
    ]
    findings = [item for item in findings if item]

    recommendations = []
    pending_action = context["pending_action"]
    if isinstance(pending_action, dict) and pending_action.get("ticket_id"):
        recommendations.append(f"优先核对待审批事项 {pending_action['ticket_id']} 后再执行现场动作。")
    recommendations.append("复核关键异常指标与图表证据，确认结论是否可直接用于汇报。")
    recommendations.append("对结论涉及的关键数据保留人工复核环节。")

    risks = []
    if not context["artifacts"]:
        risks.append("当前缺少图表或卡片类证据，判断依据主要来自文本归纳。")
    if not context["data_sources"]:
        risks.append("未识别到明确数据来源，建议补充来源说明。")
    if not context["context_summary"]:
        risks.append("跨轮对话摘要不足，可能存在上下文缺口。")

    return ConversationReportDraft(
        report_title=_build_heuristic_title(context),
        report_summary=_build_heuristic_summary(context, _first_sentence(context["latest_ai_answer"], 72)),
        executive_summary=_markdown_bullets(summary_lines[:4], "- 当前会话已导出正式报表，但可用摘要信息有限。"),
        key_findings=_markdown_bullets(findings[:4], "- 当前会话缺少足够的结构化结论。"),
        recommendations=_markdown_bullets(recommendations[:4], "- 建议先复核关键数据后再继续动作。"),
        risks_and_open_questions=_markdown_bullets(risks[:4], "- 当前未发现额外风险，但仍建议保留人工复核。"),
    )


def _build_llm_context(context: dict[str, Any]) -> str:
    transcript_lines: list[str] = []
    for role, content in context["turns"][-8:]:
        prefix = "用户" if role == "user" else "AI"
        transcript_lines.append(f"{prefix}: {_truncate(content, 240)}")

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
            f"会话标题: {context['session_title']}",
            f"分析对象: {'、'.join(context['targets']) or '未明确'}",
            f"核心指标: {context['metric']}",
            f"分析类型: {context['analysis_type']}",
            f"时间范围: {date_range_label}",
            f"数据来源: {'、'.join(context['data_sources']) or '未明确'}",
            f"最近用户问题: {_truncate(context['latest_user_question'], 260) or '无'}",
            f"最近 AI 回答: {_truncate(context['latest_ai_answer'], 320) or '无'}",
            "",
            "历史摘要:",
            context["context_summary"] or "无",
            "",
            "结构化数据摘要:",
            context["react_data_summary"] or "无",
            "",
            "图表清单:",
            context["chart_manifest"] or "无",
            "",
            "待审批事项:",
            pending_summary,
            "",
            "最近对话摘录:",
            "\n".join(transcript_lines) or "无",
        ]
    )


async def _generate_ai_sections(context: dict[str, Any], thinking_mode: str) -> ConversationReportDraft:
    llm = _build_report_llm(thinking_mode)
    prompt = (
        "你是楼宇能耗管理系统的报告编辑器。"
        "请基于给定事实生成一份正式分析报告的结构化内容。\n"
        "要求：\n"
        "1. report_title 必须是正式标题，不要复述用户问题。\n"
        "2. report_summary 必须是一句结论型摘要，不能是问句。\n"
        "3. executive_summary、key_findings、recommendations、risks_and_open_questions 都使用 markdown 列表。\n"
        "4. recommendations 必须是可执行动作；risks_and_open_questions 必须包含待确认项。\n"
        "5. 只能依据输入事实，不得编造数据，不输出代码块。"
    )
    return await llm.ainvoke(prompt + "\n\n" + _build_llm_context(context))


def _select_primary_artifact(artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred = {"LineChart", "BarChart", "Gauge", "line-chart", "bar-chart", "gauge"}
    for artifact in artifacts:
        component_type = str(artifact.get("component_type") or artifact.get("widget") or "")
        if component_type in preferred:
            return artifact
    return artifacts[0] if artifacts else None


def _extract_highlight_value(context: dict[str, Any]) -> str:
    corpus = "\n".join(
        [
            context["latest_ai_answer"],
            context["react_data_summary"],
            context["context_summary"],
        ]
    )
    percent_matches = _PERCENT_RE.findall(corpus)
    if percent_matches:
        values = [float(item) for item in percent_matches]
        return f"{max(values):.0f}%"
    value_match = _VALUE_RE.search(corpus)
    if value_match:
        return f"{value_match.group(1)} {value_match.group(2)}"
    return "待补充"


def _resolve_severity(context: dict[str, Any], draft: ConversationReportDraft) -> str:
    corpus = " ".join(
        [
            context["latest_ai_answer"],
            context["context_summary"],
            draft.key_findings,
        ]
    )
    if any(keyword in corpus for keyword in ("严重", "高风险", "泄漏", "漏水", "极高")):
        return "critical"
    if any(keyword in corpus for keyword in ("异常", "偏高", "告警", "超标")):
        return "warning"
    if any(keyword in corpus for keyword in ("波动", "关注", "待观察")):
        return "attention"
    return "pending"


def _resolve_confidence(context: dict[str, Any]) -> str:
    score = 0
    if context["react_data_summary"]:
        score += 1
    if context["data_sources"]:
        score += 1
    if context["artifacts"]:
        score += 1
    if score >= 3:
        return "高"
    if score == 2:
        return "中"
    return "待确认"


def _build_key_metrics(context: dict[str, Any], report_summary: str, draft: ConversationReportDraft) -> list[ReportSummaryItem]:
    date_range = context["date_range"]
    date_range_label = f"{date_range['start']} ~ {date_range['end']}" if date_range else "未明确"
    decision = (
        _first_sentence(context["latest_ai_answer"], 68)
        or _first_sentence(draft.key_findings, 68)
        or report_summary
    )
    return [
        ReportSummaryItem(label="分析对象", value="、".join(context["targets"]) or "未明确"),
        ReportSummaryItem(label="时间范围", value=date_range_label),
        ReportSummaryItem(label="核心指标", value=context["metric"]),
        ReportSummaryItem(label="初步判断", value=decision or "待确认"),
    ]


def _build_evidence_highlights(context: dict[str, Any], report_summary: str, draft: ConversationReportDraft) -> list[ReportSummaryItem]:
    date_range = context["date_range"]
    date_range_label = f"{date_range['start']} ~ {date_range['end']}" if date_range else "未明确"
    data_sources = "、".join(context["data_sources"]) if context["data_sources"] else "对话分析结果"
    key_judgement = (
        _first_sentence(context["react_data_summary"], 72)
        or _first_sentence(context["latest_ai_answer"], 72)
        or _first_sentence(draft.key_findings, 72)
        or report_summary
    )
    return [
        ReportSummaryItem(label="异常区间", value=date_range_label),
        ReportSummaryItem(label="异常幅度", value=_extract_highlight_value(context)),
        ReportSummaryItem(label="数据依据", value=data_sources if len(data_sources) <= 72 else _truncate(data_sources, 72)),
        ReportSummaryItem(label="判断依据", value=key_judgement or "待确认"),
    ]


def _build_appendix_content(turns: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    for index, (role, content) in enumerate(turns, start=1):
        title = "用户" if role == "user" else "AI"
        lines.append(f"{index}. **{title}**：{_truncate(content, 500)}")
    return "\n".join(lines)


def _normalize_business_text(text: str) -> str:
    clean = sanitize_report_markdown(text)
    replacements = [
        ("对话分析结果", "系统监测与研判结果"),
        ("对话分析", "业务研判"),
        ("工具调用", "数据溯源"),
        ("系统设定", "运行规则"),
        ("量化依据", "偏离度分析"),
        ("water_leak", "管网跑冒滴漏"),
        ("work_order", "运维工单"),
        ("artifact", "监测图表"),
    ]
    for source, target in replacements:
        clean = clean.replace(source, target)
    clean = re.sub(
        r"\bGB\s*([0-9]{3,6}(?:[-–][0-9]{2,4})?)\b",
        r"国家相关标准（GB \1）",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _extract_highlight_value(context: dict[str, Any]) -> str:
    corpus = "\n".join(
        [
            context["latest_ai_answer"],
            context["react_data_summary"],
            context["context_summary"],
        ]
    )
    percent_matches = _PERCENT_RE.findall(corpus)
    if percent_matches:
        values = [float(item) for item in percent_matches]
        return f"{max(values):.0f}%"
    value_match = _VALUE_RE.search(corpus)
    if value_match:
        return f"{value_match.group(1)} {value_match.group(2)}"
    return "待补充"


def _normalize_business_bullets(items: list[str], *, default: str, limit: int = 3) -> list[str]:
    normalized: list[str] = []
    for item in items:
        clean = _normalize_business_text(item)
        if not clean:
            continue
        normalized.append(_truncate(clean, 120))
        if len(normalized) >= limit:
            break
    if normalized:
        return normalized
    return [_normalize_business_text(default)]


def _format_subject(context: dict[str, Any]) -> str:
    targets = [item for item in context["targets"] if item]
    if targets:
        return "、".join(targets[:2])
    session_building = str(context.get("session_building") or "").strip()
    session_building = _BUILDING_DISPLAY.get(session_building, session_building)
    return session_building or "相关对象"


def _format_date_range_label(date_range: dict[str, str] | None) -> str:
    if not date_range:
        return "本次会话涉及时段"
    return f"{date_range['start']} 至 {date_range['end']}"


def _build_minutes_title(context: dict[str, Any]) -> str:
    subject = _format_subject(context)
    date_label = _format_date_range_label(context["date_range"])
    topic = "运行情况研判"
    corpus = " ".join(
        [
            context["latest_user_question"],
            context["latest_ai_answer"],
            context["metric"],
        ]
    )
    if any(keyword in corpus for keyword in ("用水", "漏水", "水量")):
        topic = "用水异常研判"
    elif any(keyword in corpus for keyword in ("用电", "电量", "能耗", "耗电")):
        topic = "用能异常研判"
    elif "COP" in corpus.upper():
        topic = "运行效率核查"
    elif any(keyword in corpus for keyword in ("对比", "比较", "趋势")):
        topic = "运行对比研判"
    return _truncate(f"{subject} {date_label} {topic}会话纪要", 64)


def _resolve_confidence_label(context: dict[str, Any]) -> str:
    score = 0
    if context["react_data_summary"]:
        score += 1
    if context["data_sources"]:
        score += 1
    if context["artifacts"]:
        score += 1
    if score >= 3:
        return "高"
    if score == 2:
        return "中"
    return "待确认"


def _resolve_current_judgement(context: dict[str, Any], draft: ConversationReportDraft, report_summary: str) -> str:
    corpus = " ".join(
        [
            context["latest_ai_answer"],
            context["react_data_summary"],
            draft.key_findings,
            report_summary,
        ]
    )
    if any(keyword in corpus for keyword in ("漏水", "漏损", "water_leak", "跑冒滴漏")):
        return "疑似漏损"
    if any(keyword in corpus for keyword in ("超标", "异常", "偏高", "告警")):
        return "存在异常偏离"
    if any(keyword in corpus for keyword in ("波动", "关注")):
        return "需持续关注"
    return "待进一步核查"


def _resolve_conclusion_status(context: dict[str, Any]) -> str:
    if context["artifacts"] or context["data_sources"]:
        return "待现场确认"
    return "待补充数据"


def _build_problem_statement(context: dict[str, Any]) -> str:
    question = _normalize_business_text(context["latest_user_question"])
    if question:
        return _truncate(f"本次会话中，能源管理员提出：{question}", 220)
    subject = _format_subject(context)
    return f"本次会话围绕{subject}的运行情况核查、问题判断与处置建议展开。"


def _build_process_summary(context: dict[str, Any], draft: ConversationReportDraft) -> list[str]:
    subject = _format_subject(context)
    date_label = _format_date_range_label(context["date_range"])
    process = [
        f"先围绕{subject}在{date_label}的运行情况进行核查，明确本次会话关注的问题范围。",
        (
            f"随后结合系统监测日志、历史比对和数据溯源信息，对{context['metric']}是否存在明显偏离进行了交叉核查。"
            if context["react_data_summary"] or context["data_sources"]
            else "随后结合本次会话中的已有信息，对异常特征和影响范围进行了归纳判断。"
        ),
        (
            _normalize_business_text(_first_sentence(draft.key_findings, 120))
            or _normalize_business_text(_first_sentence(context["latest_ai_answer"], 120))
            or "最终形成当前研判结论，并保留待现场确认事项。"
        ),
    ]
    return _normalize_business_bullets(process, default="已完成会话研判并形成初步结论。")


def _extract_exclusion_statement(context: dict[str, Any]) -> str:
    corpus = " ".join(
        [
            context["latest_ai_answer"],
            context["react_data_summary"],
            context["context_summary"],
        ]
    )
    parts = re.split(r"[。；;\n]", corpus)
    for part in parts:
        clean = _normalize_business_text(part)
        if not clean:
            continue
        if any(keyword in clean for keyword in ("排除", "不支持", "不属于", "暂不考虑", "未见")):
            return _truncate(clean, 72)
    return "暂无明确排除项，需结合现场复核确认。"


def _split_sentences(text: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"[。；;\n]", sanitize_report_markdown(text))
        if item and item.strip()
    ]


def _is_invalid_basis_text(text: str) -> bool:
    markers = ("未执行", "未调用", "暂无结果", "程序", "报错", "traceback", "artifact")
    return any(marker in text.lower() if marker == "traceback" else marker in text for marker in markers)


def _best_basis_sentence(context: dict[str, Any], draft: ConversationReportDraft, report_summary: str) -> str:
    candidates: list[str] = []
    for block in [
        str(context.get("react_data_summary") or ""),
        str(context.get("context_summary") or ""),
        *(context.get("ai_answers") or []),
        sanitize_report_markdown(draft.key_findings),
        report_summary,
    ]:
        for sentence in _split_sentences(block):
            clean = _normalize_business_text(sentence)
            if not clean or _is_invalid_basis_text(clean):
                continue
            candidates.append(clean)

    quantified = [
        item for item in candidates
        if re.search(r"\d", item) or any(keyword in item for keyword in ("偏高", "异常", "占比", "连续", "峰值", "基线"))
    ]
    if quantified:
        return _truncate(quantified[0], 96)
    if candidates:
        return _truncate(candidates[0], 96)
    return "当前系统暂无相关历史溯源记录，需结合现场进一步核验。"


def _build_meeting_evidence(context: dict[str, Any], draft: ConversationReportDraft, report_summary: str) -> list[ReportSummaryItem]:
    time_reference = _format_date_range_label(context["date_range"])
    corpus = " ".join(
        [
            context["latest_user_question"],
            context["latest_ai_answer"],
            context["react_data_summary"],
            context["context_summary"],
        ]
    )
    if any(keyword in corpus for keyword in ("夜间", "凌晨")):
        time_reference = "夜间/凌晨时段"
    elif any(keyword in corpus for keyword in ("白天", "日间")):
        time_reference = "日间运行时段"

    basis = (
        _normalize_business_text(_first_sentence(context["react_data_summary"], 88))
        or _normalize_business_text(_first_sentence(context["latest_ai_answer"], 88))
        or _normalize_business_text(report_summary)
        or "当前会话已完成系统监测日志与历史信息的综合研判。"
    )

    return [
        ReportSummaryItem(label="异常时段", value=time_reference),
        ReportSummaryItem(label="偏离水平", value=_extract_highlight_value(context)),
        ReportSummaryItem(label="主要依据", value=basis),
        ReportSummaryItem(label="排除项", value=_extract_exclusion_statement(context)),
    ]


def _extract_money_impact(context: dict[str, Any]) -> str:
    corpus = " ".join(
        [
            context["latest_ai_answer"],
            context["react_data_summary"],
            context["context_summary"],
        ]
    )
    match = _MONEY_RE.search(corpus)
    if match:
        return f"约 {match.group(1)} {match.group(0).replace(match.group(1), '').strip() or '元'}"
    return "待按现行单价测算"


def _extract_carbon_impact(context: dict[str, Any]) -> str:
    corpus = " ".join(
        [
            context["latest_ai_answer"],
            context["react_data_summary"],
            context["context_summary"],
        ]
    )
    match = _CARBON_RE.search(corpus)
    if match:
        return f"约 {match.group(1)} {match.group(0).replace(match.group(1), '').strip()}"
    return "待按校区核算口径测算"


def _build_impact_highlights(context: dict[str, Any]) -> list[ReportSummaryItem]:
    highlight = _extract_highlight_value(context)
    metric = context["metric"] or "运行指标"
    if highlight == "待补充":
        loss_value = "待结合现场复核结果测算"
    else:
        loss_value = f"{metric}异常规模参考值 {highlight}"
    return [
        ReportSummaryItem(label="损失预估", value=loss_value),
        ReportSummaryItem(label="费用影响", value=_extract_money_impact(context)),
        ReportSummaryItem(label="碳排影响", value=_extract_carbon_impact(context)),
    ]


def _build_overview_items(context: dict[str, Any], generated_at: str) -> list[ReportSummaryItem]:
    topic = _normalize_business_text(context["metric"] or "运行情况")
    if topic and not topic.endswith("研判"):
        topic = f"{topic}研判"
    return [
        ReportSummaryItem(label="会话主题", value=topic or "运行情况研判"),
        ReportSummaryItem(label="发起角色", value="能源管理员"),
        ReportSummaryItem(label="涉及对象", value=_format_subject(context)),
        ReportSummaryItem(label="研判时间", value=generated_at),
    ]


def _build_conclusion_text(
    context: dict[str, Any],
    report_summary: str,
    current_judgement: str,
) -> str:
    summary = _normalize_business_text(report_summary).rstrip("。")
    basis = _normalize_business_text(_first_sentence(context["latest_ai_answer"], 120))
    if basis and basis != summary:
        return (
            f"本次会话研判认为，{summary}。"
            f"依据本次会话中的系统监测、历史比对和业务研判结果，当前判断为{current_judgement}。"
        )
    return f"本次会话研判认为，{summary}。当前判断为{current_judgement}。"


def _build_management_brief_payload(
    context: dict[str, Any],
    req: ConversationReportRequest,
    report_draft: ConversationReportDraft,
) -> ConversationReportPayload:
    report_title = _resolve_report_title(context, report_draft)
    report_summary = _resolve_report_summary(context, report_draft)
    primary_artifact = _select_primary_artifact(context["artifacts"])
    actions = _extract_markdown_bullets(report_draft.recommendations, limit=3)
    if not actions:
        actions = ["复核关键指标和证据后再执行下一步动作。"]
    open_questions = _extract_markdown_bullets(report_draft.risks_and_open_questions, limit=3)
    if not open_questions:
        open_questions = ["当前结论仍需人工复核。"]

    formal_meta = FormalReportMeta(
        severity=_resolve_severity(context, report_draft),
        confidence=_resolve_confidence(context),
        decisionSummary=report_summary,
        keyMetrics=_build_key_metrics(context, report_summary, report_draft),
        evidenceHighlights=_build_evidence_highlights(context, report_summary, report_draft),
        actions=actions,
        openQuestions=open_questions,
        primaryArtifact=primary_artifact,
    )

    sections: list[ReportSection] = [
        ReportSection(
            id="conversation-overview",
            namespace="conversation-report",
            title="核心指标",
            description=report_summary,
            type="summary",
            summaryItems=formal_meta.keyMetrics,
            order=10,
        ),
        ReportSection(
            id="conversation-key-findings",
            namespace="conversation-report",
            title="关键发现",
            type="text",
            content=sanitize_report_markdown(report_draft.key_findings),
            contentFormat="markdown",
            order=20,
        ),
        ReportSection(
            id="conversation-evidence-highlights",
            namespace="conversation-report",
            title="关键证据",
            type="summary",
            summaryItems=formal_meta.evidenceHighlights,
            order=30,
        ),
        ReportSection(
            id="conversation-recommendations",
            namespace="conversation-report",
            title="建议动作",
            type="text",
            content=_markdown_bullets(actions, "- 复核关键指标后再继续处理。"),
            contentFormat="markdown",
            order=40,
        ),
        ReportSection(
            id="conversation-risks",
            namespace="conversation-report",
            title="待确认项",
            type="text",
            content=_markdown_bullets(open_questions, "- 当前无额外待确认项。"),
            contentFormat="markdown",
            order=50,
        ),
    ]

    if primary_artifact:
        sections.insert(
            2,
            ReportSection(
                id="conversation-primary-artifact",
                namespace="conversation-report",
                title=str(primary_artifact.get("title") or "主证据图表"),
                type="artifact",
                artifact=primary_artifact,
                order=25,
            ),
        )

    if req.include_appendix:
        sections.extend(
            [
                ReportSection(
                    id="conversation-executive-summary",
                    namespace="conversation-report",
                    title="执行摘要附录",
                    type="text",
                    content=sanitize_report_markdown(report_draft.executive_summary),
                    contentFormat="markdown",
                    order=60,
                ),
                ReportSection(
                    id="conversation-appendix",
                    namespace="conversation-report",
                    title="原始对话附录",
                    type="text",
                    content=_build_appendix_content(context["turns"]),
                    contentFormat="markdown",
                    order=70,
                ),
            ]
        )

        for index, artifact in enumerate(context["artifacts"], start=1):
            if primary_artifact is not None and artifact is primary_artifact:
                continue
            sections.append(
                ReportSection(
                    id=f"conversation-artifact-{index}",
                    namespace="conversation-report",
                    title=str(artifact.get("title") or f"附录图表 {index}"),
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
        template_id=DEFAULT_REPORT_TEMPLATE_ID,
        template_label="正式汇报版",
        formalMeta=formal_meta,
    )


def _build_management_brief_payload(
    context: dict[str, Any],
    req: ConversationReportRequest,
    report_draft: ConversationReportDraft,
) -> ConversationReportPayload:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_title = _build_minutes_title(context)
    report_summary = _normalize_business_text(_resolve_report_summary(context, report_draft))
    primary_artifact = _select_primary_artifact(context["artifacts"])
    actions = _normalize_business_bullets(
        _extract_markdown_bullets(report_draft.recommendations, limit=3),
        default="建议先完成现场复核，再推进后续处置。",
    )
    open_questions = _normalize_business_bullets(
        _extract_markdown_bullets(report_draft.risks_and_open_questions, limit=3),
        default="当前结论仍需结合现场复核进一步确认。",
    )
    process_summary = _build_process_summary(context, report_draft)
    current_judgement = _resolve_current_judgement(context, report_draft, report_summary)
    conclusion_status = _resolve_conclusion_status(context)
    problem_statement = _build_problem_statement(context)
    conclusion_text = _build_conclusion_text(context, report_summary, current_judgement)
    overview_items = _build_overview_items(context, generated_at)
    evidence_highlights = _build_meeting_evidence(context, report_draft, report_summary)
    impact_highlights = _build_impact_highlights(context)

    formal_meta = FormalReportMeta(
        severity=_resolve_severity(context, report_draft),
        confidence=_resolve_confidence_label(context),
        decisionSummary=report_summary,
        currentJudgement=current_judgement,
        conclusionStatus=conclusion_status,
        overviewItems=overview_items,
        processSummary=process_summary,
        keyMetrics=_build_key_metrics(context, report_summary, report_draft),
        evidenceHighlights=evidence_highlights,
        impactHighlights=impact_highlights,
        actions=actions,
        openQuestions=open_questions,
        primaryArtifact=primary_artifact,
    )

    sections: list[ReportSection] = [
        ReportSection(
            id="conversation-problem-statement",
            namespace="conversation-report",
            title="发起问题",
            type="text",
            content=problem_statement,
            contentFormat="plain",
            order=10,
        ),
        ReportSection(
            id="conversation-process-summary",
            namespace="conversation-report",
            title="研判过程摘要",
            type="text",
            content=_markdown_bullets(process_summary, "- 已完成本次会话研判。"),
            contentFormat="markdown",
            order=20,
        ),
        ReportSection(
            id="conversation-conclusion",
            namespace="conversation-report",
            title="会话结论",
            type="text",
            content=conclusion_text,
            contentFormat="plain",
            order=30,
        ),
        ReportSection(
            id="conversation-recommendations",
            namespace="conversation-report",
            title="建议动作",
            type="text",
            content=_markdown_bullets(actions, "- 建议先完成现场复核，再推进后续处置。"),
            contentFormat="markdown",
            order=40,
        ),
        ReportSection(
            id="conversation-risks",
            namespace="conversation-report",
            title="待确认事项",
            type="text",
            content=_markdown_bullets(open_questions, "- 当前暂无额外待确认事项。"),
            contentFormat="markdown",
            order=50,
        ),
    ]

    if req.include_appendix:
        sections.extend(
            [
                ReportSection(
                    id="conversation-appendix",
                    namespace="conversation-report",
                    title="原始对话附录",
                    type="text",
                    content=_build_appendix_content(context["turns"]),
                    contentFormat="markdown",
                    order=70,
                ),
            ]
        )

        for index, artifact in enumerate(context["artifacts"], start=1):
            sections.append(
                ReportSection(
                    id=f"conversation-artifact-{index}",
                    namespace="conversation-report",
                    title=str(artifact.get("title") or f"附录图表 {index}"),
                    type="artifact",
                    artifact=artifact,
                    order=100 + index,
                )
            )

    cover_subject = "、".join(context["targets"][:2]) or str(context.get("session_building") or "")
    return ConversationReportPayload(
        title=report_title,
        subtitle=report_summary,
        generatedAt=generated_at,
        buildingName=cover_subject or None,
        dateRange=context["date_range"],
        sections=sections,
        mode=req.mode,
        generatedBy="系统辅助生成",
        template_id=DEFAULT_REPORT_TEMPLATE_ID,
        template_label="AI辅助研判会话纪要",
        formalMeta=formal_meta,
    )


_REPORT_TEMPLATES: dict[str, ReportTemplateDefinition] = {
    DEFAULT_REPORT_TEMPLATE_ID: ReportTemplateDefinition(
        id=DEFAULT_REPORT_TEMPLATE_ID,
        label="AI辅助研判会话纪要",
        description="围绕一次会话形成问题、过程、结论与行动项的正式纪要模板。",
        audience="management",
        build_payload=_build_management_brief_payload,
    )
}


def _get_report_template(template_id: str | None) -> ReportTemplateDefinition:
    resolved_id = template_id or DEFAULT_REPORT_TEMPLATE_ID
    template = _REPORT_TEMPLATES.get(resolved_id)
    if template is None:
        raise ValueError(f"未知报表模板 '{resolved_id}'")
    return template


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

    template = _get_report_template(req.template_id)
    return template.build_payload(context, req, report_draft)


def _collect_turn_texts(turns: list[tuple[str, str]], role: str) -> list[str]:
    return [content for current_role, content in turns if current_role == role and content]


def _conversation_corpus(context: dict[str, Any]) -> str:
    parts: list[str] = [
        str(context.get("session_title") or ""),
        str(context.get("context_summary") or ""),
        str(context.get("react_data_summary") or ""),
        str(context.get("latest_user_question") or ""),
        str(context.get("latest_ai_answer") or ""),
    ]
    parts.extend(context.get("user_questions") or [])
    parts.extend(context.get("ai_answers") or [])
    return " ".join(part for part in parts if part)


def _derive_topics(context: dict[str, Any]) -> list[str]:
    corpus = _conversation_corpus(context)
    topics: list[str] = []
    has_power = any(keyword in corpus for keyword in ("用电", "电量", "耗电", "能耗"))
    has_water = any(keyword in corpus for keyword in ("用水", "水量", "漏水"))
    has_optimization = any(keyword in corpus for keyword in ("降低", "节能", "降耗", "优化"))
    has_abnormal = any(keyword in corpus for keyword in ("异常", "偏高", "漏损", "漏水", "排查", "核查"))

    if has_power and has_optimization:
        topics.append("节能优化")
    elif has_power:
        topics.append("用电管理")

    if has_water and has_abnormal:
        topics.append("用水排查")
    elif has_water:
        topics.append("用水管理")

    if not topics:
        topics.append("运行研判")
    return topics


def _build_session_summary(context: dict[str, Any]) -> str:
    subject = _format_subject(context)
    topics = _derive_topics(context)
    if "节能优化" in topics and any(topic in topics for topic in ("用水管理", "用水排查")):
        return f"本次会话围绕{subject}的节能优化与用水管理展开，形成了节电方向建议，并对用水情况进行了初步研判。"
    if "节能优化" in topics:
        return f"本次会话围绕{subject}的节能优化展开，形成了降低用电量的初步建议。"
    if "用水排查" in topics:
        return f"本次会话围绕{subject}的用水异常排查展开，形成了初步风险判断与处置建议。"
    if "用水管理" in topics:
        return f"本次会话围绕{subject}的用水管理展开，形成了初步分析与建议。"
    return f"本次会话围绕{subject}的运行情况展开，形成了初步研判结论。"


def _extract_date_range(context: dict[str, Any]) -> dict[str, str] | None:
    candidates: list[str] = []
    for text in [
        *(context.get("user_questions") or []),
        *(context.get("ai_answers") or []),
        str(context.get("context_summary") or ""),
        str(context.get("react_data_summary") or ""),
    ]:
        candidates.extend(_extract_dates_from_text(text))

    for artifact in context.get("artifacts") or []:
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
    raw_blocks: list[str] = [
        str(context.get("session_building") or ""),
        str(context.get("session_title") or ""),
        *(context.get("user_questions") or []),
        *(context.get("ai_answers") or []),
        " ".join(context.get("artifact_titles") or []),
    ]
    for raw in raw_blocks:
        if not raw:
            continue
        for token in _TARGET_PATTERNS:
            if token in raw:
                candidates.append(token)
        for match in re.findall(r"[A-Za-z0-9_-]{2,32}", raw):
            mapped = _BUILDING_DISPLAY.get(match, match)
            if mapped == match:
                if "_" in match or any(ch.isdigit() for ch in match):
                    continue
                if re.fullmatch(r"[A-Za-z][A-Za-z\s-]{1,31}", match):
                    continue
            candidates.append(mapped)

    unique: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        cleaned = _BUILDING_DISPLAY.get(item.strip(), item.strip())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)
    return unique[:4]


def _detect_metric(context: dict[str, Any]) -> str:
    corpus = _conversation_corpus(context)
    has_power = any(keyword in corpus for keyword in ("用电", "电量", "耗电", "能耗"))
    has_water = any(keyword in corpus for keyword in ("用水", "水量", "漏水"))
    if has_power and has_water:
        return "用电与用水"
    if has_water:
        return "用水量"
    if has_power:
        return "用电量"
    return "运行指标"


def _detect_analysis_type(context: dict[str, Any]) -> str:
    corpus = _conversation_corpus(context)
    if any(keyword in corpus for keyword in ("降低", "节能", "优化", "改进")):
        return "优化研判"
    if any(keyword in corpus for keyword in ("异常", "排查", "漏损", "漏水", "核查")):
        return "异常排查"
    if any(keyword in corpus for keyword in ("对比", "比较", "趋势")):
        return "对比研判"
    return "运行研判"


def _normalize_business_text(text: str) -> str:
    clean = sanitize_report_markdown(text)
    replacements = [
        ("对话分析结果", "系统监测与研判结果"),
        ("对话分析", "业务研判"),
        ("工具调用", "数据溯源"),
        ("系统设定", "运行规则"),
        ("量化依据", "偏离度分析"),
        ("water_leak", "管网跑冒滴漏"),
        ("work_order", "运维工单"),
        ("Artifact", "监测图表"),
        ("artifact", "监测图表"),
        ("未执行数据溯源", "当前系统暂无相关历史溯源记录"),
        ("未调用工具", "当前系统暂无相关历史溯源记录"),
    ]
    for source, target in replacements:
        clean = clean.replace(source, target)
    for source, target in _BUILDING_DISPLAY.items():
        clean = clean.replace(source, target)
    clean = re.sub(r"\((?:未执行|未调用)[^)]*\)", "当前系统暂无相关历史溯源记录", clean)
    clean = re.sub(r"\b(?:EM|ELE|DEV|METER|FOX)[A-Za-z0-9_:-]{4,}\b", "相关监测点位", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bGB\s*([0-9]{3,6}(?:[-–][0-9]{2,4})?)\b", r"国家相关标准（GB \1）", clean, flags=re.IGNORECASE)
    clean = re.sub(r"(教学楼)(?:[、,，/\s]+教学楼)+", r"\1", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" ，,。;；")
    return clean


def _resolve_report_summary(context: dict[str, Any], draft: ConversationReportDraft) -> str:
    candidate = _first_sentence(draft.report_summary, 96)
    summary = _normalize_business_text(candidate)
    topics = _derive_topics(context)
    if len(topics) >= 2:
        return _build_session_summary(context)
    if summary:
        return summary
    return _build_session_summary(context)


def _build_minutes_title(context: dict[str, Any]) -> str:
    subject = _format_subject(context)
    topics = _derive_topics(context)
    if "节能优化" in topics and any(topic in topics for topic in ("用水管理", "用水排查")):
        topic_label = "节能优化与用水管理"
    elif "用水排查" in topics:
        topic_label = "用水异常排查"
    elif "用水管理" in topics:
        topic_label = "用水管理"
    elif "节能优化" in topics:
        topic_label = "节能优化"
    else:
        topic_label = "运行研判"
    return _truncate(f"【{subject}】{topic_label}会话纪要", 40)


def _resolve_confidence_label(context: dict[str, Any]) -> str:
    score = 0
    if context.get("react_data_summary"):
        score += 1
    if context.get("data_sources"):
        score += 1
    if context.get("artifacts"):
        score += 1
    if score >= 3:
        return "高"
    if score == 2:
        return "中"
    return "待确认"


def _resolve_current_judgement(context: dict[str, Any], draft: ConversationReportDraft, report_summary: str) -> str:
    corpus = _conversation_corpus(context) + " " + sanitize_report_markdown(draft.key_findings) + " " + report_summary
    if any(keyword in corpus for keyword in ("漏水", "漏损", "water_leak", "跑冒滴漏")):
        return "疑似漏损"
    if any(keyword in corpus for keyword in ("异常", "偏高", "超标", "告警")):
        return "存在异常偏离"
    if any(keyword in corpus for keyword in ("节能", "优化", "降低用电")):
        return "具备优化空间"
    return "待进一步核查"


def _resolve_conclusion_status(context: dict[str, Any]) -> str:
    if context.get("artifacts") or context.get("data_sources"):
        return "待现场确认"
    return "待补充数据"


def _build_problem_statement(context: dict[str, Any]) -> str:
    subject = _format_subject(context)
    topics = _derive_topics(context)
    user_corpus = " ".join(context.get("user_questions") or [])
    if "节能优化" in topics and any(topic in topics for topic in ("用水管理", "用水排查")):
        return f"本次会话围绕{subject}运行优化展开，先讨论降低用电量的可行方向，随后延伸至用水管理与排查方向，并形成后续处置建议。"
    if "节能优化" in topics:
        return f"本次会话围绕{subject}节能优化展开，重点研讨降低用电量的可行措施及实施方向。"
    if "用水排查" in topics:
        return f"本次会话围绕{subject}用水情况核查展开，重点判断是否存在异常风险并明确后续处置方向。"
    if "用水管理" in topics:
        return f"本次会话围绕{subject}用水管理展开，重点讨论运行情况判断与改进方向。"
    if user_corpus:
        return f"本次会话围绕{subject}运行情况展开，重点形成业务研判与处置建议。"
    return f"本次会话围绕{subject}运行情况展开，形成了初步研判结论。"


def _build_process_summary(context: dict[str, Any], draft: ConversationReportDraft) -> list[str]:
    subject = _format_subject(context)
    topics = _derive_topics(context)
    process: list[str] = []
    if "节能优化" in topics:
        process.append(f"先围绕{subject}降低用电量的可行方向进行梳理，归纳节能优化措施。")
    if any(topic in topics for topic in ("用水管理", "用水排查")):
        process.append(f"随后将研判范围延伸至{subject}用水情况，结合系统监测信息判断是否存在明显偏离。")
    if context.get("react_data_summary") or context.get("data_sources"):
        process.append("在此基础上结合系统监测日志、历史信息和业务判断，形成当前会话结论。")
    else:
        process.append("在此基础上对会话中已有信息进行归纳整理，形成当前会话结论。")
    return _normalize_business_bullets(process, default="已完成本次会话研判并形成初步结论。")


def _extract_exclusion_statement(context: dict[str, Any]) -> str:
    corpus = " ".join(
        [
            *(context.get("ai_answers") or []),
            str(context.get("react_data_summary") or ""),
            str(context.get("context_summary") or ""),
        ]
    )
    parts = re.split(r"[。；;\n]", corpus)
    explicit_markers = ("不支持", "未见", "不属于", "暂不考虑", "可以排除", "初步排除", "基本排除", "暂不支持")
    for part in parts:
        clean = _normalize_business_text(part)
        if not clean:
            continue
        stripped = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", clean)
        if any(marker in stripped for marker in explicit_markers):
            return _truncate(stripped, 88)
        if (
            "排除" in stripped
            and not any(stripped.startswith(prefix) for prefix in ("核查", "排查", "检查", "复核", "确认"))
        ):
            return _truncate(stripped, 88)
    return "暂无明确排除项，需结合现场复核确认。"


def _build_loss_estimate_text(context: dict[str, Any]) -> str:
    corpus = _conversation_corpus(context)
    highlight = _extract_highlight_value(context)
    has_power = any(keyword in corpus for keyword in ("用电", "电量", "耗电", "能耗"))
    has_water = any(keyword in corpus for keyword in ("用水", "水量", "漏水"))

    if has_power and has_water:
        if "测算" in highlight:
            return "用电优化收益与用水异常损失需分口径测算"
        return f"用水侧异常偏离参考值 {highlight}，用电侧以优化空间研判为主"
    if has_water:
        if "测算" in highlight:
            return "用水异常损失需结合现场复核结果进一步测算"
        return f"用水异常偏离参考值 {highlight}"
    if has_power:
        if "测算" in highlight:
            return "用电优化收益需结合整改前后数据进一步测算"
        return f"用电指标偏离参考值 {highlight}"
    return "需结合现场复核结果进一步测算"


def _build_impact_facts(context: dict[str, Any]) -> list[ReportSummaryItem]:
    corpus = _conversation_corpus(context)
    has_power = any(keyword in corpus for keyword in ("用电", "电量", "耗电", "能耗"))
    has_water = any(keyword in corpus for keyword in ("用水", "水量", "漏水"))

    items = [
        ReportSummaryItem(label="损失预估", value=_build_loss_estimate_text(context)),
        ReportSummaryItem(label="费用影响", value=_extract_money_impact(context)),
        ReportSummaryItem(label="碳排影响", value=_extract_carbon_impact(context)),
    ]
    if has_power and has_water:
        items.append(ReportSummaryItem(label="评估说明", value="建议将用电节能收益与用水异常损失分别核算"))
    return items


def _build_evidence_facts(context: dict[str, Any]) -> list[ReportSummaryItem]:
    corpus = _conversation_corpus(context)
    time_reference = _format_date_range_label(context.get("date_range"))
    if any(keyword in corpus for keyword in ("夜间", "凌晨")):
        time_reference = "夜间/凌晨时段"
    elif any(keyword in corpus for keyword in ("白天", "日间")):
        time_reference = "日间运行时段"

    return [
        ReportSummaryItem(label="异常时段", value=time_reference),
        ReportSummaryItem(label="偏离水平", value=_extract_highlight_value(context)),
    ]


def _extract_highlight_value(context: dict[str, Any]) -> str:
    corpus = " ".join(
        [
            *(context.get("ai_answers") or []),
            str(context.get("react_data_summary") or ""),
            str(context.get("context_summary") or ""),
        ]
    )
    percent_matches = _PERCENT_RE.findall(corpus)
    if percent_matches:
        values = [float(item) for item in percent_matches]
        return f"{max(values):.0f}%"
    value_match = _VALUE_RE.search(corpus)
    if value_match:
        return f"{value_match.group(1)} {value_match.group(2)}"
    return "需结合历史基线进一步测算"


def _build_evidence_basis_markdown(
    context: dict[str, Any],
    draft: ConversationReportDraft,
    report_summary: str,
) -> str | None:
    bullet_candidates = _normalize_business_bullets(
        [
            _normalize_business_text(item)
            for item in _extract_markdown_bullets(draft.key_findings, limit=3)
            if item
        ],
        default="当前系统暂无相关历史溯源记录，需结合现场进一步核验。",
    )
    filtered_bullets = [
        item for item in bullet_candidates
        if not _is_invalid_basis_text(item)
        and not any(keyword in item for keyword in ("排除", "不支持", "未见", "暂不考虑"))
    ]
    if filtered_bullets:
        return _markdown_bullets(filtered_bullets[:2], filtered_bullets[0])

    basis = _best_basis_sentence(context, draft, report_summary)
    clean_basis = _normalize_business_text(basis)
    return clean_basis or None


def _build_evidence_exclusion_markdown(context: dict[str, Any]) -> str | None:
    exclusion = _normalize_business_text(_extract_exclusion_statement(context))
    return exclusion or None


def _build_meeting_evidence(context: dict[str, Any], draft: ConversationReportDraft, report_summary: str) -> list[ReportSummaryItem]:
    return _build_evidence_facts(context)


def _build_impact_highlights(context: dict[str, Any]) -> list[ReportSummaryItem]:
    return _build_impact_facts(context)


def _build_overview_items(context: dict[str, Any], generated_at: str) -> list[ReportSummaryItem]:
    topic_label = "、".join(_derive_topics(context))
    return [
        ReportSummaryItem(label="会话主题", value=topic_label),
        ReportSummaryItem(label="发起角色", value="能源管理员"),
        ReportSummaryItem(label="涉及对象", value=_format_subject(context)),
        ReportSummaryItem(label="研判时间", value=generated_at),
    ]


def _build_conclusion_text(context: dict[str, Any], report_summary: str, current_judgement: str) -> str:
    summary = _normalize_business_text(report_summary).rstrip("。")
    if current_judgement and current_judgement not in summary:
        return f"本次会话研判认为，{summary}。当前判断为{current_judgement}。"
    return f"本次会话研判认为，{summary}。"


def _build_llm_context(context: dict[str, Any]) -> str:
    transcript_lines: list[str] = []
    for role, content in context["turns"][-12:]:
        prefix = "用户" if role == "user" else "AI"
        transcript_lines.append(f"{prefix}: {_truncate(content, 240)}")

    date_range = context["date_range"]
    date_range_label = f"{date_range['start']} ~ {date_range['end']}" if date_range else "未明确"
    return "\n".join(
        [
            f"会话标题: {context['session_title']}",
            f"涉及对象: {_format_subject(context)}",
            f"时间范围: {date_range_label}",
            f"会话主题: {'、'.join(_derive_topics(context))}",
            f"全部用户问题: {'；'.join(context.get('user_questions') or []) or '无'}",
            f"全部AI结论: {'；'.join(_truncate(item, 120) for item in (context.get('ai_answers') or [])[-4:]) or '无'}",
            "",
            "上下文摘要:",
            context["context_summary"] or "无",
            "",
            "系统监测与数据摘要:",
            context["react_data_summary"] or "无",
            "",
            "最近会话片段:",
            "\n".join(transcript_lines) or "无",
        ]
    )


async def _generate_ai_sections(context: dict[str, Any], thinking_mode: str) -> ConversationReportDraft:
    llm = _build_report_llm(thinking_mode)
    prompt = (
        "你是建筑能源管理场景中的正式会议纪要撰写助手。\n"
        "请基于输入事实总结整个会话，不得只概括最后一轮追问。\n"
        "如果用户连续追问属于同一主题，必须合并成完整业务意图。\n"
        "禁止直接引用口语化原话，例如“那对于xxx呢”。必须转写成书面化业务描述。\n"
        "禁止输出未调用工具、未执行、artifact、报错、traceback 等程序运行状态词。\n"
        "report_title 要简洁正式，不要包含内部英文变量名，不要把日期直接拼进主标题。\n"
        "report_summary 要概括整个会话形成的主要结论。\n"
        "executive_summary、key_findings、recommendations、risks_and_open_questions 使用 markdown 列表。\n"
        "recommendations 必须是可执行动作，risks_and_open_questions 必须保留待确认边界。\n"
        "只能依据输入事实，不得编造数据。"
    )
    return await llm.ainvoke(prompt + "\n\n" + _build_llm_context(context))


def _build_management_brief_payload(
    context: dict[str, Any],
    req: ConversationReportRequest,
    report_draft: ConversationReportDraft,
) -> ConversationReportPayload:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_title = _build_minutes_title(context)
    report_summary = _resolve_report_summary(context, report_draft)
    actions = _normalize_business_bullets(
        _extract_markdown_bullets(report_draft.recommendations, limit=3),
        default="建议先完成现场复核，再推进后续处置。",
    )
    open_questions = _normalize_business_bullets(
        _extract_markdown_bullets(report_draft.risks_and_open_questions, limit=3),
        default="当前结论仍需结合现场复核进一步确认。",
    )
    process_summary = _build_process_summary(context, report_draft)
    current_judgement = _resolve_current_judgement(context, report_draft, report_summary)
    conclusion_status = _resolve_conclusion_status(context)
    evidence_facts = _build_evidence_facts(context)
    evidence_basis_markdown = _build_evidence_basis_markdown(context, report_draft, report_summary)
    evidence_exclusion_markdown = _build_evidence_exclusion_markdown(context)
    impact_facts = _build_impact_highlights(context)
    formal_meta = FormalReportMeta(
        severity=_resolve_severity(context, report_draft),
        confidence=_resolve_confidence_label(context),
        decisionSummary=report_summary,
        currentJudgement=current_judgement,
        conclusionStatus=conclusion_status,
        overviewItems=_build_overview_items(context, generated_at),
        processSummary=process_summary,
        keyMetrics=_build_key_metrics(context, report_summary, report_draft),
        evidenceFacts=evidence_facts,
        evidenceBasisMarkdown=evidence_basis_markdown,
        evidenceExclusionMarkdown=evidence_exclusion_markdown,
        evidenceHighlights=evidence_facts,
        impactFacts=impact_facts,
        impactHighlights=impact_facts,
        actions=actions,
        openQuestions=open_questions,
        primaryArtifact=_select_primary_artifact(context["artifacts"]),
    )

    sections: list[ReportSection] = [
        ReportSection(
            id="conversation-problem-statement",
            namespace="conversation-report",
            title="发起问题",
            type="text",
            content=_build_problem_statement(context),
            contentFormat="plain",
            order=10,
        ),
        ReportSection(
            id="conversation-process-summary",
            namespace="conversation-report",
            title="研判过程摘要",
            type="text",
            content=_markdown_bullets(process_summary, "- 已完成本次会话研判。"),
            contentFormat="markdown",
            order=20,
        ),
        ReportSection(
            id="conversation-conclusion",
            namespace="conversation-report",
            title="会话结论",
            type="text",
            content=_build_conclusion_text(context, report_summary, current_judgement),
            contentFormat="plain",
            order=30,
        ),
        ReportSection(
            id="conversation-recommendations",
            namespace="conversation-report",
            title="建议动作",
            type="text",
            content=_markdown_bullets(actions, "- 建议先完成现场复核，再推进后续处置。"),
            contentFormat="markdown",
            order=40,
        ),
        ReportSection(
            id="conversation-risks",
            namespace="conversation-report",
            title="待确认事项",
            type="text",
            content=_markdown_bullets(open_questions, "- 当前暂无额外待确认事项。"),
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
                content=_build_appendix_content(context["turns"]),
                contentFormat="markdown",
                order=70,
            )
        )

    cover_subject = _format_subject(context)
    return ConversationReportPayload(
        title=report_title,
        subtitle=report_summary,
        generatedAt=generated_at,
        buildingName=cover_subject or None,
        dateRange=context["date_range"],
        sections=sections,
        mode=req.mode,
        generatedBy="系统辅助生成",
        template_id=DEFAULT_REPORT_TEMPLATE_ID,
        template_label="AI辅助研判会话纪要",
        formalMeta=formal_meta,
    )


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

    generation_mode = req.generation_mode
    raw_artifacts = list(state.get("artifacts", [])) if req.artifact_policy == "all" else []
    artifacts = _stable_unique_artifacts(raw_artifacts)
    react_data_summary = state.get("react_data_summary") or build_data_summary(messages)
    chart_manifest = ""
    if generation_mode != "rules":
        chart_manifest = state.get("chart_manifest") or build_chart_manifest(raw_artifacts)
    user_questions = _collect_turn_texts(turns, "user")
    ai_answers = _collect_turn_texts(turns, "ai")

    context: dict[str, Any] = {
        "session_id": session_id,
        "session_title": session_title or "AI 对话会话纪要",
        "session_building": state.get("building_id"),
        "turns": turns,
        "user_turn_count": user_turn_count,
        "ai_turn_count": ai_turn_count,
        "user_questions": user_questions,
        "ai_answers": ai_answers,
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

    if generation_mode == "rules":
        report_draft = _build_fallback_sections(context)
    else:
        try:
            # Report generation is a fixed-format summarization task; always use fast mode
            # instead of inheriting the chat session's deep reasoning mode.
            thinking_mode = "fast"
            report_draft = await _generate_ai_sections(context, thinking_mode)
        except Exception:
            if generation_mode == "backend_ai":
                raise
            report_draft = _build_fallback_sections(context)

    _REPORT_TEMPLATES[DEFAULT_REPORT_TEMPLATE_ID] = ReportTemplateDefinition(
        id=DEFAULT_REPORT_TEMPLATE_ID,
        label="AI辅助研判会话纪要",
        description="围绕一次会话形成问题、过程、结论与行动项的正式纪要模板。",
        audience="management",
        build_payload=_build_management_brief_payload,
    )
    template = _get_report_template(req.template_id)
    return template.build_payload(context, req, report_draft)
