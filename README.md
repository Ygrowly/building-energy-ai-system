# 建筑能耗智能管理与运营优化系统

基于 **LangGraph 多智能体 + MCP 工具箱 + RAG + 生成式 UI** 的建筑能耗查询统计与智慧运维平台。

> 面向建筑运行能耗「查询统计 + 智慧运维」的一体化需求：用自然语言完成能耗查询、COP 能效分析、故障诊断与报表生成；并串起异常检测 → 预测预警 → 工单 → 派工 → 维修沉淀的闭环。
>
> **项目性质**：服务外包竞赛作品，2026-04 后停止迭代。完整实现约 700 个文件（含移动双端），但**不是生产系统**——文末「已知边界」一节如实列出了它没做到什么。

## 三句话讲清

1. **数据不是造出来的**——自研物理规则仿真引擎（冷热负荷、设备额定参数、作息场景）生成能耗读数，再灌入 PostgreSQL，而不是往表里塞随机数。
2. **Agent 不是聊天框**——16 个 MCP 原子工具是它唯一能碰的东西，路由 / 数据 / 诊断三个 Agent 由 LangGraph 状态机编排，工具调用前后有参数校验与结果约束。
3. **Agent 行为有回归**——`backend/app/eval` 内置评测集，覆盖意图路由、工具选择、MCP Schema 合法性、RAG 回退与元数据过滤，改 prompt 或加工具后能跑一遍看有没有退化。

## 核心功能

### 能耗查询与统计
- 多条件能耗查询（建筑 / 时间段 / 监测参数），支持跨楼宇对比与时段对比
- COP 能效代理指标计算，与 GB 50189-2015 国标基准对比（制冷季 3.5 / 供暖季 2.5）
- 国标期望值 vs 实际值逐小时对比，超阈值自动标记偏差
- ECharts 可视化 + 报表自动生成导出

### 多智能体对话助手

Router Agent（意图识别）→ Data Agent（ReAct 工具编排 → 结果合成）→ Diagnose Agent（复合意图接力诊断）。

```mermaid
graph LR
    START((START)) --> R[Router Agent<br/>意图识别]
    R -->|数据查询 / 能效分析| D1[Data Agent<br/>ReAct 工具调用]
    R -->|故障诊断 / 运维问答| D2[Diagnose Agent]
    R -->|澄清 / 结束| E((END))
    D1 --> S[结果合成<br/>图表 + 分析文字]
    S -->|需进一步诊断| D2
    S --> E
    D2 --> E
```

生成式交互：对话内直接渲染图表、KPI 卡片、工单草稿等 UI 组件，支持一键建单。

### MCP 工具箱（16 个原子工具）

| 类别 | 工具 |
|---|---|
| 能耗查询 | `query_energy_metrics`、`query_daily_energy_summary`、`get_device_live_status`、`list_available_buildings` |
| 能效与异常 | `calculate_system_cop`、`get_building_rated_values`、`detect_energy_anomalies` |
| 对比与报表 | `compare_metric_across_buildings`、`compare_time_periods`、`generate_report` |
| 知识与检索 | `rag_hybrid_search`、`web_search` |
| 预测 | `building_kpi_forecast_6h_12h`、`building_kpi_forecast_from_features` |
| 交互与工单 | `render_ui_component`、`create_work_order_draft` |

工具定义在 `backend/app/mcp/server.py`，实现在 `backend/app/mcp/tools/`。

### 智慧运维闭环
- **RAG 知识库**：RAGFlow 混合检索运维手册（语义 + 关键词 + 可选重排），回答带来源
- **异常检测**：整点扫描国标期望偏差，事件化沉淀 Incident
- **预测预警**：sklearn 时序模型（6h / 12h bundle）逐小时预测 KPI，自动生成预测工单
- **工单与派工**：AI 审批 → 派工大厅抢单 / 自动派工（评分 + 灰度）→ SLA 分钟级扫描 → 超时重派
- **经验沉淀**：维修完成后回写维保经验库，供后续诊断复用

### 双端
- Web 管理端（Vue 3 + Vite + ECharts）：运营人员用
- 移动端（Uni-app，H5 / App）：运营「运小维」与维修「维小修」双角色，维修端支持语音 / 图像多模态交互

## 系统架构

```mermaid
graph LR
    subgraph 客户端
        FE[Web 管理端<br/>Vue 3 + ECharts]
        MO[移动端<br/>Uni-app]
    end

    subgraph 后端服务
        API[REST API 层<br/>认证 / 数据 / 工单 / 派工 / AI]
        AG[多智能体编排<br/>LangGraph StateGraph]
        MCP[MCP 工具箱<br/>16 个原子工具]
        BG[后台任务<br/>异常检测 / 预测 / SLA 扫描]
        AG --> MCP
    end

    subgraph 基础设施
        PG[(PostgreSQL<br/>能耗数据 + 业务表)]
        RD[(Redis<br/>高频查询缓存)]
        RF[RAGFlow<br/>运维知识库]
        LLM[LLM 服务<br/>DeepSeek / Qwen]
    end

    FE --> API
    MO --> API
    API --> AG
    API --> RD
    MCP --> PG
    MCP --> RF
    AG --> LLM
    BG --> PG
```

## 快速开始

### 环境要求
- Python 3.10+（推荐 3.11 / 3.12）
- Node.js 18+ 与 pnpm
- PostgreSQL 14+、Redis 7（可用 `deploy/docker-compose.yml` 起 Redis）
- RAGFlow 实例（知识库检索必需，需单独部署）

### 1. 后端

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env    # 填 DATABASE_URL / LLM_API_KEY / RAGFLOW_* / JWT_SECRET_KEY
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

启动后：API 文档 `http://localhost:8000/docs`，健康检查 `GET /health`。

数据库表结构由 `backend/app/db` 的模型在服务启动时自动补齐；后台任务（异常检测 / 预测 / SLA 扫描）默认关闭，通过 `.env` 开关显式开启。

### 2. Web 管理端

```bash
cd frontend
pnpm install
pnpm dev        # vite，默认 http://localhost:5173
```

### 3. 移动端（可选）

```bash
cd mobile
pnpm install
pnpm dev:h5     # uni-app H5 模式
```

### 4. 造数据（可选）

```bash
cd dataset
python generator.py        # 物理规则仿真生成读数
python import_script.py     # 导入 PostgreSQL
```

### 5. 跑 Agent 评测集（可选）

```bash
cd backend
python -m app.eval.runner
```

覆盖：意图路由 / 快路径、工具选择、MCP Schema 合法性、RAG 回退与元数据过滤、工单草稿、图端到端。

## 项目结构

```
construction-management/
├── backend/                  # FastAPI + LangGraph + MCP（167 个 Python 文件）
│   ├── main.py               # 应用入口
│   ├── app/
│   │   ├── api/              # REST 路由（auth / chat / data / 工单 / 派工 / 报表……）
│   │   ├── graph/nodes/      # router_agent · data_agent · diagnose_agent
│   │   ├── mcp/              # MCP 服务与 16 个原子工具实现
│   │   ├── services/         # 异常检测 / 预测 / 派工 / AI 审批 / 审计……
│   │   ├── eval/             # Agent 评测集（cases · models · runner）
│   │   └── db/ core/ schemas/
│   └── scripts/              # 造数、初始化库
├── frontend/                 # Vue 3 + Vite + ECharts 管理端
├── mobile/                   # Uni-app 双角色移动端
├── dataset/                  # 物理规则仿真引擎 + 导入脚本
├── deploy/                   # docker-compose（本地 Redis）
├── docs/                     # 需求模块、项目架构、UI 设计
└── tests/                    # Playwright 冒烟样例
```

## 技术栈

| 层级 | 选型 |
|---|---|
| 后端 | Python 3.10+、FastAPI、uvicorn |
| 智能体 | LangGraph（StateGraph）、langchain-openai、MCP |
| LLM | DeepSeek（对话编排）、Qwen / DashScope（双端多模态） |
| 数据 | PostgreSQL、SQLAlchemy 2.0（async）、Redis 7 |
| RAG | RAGFlow（混合检索 + 可选重排） |
| 预测 | scikit-learn（joblib bundle） |
| Web | Vue 3、Vite、TypeScript、Pinia、ECharts |
| 移动端 | Uni-app（H5 / App） |

## 已知边界（如实列出）

读代码前先看这几条，省得误会：

- **没有 pytest 测试套件**。仓库里只有一份 Playwright 冒烟样例（`tests/example.spec.ts`）。Agent 行为的回归靠 `backend/app/eval` 的评测集，不是单测覆盖——这两件事的强度不一样。
- **预测模型 bundle 不在仓库**（约 265MB，joblib/pkl）。要跑预测功能需自行训练，其余功能不受影响。
- **RAGFlow 需单独部署**，没有它时 `rag_hybrid_search` 走降级路径（评测集里有对应的回退用例）。
- **竞赛作品，不再迭代**。评级口径、权限模型、多租户隔离这些生产必备件都没做。
- **LLM 依赖外部 API**，没有 key 时对话链路不可用，但数据查询、统计、报表等 REST 接口仍可独立使用。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/项目架构.md](docs/项目架构.md) | 系统架构设计 |
| [docs/需求模块.md](docs/需求模块.md) | 需求与模块划分 |
| [docs/UI设计.md](docs/UI设计.md) | 界面设计规范 |
| [docs/README.md](docs/README.md) | 文档索引 |

## 开发规范

- 配置一律从 `backend/.env` 加载，不要把密钥提交到仓库
- 新增 MCP 工具需同时在 `app/mcp/server.py` 注册并补一条评测用例

## License

MIT
