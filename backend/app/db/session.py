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
    pool_recycle=600,  # 10 分钟回收空闲连接，防止 idle in transaction 残留
    connect_args={
        "ssl": _ssl_ctx,  # Supabase 强制 SSL
        "server_settings": {
            "statement_timeout": "30000",      # 30s — 防止单条 SQL 无限等待
            "lock_timeout": "10000",            # 10s — 防止 DDL 获取锁时无限阻塞
            "idle_in_transaction_session_timeout": "60000",  # 60s — 自动终止空闲事务
        },
    },
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
    attempts: int = 3,
    base_delay_seconds: float = 1.0,
    per_attempt_timeout: float = 15.0,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await asyncio.wait_for(operation(), timeout=per_attempt_timeout)
            if attempt > 1:
                logger.warning("%s 在第 %d 次尝试后成功", op_name, attempt)
            return
        except asyncio.TimeoutError:
            logger.warning(
                "%s 第 %d/%d 次执行超时（%.0fs），%s",
                op_name,
                attempt,
                attempts,
                per_attempt_timeout,
                "将重试" if attempt < attempts else "放弃",
            )
            if attempt >= attempts:
                raise
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
        delay = base_delay_seconds * attempt
        await asyncio.sleep(delay)


async def ensure_auth_schema_compat() -> None:
    """
    兼容旧库结构：确保 users.role 字段存在。
    历史库可能未执行 012_add_user_role.sql，登录查询会因缺列报错。
    连接失败时仅记录警告，不阻断服务启动（连接池预热后下次请求会自动重连）。

    优化：先用轻量 SELECT 检查列是否已存在，仅在缺失时执行 ALTER TABLE，
    避免每次启动都获取 AccessExclusiveLock。
    """
    async def _op():
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'users' AND column_name = 'role'
                    """
                )
            )
            if result.fetchone() is not None:
                logger.info("users.role 列已存在，跳过 ALTER TABLE")
                return

            logger.info("users.role 列缺失，执行 ALTER TABLE 添加...")
            await conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'resident'
                    """
                )
            )

    try:
        await _run_startup_db_op_with_retry("ensure_auth_schema_compat", _op)
    except Exception as exc:
        logger.warning("ensure_auth_schema_compat 失败，已跳过（不影响启动）: %s", exc)


async def ensure_daily_energy_summary_view() -> None:
    """
    启动时 DROP + 重建 daily_energy_summary 物化视图，确保列结构最新、数据已刷新。

    策略：每次启动都重建，保证：
      1. 新增列立即生效（无需手动跑 migration）
      2. 数据始终与 energy_data 同步（不会出现视图为空的情况）
    """
    async def _op():
        async with engine.begin() as conn:
            await conn.execute(
                text("DROP MATERIALIZED VIEW IF EXISTS daily_energy_summary")
            )
            await conn.execute(text("""
                CREATE MATERIALIZED VIEW daily_energy_summary AS
                SELECT
                    date_trunc('day', "timestamp")::date AS day,
                    building_id,
                    SUM(electricity_kwh)    AS total_electricity_kwh,
                    AVG(air_temp_c)         AS avg_ambient_temp,
                    SUM(water_m3)           AS total_water_m3,
                    SUM(hac_energy)         AS total_hac_energy,
                    AVG(sim_supply_temp_c)  AS avg_supply_temp,
                    AVG(sim_return_temp_c)  AS avg_return_temp,
                    AVG(humidity_rh_pct)    AS avg_humidity,
                    AVG(dew_temp_c)         AS avg_dew_temp
                FROM energy_data
                GROUP BY date_trunc('day', "timestamp")::date, building_id
                WITH DATA
            """))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_summary_day_building "
                "ON daily_energy_summary (day, building_id)"
            ))
            result = await conn.execute(
                text("SELECT COUNT(*) FROM daily_energy_summary")
            )
            cnt = result.scalar()
            logger.info(
                "daily_energy_summary 物化视图已重建并刷新，共 %d 行", cnt
            )

    try:
        await _run_startup_db_op_with_retry(
            "ensure_daily_energy_summary_view",
            _op,
            per_attempt_timeout=120.0,
        )
    except Exception as exc:
        logger.warning("创建/刷新 daily_energy_summary 失败，仍将使用工具降级。error=%s", exc)
