# 维小修与运小维 AI 阶段 1：动作对话化与只读问询实施方案

## 1. 阶段定位

本阶段是双端 AI 的最小可上线闭环，对应总框架文档中的 Phase 1：

- 维小修：把维修端已有的工单动作变成对话式确认和执行入口。
- 运小维：接入只读工单问询，回答“查和解释”类问题。
- 模型 API：默认优先 Qwen / DashScope / 阿里云百炼，通过 Provider 层封装。

本阶段不追求完整维修指导，不做图片、语音、TTS，也不建设经验库。目标是先把“AI 入口、状态机边界、审计闭环、只读运维问询”跑通。

## 2. 本阶段做什么

### 2.1 维小修

维小修第一阶段只处理“工单执行动作”相关对话：

- 确认接单。
- 确认到场。
- 开始处理。
- 请求协同。
- 协同已解决。
- 确认协同。
- 无法支援。
- 无法接单或退回改派。
- 处理完成。

核心逻辑是：

```text
用户说话
-> AI 识别动作意图
-> 后端重新读取工单当前状态
-> 后端判断该动作是否允许
-> 需要确认则进入 pending confirmation
-> 用户确认
-> 调用现有工单/派工状态机服务
-> 写入 AI 动作审计和现有工单审计
-> 返回执行结果
```

### 2.2 运小维

运小维第一阶段只处理只读问题：

- “这张工单是谁接的？”
- “这张工单现在到哪一步了？”
- “今天有哪些超时工单？”
- “这个月谁处理的单最多？”
- “这张单为什么发生过改派？”
- “这张单有没有协同或接管？”

核心逻辑是：

```text
用户问题
-> 只读意图分类
-> 参数抽取：工单号、日期、人员、楼宇、状态
-> 调用 review-context 或 work-order-insights
-> 组织证据引用
-> AI 用自然语言解释
```

## 3. 本阶段不做什么

维小修不做：

- 不做维修步骤生成。
- 不做图片识别。
- 不做语音输入和语音播报。
- 不做经验库入库。
- 不根据 AI 自己的判断绕过状态机。

运小维不做：

- 不改派。
- 不关闭工单。
- 不审批工单。
- 不驳回工单。
- 不修改维修员画像、班组、技能、负载上限。
- 不替管理员确认任何状态动作。

## 4. 后端模块设计

建议新增：

```text
backend/app/api/routes_worker_ai.py
backend/app/api/routes_operator_ai.py
backend/app/services/ai_model_provider.py
backend/app/services/worker_ai_service.py
backend/app/services/operator_ai_service.py
backend/app/services/worker_ai_action_gate.py
backend/app/graph/worker_ai_graph.py
backend/app/graph/operator_ai_graph.py
```

### 4.1 `ai_model_provider.py`

统一封装模型能力，第一阶段只需要文本对话和结构化输出：

```python
class ModelProvider:
    async def chat(self, messages, tools=None, response_schema=None, stream=False):
        ...

class QwenDashScopeProvider(ModelProvider):
    ...
```

配置建议：

```text
AI_PROVIDER=qwen_dashscope
AI_TEXT_MODEL=qwen-plus
AI_FALLBACK_PROVIDER=
AI_STRUCTURED_OUTPUT_STRICT=true
```

如果 Qwen API 临时不可用：

- 维小修动作识别可降级到规则关键词。
- 运小维可以降级到已有 `work-order-insights/query` 的确定性摘要。

### 4.2 `worker_ai_action_gate.py`

该模块是维小修的安全闸门，职责不是调用大模型，而是做确定性业务校验：

- 重新读取工单、当前派工任务、协同大厅事项。
- 判断当前用户是否有权限处理该工单。
- 判断动作是否在白名单内。
- 判断当前状态是否允许该动作。
- 判断是否需要原因。
- 判断是否需要二次确认。
- 调用现有服务或接口执行动作。
- 写入 AI 动作审计。

动作白名单：

| AI action | 业务含义 | 后端复用能力 |
| --- | --- | --- |
| `accept` | 确认接单 | dispatch task accept 或 worker-action |
| `arrive` | 确认到场 | dispatch task arrive 或 worker-action |
| `start` | 开始处理 | dispatch task start 或 worker-action |
| `request_support` | 请求协同 | `/api/dispatch-tasks/{id}/request-support` |
| `support_resolved` | 协同已解决 | `/api/dispatch-tasks/{id}/support-resolved` |
| `accept_support` | 确认协同 | `/api/dispatch-hall/{entry_id}/accept-support` |
| `reject_support` | 无法支援 | `/api/dispatch-hall/{entry_id}/reject-support` |
| `reject` | 无法接单/退回改派 | `/api/dispatch-tasks/{id}/reject` |
| `complete` | 处理完成 | `/api/dispatch-tasks/{id}/complete` |

### 4.3 `worker_ai_graph.py`

第一阶段不需要复杂 RAG，只需要轻量编排：

```text
load_context
-> classify_intent
-> resolve_action
-> need_confirmation?
-> execute_action
-> format_response
```

意图识别输出建议：

```json
{
  "intent_type": "worker_action",
  "action": "accept",
  "confidence": 0.93,
  "reason": null,
  "needs_confirmation": true,
  "missing_fields": [],
  "reply": "你是要确认接单吗？"
}
```

低置信度时不执行：

```json
{
  "intent_type": "unclear",
  "action": null,
  "confidence": 0.42,
  "needs_confirmation": false,
  "reply": "我不确定你是要接单还是查看工单详情，请再说清楚一点。"
}
```

### 4.4 `operator_ai_graph.py`

第一阶段只读：

```text
classify_readonly_intent
-> extract_query_params
-> call_readonly_tools
-> evidence_pack
-> explain
```

只读工具优先复用：

```text
GET  /api/work-orders/{ticket_id}/review-context
GET  /api/work-order-insights/metrics
POST /api/work-order-insights/query
```

如果问题涉及写动作，例如“帮我关闭这张单”，应返回阻断信息：

```json
{
  "answer": "我可以帮你查看这张工单是否满足关闭条件，但第一版不会直接关闭工单。",
  "readonly": true,
  "blocked_actions": ["close_work_order"]
}
```

## 5. API 设计

### 5.1 维小修对话

```text
POST /api/worker-ai/chat
```

请求：

```json
{
  "message": "我确认接单",
  "session_id": "wx_work_001",
  "ticket_id": "WO-20260403-005",
  "dispatch_id": 123,
  "hall_entry_id": null,
  "client_context": {
    "source_page": "worker_active",
    "current_execution_status": "pending_accept"
  }
}
```

响应：

```json
{
  "assistant": "维小修",
  "message_type": "action_confirmation",
  "answer": "你要确认接单这张工单吗？确认后我会提交到后端状态机。",
  "pending_action": {
    "action": "accept",
    "ticket_id": "WO-20260403-005",
    "dispatch_id": 123,
    "requires_reason": false
  },
  "executed": false
}
```

用户确认后：

```json
{
  "message": "确认",
  "session_id": "wx_work_001",
  "ticket_id": "WO-20260403-005"
}
```

执行成功响应：

```json
{
  "assistant": "维小修",
  "message_type": "action_result",
  "answer": "已确认接单。下一步到达现场后，你可以对我说“我已到场”。",
  "executed": true,
  "action_result": {
    "action": "accept",
    "status": "success",
    "work_order_status": "dispatched",
    "execution_status": "accepted"
  }
}
```

### 5.2 运小维对话

```text
POST /api/operator-ai/chat
```

请求：

```json
{
  "message": "这个月谁处理的工单最多？",
  "session_id": "opai_001",
  "scope": {
    "date_from": "2026-04-01",
    "date_to": "2026-04-30"
  },
  "include_evidence": true
}
```

响应：

```json
{
  "assistant": "运小维",
  "answer": "这个月处理工单最多的是张三，共 18 单，其中 2 单发生到场超时。",
  "readonly": true,
  "facts": [],
  "evidence_refs": [
    "metrics.worker_rank[0]",
    "metrics.overdue_tasks"
  ],
  "blocked_actions": []
}
```

## 6. 数据库设计

第一阶段建议新增三张通用表：

```text
ai_assistant_sessions
- id
- assistant_name        -- wei_xiao_xiu / yun_xiao_wei
- user_id
- role
- work_order_id
- session_state_json
- readonly
- created_at
- updated_at

ai_assistant_messages
- id
- session_id
- role                  -- user / assistant / tool / system
- content
- content_type          -- text / tool_result
- model_provider
- model_name
- created_at

ai_assistant_action_audits
- id
- session_id
- work_order_id
- dispatch_id
- hall_entry_id
- proposed_action
- confirmation_text
- execution_status      -- pending / executed / rejected / failed
- backend_action_ref
- error_message
- created_at
```

说明：

- 运小维会话 `readonly=true`。
- 维小修每一次动作意图都写动作审计。
- 后端状态机执行成功后，仍然写现有工单审计日志。

## 7. 前端与移动端改造

### 7.1 维修端

建议新增页面：

```text
mobile/src/pages/worker/ai-workorder/index.vue
```

入口：

- `mobile/src/pages/worker/active/index.vue` 的“立即处理/继续处理”进入维小修页面。
- `mobile/src/pages/worker/pending/index.vue` 的优先处理入口进入维小修页面。
- 工单详情页可保留原按钮作为兜底，不要第一版就删干净。

页面能力：

- 自动带入 `ticket_id`、`dispatch_id`、`hall_entry_id`。
- 展示工单摘要和当前状态。
- 展示 AI 对话流。
- 展示待确认动作卡片。
- 用户点击“确认执行”或输入“确认”后执行。
- 执行成功后刷新工单详情或同步状态。

### 7.2 运维端

建议先做一个独立入口，后续再嵌入工单列表页：

```text
frontend/src/views/OperatorAI.vue
mobile/src/pages/operator/ai/index.vue
```

第一阶段重点：

- 输入自然语言问题。
- 展示回答。
- 展示证据引用。
- 如果用户要求写动作，展示只读边界提示。

## 8. 权限与安全

- 维小修只能处理当前用户有权限处理的工单。
- 运小维只允许 `admin / manager` 访问全局统计；如果后续开放给 `ops`，必须按权限裁剪。
- 所有动作执行前重新查数据库，不信任前端传入状态。
- 需要原因的动作必须收集原因。
- 低置信度动作不执行。
- `complete`、`reject`、`request_support`、`reject_support` 必须二次确认。

## 9. 性能策略

- 维小修明确动作先走规则关键词，歧义时再调用 Qwen。
- 运小维优先复用已有确定性 `work-order-insights/query`，再让模型做表达层。
- 工单上下文可以短 TTL 缓存，但执行动作前必须重新查数据库。
- SSE 流式输出可沿用现有 `/api/chat` 的设计，第一版也可以先用普通 JSON 响应降低复杂度。

## 10. 验收标准

维小修：

- 待接单工单中说“确认接单”，AI 会先确认，再执行接单。
- 已接单工单中说“我已到场”，AI 会确认并执行到场。
- 已到场工单中说“开始处理”，AI 会确认并执行开始处理。
- 处理中说“请求协同”，如果没有原因，AI 会追问原因。
- 说“完成处理”，AI 二次确认后执行完成。
- 当前状态不允许的动作不会执行，并给出解释。

运小维：

- 能回答单张工单当前状态和责任人。
- 能回答某时间范围内人员处理数量排名。
- 能解释工单是否发生过拒单、改派、协同、接管。
- 用户要求“改派/关闭/审批”时，明确拒绝执行并引导到人工页面。

工程：

- 新增后端单元测试覆盖动作意图、确认流、状态不允许、只读阻断。
- 移动端构建通过。
- 后端快速测试通过。

## 11. 交付清单

- `QwenDashScopeProvider` 文本能力。
- `POST /api/worker-ai/chat`。
- `POST /api/operator-ai/chat`。
- 维小修动作白名单和 Action Gate。
- 运小维只读问询编排。
- AI 会话与动作审计表。
- 维修端维小修入口页面。
- 运维端运小维入口页面。
- 基础测试与验收用例。
