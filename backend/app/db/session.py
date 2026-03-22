"""
数据库连接池：异步 SQLAlchemy 2.0 引擎 + Session 工厂。
FastAPI 依赖注入用 get_db_session()；工具函数直接用 AsyncSessionLocal。
"""
import logging
import ssl
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_settings = get_settings()

# asyncpg 只接受 ssl.SSLContext / True / False，不接受字符串 "require"
# Supabase 使用合法 CA 证书，直接 create_default_context() 即可
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

engine = create_async_engine(
    _settings.DATABASE_URL,
    echo=_settings.DEBUG,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    connect_args={"ssl": _ssl_ctx},  # Supabase 强制 SSL
)

logger = logging.getLogger(__name__)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends 注入用。每次请求独立 Session，请求结束自动关闭。"""
    async with AsyncSessionLocal() as session:
        yield session


async def ensure_auth_schema_compat() -> None:
    """
    兼容旧库结构：确保 users.role 字段存在。
    历史库可能未执行 012_add_user_role.sql，登录查询会因缺列报错。
    连接失败时仅记录警告，不阻断服务启动（连接池预热后下次请求会自动重连）。
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'resident'
                    """
                )
            )
    except Exception as exc:
        logger.warning("ensure_auth_schema_compat 失败，已跳过（不影响启动）: %s", exc)


async def ensure_daily_energy_summary_view() -> None:
    """
    确保 daily_energy_summary 物化视图存在（用于 Tool 4 的极速查询）。

    如果数据库还没执行 migrations/007_create_daily_energy_summary.sql，
    会导致 query_daily_energy_summary 的 day 粒度查询抛 UndefinedTableError。

    注意：使用两个独立的 engine.begin() 事务块，避免在同一事务内捕获并吞掉异常后
    context manager 的 __aexit__ 仍尝试 COMMIT 导致 PendingRollbackError。
    """
    # ── Step 1：检查视图是否已存在（独立事务，失败时干净回滚）────────────────
    view_exists = False
    try:
        async with engine.begin() as conn:
            await conn.execute(text('SELECT 1 FROM daily_energy_summary LIMIT 1'))
            view_exists = True
    except Exception as exc:
        msg = str(exc).lower()
        if "daily_energy_summary" not in msg:
            # 非预期错误（连接问题、权限等）：记录警告并跳过，后续工具层降级兜底
            logger.warning("检查 daily_energy_summary 时发生意外错误，已跳过: %s", exc)
            return

    if view_exists:
        return

    # ── Step 2：视图缺失时尝试创建（独立事务）────────────────────────────────
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE MATERIALIZED VIEW IF NOT EXISTS daily_energy_summary AS
                    SELECT
                        date_trunc('day', "timestamp")::date AS day,
                        building_id,
                        SUM(electricity_kwh)  AS total_electricity_kwh,
                        AVG(air_temp_c)       AS avg_ambient_temp,
                        SUM(water_m3)         AS total_water_m3
                    FROM energy_data
                    GROUP BY date_trunc('day', "timestamp")::date, building_id
                    WITH DATA;

                    CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_summary_day_building
                        ON daily_energy_summary (day, building_id);
                    """
                )
            )
            await conn.execute(text('REFRESH MATERIALIZED VIEW daily_energy_summary'))
        logger.info("已确保 daily_energy_summary 物化视图可用")
    except Exception as exc:
        logger.warning("创建/刷新 daily_energy_summary 失败，仍将使用工具降级。error=%s", exc)
