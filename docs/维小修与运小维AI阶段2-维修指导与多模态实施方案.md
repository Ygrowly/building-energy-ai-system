# 维小修与运小维 AI 阶段 2：维修指导与多模态实施方案

## 1. 阶段定位

本阶段对应总框架文档中的 Phase 2。阶段 1 解决“AI 能不能安全地代替按钮入口”的问题；阶段 2 解决“真正开始维修后，AI 能不能指导现场人员”的问题。

核心目标：

- 维小修在工单进入处理阶段后，生成维修步骤卡片。
- 维修人员可以边聊天边按步骤打勾。
- 支持现场图片上传，由视觉模型辅助判断。
- 支持语音输入和 AI 语音播报。
- 维修指导优先使用 Qwen / DashScope / 阿里云百炼能力，RAG 复用现有 RAGFlow 管线。

## 2. 本阶段做什么

维小修新增：

- 维修指导模式。
- 步骤卡片生成。
- 步骤状态更新：待处理、已完成、跳过、需要协同、无法判断。
- 图片上传和图片理解。
- 语音转文字。
- AI 回复转语音播放。
- 维修手册 RAG 检索。
- 相似工单基础检索，不引入经验库闭环。

运小维本阶段只需要能查询维修指导记录，不需要执行动作。

## 3. 本阶段不做什么

- 不把 AI 步骤作为强制规范。
- 不让 AI 自动判断工单完成。
- 不把维修人员的经验沉淀为正式经验库，经验库放到 Phase 3。
- 不做端到端实时语音 Agent。
- 不做运小维的改派、关闭、审批。

## 4. 维修指导编排

当工单状态满足以下条件之一时进入指导模式：

- `currentExecutionStatus == processing`
- `currentExecutionStatus == waiting_support`
- 工单存在 `processing_started_at`

编排流程：

```text
load_work_order_context
-> collect_anomaly_evidence
-> retrieve_manual_rag
-> retrieve_similar_work_orders
-> generate_root_cause_candidates
-> generate_step_plan
-> stream_chat_answer
-> persist_step_plan
```

当用户上传图片时：

```text
upload_image
-> image_safety_check
-> vision_analyze
-> merge_with_work_order_context
-> update_step_suggestion
-> return_chat_answer
```

当用户语音输入时：

```text
record_audio
-> ASR
-> text_normalization
-> worker_ai_graph
-> TTS
-> mobile_playback
```

## 5. 后端模块设计

建议新增或扩展：

```text
backend/app/services/maintenance_guidance_service.py
backend/app/services/ai_media_service.py
backend/app/services/worker_ai_step_service.py
backend/app/api/routes_worker_ai.py
backend/app/graph/worker_ai_graph.py
```

### 5.1 `maintenance_guidance_service.py`

职责：

- 构造维修指导上下文。
- 调用 RAGFlow 或现有 `rag_hybrid_search`。
- 查询相似历史工单。
- 生成故障原因候选。
- 生成步骤卡片。
- 标记每一步的风险提示和预期结果。

步骤生成输出建议：

```json
{
  "guide_version": 1,
  "summary": "该工单为公共楼供水温度偏离，建议先排查读数和传感器，再检查阀门与泵运行。",
  "root_cause_candidates": [
    {
      "name": "供水温度传感器读数异常",
      "confidence": "medium",
      "evidence": ["最新实际值与预测值偏差较大"]
    }
  ],
  "steps": [
    {
      "id": "step_1",
      "title": "核对现场温度读数",
      "instruction": "到现场读取就地温度表，并拍照记录。",
      "reason": "先判断系统读数与现场读数是否一致。",
      "expected_result": "现场读数与系统读数偏差在允许范围内。",
      "risk_note": "不要先重置传感器。",
      "requires_photo": true,
      "status": "pending"
    }
  ],
  "safety_notes": [
    "涉及电控柜检查时先确认安全规范和授权。"
  ]
}
```

### 5.2 `ai_media_service.py`

职责：

- 保存音频和图片。
- 调用 Qwen / DashScope 的 ASR、TTS、视觉理解能力。
- 返回转写文本、图片理解结果、音频播放地址。
- 做文件大小、类型和权限校验。

第一版媒体限制建议：

- 图片：限制 5MB 内，支持 jpg/png/webp。
- 音频：限制 60 秒内，移动端先压缩。
- 不保存无关联工单的现场媒体。
- 媒体必须绑定 `work_order_id` 和上传用户。

## 6. API 设计

### 6.1 获取或生成步骤计划

```text
GET /api/worker-ai/work-orders/{ticket_id}/steps
```

响应：

```json
{
  "ticket_id": "WO-20260403-005",
  "dispatch_id": 123,
  "plan_id": 88,
  "status": "active",
  "summary": "建议先核对传感器读数，再检查阀门与泵运行。",
  "steps": []
}
```

如果没有步骤计划，后端可以按参数决定是否生成：

```text
GET /api/worker-ai/work-orders/{ticket_id}/steps?auto_generate=true
```

### 6.2 更新步骤状态

```text
POST /api/worker-ai/work-orders/{ticket_id}/steps/{step_id}/update
```

请求：

```json
{
  "plan_id": 88,
  "status": "completed",
  "note": "现场温度表读数为 3.7，和系统读数接近。",
  "client_version": 2
}
```

响应：

```json
{
  "ok": true,
  "plan_version": 3,
  "next_suggestion": "下一步检查供水阀门开度。"
}
```

### 6.3 图片分析

```text
POST /api/worker-ai/media/analyze-image
```

表单字段：

```text
ticket_id
dispatch_id
step_id
image
prompt
```

响应：

```json
{
  "asset_id": 501,
  "analysis": {
    "summary": "图片中可见温度表读数约为 3.7。",
    "observations": ["仪表读数清晰", "未看到明显漏水"],
    "uncertainties": ["图片角度无法确认阀门开度"]
  },
  "suggested_next_message": "读数看起来和系统最新实际值接近，建议继续检查阀门和泵运行状态。"
}
```

### 6.4 语音转文字

```text
POST /api/worker-ai/media/transcribe
```

响应：

```json
{
  "asset_id": 601,
  "transcript": "我已经核对现场读数，温度是三点七。",
  "confidence": 0.91
}
```

### 6.5 文字转语音

```text
POST /api/worker-ai/tts
```

请求：

```json
{
  "text": "下一步请检查供水阀门开度，并拍照记录。",
  "voice": "default"
}
```

响应：

```json
{
  "audio_url": "/api/worker-ai/tts/cache/tts_abc123.mp3",
  "cache_hit": true
}
```

## 7. 数据库设计

建议新增：

```text
worker_ai_step_plans
- id
- work_order_id
- dispatch_id
- generated_from_json
- root_cause_candidates_json
- summary
- steps_json
- status                -- active / completed / abandoned
- version
- model_provider
- model_name
- created_by
- created_at
- updated_at

worker_ai_step_events
- id
- plan_id
- step_id
- user_id
- event_type            -- complete / skip / reopen / note / attach_image
- note
- payload_json
- created_at

ai_media_assets
- id
- owner_user_id
- work_order_id
- dispatch_id
- step_id
- media_type            -- image / audio
- storage_url
- transcript
- analysis_json
- model_provider
- model_name
- created_at
```

说明：

- `steps_json` 保留当前步骤快照。
- `worker_ai_step_events` 保留操作历史。
- 后续 Phase 3 可以从 `worker_ai_step_events` 和完成反馈中抽取经验。

## 8. RAG 设计

优先复用现有：

```text
backend/app/mcp/tools/rag_search.py
backend/app/services/rag_engine.py
RAGFlow /api/v1/retrieval
```

检索 query 由工单上下文生成，例如：

```text
供水温度偏离 公共楼 冷站系统 温度传感器 阀门 泵 检查步骤
```

metadata filter 建议：

```json
{
  "building_id": "Public",
  "device_type": "cold_station",
  "fault_type": "supply_water_temperature_deviation"
}
```

如果 RAGFlow 未配置：

- 返回本地知识库 fallback。
- 维小修需要明确说明“当前没有检索到完整手册，仅基于工单事实给出通用检查建议”。

## 9. 移动端交互

维小修页面新增：

- 步骤卡片区。
- 图片上传按钮。
- 语音输入按钮。
- AI 回复播放按钮。
- 步骤状态按钮：完成、跳过、需要协同、记备注。

建议布局：

```text
顶部：工单状态 + SLA
中间：AI 对话流
下方：当前推荐步骤卡片
底部：输入区 + 语音 + 图片
```

当步骤卡片变化时，不应引起整页大幅跳动；卡片高度和按钮区域要保持稳定。

## 10. 性能策略

- 生成步骤计划是慢路径，用流式状态提示。
- 图片先上传再分析，分析失败不影响文字对话。
- TTS 做文本 hash 缓存。
- RAG 检索按 `ticket_id + fault_type + device_type` 短期缓存。
- 步骤状态更新不调用大模型，直接写库。
- 图片和音频走异步存储，接口只返回必要摘要。

## 11. 验收标准

- 工单开始处理后，维小修能生成步骤卡片。
- 用户能完成、跳过、备注某一步。
- 用户上传现场图片后，维小修能结合图片给出下一步建议。
- 用户语音输入后，系统能转文字并进入原对话流程。
- AI 回复可以生成音频并在移动端播放。
- RAGFlow 不可用时，维小修有明确降级话术，不崩溃。
- 所有媒体都绑定工单和用户，不允许越权读取。

## 12. 交付清单

- 维修指导服务。
- 步骤计划表和步骤事件表。
- 图片分析 API。
- 语音转文字 API。
- 文字转语音 API。
- 移动端步骤卡片、图片上传、语音输入、音频播放。
- RAG 检索接入和降级策略。
- 后端和移动端基础验收用例。
