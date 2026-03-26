"""
阶段一：接口契约 —— MCP 工具出入参规范（12 个核心工具）
==========================================================
所有工具参数必须通过 Pydantic v2 严格校验，禁止裸 dict 传参。
工具报错时不抛 Exception，统一返回 MCPError 结构（让大模型读懂并自我修正）。

数据库四层架构对应：
  buildings（楼宇静态元数据，含 timezone）
  devices（计量设备/传感器，1:N 关联 buildings）
  energy_data（时序能耗事实表，直接外键关联 buildings）
  anomaly_events（异常事件业务表，含运维闭环 is_resolved）

工具清单：
  1. query_energy_metrics        ← 能耗时序数据查询
  2. get_device_live_status      ← 设备实时状态快照
  3. calculate_system_cop        ← 空调能效比 COP 计算
  4. query_daily_energy_summary  ← 按天/周/月聚合趋势（granularity 参数）
  5. rag_hybrid_search           ← 混合检索运维手册（device_id 元数据精准过滤）
  6. detect_energy_anomalies     ← 基于规则的异常检测
  7. render_ui_component         ← 生成前端组件 JSON 指令
  8. create_work_order_draft     ← 生成工单草稿（需人工审批）
  9. list_available_buildings    ← 列出所有楼宇及其设备（动态校验白名单）
 10. compare_metric_across_buildings ← 多楼宇横向对比（含能耗强度 kWh/㎡）
 11. compare_time_periods        ← 同环比分析（period_a vs period_b）
 12. generate_report             ← 生成统计报表 CSV 下载链接
"""

from __future__ import annotations

from datetime import datetime, timezone
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
    building_id（数据库内部）→ building_type（工具参数）：
      Fox_education_Louie → Education
      Fox_office_Alice    → Office
      Fox_public_Henry    → Public services
    """
    EDUCATION = "Education"
    OFFICE = "Office"
    PUBLIC = "Public services"


class MetricType(str, Enum):
    """
    energy_data 表中的真实列名映射，杜绝大模型编造列名。
    以 Supabase 实际 schema 为准：
      - hac_energy        → 暖通空调综合能耗（Heating/Air-Conditioning）
      - sim_supply_temp_c → 模拟供水温度（送水端）
      - sim_return_temp_c → 模拟回水温度（回水端）
    COP 由后端计算，不直接暴露给大模型。
    """
    ELECTRICITY_KWH = "electricity_kwh"
    WATER_M3 = "water_m3"
    HAC_ENERGY = "hac_energy"
    SIM_SUPPLY_TEMP_C = "sim_supply_temp_c"
    SIM_RETURN_TEMP_C = "sim_return_temp_c"
    AIR_TEMP_C = "air_temp_c"
    DEW_TEMP_C = "dew_temp_c"
    HUMIDITY_RH_PCT = "humidity_rh_pct"


class OperationStatus(str, Enum):
    """设备运行状态（由 anomaly_events 表推断）。"""
    NORMAL = "Normal"
    ANOMALY = "Anomaly"


class AnomalyRule(str, Enum):
    """
    detect_energy_anomalies 支持的检测规则白名单（双阈值 GB 物理规则）。

    GB 规则 — 基于国标期望值的相对+绝对双阈值：
      water_leak            → 水耗偏差 > 20% 且 > 1.0 m³（管网漏水/异常用水）
      electricity_overload  → 总电耗偏差 > 15% 且 > 5 kWh（异常高电耗）
      hvac_overconsumption  → 空调能耗偏差 > 20% 且 > 20 kWh（空调系统过耗）

    HVAC 根因规则（第二层，仅当 hvac_overconsumption 触发后附加输出）：
      hvac_A_low_efficiency → 主机效能衰退（供水温度偏离期望 > 1.5℃）
      hvac_B_small_deltaT   → 水力失调/大流量小温差（供回水温差 < 3℃）
      hvac_C_unexpected_on  → 非预期开机（负荷率 ≤ 0.05 但空调仍运行）
    """
    # ── GB 物理双阈值规则（主要检测层）────────────────────────────────────
    WATER_LEAK = "water_leak"
    ELECTRICITY_OVERLOAD = "electricity_overload"
    HVAC_OVERCONSUMPTION = "hvac_overconsumption"

    # ── HVAC 根因诊断规则（第二层，附加到 hvac_overconsumption 记录上）──
    HVAC_A_LOW_EFFICIENCY = "hvac_A_low_efficiency"
    HVAC_B_SMALL_DELTA_T = "hvac_B_small_deltaT"
    HVAC_C_UNEXPECTED_ON = "hvac_C_unexpected_on"

    # ── 旧规则（已废弃，仅用于读取历史数据）────────────────────────────
    NIGHT_HIGH_POWER = "night_high_power"
    HIGH_HAC_ENERGY = "high_hac_energy"
    SENSOR_SPIKE = "sensor_spike"


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
    def _normalize(self) -> "TimeRange":
        # LLM 传入的 datetime 可能不带时区，强制标记为 UTC
        # 避免 PostgreSQL 用服务器本地时区解释 naive datetime
        if self.start.tzinfo is None:
            self.start = self.start.replace(tzinfo=timezone.utc)
        if self.end.tzinfo is None:
            self.end = self.end.replace(tzinfo=timezone.utc)
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
    building_id 为 buildings.building_type 的值（如 'Education'/'Office'/'Public services'），
    由数据库层动态校验，新增楼宇无需修改代码。
    """
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public services'，由数据库动态校验"
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
    meter_device_id: str = Field(description="如 'EM_ELE_Fox_education_Louie'，来自 devices 表")
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
    通过 building_type（primary_space_usage，如 'Office'）查询该楼宇所有设备的实时状态。
    数据来自 device_status_latest 表；若该表暂无记录则降级返回 devices 表的设备清单。
    """
    building_type: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public services'，由数据库动态校验"
    )


class DeviceLiveStatus(BaseModel):
    """单台设备的实时状态快照（来自 device_status_latest 表）。"""
    device_id: str = Field(description="设备唯一标识，如 'EM_AC_Fox_office_Alice'")
    device_type: str = Field(description="设备类型：electricity / water / ac")
    online_status: Optional[str] = Field(default=None, description="在线状态：online / offline / unknown")
    running_state: Optional[str] = Field(default=None, description="运行状态：running / idle / fault")
    health_status: Optional[str] = Field(default=None, description="健康状态：normal / warning / critical")
    latest_power_kw: Optional[float] = Field(default=None, description="最新功率（kW），ac 设备适用")
    latest_flow_rate: Optional[float] = Field(default=None, description="最新流量，water 设备适用")
    latest_supply_temp_c: Optional[float] = Field(default=None, description="供水温度（℃），ac 设备适用")
    latest_return_temp_c: Optional[float] = Field(default=None, description="回水温度（℃），ac 设备适用")
    last_seen_at: Optional[datetime] = Field(default=None, description="最后更新时间（UTC）")


class GetDeviceLiveStatusOutput(BaseModel):
    """楼宇下所有设备的实时状态列表。"""
    building_type: str
    building_id: str
    devices: list[DeviceLiveStatus]
    total: int
    has_live_data: bool = Field(description="True=来自 device_status_latest；False=降级为 devices 表静态清单")
    source_table: str = Field(default="device_status_latest")


# ===========================================================================
# Tool 3：calculate_system_cop — 空调能效比 COP 计算
# ===========================================================================

class CalculateSystemCOPInput(BaseModel):
    """
    基于 energy_data 表中 hac_energy（暖通空调综合能耗）与供回水温差
    （sim_supply_temp_c / sim_return_temp_c）估算制冷效率指标。
    物理异常捕获：若 hac_energy ≈ 0 但温差较大，
    后端抛出 MCPError(error_code='SENSOR_FAULT_DIVIDE_BY_ZERO')，不进行计算。
    """
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public services'，由数据库动态校验"
    )
    time_range: TimeRange


class CalculateSystemCOPOutput(BaseModel):
    """
    COP 计算结果，基于 GB 50189-2015 国标进行基准对比。
    hvac_mode 由平均气温推断：Cooling / Heating / Mixed（过渡季）。
    """
    building_id: str
    cop_mean: float = Field(description="时间段内平均 COP（代理指标）")
    cop_min: float
    cop_max: float
    hvac_mode: str = Field(description="推断的 HVAC 工况：Cooling / Heating / Mixed")
    # 国标基准 — GB 50189-2015
    gb_baseline: float = Field(
        description="GB 50189-2015 国标基准：制冷季 3.5 / 供暖季 2.5 / 过渡季 3.5"
    )
    is_below_gb: bool = Field(description="低于 GB 50189-2015 国标基准时为 True")
    period_start: datetime
    period_end: datetime
    data_points_used: int = Field(ge=1)
    source_table: Literal["energy_data"] = "energy_data"


# ===========================================================================
# Tool 3b：get_building_rated_values — 国标期望值查询（新增）
# ===========================================================================

class GetBuildingRatedValuesInput(BaseModel):
    """
    查询指定建筑在某时间段内每小时的国标（GB）期望值。
    返回结果包含 rated（期望）和 actual（实际）两列数据，便于 AI 做对比分析
    或前端渲染"实际 vs 期望"折线图。

    注意：期望值由 gb_simulator 实时计算（无需额外存储），轻量且精确。
    建议时间范围不超过 7 天（168 条），以避免响应体过大。
    """
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public services'，由数据库动态校验"
    )
    time_range: TimeRange
    metrics: list[Literal["water", "electricity", "hac_energy"]] = Field(
        default=["water", "electricity", "hac_energy"],
        description="需要对比的指标子集，默认全部三项",
    )


class RatedActualRecord(BaseModel):
    """单小时的期望值与实际值对比记录。"""
    timestamp: datetime
    hvac_mode: str = Field(description="当前小时 HVAC 工况：Cooling / Heating / Ventilation")
    schedule_factor: float = Field(description="建筑负荷率 S ∈ [0.05, 1.0]")
    # 期望值（国标）
    rated_water_m3: float
    rated_electricity_kwh: float
    rated_hac_energy: float
    expected_supply_temp: float
    expected_return_temp: float
    # 实际值（来自 energy_data，可能为 None 表示数据库无记录）
    actual_water_m3: Optional[float] = None
    actual_electricity_kwh: Optional[float] = None
    actual_hac_energy: Optional[float] = None
    actual_supply_temp: Optional[float] = None
    actual_return_temp: Optional[float] = None
    # 偏差（仅当实际值存在时计算）
    water_deviation_pct: Optional[float] = Field(default=None, description="水耗偏差%")
    electricity_deviation_pct: Optional[float] = Field(default=None, description="电耗偏差%")
    hac_deviation_pct: Optional[float] = Field(default=None, description="空调偏差%")


class GetBuildingRatedValuesOutput(BaseModel):
    """国标期望值 vs 实际值的逐小时对比数据集。"""
    building_id: str
    primary_space_usage: str = Field(description="建筑用途类型，如 'Office'")
    sqm: float = Field(description="建筑面积（㎡）")
    records: list[RatedActualRecord]
    total_hours: int = Field(description="查询覆盖的总小时数")
    anomaly_hours: int = Field(description="至少一项指标存在异常偏差的小时数")
    period_start: datetime
    period_end: datetime
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
        description="建筑类型名称，如 'Education'、'Office'、'Public services'，由数据库动态校验"
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
      SELECT date_trunc('day', timestamp)::date AS day, building_id,
             SUM(electricity_kwh) AS total_electricity_kwh,
             AVG(air_temp_c)      AS avg_ambient_temp,
             SUM(water_m3)        AS total_water_m3
      FROM energy_data GROUP BY day, building_id;
    """
    day: str = Field(description="日期，如 '2023-10-25'")
    building_id: str
    total_electricity_kwh: float
    avg_ambient_temp: float = Field(description="当天平均环境温度（°C）")
    total_water_m3: float = Field(default=0.0, description="当天总用水量（m³）")
    total_hac_energy: float = Field(default=0.0, description="当天空调总能耗（kWh）")


class QueryDailyEnergySummaryOutput(BaseModel):
    records: list[DailyEnergySummaryRecord]
    building_id: str
    granularity: str = Field(default="day", description="实际使用的聚合粒度 (day/week/month)")
    date_range_days: int = Field(default=0, description="查询时间跨度（天数）")
    source_view: Literal["daily_energy_summary"] = "daily_energy_summary"
    base_table: Literal["energy_data"] = "energy_data"
    query_ms: Optional[int] = Field(default=None, description="物化视图查询耗时（毫秒）")


# ===========================================================================
# Tool 5：rag_hybrid_search — 混合检索运维手册
# ===========================================================================

class MetadataFilter(BaseModel):
    """
    RAG 元数据硬过滤：先用 device_id 过滤掉 90% 无关文档，再做向量检索。
    device_id 来自 devices 表（如 'EM_AC_Fox_office_Alice'）；
    building_type 来自 buildings.primary_space_usage（如 'Office'）。
    全部字段可选，不传则不过滤（全库范围检索模式）。
    """
    device_id: Optional[str] = Field(
        default=None,
        description="设备 ID，来自 devices 表，如 'EM_AC_Fox_office_Alice'"
    )
    building_type: Optional[str] = Field(
        default=None,
        description="建筑用途类型，来自 buildings.primary_space_usage，如 'Office'"
    )
    doc_category: Optional[str] = Field(
        default=None,
        description="文档分类标签，如 'maintenance_manual' / 'energy_standard'"
    )


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
        description="建筑类型名称，如 'Education'、'Office'、'Public services'，由数据库动态校验"
    )
    time_range: TimeRange
    rules: list[AnomalyRule] = Field(
        default=[
            AnomalyRule.WATER_LEAK,
            AnomalyRule.ELECTRICITY_OVERLOAD,
            AnomalyRule.HVAC_OVERCONSUMPTION,
        ],
        min_length=1,
        description="检测规则白名单，默认启用全部 GB 物理规则",
    )


class AnomalyRecord(BaseModel):
    """
    单条异常记录，携带足够信息供 Diagnose Agent 做后续归因。
    新增 expected_value / deviation_pct / hvac_root_cause 支持物理分层诊断。
    """
    timestamp: datetime
    building_id: str
    meter_device_id: str
    rule_triggered: AnomalyRule
    actual_value: float
    threshold_value: float
    expected_value: Optional[float] = Field(default=None, description="国标期望值（同量纲）")
    deviation_pct: Optional[float] = Field(default=None, description="相对偏差百分比")
    hvac_root_cause: Optional[str] = Field(
        default=None,
        description="HVAC 根因诊断码：A_low_efficiency / B_small_deltaT / C_unexpected_on / other_hvac",
    )
    duration_hours: Optional[float] = Field(default=None, description="持续时长（小时）")
    anomaly_status: OperationStatus = Field(default=OperationStatus.ANOMALY)


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
    component_type: Literal["LineChart", "BarChart", "Gauge", "WorkOrderCard", "ReportDownload"]
    title: str
    data_payload: dict[str, Any] = Field(description="组件所需的结构化数据")
    source_info: Optional[dict[str, Any]] = Field(
        default=None,
        description="审计溯源信息，用于'🔍 数据来源'浮层"
    )


class RenderUIComponentOutput(BaseModel):
    artifact_id: str = Field(description="唯一标识，前端用于绑定审批回调")
    widget: str
    component_type: str = Field(description="原始组件类型，如 'LineChart'")
    title: str = Field(description="图表/卡片标题")
    data_payload: dict[str, Any] = Field(description="组件所需的结构化数据")
    source_info: Optional[dict[str, Any]] = Field(
        default=None,
        description="审计溯源信息，用于数据来源浮层"
    )
    status: Literal["rendered"] = "rendered"


# ===========================================================================
# Tool 8：create_work_order_draft — 生成工单草稿（Human-in-the-loop 核心）
# ===========================================================================

class CreateWorkOrderDraftInput(BaseModel):
    """
    Human-in-the-loop 核心工具。
    此工具绝不直接写入生产数据库，只生成草稿并触发前端审批卡片。
    用户点击"批准"后，前端才发出真正的派单 API 请求。

    device_id 应来自 devices 表中的真实设备 ID（可先调用 list_available_buildings 获取）。
    格式约束已放宽以兼容 devices 表中的自由格式 device_id（如 'Building_hvac'）。
    """
    device_id: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "设备 ID，来自 devices 表，如 'Fox_office_Alice_hvac'。"
            "可先调用 list_available_buildings 查看各楼宇的关联设备列表"
        )
    )
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public services'，由数据库动态校验"
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

class DeviceInfo(BaseModel):
    """单个设备的基本信息（来自 devices 表）。"""
    device_id: str = Field(
        description="设备唯一标识，如 'EM_AC_Fox_office_Alice'（ac）/ 'EM_ELE_Fox_office_Alice'（electricity）"
    )
    device_type: str = Field(
        description="设备类型：'electricity'（电表）/ 'water'（水表）/ 'ac'（空调/暖通）"
    )


class BuildingInfo(BaseModel):
    """
    单栋建筑的基本信息，用于向 Agent 动态告知合法 building_type 和关联设备。
    当 Agent 需要填写 device_id（如 create_work_order_draft、rag_hybrid_search 过滤）时，
    应从此列表的 devices 字段中选取真实 device_id。
    """
    building_id: str = Field(description="数据库中的实际主键，如 'Fox_office_Alice'")
    building_type: str = Field(
        description="用途类型标签（primary_space_usage），工具传参时使用此值，如 'Office'"
    )
    sqm: Optional[float] = Field(default=None, description="建筑面积（平方米）")
    devices: list[DeviceInfo] = Field(
        default_factory=list,
        description="该楼宇下的所有设备列表，device_id 可用于工单和 RAG 过滤"
    )


class ListBuildingsOutput(BaseModel):
    """
    当前数据库中所有建筑的清单（含设备列表）。
    Agent 在不确定有哪些合法 building_id 或 device_id 时应先调用此工具。
    """
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
        description="建筑类型名称，如 'Education'、'Office'、'Public services'"
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
    period_a_label: str = Field(description="当期标签，如 '2026-01-15 ~ 2026-01-31'")
    period_b_label: str = Field(description="基期标签，如 '2026-01-01 ~ 2026-01-15'")
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


# ===========================================================================
# Tool 12：generate_report — 生成统计报表（AI 对话触发）
# ===========================================================================

class GenerateReportInput(BaseModel):
    """
    AI 对话中生成统计报表。
    生成后返回下载链接作为 artifact 供前端渲染下载按钮。
    """
    building_id: str = Field(min_length=1, description="建筑类型名称")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    report_type: Literal["daily_summary", "energy_detail"] = Field(
        default="daily_summary",
        description="报表类型：daily_summary / energy_detail"
    )


class GenerateReportOutput(BaseModel):
    """报表生成结果，含下载 URL。"""
    component_type: Literal["ReportDownload"] = "ReportDownload"
    widget: Literal["report-download"] = "report-download"
    title: str
    download_url: str = Field(description="报表 CSV 下载地址")
    building_id: str
    report_type: str
    period: str


# ===========================================================================
# Tool 13：building_kpi_forecast_6h_12h — ML 模型预测 + 预测预警
# ===========================================================================

class ForecastKPIInput(BaseModel):
    """
    基于 ML 模型预测楼宇未来 6h / 12h 的 5 项 KPI，
    并与 kpi_expected_hourly 基线对比，生成预测预警标志。
    典型场景：
      - "未来 6 小时教学楼是否可能出现能耗超标？"
      - "预测一下办公楼接下来 12 小时的水电消耗"
    """
    building_id: str = Field(
        min_length=1,
        description="建筑类型名称，如 'Education'、'Office'、'Public services'"
    )
    as_of: Optional[datetime] = Field(
        default=None,
        description="预测基准时刻（默认取数据库中该楼最新可用行）"
    )
    include_expected_comparison: bool = Field(
        default=True,
        description="是否与 kpi_expected_hourly 基线对比并生成预测预警"
    )


class ForecastedMetric(BaseModel):
    """单个指标在单个 horizon 的预测结果。"""
    metric_name: str = Field(description="KPI 名称：water_l / electricity_kwh / sim_supply_temp_c / sim_return_temp_c / hac_energy")
    horizon_h: int = Field(description="预测跨度：6 或 12 小时")
    predicted_value: float
    expected_value: Optional[float] = Field(default=None, description="kpi_expected_hourly 基线值（可能为空）")
    deviation_pct: Optional[float] = Field(default=None, description="(predicted - expected) / expected * 100")
    risk_level: str = Field(default="normal", description="normal / warning / critical")
    rule_triggered: Optional[str] = Field(default=None, description="触发的预警规则")


class ForecastKPIOutput(BaseModel):
    """ML 模型预测结果，含预测值和预测预警。"""
    building_id: str
    as_of_timestamp: datetime = Field(description="预测基准时刻")
    model_name: str
    horizons_h: list[int] = Field(description="预测跨度列表，固定为 [6, 12]")
    metrics: list[ForecastedMetric] = Field(description="各指标各 horizon 的预测结果（10 条）")
    warnings_count: int = Field(description="预测预警数量（risk_level != normal）")
    data_rows_used: int = Field(description="用于构造特征的历史数据行数")
    persisted: bool = Field(default=False, description="预测预警是否已写入 predicted_anomaly_events")


# ===========================================================================
# Tool 14：building_kpi_forecast_from_features — 调试用 features 直传
# ===========================================================================

class ForecastFromFeaturesInput(BaseModel):
    """
    内部调试工具：直接传入已构造好的特征向量调用模型 predict。
    用于验证模型可用性、验证 target_cols 输出映射、
    与服务端自动构造特征的结果做对照。
    键名必须与 artifact["feature_cols"] 完全一致（41 个）。
    """
    features: dict[str, float] = Field(
        description="键为 feature_cols 中的列名，值为 number；须与训练时特征工程完全一致"
    )


class ForecastFromFeaturesOutput(BaseModel):
    """调试工具返回：模型原始预测输出 + 元数据。"""
    model_name: str
    horizons_h: list[int]
    target_cols: list[str]
    predictions: dict[str, float] = Field(
        description="键为 target_cols 中的列名，值为预测值"
    )
    feature_count_received: int
    feature_count_expected: int


# ---------------------------------------------------------------------------
# 联网搜索
# ---------------------------------------------------------------------------

class WebSearchInput(BaseModel):
    """联网搜索工具入参。"""
    query: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="搜索关键词，应为简洁的中文或英文短语，如'建筑空调系统节能优化方案'"
    )
