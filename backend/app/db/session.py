"""
数据库连接池：异步 SQLAlchemy 2.0 引擎 + Session 工厂。
FastAPI 依赖注入用 get_db_session()；工具函数直接用 AsyncSessionLocal。
"""
import asyncio
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


def _is_transient_db_error(exc: Exception) -> bool:
    """识别启动期常见的瞬时连库异常，避免单次握手抖动直接导致应用退出。"""
    cursor: Exception | None = exc
    keywords = (
        "connection reset",
        "connectionreseterror",
        "ssl",
        "handshake",
        "timeout",
        "connection refused",
        "closed the connection unexpectedly",
        "cannot connect",
        "connection_lost",
    )
    while cursor is not None:
        text_repr = f"{type(cursor).__name__}: {cursor}".lower()
        if any(keyword in text_repr for keyword in keywords):
            return True
        cursor = getattr(cursor, "__cause__", None) or getattr(cursor, "__context__", None)
    return False


async def _run_startup_db_op_with_retry(
    op_name: str,
    operation,
    *,
    attempts: int = 5,
    base_delay_seconds: float = 1.0,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await operation()
            if attempt > 1:
                logger.warning("%s 在第 %d 次尝试后成功", op_name, attempt)
            return
        except Exception as exc:
            if attempt >= attempts or not _is_transient_db_error(exc):
                raise
            delay = base_delay_seconds * attempt
            logger.warning(
                "%s 第 %d/%d 次执行失败，%ss 后重试。error=%s: %s",
                op_name,
                attempt,
                attempts,
                delay,
                type(exc).__name__,
                exc,
            )
            await asyncio.sleep(delay)


async def ensure_auth_schema_compat() -> None:
    """
    兼容旧库结构：确保 users.role 字段存在。
    历史库可能未执行 012_add_user_role.sql，登录查询会因缺列报错。
    """
    async def _op() -> None:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'resident'
                    """
                )
            )

    await _run_startup_db_op_with_retry("ensure_auth_schema_compat", _op)


async def ensure_daily_energy_summary_view() -> None:
    """
    确保 daily_energy_summary 物化视图存在（用于 Tool 4 的极速查询）。

    如果数据库还没执行 migrations/007_create_daily_energy_summary.sql，
    会导致 query_daily_energy_summary 的 day 粒度查询抛 UndefinedTableError。
    """
    async def _op() -> None:
        async with engine.begin() as conn:
            try:
                await conn.execute(text('SELECT 1 FROM daily_energy_summary LIMIT 1'))
                return
            except Exception as exc:
                msg = str(exc).lower()
                if "daily_energy_summary" not in msg:
                    raise

            # 视图缺失：尝试创建（创建失败则仅记录警告，后续由工具层降级兜底）
            try:
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
                # 即使创建语句里带 WITH DATA，这里也再 refresh 一次，确保数据是最新的。
                await conn.execute(text('REFRESH MATERIALIZED VIEW daily_energy_summary'))
                logger.info("已确保 daily_energy_summary 物化视图可用")
            except Exception as exc:
                logger.warning("创建/刷新 daily_energy_summary 失败，仍将使用工具降级。error=%s", exc)

    await _run_startup_db_op_with_retry("ensure_daily_energy_summary_view", _op)
