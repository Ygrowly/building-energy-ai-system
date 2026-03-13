"""
pytest 根配置：为集成测试提供真实数据库 Session fixture。
单元测试不依赖此 fixture，集成测试通过 `db_session` 参数自动注入。

设计要点：
  - 使用 NullPool 禁用连接池，每个测试创建并立即释放独立连接，
    避免 asyncpg 在 event loop 切换时出现 "Event loop is closed" 错误。
  - 引擎懒加载：只有集成测试（使用 db_session fixture）才会真正连接数据库，
    单元测试和 mock API 测试无需 asyncpg 即可正常运行。
"""
from __future__ import annotations

import pathlib
import ssl

import pytest_asyncio
from dotenv import load_dotenv

# 确保在 fixture 初始化前加载 .env（解决 pydantic-settings 缓存问题）
load_dotenv(pathlib.Path(__file__).parent / ".env", override=True)

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()


def _build_test_engine():
    """懒加载：只在集成测试 fixture 第一次被请求时才创建引擎。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    _settings = get_settings()
    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE

    return create_async_engine(
        _settings.DATABASE_URL,
        echo=False,
        poolclass=NullPool,
        connect_args={"ssl": _ssl_ctx},
    )


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """
    每个集成测试独立连接（NullPool），测试结束后立即关闭，避免 loop 冲突。
    只有标注了 @pytest.mark.integration 并使用此 fixture 的测试才会触发数据库连接。
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    engine = _build_test_engine()
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()
