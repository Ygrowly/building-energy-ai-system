# 【文档 5】项目框架与目录结构设计（多智能体 + 生成式 UI 适配版）

**核心原则：**  
针对这种融合了**“传统 Web 业务 + 多智能体架构 (LangGraph) + MCP + 混合知识库”**的综合型赛题，最适合的工程目录结构依然是前后端分离的 Monorepo（单体仓库）。

**技术栈建议：**

- **Backend**: Python 3.10+ (FastAPI + LangGraph + SQLAlchemy + Pydantic)
- **Frontend**: Vue 3 + Vite + Pinia + ECharts (适配 Generative UI)
- **Database**: PostgreSQL

---

## 1. 📂 全局项目根目录结构

```latex
building-energy-agent/              # 项目根目录
├── backend/                        # 1. 后端工程 (多智能体核心大脑)
├── frontend/                       # 2. 前端工程 (生成式智能指挥舱)
├── dataset/                        # 3. 物理仿真与数据集构建 (核心升级)
├── docs/                           # 4. 比赛交付文档 (架构图、API文档)
├── docker-compose.yml              # 容器编排 (一键启动 DB、Redis、App)
├── README.md                       # 项目介绍与快速启动指南
└── .gitignore                      # Git 忽略文件
```

---

## 2. 🐍 后端目录 (`/backend`) —— 多智能体核心大脑

**架构升级点**：我们将原有的扁平结构升级为 **LangGraph 编排层** 与 **MCP 协议层** 分离的架构。

```latex
backend/
├── app/
│   ├── api/                        # ① 传统 RESTful API 接口层
│   │   ├── routes_chat.py          # SSE 流式接口 (支持 "Thinking" 和 "Artifacts" 推送)
│   │   └── routes_data.py          # 普通数据接口 (历史记录、用户配置)
│   │
│   ├── core/                       # ② 核心配置
│   │   ├── config.py               # 环境变量管理 (LLM API Keys, DB URL)
│   │   └── security.py             # 简单的 Token 验证 (防攻击)
│   │
│   ├── db/                         # ③ 数据库层 (SQLAlchemy)
│   │   ├── session.py              # 数据库连接池
│   │   └── models.py               # 表定义 (Buildings, EnergyLogs, 【AI_Audit_Log】)
│   │
│   ├── graph/                      # ④ 【核心】多智能体编排层 (LangGraph)
│   │   ├── __init__.py
│   │   ├── state.py                # 定义全局 State (包含 messages, current_agent, evidence_ids)
│   │   ├── workflow.py             # 定义图的边 (Edges) 与路由逻辑 (Router -> Data/Diagnose)
│   │   └── nodes/                  # 具体的 Agent 节点逻辑
│   │       ├── router_agent.py     # 意图识别
│   │       ├── data_agent.py       # 数据分析 (调用 MCP)
│   │       └── diagnose_agent.py   # 故障诊断 (调用 RAG)
│   │
│   ├── mcp/                        # ⑤ 【核心】MCP 协议实现层 (工具箱)
│   │   ├── server.py               # 工具注册中心
│   │   └── tools/                  # 具体的原子能力 (纯函数，无状态)
│   │       ├── data_query.py       # 查库 (Pydantic 校验)
│   │       ├── physics_calc.py     # COP 计算 (带物理校验)
│   │       ├── rag_search.py       # 混合检索
│   │       └── ui_render.py        # 生成前端组件 JSON 协议
│   │
│   └── services/                   # ⑥ 通用服务层
│       └── rag_engine.py           # 封装 RAGFlow / 向量库的调用逻辑
│
├── tests/                          # 单元测试 (加分项：展示你对工具稳定性的测试)
├── requirements.txt                # 依赖包 (langgraph, fastapi, asyncpg, etc.)
└── main.py                         # FastAPI 启动入口
```

**👨‍💻\*\*** 团队分工建议\*\*：

- **同学 A (AI 架构)**：专注 `graph/` 和 `core/`，负责把三个 Agent 串起来。
- **同学 B (工具开发)**：专注 `mcp/` 和 `db/`，负责写出健壮的 Python 函数供 AI 调用。

---

## 3. 🖥️ 前端目录 (`/frontend`) —— 生成式智能指挥舱

**架构升级点**：新增 **Generative UI 组件库**，专门用于渲染 AI 返回的结构化数据。

```latex
frontend/
├── src/
│   ├── api/                        # Axios 封装
│   │   └── stream_client.js        # 【关键】处理 SSE 流，解析 "Thinking" 和 "Component" 事件
│   │
│   ├── assets/                     # 静态资源 (3D 模型 glb 文件, 图片)
│   │
│   ├── components/                 # 全局基础组件
│   │   ├── layout/                 # 三栏式布局骨架
│   │   └── common/                 # 按钮、输入框
│   │
│   ├── generative-ui/              # 【核心】AI 生成式组件库 (Artifacts)
│   │   ├── ThinkingBubble.vue      # 思维链折叠气泡 ("正在查询数据库...")
│   │   ├── DynamicChart.vue        # 动态图表 (ECharts, 接收 AI 的 JSON 数据)
│   │   ├── WorkOrderCard.vue       # 工单审批卡片 (人机协同交互)
│   │   └── EvidenceLink.vue        # [1] 数据血缘溯源链接
│   │
│   ├── stores/                     # 状态管理 (Pinia)
│   │   ├── chatStore.js            # 存储对话历史和当前的 Artifacts
│   │   └── deviceStore.js          # 存储当前选中的设备上下文
│   │
│   ├── views/                      # 页面视图
│   │   ├── Dashboard.vue           # 首页驾驶舱
│   │   ├── Operations.vue          # 智慧运维页 (集成聊天控制台)
│   │   └── ...
│   │
│   ├── App.vue
│   └── main.js
│
├── package.json
└── vite.config.js
```

---

## 4. 📊 数据集与仿真引擎 (`/dataset`) —— 应对“剧本式模拟”

**架构升级点**：摒弃简单的随机数生成，建立一个微型的**物理仿真引擎**。

```latex
dataset/
├── raw_knowledge/                  # 非结构化知识库 (PDF, Markdown)
│   ├── chiller_manual_v2.pdf       # 冷水机组运维手册
│   └── error_codes.xlsx            # 故障代码表
│
├── simulation_engine/              # 【核心】物理仿真引擎
│   ├── physics_rules.py            # 定义物理规则 (如: 气温升高1度 -> 负荷增加5%)
│   ├── scenario_builder.py         # 剧本生成器 (定义: "Scenario A: 夜间泄露")
│   └── generator.py                # 执行脚本
│
├── output/                         # 生成结果
│   ├── energy_logs_mock.csv        # 最终导入数据库的 CSV
│   └── knowledge_vectors/          # (可选) 预处理好的向量索引
│
└── import_script.py                # 一键将 CSV 导入 Postgres 的脚本
```

**💡\*\*** 仿真剧本设计 (Scenario A - 夜间能耗异常)：\*\*

- 在 `scenario_builder.py` 中编写逻辑：
  - 时间：02:00 - 05:00
  - 对象：Administrative_Building (行政楼)
  - 规则：强制设置 `electricity_usage = 450 kWh` (正常应为 40 kWh)，但保持 `occupancy = 0` (无人)。
  - 目的：制造一个完美的“异常数据”，供 `Diagnose Agent` 在演示时发现。

---

## 5. 📜 文档目录 (`/docs`) —— 国赛拿奖的门面

把比赛要求提交的东西整整齐齐放在这里，这是加分项。

```latex
docs/
├── 01_Project_Overview.pdf         # 项目概要介绍
├── 02_System_Architecture.png      # 【关键】多智能体架构图 (LangGraph可视化)
├── 03_Database_Design.md           # ER 图与数据血缘表设计
├── 04_User_Manual.pdf              # 用户操作手册
└── assets/                         # 原始素材 (PPT源文件, Visio图)
```

---

## ⏳ 多人开发的最佳实践建议 (Team Workflow Upgrade)

为了让你们团队驾驭这套高级架构，建议遵守以下流程：

1. **接口契约先行 (Schema First)**：
   - 在写代码前，先定义好 `Generative UI Protocol`。
   - 例如约定：当 AI 想画图时，必须返回 `{"type": "artifact", "widget": "line-chart", "data": [...]}`。前端拿到这个 JSON 才会渲染组件，否则只显示文本。
2. **后端彻底模块化**：
   - `mcp/tools/` 下的每个工具函数必须**独立可运行**。写完一个 `calculate_cop` 函数，马上写一个 `test_calculate_cop.py` 测一下。
   - 不要等到 LangGraph 全部连起来再测试工具，那样调试会死人的。
3. **大模型统一配置**：
   - 建议开发阶段使用 **DeepSeek-V3** (API 兼容 OpenAI)，速度极快且便宜，非常适合调试复杂的 Agent 逻辑。
   - 演示时可以切换到更强的模型（如 GPT-4o），如果 DeepSeek 效果够好也可以不换（毕竟DeepSeek现在的代码和逻辑能力极强，且支持 JSON Mode）。

---

**最后的话：**  
这五份文档构成了一套完整的**“企业级 AI Native 应用”**解决方案。从架构设计、数据库选型、MCP 工具链、UI 交互到代码目录结构，逻辑闭环，层层递进。

- **对于评委**：他们看到的是一套有思考、有技术含量、贴合工业场景的系统。
- **对于团队**：这是一份清晰的作战地图。

祝你们在比赛中势如破竹，斩获大奖！加油！
