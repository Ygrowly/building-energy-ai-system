from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ReportSummaryItem(BaseModel):
    label: str
    value: str


class ReportTableColumn(BaseModel):
    key: str
    label: str
    align: Literal["left", "right", "center"] | None = None


class ReportSection(BaseModel):
    id: str
    namespace: str
    title: str
    description: str | None = None
    type: Literal["kpi", "table", "chart", "text", "summary", "artifact"]
    kpis: list[dict[str, Any]] | None = None
    columns: list[ReportTableColumn] | None = None
    rows: list[dict[str, Any]] | None = None
    chartImage: str | None = None
    summaryItems: list[ReportSummaryItem] | None = None
    content: str | None = None
    contentFormat: Literal["plain", "markdown"] | None = None
    artifact: dict[str, Any] | None = None
    order: int | None = None


class FormalReportMeta(BaseModel):
    severity: str | None = None
    confidence: str | None = None
    decisionSummary: str | None = None
    currentJudgement: str | None = None
    conclusionStatus: str | None = None
    overviewItems: list[ReportSummaryItem] = Field(default_factory=list)
    processSummary: list[str] = Field(default_factory=list)
    keyMetrics: list[ReportSummaryItem] = Field(default_factory=list)
    evidenceFacts: list[ReportSummaryItem] = Field(default_factory=list)
    evidenceBasisMarkdown: str | None = None
    evidenceExclusionMarkdown: str | None = None
    evidenceHighlights: list[ReportSummaryItem] = Field(default_factory=list)
    impactFacts: list[ReportSummaryItem] = Field(default_factory=list)
    impactHighlights: list[ReportSummaryItem] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    openQuestions: list[str] = Field(default_factory=list)
    primaryArtifact: dict[str, Any] | None = None


class ConversationReportRequest(BaseModel):
    mode: Literal["snapshot", "formal"] = "formal"
    generation_mode: Literal["hybrid", "backend_ai", "rules"] = "hybrid"
    artifact_policy: Literal["all", "none"] = "all"
    include_appendix: bool = False
    template_id: str | None = None


class ConversationReportPayload(BaseModel):
    title: str
    subtitle: str | None = None
    generatedAt: str
    buildingName: str | None = None
    dateRange: dict[str, str] | None = None
    sections: list[ReportSection]
    mode: Literal["snapshot", "formal"]
    generatedBy: str | None = None
    template_id: str | None = None
    template_label: str | None = None
    formalMeta: FormalReportMeta | None = None
