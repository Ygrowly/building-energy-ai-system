# 维小修与运小维 AI 阶段 3：经验库闭环实施方案

## 1. 阶段定位

本阶段对应总框架文档中的 Phase 3。阶段 2 已经让维小修能指导维修，本阶段要解决“经验如何沉淀，并在下次类似工单中被用起来”的问题。

用户已明确要求：

- AI 只对经验类内容进行整理。
- AI 不覆盖原始经验。
- 经验要存进数据库。
- 经验不需要审核。

因此，本阶段的核心不是审批流程，而是“原文保真、AI 整理、结构化入库、可检索、可停用、可追溯”。

## 2. 本阶段做什么

- 新增维修经验库表。
- 从维修人员、运维人员和工单完成总结中收集经验。
- AI 将经验整理成标签、适用条件、建议步骤、安全注意事项。
- 原始内容和整理内容同时保存。
- 经验异步向量化，进入相似工单召回。
- 维小修在生成步骤时引用经验推荐。
- 运小维可以只读查询经验沉淀情况。

## 3. 本阶段不做什么

- 不做经验审核流程。
- 不让 AI 擅自改写原始经验。
- 不把经验推荐伪装成官方规范。
- 不让经验覆盖安全规范或维修手册。
- 不做复杂知识图谱，第一版用结构化字段 + 向量检索即可。

## 4. 经验来源

经验可以来自：

- 维修人员在维小修中说：“我以前遇到这个问题，先检查某个阀门更快。”
- 维修人员完成工单时填写的处理总结。
- 运维人员在运小维中补充的经验类说明。
- 协同人员对本次处理的备注。
- 阶段 2 的步骤事件和图片分析结论。

AI 需要先判断内容是否属于经验类：

```json
{
  "is_experience": true,
  "experience_type": "troubleshooting_tip",
  "reason": "用户描述了类似供水温度偏离场景下的优先检查步骤。"
}
```

不是经验类时，不进入经验库。

## 5. 经验整理流程

```text
capture_source_text
-> classify_experience
-> persist_source_text
-> organize_experience
-> persist_organized_text
-> enqueue_vector_index
-> available_for_retrieval
```

关键原则：

- 先保存原文，再做 AI 整理。
- AI 整理失败时，原文仍保留，索引状态标记为 `organize_failed`。
- 经验可直接可用，不需要审核。
- 后续发现错误时，通过 `is_active=false` 停用，不物理删除。

## 6. 数据库设计

建议新增：

```text
maintenance_experiences
- id
- source_type                    -- worker_note / operator_note / completion_summary / step_event
- source_work_order_id
- source_dispatch_id
- source_step_plan_id
- contributor_user_id
- contributor_role
- building_id
- device_id
- device_type
- fault_type
- fault_keywords_json
- symptom_tags_json
- source_text                    -- 原始经验，不覆盖
- organized_text                 -- AI 整理后的经验
- suggested_steps_json
- safety_notes_json
- applicable_conditions_json
- conflict_flags_json
- model_provider
- model_name
- vector_index_status            -- pending / indexed / failed / organize_failed
- vector_ref
- usage_count
- helpful_count
- unhelpful_count
- is_active
- created_at
- updated_at

maintenance_experience_usage_logs
- id
- experience_id
- work_order_id
- dispatch_id
- assistant_session_id
- usage_type                     -- retrieved / cited / accepted / ignored
- created_at

maintenance_experience_feedback
- id
- experience_id
- user_id
- work_order_id
- feedback                       -- helpful / unhelpful / incorrect
- note
- created_at
```

说明：

- `source_text` 是用户原文，永不覆盖。
- `organized_text` 是 AI 整理结果，可以追加新版本字段，第一版可先直接更新并保留 `updated_at`。
- `is_active=false` 用于停用错误经验。
- 经验不需要审核，但需要反馈和停用能力。

## 7. AI 整理输出结构

建议结构化输出：

```json
{
  "organized_text": "遇到供水温度偏离时，可优先核对现场温度表与系统读数是否一致，再检查阀门开度和泵运行状态。",
  "fault_type": "supply_water_temperature_deviation",
  "symptom_tags": ["供水温度偏离", "读数异常", "阀门检查"],
  "fault_keywords": ["供水温度", "传感器", "阀门", "泵"],
  "applicable_conditions": [
    "适用于公共楼冷站系统供水温度偏离场景",
    "适用于现场读数可获取的情况"
  ],
  "suggested_steps": [
    "先核对现场温度表读数",
    "再检查阀门开度",
    "最后检查泵运行状态"
  ],
  "safety_notes": [
    "涉及电控柜检查时遵守断电和授权要求"
  ],
  "conflict_flags": []
}
```

如果经验和安全规范冲突：

```json
{
  "conflict_flags": [
    {
      "type": "safety_conflict",
      "message": "经验建议先打开电控柜检查，但未提及断电和授权。"
    }
  ]
}
```

冲突经验可以入库，但维小修引用时必须优先提示安全规范。

## 8. 检索与推荐

维小修生成步骤时新增检索：

```text
retrieve_manual_rag
-> retrieve_experience
-> merge_recommendations
-> generate_step_plan
```

经验召回条件：

- `is_active=true`
- 同楼宇或同设备类型优先。
- 同故障类型优先。
- 语义相似度达到阈值。
- `helpful_count` 高的优先。
- `incorrect` 或 `unhelpful_count` 高的降权。

推荐展示方式：

```text
经验推荐：之前类似供水温度偏离工单中，维修人员建议先核对现场温度表，再检查阀门开度。该经验来自 WO-20260403-005。
```

不要写成：

```text
必须先核对现场温度表。
```

经验只是推荐，不是强制规范。

## 9. API 设计

### 9.1 新增经验

```text
POST /api/maintenance-experiences
```

请求：

```json
{
  "source_type": "worker_note",
  "source_work_order_id": "WO-20260403-005",
  "source_dispatch_id": 123,
  "source_text": "我以前处理过这个问题，先看现场温度表和阀门开度，比直接重启传感器更稳。"
}
```

响应：

```json
{
  "id": 1001,
  "status": "created",
  "vector_index_status": "pending",
  "organized_text": "遇到供水温度偏离时，建议先核对现场温度表和阀门开度，不要直接重启传感器。"
}
```

### 9.2 搜索经验

```text
GET /api/maintenance-experiences/search
```

参数：

```text
query=供水温度偏离
building_id=Public
device_type=cold_station
fault_type=supply_water_temperature_deviation
limit=5
```

响应：

```json
{
  "items": [
    {
      "id": 1001,
      "organized_text": "遇到供水温度偏离时，建议先核对现场温度表和阀门开度。",
      "source_work_order_id": "WO-20260403-005",
      "score": 0.86,
      "helpful_count": 3
    }
  ]
}
```

### 9.3 经验反馈

```text
POST /api/maintenance-experiences/{experience_id}/feedback
```

请求：

```json
{
  "work_order_id": "WO-20260411-002",
  "feedback": "helpful",
  "note": "按这个经验先检查阀门，确实更快定位。"
}
```

### 9.4 停用经验

```text
POST /api/maintenance-experiences/{experience_id}/deactivate
```

说明：

- 不是审核流程。
- 用于错误经验、过期经验或安全冲突经验的人工停用。
- 需要记录停用人和原因。

## 10. 和维小修的集成

阶段 2 的步骤生成输入增加：

```json
{
  "experience_recommendations": [
    {
      "experience_id": 1001,
      "source_work_order_id": "WO-20260403-005",
      "organized_text": "遇到供水温度偏离时，建议先核对现场温度表和阀门开度。",
      "confidence": 0.86
    }
  ]
}
```

维小修回答时要区分来源：

- “维修手册建议……”
- “历史经验推荐……”
- “本次工单事实显示……”

## 11. 和运小维的集成

运小维第一阶段仍只读，本阶段可新增只读问题：

- “最近有哪些供水温度偏离的经验？”
- “这类问题历史上大家怎么处理？”
- “哪条经验被引用最多？”
- “有没有被标记为无效的经验？”

运小维不能自动编辑或停用经验；如果后续要做，也需要单独设计权限和确认。

## 12. 性能策略

- 经验整理可同步返回初步结果，向量化异步。
- 经验检索结果按 `fault_type + device_type + building_id` 缓存。
- 写经验不阻塞工单动作。
- 经验索引失败要重试，但不影响原文保存。
- 大量经验时，先用结构化过滤再做向量召回。

## 13. 验收标准

- 用户提出经验后，系统保存原文。
- AI 生成整理版经验，不覆盖原文。
- 经验无需审核即可进入可检索状态。
- 维小修处理类似工单时能召回经验。
- 维小修引用经验时明确标注“经验推荐”。
- 经验可被标记 helpful/unhelpful/incorrect。
- 错误经验可停用，停用后不再被推荐。

## 14. 交付清单

- 经验库表和迁移。
- 经验新增 API。
- 经验检索 API。
- 经验反馈 API。
- 经验停用 API。
- Qwen 经验整理结构化输出。
- 向量索引异步任务。
- 维小修步骤生成接入经验推荐。
- 运小维只读经验查询。
