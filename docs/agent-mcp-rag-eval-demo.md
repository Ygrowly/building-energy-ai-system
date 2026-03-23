# Agent 面试演示：MCP + RAG + Eval（基于本仓库）

这份文档把你当前的「建筑能源智能管理系统」项目，整理成一套可在面试中演示的闭环：**工具化（MCP）→ 知识增强（RAG）→ 可复现评测（Eval）**。

## 1) MCP：把“能力”做成可调用工具

后端已实现 MCP 工具注册中心与统一入口：

- 工具注册/参数校验：`backend/app/mcp/server.py`
- 工具 Schema（Pydantic v2）：`backend/app/schemas/mcp_schemas.py`
- 代表性工具：
  - 数据查询：`backend/app/mcp/tools/data_query.py`
  - 物理/规则诊断：`backend/app/mcp/tools/physics_calc.py`
  - 知识检索（RAG）：`backend/app/mcp/tools/rag_search.py`

面试讲法（一句话）：**把业务能力拆成强约束工具（Schema + 白名单 + 可观测错误），让 Agent“可控地调用”而不是“胡编”。**

## 2) RAG：知识查询与故障诊断的证据来源

RAG 引擎做了两层：

- 优先调用 RAGFlow（可选外部服务）
- 未配置时自动降级到本地知识库（可离线演示）

实现位置：`backend/app/services/rag_engine.py`

## 3) Eval：把“好不好”变成可复现的检查

本仓库新增了一个轻量、可离线运行的评测脚手架（不会请求真实 LLM / RAGFlow）：

- Eval 用例：`backend/app/eval/cases.py`
- Eval Runner：`backend/app/eval/runner.py`
- CLI：`backend/scripts/run_eval.py`

运行：

```bash
python backend/scripts/run_eval.py
```

你会得到一份 summary（PASS/FAIL + 细节），覆盖：

- Router 的意图/路由契约（mock LLM 输出，验证状态更新与继承逻辑）
- Router 的 fast-path（常见寒暄不走 LLM，0 延迟返回）
- RAG 的 fallback 行为（无 RAGFlow 配置时仍能返回结果）
- RAG 的 metadata_filter 透传（device_id / building_type 硬过滤是否正确传到检索层）
- MCP 的 Schema 校验行为（参数错误时返回 `MCPError`，而不是抛异常）
- MCP 工具清单完整性（核心工具是否在 `list_tools()` 中暴露）
- HITL 工单草稿契约（`create_work_order_draft` 输出必须是 `pending_approval`）
- Graph 端到端（Router → Diagnose → HITL），并校验 evidence / artifacts / pending_action 是否写回 state

## 推荐的面试“10 分钟演示流程”

1. 先用工具列表说明“系统能做什么”（工具白名单 + Schema）
2. 讲清楚 RAG 的双通道（RAGFlow / 本地 fallback）与抗不可用策略
3. 现场跑一遍 `run_eval.py`，展示“可复现”的质量门禁思维
