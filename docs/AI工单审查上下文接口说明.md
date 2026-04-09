# AI 工单审查上下文接口说明

## 定位

`review-context` 是给后续 AI 审查工单准备的上下文接口。它当前不调用大模型，也不生成 AI 审查结论，只负责把一张工单的关键证据组织成结构化数据。

它的核心目标是：

- 给运维人员和开发人员提供只读排查能力。
- 给未来 AI 审查入口提供稳定的数据输入。
- 避免 AI 接入时到处调用零散接口拼上下文。

## 和执行时间线的区别

执行时间线更偏“现场执行过程”，主要描述派工任务如何推进，例如派工、接单、到场、开始处理、协同、催办、完成、关闭。

审查上下文更偏“系统审查总账”，除了执行过程，还会合并：

- 工单当前状态
- 当前派工
- 历史派工任务
- 派工事件流
- 审计日志
- 工单大厅事项与申请
- 异常证据快照
- 规则生成的风险标记
- 面向 AI 的摘要文本

一句话：执行时间线适合看“工单执行到哪一步”，审查上下文适合问“这张工单全过程是否合理”。

## 当前接口

```text
GET /api/work-orders/{ticket_id}/review-context
```

权限规则：

- `admin` / `manager` 可以查看全部工单。
- `ops` 只能查看当前正式派给自己的工单。

当前接口由后端服务 `work_order_review_context_service` 生成，不调用 LLM，不写数据库。

## 返回结构

典型返回结构如下：

```json
{
  "ticket_id": "WO-20260328-010",
  "context_type": "work_order_ai_review_context",
  "work_order": {},
  "current_dispatch": {},
  "dispatch_tasks": [],
  "dispatch_events": [],
  "audit_logs": [],
  "hall_entries": [],
  "anomaly_evidence": [],
  "risk_flags": [],
  "ai_context_summary": "..."
}
```

字段说明：

- `work_order`：工单基础信息与当前状态。
- `current_dispatch`：当前正式派工任务。
- `dispatch_tasks`：该工单的历史派工任务。
- `dispatch_events`：派工执行事件流。
- `audit_logs`：工单审计总账，记录关键状态变更和操作来源。
- `hall_entries`：工单大厅事项与申请记录。
- `anomaly_evidence`：该工单关联的异常证据快照。
- `risk_flags`：规则识别出的风险标记，例如超时、改派、缺少审计日志。
- `ai_context_summary`：规则生成的中文摘要，后续可作为 AI prompt 的摘要输入。

## 命令行查看脚本

如果不想打开前端或直接查数据库，可以用脚本查看上下文。

```powershell
cd E:\27_fwwb_A08\project\backend
python scripts/show_work_order_review_context.py WO-20260328-010
```

输出完整 JSON：

```powershell
python scripts/show_work_order_review_context.py WO-20260328-010 --json
```

脚本只读，不修改数据库。

## 后续 AI 接入建议

建议后续新增一个真正调用 AI 的接口，而不是把 LLM 调用塞进 `review-context`。

推荐接口：

```text
POST /api/work-orders/{ticket_id}/ai-review
```

建议调用流程：

1. 后端先调用 `GET /review-context` 同源服务，构造结构化上下文。
2. 根据模型上下文长度裁剪明细，例如保留最近若干条审计日志和派工事件。
3. 将 `ai_context_summary` 与结构化 JSON 一起传给 LLM。
4. 要求 LLM 返回结构化结论。
5. 将 AI 审查结果写入审计日志或未来的 `work_order_ai_review_results` 表。

建议 AI 输出结构：

```json
{
  "risk_level": "low|medium|high",
  "conclusion": "这张工单的处理过程是否合理",
  "findings": [
    {
      "type": "timeout|reassign|audit_gap|status_conflict",
      "severity": "low|medium|high",
      "message": "发现的问题",
      "evidence_refs": ["dispatch_events[3]", "audit_logs[2]"]
    }
  ],
  "recommended_actions": ["建议管理员复核接管原因"],
  "confidence": 0.82
}
```

## 边界说明

- `review-context` 不是回滚接口。
- `review-context` 不负责恢复历史责任人。
- 如果旧数据没有审计日志，系统不能凭空推断过去责任人，只能依赖外部日志、备份或人工记录。
- 未来 AI 审查结论只能作为辅助建议，不能直接替代管理员确认。

