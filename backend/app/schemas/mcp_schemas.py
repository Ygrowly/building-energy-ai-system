"""
阶段一：接口契约 —— MCP 工具出入参规范（8 个核心工具）
==========================================================
所有工具参数必须通过 Pydantic v2 严格校验，禁止裸 dict 传参。
工具报错时不抛 Exception，统一返回 MCPError 结构（让大模型读懂并自我修正）。

工具清单：
  1. query_energy_metrics        ← 能耗时序数据查询
  2. get_device_live_status      ← 设备实时状态快照
  3. calculate_system_cop        ← 空调能效比 COP 计算
  4. query_daily_energy_summary  ← 按天/周/月聚合趋势（granularity 参数）
  5. rag_hybrid_search           ← 混合检索运维手册
  6. detect_energy_anomalies     ← 基于规则的异常检测
  7. render_ui_component         ← 生成前端组件 JSON 指令
  8. create_work_order_draft     ← 生成工单草稿（需人工审批）
  9. list_available_buildings    ← 列出所有楼宇（动态校验白名单）
 10. compare_metric_across_buildings ← 多楼宇横向对比（含能耗强度）
 11. compare_time_periods        ← 同环比分析（period_a vs period_b）
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ===========================================================================
# 公共枚举与类型
# ===========================================================================

class BuildingID(str, Enum):
    """
    已知 building_type 参考枚举（仅作文档用途）。
    工具输入参数统一使用 str 类型 + 数据库层动态校验，
    新增楼宇后无需修改代码，重启应用即自动生效。
    对应 meter_device_id：Education→M-EDU-001, Office→M-OFF-001, Public→M-PUB-001
    """
    EDUCATION = "Education"
    OFFICE = "Office"
    PUBLIC = "Public"


class MetricType(str, Enum):
    """
    energy_data 表中的真实列名映射，杜绝大模型编造列名。
    hvac 字段说明：
      - hvac_energy_kwh      → 空调系统总能耗
      - hvac_supply_temp_c   → 供水温度（冷冻水送水端）
      - hvac_return_temp_c   → 回水温度（冷冻水回水端）
    COP 由后端计算，不直接暴露给大模型。
    """
    ELECTRICITY_KWH = "electricity_kwh"
    WATER_M3 = "water_m3"
    HVAC_ENERGY_KWH = "hvac_energy_kwh"
    HVAC_SUPPLY_TEMP_C = "hvac_supply_temp_c"
    HVAC_RETURN_TEMP_C = "hvac_return_temp_c"
    AMBIENT_TEMP_C = "ambient_temp_c"
    HUMIDITY_RH_PCT = "humidity_rh_pct"
    OCCUPANCY_DENSITY = "occupancy_density_per_100sqm"


class OperationStatus(str, Enum):
    """energy_data.operation_status 枚举值，与 DB 枚举类型 operation_status_enum 一致。"""
    NORMAL = "Normal"
    ANOMALY = "Anomaly"


class AnomalyRule(str, Enum):
    """detect_energy_anomalies 支持的检测规则白名单。"""
    NIGHT_HIGH_POWER = "night_high_power"           # 夜间(0-6点)功率 > 50kW
    ZERO_OCC_HIGH_HVAC = "zero_occupancy_high_hvac"  # 无人 + 空调高耗电
    SENSOR_SPIKE = "sensor_spike"                   # 传感器数值跳变（疑似故障）


class WorkOrderPriority(str, Enum):
    """工单优先级。"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ===========================================================================
# 公共结构
# ===========================================================================

class TimeRange(BaseModel):
    """时间范围，TIMESTAMPTZ 精度，end 必须晚于 start。"""
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def end_after_start(self) -> "TimeRange":
        if self.end <= self.start:
            raise ValueError(
                f"time_range.end ({self.end}) 必须晚于 time_range.start ({self.start})"
            )
        return self


class MCPError(BaseModel):
    """
    工具级别错误的统一返回格式。
    大模型收到此结构后可读取 message 并自我修正调用参数，而非触发系统崩溃。
    """
    error: str = Field(description="自然语言错误描述，供 LLM 自我修正")
    error_code: str = Field(description="机器可读错误码，如 'BUILDING_NOT_FOUND'")
    tool_name: str = Field(description="触发错误的工具名，如 'query_energy_metrics'")


# ===========================================================================
# Tool 1：query_energy_metrics — 能耗时序数据查询
# ===========================================================================

class QueryEnergyMetricsInput(BaseModel):
    """
    查询 energy_data 超表中指定建筑、时间段、指标的原始读数。
    building_id 为 buildings.building_type 的值（如 'Education'/'Office'/'Public'），
    由数据库层动态校验，新增楼宇无需修改代码。
    """
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public'，由数据库动态校验"
    )
    time_range: TimeRange
    metrics: list[MetricType] = Field(min_length=1, description="至少指定一个指标")


class EnergyMetricRecord(BaseModel):
    """单条时序读数，携带数据血缘溯源信息。"""
    timestamp: datetime
    building_id: str
    metric: MetricType
    value: float
    unit: str = Field(description="如 'kWh', 'm³', '°C'")
    meter_device_id: str = Field(description="如 'M-EDU-001'，来自 buildings 表")
    source_table: Literal["energy_data"] = "energy_data"


class QueryEnergyMetricsOutput(BaseModel):
    records: list[EnergyMetricRecord]
    total_count: int
    building_id: str
    meter_device_id: str
    source_table: Literal["energy_data"] = "energy_data"


# ===========================================================================
# Tool 2：get_device_live_status — 设备实时状态快照
# ===========================================================================

class GetDeviceLiveStatusInput(BaseModel):
    """
    通过 meter_device_id 查询 energy_data 最新 1 条记录（按 timestamp DESC）。
    device_id 必须符合 M-XXX-NNN 格式，防止非法查询。
    """
    meter_device_id: str = Field(
        pattern=r"^M-(EDU|OFF|PUB)-\d{3}$",
        description="如 'M-OFF-001'，格式必须符合 M-{类型}-{编号}"
    )


class GetDeviceLiveStatusOutput(BaseModel):
    """设备最新传感器快照，含运行状态枚举（与 DB 一致）。"""
    meter_device_id: str
    operation_status: OperationStatus
    ambient_temp_c: float
    humidity_rh_pct: float
    electricity_kwh: float
    occupancy_density_per_100sqm: float
    last_updated_utc: datetime
    source_table: Literal["energy_data"] = "energy_data"


# ===========================================================================
# Tool 3：calculate_system_cop — 空调能效比 COP 计算
# ===========================================================================

class CalculateSystemCOPInput(BaseModel):
    """
    基于 energy_data 表中 hvac_energy_kwh（空调总能耗）与供回水温差
    （hvac_supply_temp_c / hvac_return_temp_c）估算制冷效率指标。
    物理异常捕获：若 hvac_energy_kwh ≈ 0 但温差较大，
    后端抛出 MCPError(error_code='SENSOR_FAULT_DIVIDE_BY_ZERO')，不进行计算。
    """
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public'，由数据库动态校验"
    )
    time_range: TimeRange


class CalculateSystemCOPOutput(BaseModel):
    """COP 计算结果，含 ASHRAE 90.1 基准比对。"""
    building_id: str
    cop_mean: float = Field(description="时间段内平均 COP")
    cop_min: float
    cop_max: float
    ashrae_baseline: float = Field(default=3.0, description="ASHRAE 90.1 标准基准值")
    is_below_baseline: bool = Field(description="低于基准则需关注，True=需告警")
    period_start: datetime
    period_end: datetime
    data_points_used: int = Field(ge=1)
    source_table: Literal["energy_data"] = "energy_data"


# ===========================================================================
# Tool 4：query_daily_energy_summary — 按天聚合趋势
# ===========================================================================

class QueryDailyEnergySummaryInput(BaseModel):
    """
    按天/周/月汇总 energy_data 表中的能耗数据。
    granularity='day' 时查物化视图（极速），week/month 时直查 energy_data 用 date_trunc 聚合。
    """
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public'，由数据库动态校验"
    )
    date_range: TimeRange
    granularity: Literal["day", "week", "month"] = Field(
        default="day",
        description="聚合粒度：day 按天 / week 按自然周 / month 按自然月"
    )


class DailyEnergySummaryRecord(BaseModel):
    """
    按天汇总记录，字段与物化视图 daily_energy_summary 列名严格一一对应。
    视图定义：
      SELECT date_trunc('day', timestamp) AS day, building_id,
             SUM(electricity_kwh) AS total_electricity_kwh,
             AVG(ambient_temp_c)  AS avg_ambient_temp,
             MAX(occupancy_density_per_100sqm) AS max_occupancy
      FROM energy_data GROUP BY day, building_id;
    """
    day: str = Field(description="日期截断结果，如 '2023-10-25 00:00:00+00'")
    building_id: str
    total_electricity_kwh: float
    avg_ambient_temp: float = Field(description="当天平均环境温度（°C）")
    max_occupancy: float = Field(description="当天最高人员密度（人/100㎡）")


class QueryDailyEnergySummaryOutput(BaseModel):
    records: list[DailyEnergySummaryRecord]
    building_id: str
    source_view: Literal["daily_energy_summary"] = "daily_energy_summary"
    base_table: Literal["energy_data"] = "energy_data"
    query_ms: Optional[int] = Field(default=None, description="物化视图查询耗时（毫秒）")


# ===========================================================================
# Tool 5：rag_hybrid_search — 混合检索运维手册
# ===========================================================================

class MetadataFilter(BaseModel):
    """
    元数据硬过滤：先用 device_id 过滤掉 90% 无关文档，再做向量检索。
    全部字段可选，不传则不过滤（范围检索模式）。
    """
    device_id: Optional[str] = Field(default=None, description="如 'M-OFF-001'")
    building_type: Optional[str] = Field(default=None, description="如 'Office'")
    doc_category: Optional[str] = Field(default=None, description="如 'maintenance_manual'")


class RAGHybridSearchInput(BaseModel):
    """
    混合检索：元数据硬过滤 → 向量召回 Top-20 → BGE-Reranker 精排 → 返回 Top-K。
    enable_rerank=True 时触发 BGE-Reranker，enable_rerank=False 时仅向量检索（速度优先）。
    """
    query: str = Field(min_length=1, description="用户问题或故障描述")
    metadata_filter: MetadataFilter = Field(default_factory=MetadataFilter)
    enable_rerank: bool = Field(default=True, description="是否启用语义重排序")
    top_k: int = Field(default=3, ge=1, le=10, description="最终返回文档数量")


class RAGSearchResult(BaseModel):
    """单条检索结果，含父子索引的章节信息，防止断章取义。"""
    content: str = Field(description="匹配的段落原文")
    parent_section: str = Field(description="父章节标题，如 '4.2 常见故障排除'")
    source_doc: str = Field(description="如 'Chiller_Maintenance_Manual_V2.pdf'")
    page: int = Field(ge=1)
    similarity: float = Field(ge=0.0, le=1.0, description="向量相似度")
    rerank_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="重排序分数")


class RAGHybridSearchOutput(BaseModel):
    results: list[RAGSearchResult]
    query: str
    total_retrieved: int = Field(description="向量召回的总数量（精排前）")
    reranked: bool


# ===========================================================================
# Tool 6：detect_energy_anomalies — 基于规则的异常检测
# ===========================================================================

class DetectEnergyAnomaliesInput(BaseModel):
    """
    基于物理规则的异常检测，严禁让大模型自己做阈值判断。
    rules 白名单确保只运行已定义的检测逻辑。
    """
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public'，由数据库动态校验"
    )
    time_range: TimeRange
    rules: list[AnomalyRule] = Field(
        default=[AnomalyRule.NIGHT_HIGH_POWER, AnomalyRule.ZERO_OCC_HIGH_HVAC, AnomalyRule.SENSOR_SPIKE],
        min_length=1
    )


class AnomalyRecord(BaseModel):
    """单条异常记录，携带足够信息供 Diagnose Agent 做后续归因。"""
    timestamp: datetime
    building_id: str
    meter_device_id: str
    rule_triggered: AnomalyRule
    actual_value: float
    threshold_value: float
    duration_hours: Optional[float] = Field(default=None, description="持续时长（小时）")
    operation_status: OperationStatus


class DetectEnergyAnomaliesOutput(BaseModel):
    anomalies: list[AnomalyRecord]
    total_anomalies: int = Field(ge=0)
    building_id: str
    period_start: datetime
    period_end: datetime
    source_table: Literal["energy_data"] = "energy_data"


# ===========================================================================
# Tool 7：render_ui_component — 生成前端组件 JSON 指令
# ===========================================================================

class RenderUIComponentInput(BaseModel):
    """
    Action Agent 调用此工具，生成结构化 JSON 指令推送给前端。
    前端收到后，拦截 JSON 并渲染对应 Vue 组件，而非显示纯文本。
    """
    component_type: Literal["LineChart", "BarChart", "Gauge", "WorkOrderCard"]
    title: str
    data_payload: dict[str, Any] = Field(description="组件所需的结构化数据")
    source_info: Optional[dict[str, Any]] = Field(
        default=None,
        description="审计溯源信息，用于'🔍 数据来源'浮层"
    )


class RenderUIComponentOutput(BaseModel):
    artifact_id: str = Field(description="唯一标识，前端用于绑定审批回调")
    widget: str
    status: Literal["rendered"] = "rendered"


# ===========================================================================
# Tool 8：create_work_order_draft — 生成工单草稿（Human-in-the-loop 核心）
# ===========================================================================

class CreateWorkOrderDraftInput(BaseModel):
    """
    Human-in-the-loop 核心工具。
    此工具绝不直接写入生产数据库，只生成草稿并触发前端审批卡片。
    用户点击"批准"后，前端才发出真正的派单 API 请求。
    """
    device_id: str = Field(
        pattern=r"^M-[A-Z]+-\d{3}$",
        description="如 'M-OFF-001'，格式：M-{类型缩写}-{编号}"
    )
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public'，由数据库动态校验"
    )
    issue_description: str = Field(min_length=10, description="故障描述，至少 10 字")
    suggested_action: str = Field(min_length=5, description="建议处置动作")
    priority: WorkOrderPriority
    evidence_timestamp: Optional[datetime] = Field(
        default=None,
        description="异常发生时间，作为工单的时间证据"
    )


class CreateWorkOrderDraftOutput(BaseModel):
    """工单草稿。status 固定为 'pending_approval'，前端渲染黄色待审批卡片。"""
    status: Literal["pending_approval"] = "pending_approval"
    ticket_id: str = Field(description="临时工单 ID，如 'temp_abc123'")
    device_id: str
    building_id: str
    priority: WorkOrderPriority
    issue_description: str
    suggested_action: str
    created_at: datetime
    requires_human_approval: Literal[True] = True
    ui_hint: Literal["render_work_order_card"] = "render_work_order_card"


# ===========================================================================
# Tool 9：list_available_buildings — 列举当前数据库中所有楼宇
# ===========================================================================

class BuildingInfo(BaseModel):
    """单栋建筑的基本信息，用于向 Agent 动态告知合法 building_id。"""
    building_id: str = Field(description="数据库中的实际主键，如 'Bobcat_office_Kassandra'")
    building_type: str = Field(description="类型标签，工具传参时使用此值，如 'Office'")
    meter_device_id: str = Field(description="仪表设备 ID，如 'M-OFF-001'")
    sqm: Optional[float] = Field(default=None, description="建筑面积（平方米）")


class ListBuildingsOutput(BaseModel):
    """当前数据库中所有建筑的清单，Agent 路由前可先调用此工具确认合法 building_type。"""
    buildings: list[BuildingInfo]
    total: int


# ===========================================================================
# Tool 10：compare_metric_across_buildings — 多楼宇同一指标横向对比
# ===========================================================================

class CompareMetricAcrossBuildingsInput(BaseModel):
    """
    对多栋楼在同一时间段内的同一指标进行横向统计对比。
    解决"A 楼和 B 楼的平均湿度差多少"这类跨楼问题。
    building_ids 不传时自动对比数据库中所有楼宇。
    aggregation 支持：avg（平均）、sum（总量）、max（峰值）、min（最低值）。
    """
    building_ids: list[str] = Field(
        default_factory=list,
        description="要对比的建筑类型列表，如 ['Office', 'Education']；为空则对比所有建筑"
    )
    time_range: TimeRange
    metric: MetricType
    aggregation: Literal["avg", "sum", "max", "min"] = Field(
        default="avg",
        description="聚合方式：avg 平均 / sum 总量 / max 峰值 / min 最低"
    )


class BuildingMetricStats(BaseModel):
    """单栋楼的聚合统计结果，含能耗强度（当 metric=electricity_kwh 时有值）。"""
    building_type: str
    meter_device_id: str
    aggregated_value: float
    unit: str
    data_points: int = Field(description="参与统计的数据点数量")
    sqm: float | None = Field(default=None, description="建筑面积（㎡）")
    energy_intensity_kwh_per_sqm: float | None = Field(
        default=None,
        description="能耗强度（kWh/㎡），仅 metric=electricity_kwh 时有值"
    )


class CompareMetricAcrossBuildingsOutput(BaseModel):
    """多楼宇横向对比结果，按 aggregated_value 降序排列。"""
    metric: MetricType
    aggregation: str
    results: list[BuildingMetricStats]
    period_start: datetime
    period_end: datetime
    source_table: Literal["energy_data"] = "energy_data"


# ===========================================================================
# Tool 11：compare_time_periods — 同环比分析
# ===========================================================================

class CompareTimePeriodsInput(BaseModel):
    """
    对同一建筑、同一指标，在两个时间段（period_a vs period_b）之间做同环比分析。
    典型场景：
      · "本周 vs 上周办公楼用电对比"
      · "4月 vs 3月教学楼平均湿度变化"
      · "今日 vs 昨日公共楼峰值功率"
    """
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public'"
    )
    metric: MetricType
    period_a: TimeRange = Field(description="当期（较新的时间段，如本周）")
    period_b: TimeRange = Field(description="基期（较旧的时间段，如上周）")
    aggregation: Literal["avg", "sum", "max", "min"] = Field(
        default="avg",
        description="聚合方式：avg 平均 / sum 总量 / max 峰值 / min 最低"
    )


class CompareTimePeriodsOutput(BaseModel):
    """同环比分析结果。"""
    building_id: str
    metric: MetricType
    aggregation: str
    unit: str
    period_a_label: str = Field(description="当期标签，如 '2016-04-25 ~ 2016-05-02'")
    period_b_label: str = Field(description="基期标签，如 '2016-04-18 ~ 2016-04-25'")
    period_a_value: float
    period_b_value: float
    delta: float = Field(description="绝对变化量：period_a - period_b")
    delta_pct: float | None = Field(
        default=None,
        description="相对变化率（%）：(a-b)/b * 100，period_b=0 时为 None"
    )
    data_points_a: int
    data_points_b: int
    source_table: Literal["energy_data"] = "energy_data"
