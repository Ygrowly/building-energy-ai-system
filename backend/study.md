技术栈
FastAPI + LangGraph + PostgreSQL（通过 Tailscale 连接共享开发库）+ 阿里云通义 Qwen

目录
backend/
├── main.py                    # 应用入口
├── requirements.txt           # 依赖
├── app/
│   ├── api/                   # HTTP 路由层（4 个路由文件）
│   ├── core/                  # 配置 & 安全认证
│   ├── db/                    # 数据库模型 & Session
│   ├── graph/                 # LangGraph 多智能体编排
│   │   └── nodes/             # 三个 Agent 节点
│   ├── mcp/                   # MCP 工具层（12 个工具）
│   │   └── tools/
│   ├── schemas/               # Pydantic Schema + SSE 协议
│   └── services/              # RAGFlow 封装 + 降级策略
└── tests/                     # 测试套件


