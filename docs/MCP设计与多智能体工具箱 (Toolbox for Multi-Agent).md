# 【文档 1】MCP 设计与多智能体工具箱 (Toolbox for Multi-Agent - Enterprise Edition)
**核心架构：**

+ **Layer 1：基础数据查询类 (Data Query)** —— _带数据血缘_
+ **Layer 2：统计分析类 (Statistical Analysis)** —— _带物理逻辑校验与连续聚合视图_
+ **Layer 3：智能诊断与知识检索类 (Diagnosis & RAG)** —— _带混合检索与重排序_
+ **Layer 4：业务动作与UI渲染类 (Action & GenUI)** —— _带人机协同协议_

这是一个非常扎实的工程化思路。要把赛题要求落地，核心就是把模糊的业务需求翻译成**精确、类型安全、可追溯**的函数定义（MCP Tools）。

在企业级落地中，单 Agent 容易因为 Prompt 太长而产生幻觉或调用错工具。因此，基于赛题的【核心开发任务】，我们构建了 4 大类共 8 个核心 MCP 工具，并将它们**解耦分配**给不同的专业智能体，实现高稳定性协同。

## 第一类：基础数据查询类 (Data Query Layer)
**专属 Agent**： `Data Agent` （数据分析师）  
**目标**：解决“自然语言数据查询”需求。这是系统的“眼睛”。

### 1. `query_energy_metrics` (能耗时序数据查询)
+ **功能描述**：查询指定建筑、指定时间段内的传感器读数。
+ **Pydantic 参数校验 (严格绑定 DB)**：
    - `building_id` (String): 必须匹配 `buildings` 表中的主键（如 "Education", "Office", "Public"）。
    - `time_range` (Object): `{"start": TIMESTAMPTZ, "end": TIMESTAMPTZ}`。
    - `metric` (Enum): 映射底层真实列名，如 `["electricity_kwh", "water_m3", "ambient_temp_c", "humidity_rh_pct", "occupancy_density_per_100sqm"]`。
+ **返回结构 (数据血缘溯源)**：

```json
{
  "value": 1520.5,
  "unit": "kWh",
  "meter_device_id": "M-EDU-001", // 【溯源】关联 buildings 表的监测设备 ID
  "source_table": "energy_data"   // 明确告知大模型数据来源
}
```

+ **作用**：不仅回答“用了多少电”，还为后续的“数据血缘”提供明确的表和设备关联 ID。

### 2. `get_device_live_status` (设备实时状态快照)
+ **参数**：`meter_device_id` (如 "M-OFF-001")。
+ **逻辑**：直接查询 `energy_data` 表，按 `timestamp` DESC 降序取最新 1 条记录。
+ **返回示例**：`{"operation_status": "Normal", "ambient_temp_c": 24.5, "last_updated_utc": "2023-10-25T14:00:00Z"}`。（直接返回真实的枚举值和传感器读数）

---

## 第二类：统计分析类 (Statistical Analysis Layer)
**专属 Agent**： `Data Agent`  
**目标**：解决“COP计算”、“同比环比”等复杂逻辑。**严禁让大模型自己做加减乘除。**

### 3. `calculate_system_cop` (能效比计算 - 物理约束版)
+ **功能描述**：赛题核心算法。计算空调系统的能效比（制冷量/耗电量）。
+ **内部逻辑 (SQL + Python实现)**：
    1. 从 `energy_data` 表拉取特定 `building_id` 的 `hvac_*`（制冷量）和 `electricity_kwh`（耗电量）。
    2. **物理异常捕获**：如果 `electricity_kwh` 接近 0，但 `hvac_*` 很高，判定为传感器故障，不进行计算，直接抛出 `SensorError`。
    3. **基准比对**：计算结果与 `ASHRAE 90.1` 标准对比。返回计算后的 COP 均值。

### 4. `query_daily_energy_summary` (趋势聚合分析 —— 【性能杀手锏】)
+ **<font style="color:rgb(43, 45, 49);">功能描述</font>**<font style="color:rgb(43, 45, 49);">：获取按天汇总的能耗趋势图表数据。</font>
+ **<font style="color:rgb(43, 45, 49);">底层逻辑</font>**<font style="color:rgb(43, 45, 49);">：直接查询数据库中预先计算好的 </font>**<font style="color:rgb(43, 45, 49);">物化视图 (Materialized View) daily_energy_summary</font>**<font style="color:rgb(43, 45, 49);">。避免全表扫描，确保长周期趋势查询在毫秒级完成。</font>

---

## 第三类：智能诊断与知识检索类 (Diagnosis & RAG Layer)
**专属 Agent**： `Diagnose Agent` （运维老专家）  
**目标**：解决“故障诊断”。这是系统的“大脑”。

### 5. `rag_hybrid_search` (混合检索 - 企业增强版)
+ **功能描述**：调用 RAGFlow API，精准检索运维手册。
+ **参数设计 (核心升级)**：
    - `query` (String): 用户的问题。
    - `metadata_filter` (Object): **【核心】** 必须传入设备上下文。如 `{"device_id": "M-OFF-001"}`。
    - `enable_rerank` (Boolean): `True` (开启语义重排序)。
+ **企业级检索逻辑 (Pipeline)**：
    1. **元数据过滤 (Hard Filter)**：先用 `WHERE device_id = 'M-OFF-001'` 过滤掉 90% 无关文档。
    2. **父子索引 (Parent-Child Indexing)**：检索时匹配细粒度的“段落”，返回时自动带上“章节标题”。防止断章取义。
    3. **语义重排序 (Reranking)**：对召回的 Top-20 结果，使用 BGE-Reranker 模型进行精排，剔除噪声，只保留 Top-3 给 Agent。
+ **返回示例**：

```json
{
  "content": "若夜间监控人员密度归零... (父章节: 4.2 常见故障排除)",
  "source_doc": "Chiller_Maintenance_Manual_V2.pdf",
  "page": 42,
  "similarity": 0.98,
  "rerank_score": 0.85 
}
```

### 6. `detect_energy_anomalies` (基于规则的异常检测)
+ **逻辑**：例如“夜间模式下功率 > 50kW”即判定异常。返回异常的具体时间点和持续时长。

---

## 第四类：业务与交互类 (Action & GenUI Layer) —— 【杀手锏】
**专属 Agent**： `Action Agent` / `Router Agent`  
**目标**：实现 Generative UI 和 Human-in-the-loop。

### 7. `render_ui_component` (生成式 UI 渲染协议)
+ **功能描述**：当 Agent 觉得单纯说话不够清楚时，指示前端渲染特殊组件。
+ **参数设计**：
    - `component_type` (Enum): `["LineChart", "BarChart", "Gauge", "WorkOrderCard"]`。
    - `data_payload` (Object): 组件所需的数据。
+ **返回**：前端接收指令后，拦截 JSON，在聊天框中**原地绘制**图表。

### 8. `create_work_order_draft` (工单生成 - 需授权)
+ **安全机制 (Human-in-the-loop)**：
    - 此工具**不会**直接写入生产数据库。返回 `{"status": "pending_approval", "ticket_id": "temp_123"}`。
    - **前端交互**：UI 弹出“确认/驳回”卡片。用户点击“确认”才发送真正的派单请求。

---



