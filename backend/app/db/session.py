"""
数据库连接池：异步 SQLAlchemy 2.0 引擎 + Session 工厂。
FastAPI 依赖注入用 get_db_session()；工具函数直接用 AsyncSessionLocal。
"""
import ssl
from collections.abc import AsyncGenerator

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

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends 注入用。每次请求独立 Session，请求结束自动关闭。"""
    async with AsyncSessionLocal() as session:
        yield session
