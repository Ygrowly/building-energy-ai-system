"""
FastAPI 应用入口。

启动命令：
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_chat import router as chat_router
from app.api.routes_data import router as data_router
from app.api.routes_report import router as report_router
from app.api.routes_workorder import router as workorder_router
from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时预热图编译，关闭时清理连接池。"""
    # 注册会话管理 ORM 模型（触发 SQLAlchemy metadata 注册，供 session_store 使用）
    import app.db.chat_models  # noqa: F401

    # 预编译 LangGraph 图（避免首次请求延迟）
    from app.graph.workflow import get_graph
    get_graph()

    yield

    # 关闭数据库连接池
    from app.db.session import engine
    await engine.dispose()


app = FastAPI(
    title="楼宇能耗多智能体系统 API",
    description="基于 LangGraph + MCP 的楼宇能耗管理智能体后端",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS（开发阶段放开，生产环境收紧 origins）
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.APP_ENV == "development" else [
        "http://localhost:5173",   # Vite dev server
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 注册路由
# ---------------------------------------------------------------------------
app.include_router(chat_router, prefix="/api")
app.include_router(data_router, prefix="/api")
app.include_router(workorder_router, prefix="/api")
app.include_router(report_router, prefix="/api")


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------
@app.get("/health", tags=["系统"])
async def health_check():
    """快速健康检查（负载均衡 / K8s 探针用）。"""
    return {"status": "ok", "env": settings.APP_ENV}


@app.get("/health/db", tags=["系统"])
async def health_db():
    """数据库连通性检查。"""
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1 AS ping"))
            row = result.fetchone()
        return {"status": "ok", "ping": row[0]}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
