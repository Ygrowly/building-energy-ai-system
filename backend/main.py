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
from app.api.routes_incidents import router as incidents_router
from app.api.routes_dispatch import router as dispatch_router
from app.api.routes_dispatch_hall import router as dispatch_hall_router
from app.api.routes_worker_profiles import router as worker_profiles_router
from app.api.routes_context_events import router as context_events_router
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

    tasks: list[asyncio.Task] = []
    if settings.ENABLE_STARTUP_JOBS:
        if settings.ENABLE_TOKEN_CLEANUP_JOB:
            tasks.append(
                asyncio.create_task(
                    _cleanup_refresh_tokens(interval_seconds=86400)
                )
            )
        if settings.ENABLE_ANOMALY_JOB:
            tasks.append(
                asyncio.create_task(
                    _periodic_anomaly_detect(
                        interval_seconds=settings.ANOMALY_JOB_INTERVAL_SECONDS
                    )
                )
            )
        if settings.ENABLE_FORECAST_JOB:
            tasks.append(
                asyncio.create_task(
                    _periodic_forecast(
                        interval_seconds=settings.FORECAST_JOB_INTERVAL_SECONDS
                    )
                )
            )
        if settings.ENABLE_DISPATCH_SLA_JOB:
            tasks.append(
                asyncio.create_task(
                    _periodic_dispatch_sla_scan(
                        interval_seconds=settings.DISPATCH_SLA_JOB_INTERVAL_SECONDS
                    )
                )
            )

    yield

    # 关闭时取消定期任务
    for task in tasks:
        task.cancel()
    for task in tasks:
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


async def _wait_until_next_hour(offset_seconds: int = 0) -> None:
    """等待到下一个整点 + offset_seconds，用于对齐定时任务到整点执行。"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    # 距下一个整点的秒数
    seconds_past = now.minute * 60 + now.second
    wait = 3600 - seconds_past + offset_seconds
    if wait > 3600:
        wait -= 3600
    if wait < 10:
        wait += 3600  # 如果离整点太近，跳到下下个整点
    logging.getLogger(__name__).info(
        "定时任务将在 %d 秒后（整点 +%ds）首次执行", wait, offset_seconds,
    )
    await asyncio.sleep(wait)


async def _wait_until_next_minute(offset_seconds: int = 0) -> None:
    """等待到下一个整分钟 + offset_seconds，用于分钟级调度任务。"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    wait = 60 - now.second + offset_seconds
    if wait > 60:
        wait -= 60
    if wait < 3:
        wait += 60
    logging.getLogger(__name__).info(
        "分钟级任务将在 %d 秒后（整分钟 +%ds）首次执行", wait, offset_seconds,
    )
    await asyncio.sleep(wait)


async def _periodic_anomaly_detect(interval_seconds: int = 3600) -> None:
    """定时异常检测 + 自动建工单 + AI 审批（每整点执行）。"""
    from app.db.session import AsyncSessionLocal
    from app.services.kpi_expected_service import compute_and_store_all_buildings
    from app.services.anomaly_detection_service import detect_and_store_all_buildings

    log = logging.getLogger(__name__)

    # 等待到下一个整点
    await _wait_until_next_hour(offset_seconds=0)

    while True:
        try:
            log.info("定时异常检测开始 ...")
            async with AsyncSessionLocal() as db:
                await compute_and_store_all_buildings(db)

            async with AsyncSessionLocal() as db:
                summary = await detect_and_store_all_buildings(db)
                total_events = sum(v.get("events", 0) for v in summary.values())
                total_wo = sum(v.get("work_orders_created", 0) for v in summary.values())
                log.info(
                    "定时异常检测完成: events=%d, work_orders=%d",
                    total_events, total_wo,
                )
        except Exception:
            log.exception("定时异常检测任务异常")

        await asyncio.sleep(interval_seconds)


async def _periodic_forecast(interval_seconds: int = 3600) -> None:
    """定时预测预警 + 自动建工单（每小时，与异常检测同频）。"""
    from sqlalchemy import select as sa_select

    from app.db.models import Building
    from app.db.session import AsyncSessionLocal
    from app.schemas.mcp_schemas import MCPError
    from app.services.forecast_service import forecast_building_kpi
    from app.services.auto_work_order_service import (
        auto_create_prediction_orders,
        trigger_ai_review_for_pending,
    )

    log = logging.getLogger(__name__)

    # 等待到下一个整点 + 30s（与异常检测错开，避免同时占用数据库）
    await _wait_until_next_hour(offset_seconds=30)

    while True:
        try:
            log.info("定时预测预警开始 ...")
            async with AsyncSessionLocal() as db:
                bld_result = await db.execute(
                    sa_select(Building.building_id).order_by(Building.building_id)
                )
                building_ids = [r[0] for r in bld_result.fetchall()]

                for bid in building_ids:
                    res = await forecast_building_kpi(
                        building_id=bid, session=db,
                    )
                    if isinstance(res, MCPError):
                        log.warning("forecast failed: %s → %s", bid, res.error)

            # 预测完成后自动建工单
            async with AsyncSessionLocal() as db:
                bld_result = await db.execute(
                    sa_select(Building.building_id)
                )
                all_bids = [r[0] for r in bld_result.fetchall()]

            total_wo = 0
            for bid in all_bids:
                try:
                    async with AsyncSessionLocal() as db:
                        wo_result = await auto_create_prediction_orders(db, bid)
                        total_wo += wo_result.get("created", 0)
                except Exception:
                    log.exception("预警自动建工单失败: %s", bid)

            if total_wo > 0:
                async with AsyncSessionLocal() as db:
                    await trigger_ai_review_for_pending(db)

            log.info("定时预测预警完成: work_orders=%d", total_wo)
        except Exception:
            log.exception("定时预测预警任务异常")

        await asyncio.sleep(interval_seconds)


async def _periodic_dispatch_sla_scan(interval_seconds: int = 60) -> None:
    """定时扫描派工任务 SLA，写入临期/超时事件。"""
    from app.core.cache import delete_cache_by_prefix
    from app.db.session import AsyncSessionLocal
    from app.services.dispatch_service import scan_dispatch_sla_states

    log = logging.getLogger(__name__)

    await _wait_until_next_minute(offset_seconds=5)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                summary = await scan_dispatch_sla_states(db)
                await db.commit()
            if summary.get("updated", 0) > 0:
                await delete_cache_by_prefix("workorders:")
                await delete_cache_by_prefix("incidents:")
            log.info(
                "dispatch SLA 扫描完成: scanned=%d updated=%d warnings=%d overdue=%d",
                summary.get("scanned", 0),
                summary.get("updated", 0),
                summary.get("warning_events", 0),
                summary.get("overdue_events", 0),
            )
        except Exception:
            log.exception("dispatch SLA 扫描任务异常")

        await asyncio.sleep(interval_seconds)


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
app.include_router(incidents_router, prefix="/api")
app.include_router(dispatch_router, prefix="/api")
app.include_router(dispatch_hall_router, prefix="/api")
app.include_router(worker_profiles_router, prefix="/api")
app.include_router(context_events_router, prefix="/api")
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
