# 维小修与运小维 AI 阶段 4：运维运营分析增强实施方案

## 1. 阶段定位

本阶段对应总框架文档中的 Phase 4。前面三个阶段主要让维修端形成“执行 + 指导 + 经验”的闭环；阶段 4 重点增强运小维，让运维人员可以用自然语言做更复杂的运营分析。

核心目标：

- 运小维能回答跨工单、跨人员、跨楼宇、跨时间范围的统计问题。
- 运小维能生成月报、班组对比、超时原因归因。
- 运小维能返回证据引用和可视化数据。
- 运小维仍保持只读，不执行改派、关闭、审批。

## 2. 本阶段做什么

- 扩展运小维查询意图。
- 扩展 `work-order-insights` 参数化统计能力。
- 新增运营分析事实包。
- 支持月报和日报摘要。
- 支持人员、班组、楼宇、状态、SLA 多维分析。
- 支持图表数据返回。
- 支持追问上下文。

## 3. 本阶段不做什么

- 不做自动改派。
- 不做自动关闭。
- 不做自动审批。
- 不替管理员执行工单动作。
- 不用大模型直接算统计口径。
- 不让 AI 编造没有查询到的数据。

## 4. 运小维增强后的问题范围

单张工单：

- “这张工单完整流程是什么？”
- “这张工单为什么超时？”
- “这张工单中间谁接过、谁拒过、谁协同过？”
- “这张工单有没有审计缺口？”

跨工单统计：

- “这个月谁处理得最多？”
- “本周哪个班组超时率最高？”
- “公共楼最近 7 天哪类问题最多？”
- “哪些工单重复发生类似问题？”
- “最近哪些工单用了维小修经验推荐？”

运营报告：

- “生成本月工单运营总结。”
- “给我看今天的异常工单和处理进展。”
- “对比本周和上周的派工效率。”

## 5. 查询编排

增强后的编排：

```text
classify_intent
-> extract_dimensions
-> normalize_time_range
-> choose_fact_tool
-> execute_readonly_query
-> build_evidence_pack
-> generate_explanation
-> generate_chart_payload_optional
-> suggest_followups
```

意图类型扩展：

```text
single_work_order_summary
single_work_order_timeline_question
worker_performance
team_performance
building_hotspot
overdue_analysis
support_takeover_analysis
reassign_analysis
experience_usage_analysis
daily_report
weekly_report
monthly_report
comparison_analysis
```

维度抽取：

```json
{
  "date_from": "2026-04-01",
  "date_to": "2026-04-30",
  "building_id": "Public",
  "worker_id": null,
  "team_id": null,
  "status": ["completed", "waiting_support"],
  "metric": "completion_count",
  "group_by": "worker"
}
```

## 6. 事实层设计

运小维必须先查事实层，再生成解释。事实层建议继续扩展：

```text
backend/app/services/work_order_insights_service.py
backend/app/api/routes_work_order_insights.py
```

建议新增或增强的只读能力：

```text
GET  /api/work-order-insights/metrics
POST /api/work-order-insights/query
POST /api/work-order-insights/report
GET  /api/work-order-insights/timeline
GET  /api/work-order-insights/rankings
GET  /api/work-order-insights/overdue-analysis
GET  /api/work-order-insights/experience-usage
```

也可以先只新增一个综合查询接口：

```text
POST /api/work-order-insights/facts
```

请求：

```json
{
  "intent": "worker_performance",
  "date_from": "2026-04-01",
  "date_to": "2026-04-30",
  "group_by": "worker",
  "metrics": ["assigned_count", "completed_count", "avg_arrive_minutes", "overdue_count"]
}
```

响应：

```json
{
  "facts": [],
  "metrics": {
    "rows": [
      {
        "worker_id": 12,
        "worker_name": "张三",
        "assigned_count": 20,
        "completed_count": 18,
        "avg_arrive_minutes": 22.5,
        "overdue_count": 2
      }
    ]
  },
  "evidence_refs": ["dispatch_tasks", "work_orders"]
}
```

## 7. 运小维 API

继续使用：

```text
POST /api/operator-ai/chat
```

增强请求：

```json
{
  "message": "对比本周和上周公共楼工单处理效率",
  "session_id": "opai_20260412_001",
  "scope": {
    "building_id": "Public"
  },
  "include_evidence": true,
  "include_chart": true
}
```

增强响应：

```json
{
  "assistant": "运小维",
  "answer": "本周公共楼工单 16 单，上周 12 单；本周平均到场 24 分钟，上周 31 分钟，整体到场效率提升。",
  "readonly": true,
  "facts": [],
  "metrics": {},
  "chart": {
    "type": "bar",
    "title": "公共楼本周与上周工单效率对比",
    "x": ["上周", "本周"],
    "series": [
      { "name": "工单数", "data": [12, 16] },
      { "name": "平均到场分钟", "data": [31, 24] }
    ]
  },
  "evidence_refs": [],
  "suggested_followups": [
    "查看本周超时工单明细",
    "按维修人员拆分公共楼处理效率"
  ],
  "blocked_actions": []
}
```

如果用户要求写动作：

```json
{
  "answer": "我可以帮你分析是否需要改派，也可以列出候选人和原因，但当前版本不会直接执行改派。",
  "readonly": true,
  "blocked_actions": ["reassign_dispatch"]
}
```

## 8. 可视化设计

运小维可以返回图表 payload，但不直接操作数据库。

支持图表：

- 柱状图：人员处理量、班组完成量、楼宇热点。
- 折线图：每日工单数量、超时率趋势。
- 饼图或环图：工单状态分布。
- 表格：超时工单明细、待关闭工单明细。

前端可在对话中渲染图表卡片，但要保留数据来源说明。

示例图表 payload：

```json
{
  "component_type": "bar_chart",
  "title": "本月维修人员完成量排名",
  "source": "work_order_insights.worker_rank",
  "data": [
    { "name": "张三", "value": 18 },
    { "name": "李四", "value": 15 }
  ]
}
```

## 9. 证据引用

运小维每个关键结论都要有证据：

```json
{
  "claim": "张三本月完成 18 单",
  "evidence_refs": [
    "metrics.worker_rank[0].completed_count"
  ]
}
```

如果没有查到数据，回答：

```text
我没有查到 2026-04-01 到 2026-04-30 期间公共楼的已完成工单记录，因此不能判断谁处理最多。
```

不要回答：

```text
可能是张三处理最多。
```

## 10. 数据与性能

统计口径建议：

- 大模型不直接算总数和平均值。
- 所有统计由 SQL 或服务层完成。
- 长周期趋势优先用已有物化视图或预聚合结果。
- 高频指标可以 Redis 缓存 30-120 秒。
- 单次分析限制最大时间范围，超大范围返回提示或异步报告。

可增加的预聚合：

```text
work_order_daily_metrics
worker_daily_dispatch_metrics
team_daily_dispatch_metrics
building_daily_work_order_metrics
```

第一版也可以先不建新表，直接在服务层查询；当数据量上来后再加预聚合。

## 11. 前端交互

运小维页面增强：

- 支持选择时间范围。
- 支持选择楼宇、人员、班组。
- 支持图表卡片。
- 支持证据展开。
- 支持追问按钮。
- 对写动作请求显示只读边界提示。

建议保留“只读”视觉标识：

```text
运小维 · 只读分析模式
```

避免用户误以为 AI 已经执行了派工动作。

## 12. 权限设计

- `admin / manager` 可以看全局统计。
- `ops` 如后续开放，只能看自己相关工单或授权范围。
- 运小维不暴露写工具。
- 所有回答都带 `readonly=true`。
- 敏感人员绩效统计需要按角色控制。

## 13. 验收标准

- 能生成本月工单运营总结。
- 能回答某天是谁接了某张单。
- 能按人员统计接单数、完成数、超时数。
- 能按楼宇统计热点问题。
- 能对比两个时间段的处理效率。
- 能返回图表 payload。
- 能展示证据引用。
- 用户要求改派、关闭、审批时不会执行，只给只读分析和人工入口建议。

## 14. 交付清单

- 运小维增强意图分类。
- 参数化事实查询服务。
- 报告生成接口。
- 图表 payload 协议。
- 证据引用结构。
- 前端运小维图表卡片和证据展开。
- 权限裁剪。
- 运营分析测试用例。
