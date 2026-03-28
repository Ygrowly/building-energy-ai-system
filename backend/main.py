"""
FastAPI 应用入口。

启动命令：
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.cache import close_redis_client, init_redis_client
from app.api.routes_auth import router as auth_router
from app.api.routes_chat import router as chat_router
from app.api.routes_data import router as data_router
from app.api.routes_datacenter import router as datacenter_router
from app.api.routes_report import router as report_router
from app.api.routes_workorder import router as workorder_router
from app.api.routes_admin import router as admin_router
from app.core.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    force=True,  # uvicorn --reload 会预先配置 root logger，force 确保我们的配置覆盖
)
# 强制关键模块日志在控制台可见
for _logger_name in (
    "app.core.cache", "app.api.routes_data", "app.api.routes_chat",
    "app.api.routes_workorder", "app.graph.nodes.router_agent",
    "app.graph.nodes.data_agent", "app.graph.nodes.diagnose_agent",
    "app.graph.workflow",
):
    logging.getLogger(_logger_name).setLevel(logging.INFO)


_DEFAULT_JWT_KEY = "change-this-to-a-random-secret-in-production"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时预热 + 启动异常检测后台任务，关闭时清理。"""
    # 生产环境安全检查：禁止使用默认 JWT 密钥
    if settings.APP_ENV == "production" and settings.JWT_SECRET_KEY == _DEFAULT_JWT_KEY:
        raise RuntimeError(
            "生产环境必须在 .env 中设置随机的 JWT_SECRET_KEY，"
            "请运行: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    # P2：生产环境必须配置 LLM API Key，避免用 placeholder 误请求
    if settings.APP_ENV == "production" and (not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip()):
        raise RuntimeError(
            "生产环境必须在 .env 中设置 LLM_API_KEY（如 DeepSeek/OpenAI API Key），"
            "否则 Agent 无法正常调用大模型。"
        )

    # 注册会话管理 ORM 模型（触发 SQLAlchemy metadata 注册，供 session_store 使用）
    import app.db.chat_models  # noqa: F401
    import app.db.models  # noqa: F401  — 触发 User/RefreshToken metadata 注册
    from app.db.session import ensure_auth_schema_compat, ensure_daily_energy_summary_view

    # 初始化缓存层（Redis 不可用时会自动降级到本地缓存）
    await init_redis_client()

    # 兼容历史数据库结构，避免 users.role 缺失导致登录 500
    await ensure_auth_schema_compat()

    # P2：确保 Tool 4 的物化视图可用，避免日粒度查询抛 UndefinedTableError
    await ensure_daily_energy_summary_view()

    # 预编译 LangGraph 图（避免首次请求延迟）
    from app.graph.workflow import get_graph
    get_graph()

    # 预加载楼宇列表（运行期间不变，避免每次对话查 DB）
    from app.db.session import AsyncSessionLocal
    from app.mcp.tools.data_query import list_available_buildings
    try:
        async with AsyncSessionLocal() as db:
            buildings = await list_available_buildings(db)
            logging.getLogger(__name__).info(
                "楼宇列表预加载完成: %d 栋",
                buildings.total,
            )
    except Exception as exc:
        logging.getLogger(__name__).warning("楼宇列表预加载失败（首次请求时重试）: %s", exc)

    # 定期清理过期/已吊销的 refresh token（每 24 小时一次）
    token_cleanup_task = asyncio.create_task(_cleanup_refresh_tokens(interval_seconds=86400))

    # ── 预测预警自动调度接入点（第一版不启用，手动通过 POST /api/admin/run-forecast 触发）
    # 下一步可在此处接入 APScheduler 或 asyncio 定时任务：
    #   from app.services.forecast_service import forecast_building_kpi
    #   forecast_task = asyncio.create_task(_run_periodic_forecast(interval_seconds=3600))
    # 批量逻辑复用 routes_admin.run_forecast 中已有的 forecast_building_kpi 调用。

    yield

    # 关闭时取消定期任务
    token_cleanup_task.cancel()
    for task in (token_cleanup_task,):
        try:
            await task
        except asyncio.CancelledError:
            pass

    # 关闭数据库连接池（close=True 强制关闭所有活跃连接，避免残留 idle in transaction）
    from app.db.session import engine
    await engine.dispose(close=True)

    # 关闭 Redis client（若可用）
    await close_redis_client()


async def _cleanup_refresh_tokens(interval_seconds: int = 86400) -> None:
    """定期删除已过期或已吊销的 refresh token，防止表无限膨胀。"""
    import logging
    from datetime import datetime, timezone

    from sqlalchemy import delete
    from sqlalchemy.future import select as sa_select

    from app.db.models import RefreshToken
    from app.db.session import AsyncSessionLocal

    log = logging.getLogger(__name__)

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                result = await db.execute(
                    delete(RefreshToken).where(
                        (RefreshToken.revoked == True)  # noqa: E712
                        | (RefreshToken.expires_at < now)
                    )
                )
                await db.commit()
                log.info("refresh_tokens 清理完成，删除 %d 条记录", result.rowcount)
        except Exception:
            log.exception("refresh_tokens 清理任务异常")


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
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(data_router, prefix="/api")
app.include_router(datacenter_router, prefix="/api")
app.include_router(workorder_router, prefix="/api")
app.include_router(report_router, prefix="/api")
app.include_router(admin_router)


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
