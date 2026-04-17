"""临时测试脚本：验证 当前共享 PostgreSQL 连接"""
import asyncio
from pathlib import Path
import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from app.core.config import get_settings
from app.db.session import _build_connect_args

get_settings.cache_clear()
settings = get_settings()

POOL_URL = (
    settings.SYNC_DATABASE_URL
    or settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
)
CONNECT_ARGS = {
    key: value
    for key, value in _build_connect_args(settings.DATABASE_URL).items()
    if key in {"ssl", "server_settings"}
}

async def main():
    print("正在连接 当前共享 PostgreSQL ...")
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(POOL_URL, **CONNECT_ARGS),
            timeout=15,
        )
        print("✅ 连接成功！")

        row = await conn.fetchrow("SELECT version()")
        print("PG 版本:", row[0][:70])

        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        print(f"\n数据库表（共 {len(tables)} 张）:")
        for t in tables:
            print(f"  · {t['tablename']}")

        # 检查核心表行数
        for tbl in ["energy_data", "buildings", "daily_energy_summary"]:
            try:
                cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {tbl}")
                print(f"  {tbl}: {cnt} 行")
            except Exception as e:
                print(f"  {tbl}: 不存在或出错 ({e})")

        await conn.close()
    except asyncio.TimeoutError:
        print("❌ 超时（15s）：网络仍然不通")
    except Exception as e:
        print(f"❌ 连接失败: {type(e).__name__}: {e}")

asyncio.run(main())

