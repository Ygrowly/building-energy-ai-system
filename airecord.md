AI 对话总结报表改造方案文档
Summary
将当前“导出对话报表”从前端逐条导出 用户提问 / AI回答 的聊天记录模式，改为“基于会话状态生成正式总结报表”的模式。
本次方案采用你确认的默认策略：

生成方式：混合模式，优先后端 AI 总结，失败时降级为规则化摘要
内容范围：摘要 + 结论 + 建议，不附完整问答附录
工件策略：保留对话中出现过的全部工件，按原出现顺序纳入报表
生成时机：点击“导出对话报表”时按当前会话即时生成
现有 /api/reports/export 的 CSV 数据导出链路保持不变；本次只改 AI 对话报表导出链路。

Public API / Type Changes
新增后端接口：

POST /api/chat/sessions/{session_id}/report
请求体：

{
  "mode": "formal",
  "generation_mode": "hybrid",
  "artifact_policy": "all",
  "include_appendix": false
}
返回体：沿用前端报表预览所需的结构化 payload，直接给 reportStore.openPreviewWithPayload() 使用。

interface ConversationReportPayload {
  title: string
  subtitle?: string
  generatedAt: string
  buildingName?: string
  generatedBy?: string
  mode: 'snapshot' | 'formal'
  sections: ReportSection[]
}
前端类型扩展：

type ReportSectionType = 'kpi' | 'table' | 'chart' | 'text' | 'summary' | 'artifact'

interface ReportSection {
  id: string
  namespace: string
  title: string
  type: ReportSectionType
  content?: string
  contentFormat?: 'plain' | 'markdown'
  summaryItems?: { label: string; value: string }[]
  artifact?: ArtifactEvent
}
Implementation Changes
1. 后端生成“真正总结报表”
新增会话报表生成服务，输入为持久化会话状态，输出为结构化报表 payload，不再返回原始聊天记录拼接结果。

报表正文固定结构：

会话概览
执行摘要
关键结论
建议行动
风险与待确认项
会话工件
生成逻辑：

读取会话持久化的 messages / artifacts / context_summary / evidence / pending_action
补充持久化 react_data_summary 与 chart_manifest，便于导出时直接复用
先构建稳定的摘要输入上下文，再调用 LLM 仅生成正文块内容
后端负责把正文块组装成 ReportSection[]
若 LLM 失败或返回不可用内容，降级为规则化报表：
从 context_summary、最近一轮 AI 最终答复、pending_action、artifacts 提炼概览/结论/建议
严禁降级回“逐条问答导出”
2. 前端导出入口改造
AgentConsole 中“导出对话报表”改为：

点击后调用新接口
成功后直接打开现有报表预览弹窗
默认以 formal 模式打开
页面级报表导出逻辑保持原样，不影响现有 dashboard/reportStore 用法
删除现有“每条消息生成一个 text section”的导出逻辑，不再出现“用户提问 1 / AI 回答”这种报表结构。

3. Markdown 真正渲染
报表正文的 text section 支持 contentFormat: 'markdown'，ReportRenderer 复用现有 marked 渲染链路，不再把 Markdown 原文直接打印到 PDF/HTML。

要求：

聊天区与报表区共用同一套 Markdown 渲染工具
导出后的 PDF/HTML 中标题、列表、粗体、表格按渲染结果展示
现有聊天中的 <<CHART:...>> 占位符、工具调用残留文本在报表正文中清洗掉
4. 工件纳入报表
报表新增 artifact section，复用现有生成式 UI 组件渲染：

图表类：LineChart / BarChart / Gauge
卡片类：WorkOrderCard / ReportDownload
工件展示规则：

全部保留
放在正文后面的“会话工件”部分
顺序按对话中首次出现顺序
PDF 导出依赖现有 DOM 截图链路，无需后端转图片
Test Plan
当前会话导出后，报表正文不再按“用户提问 / AI回答”逐条展示
AI 回复含 Markdown 标题、列表、粗体时，报表预览和导出文件能正确渲染
会话包含图表、工单卡片、CSV 报表卡片时，报表中全部出现
刷新页面后重新打开历史会话再导出，报表仍可生成，证明后端使用持久化状态
LLM 失败时，接口仍返回规则化总结报表，而不是回退为原始聊天记录
空会话或无有效消息时，接口返回明确错误，不打开空报表
会话归属校验沿用现有 chat session 访问控制，不能导出他人会话
Assumptions
不新增数据库表，也不做 schema migration；只扩展 extra_state_json 中持久化的字段
现有数据类 CSV 导出接口继续保留，不与对话总结报表合并
对话总结报表默认不附原始问答附录；如果后续需要，可在接口中开启 include_appendix
老会话若缺少 react_data_summary/chart_manifest，按兼容模式走降级生成