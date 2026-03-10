"""
pytest 根配置：为集成测试提供真实数据库 Session fixture。
单元测试不依赖此 fixture，集成测试通过 `db_session` 参数自动注入。

设计要点：
  - 使用 NullPool 禁用连接池，每个测试创建并立即释放独立连接，
    避免 asyncpg 在 event loop 切换时出现 "Event loop is closed" 错误。
"""
import pathlib
import ssl

import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# 确保在 fixture 初始化前加载 .env（解决 pydantic-settings 缓存问题）
load_dotenv(pathlib.Path(__file__).parent / ".env", override=True)

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
_settings = get_settings()

# 创建测试专用 engine（NullPool — 不缓存连接，每次独立建立/关闭）
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

_test_engine = create_async_engine(
    _settings.DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    connect_args={"ssl": _ssl_ctx},
)

_TestSession = async_sessionmaker(
    _test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncSession:
    """每个集成测试独立连接（NullPool），测试结束后立即关闭，避免 loop 冲突。"""
    async with _TestSession() as session:
        yield session
