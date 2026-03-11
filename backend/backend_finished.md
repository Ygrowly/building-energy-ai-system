cd backend

uvicorn main:app --reload --host 0.0.0.0 --port 8000



后端完整 API 路由总览
方法	路径	说明
GET	/health	健康检查
GET	/health/db	数据库连通性检查
POST	/api/chat	SSE 流式对话（返回 text/event-stream）
POST	/api/chat/approve	工单审批（兼容旧路径，内部转发）
GET	/api/chat/sessions/{session_id}	获取会话状态摘要
GET	/api/chat/sessions/{session_id}/messages	获取对话消息历史
DELETE	/api/chat/sessions/{session_id}	清除会话
GET	/api/buildings	获取所有建筑列表
GET	/api/buildings/{building_type}/status	获取建筑最新设备状态
GET	/api/buildings/{building_type}/energy	获取每日能耗趋势（支持 include_water）
GET	/api/overview	Dashboard KPI 汇总
GET	/api/anomalies/recent	近期异常告警（支持 hours / building_type 过滤）
GET	/api/tools	列出所有 MCP 工具（调试用）
GET	/api/work-orders	获取所有工单（支持 status 过滤）
GET	/api/work-orders/{ticket_id}	获取单个工单详情
POST	/api/work-orders/approve	审批/驳回工单
GET	/api/reports/export	CSV 报表下载（building_type / start_date / end_date / report_type）
SSE 事件类型（前端 EventSource 需处理）
{ "type": "thinking", "agent": "data_agent", "message": "...", "hop_count": 1 }
{ "type": "text", "content": "分析结论...", "is_final": true }
{ "type": "artifact", "widget": "line-chart", "component_type": "LineChart", "title": "...", "data_payload": {...} }
{ "type": "artifact", "widget": "work-order-card", "component_type": "WorkOrderCard", "title": "维修工单待确认", "data_payload": {...} }
{ "type": "artifact", "widget": "report-download", "component_type": "ReportDownload", "title": "...", "download_url": "/api/reports/export?..." }
{ "type": "error", "message": "...", "recoverable": true }
{ "type": "done", "session_id": "xxx", "hop_count": 2 }
MCP 工具清单（12 个）
#	工具名	职责	需要 DB
1	list_available_buildings	动态获取楼宇白名单	✓
2	query_energy_metrics	能耗时序原始数据	✓
3	get_device_live_status	设备实时状态快照	✓
4	query_daily_energy_summary	按天/周/月聚合趋势	✓
5	calculate_system_cop	空调能效比 COP	✓
6	detect_energy_anomalies	基于规则异常检测	✓
7	compare_metric_across_buildings	多楼宇横向对比	✓
8	compare_time_periods	同环比分析	✓
9	rag_hybrid_search	运维手册混合检索（RAGFlow/本地降级）	✗
10	render_ui_component	生成图表/卡片渲染指令	✗
11	create_work_order_draft	生成工单草稿（HITL）	✗
12	generate_report	生成 CSV 报表下载链接	✗
前端开发关键注意事项
聊天接口：POST /api/chat 需设置 Content-Type: application/json，响应是 text/event-stream，Session ID 在响应头 X-Session-Id 中返回
Artifact 渲染：按 widget 字段路由 Vue 组件：line-chart → LineChart、bar-chart → BarChart、gauge → Gauge、work-order-card → WorkOrderCard、report-download → 下载按钮
工单审批：拿到 ticket_id 后，调用 POST /api/work-orders/approve，需带 session_id
报表下载：AI 触发时通过 download_url 直接 <a href> 即可；手动导出走 GET /api/reports/export
API Key：开发环境 DEBUG=true 时不需要携带，生产环境需在请求头加 X-API-Key
数据时间范围：数据库有效数据为 2016-04-01 ~ 2016-05-02