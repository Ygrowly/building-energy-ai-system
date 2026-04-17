"""检查真实数据库表结构与数据"""
import asyncio
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from app.core.config import get_settings
from app.db.session import _build_connect_args

get_settings.cache_clear()
settings = get_settings()

URL = settings.SYNC_DATABASE_URL or settings.DATABASE_URL.replace(
    "postgresql+asyncpg://",
    "postgresql://",
)
CONNECT_ARGS = {
    key: value
    for key, value in _build_connect_args(settings.DATABASE_URL).items()
    if key in {"ssl", "server_settings"}
}

async def main():
    conn = await asyncpg.connect(URL, **CONNECT_ARGS)

    print("=" * 60)
    print("buildings 表结构")
    cols = await conn.fetch("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name='buildings' ORDER BY ordinal_position
    """)
    for c in cols:
        print(f"  {c['column_name']:35s} {c['data_type']}")

    print("\nbuildings 所有数据:")
    rows = await conn.fetch("SELECT * FROM buildings")
    for r in rows:
        print(dict(r))

    print("\n" + "=" * 60)
    print("energy_data 表结构")
    cols2 = await conn.fetch("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name='energy_data' ORDER BY ordinal_position
    """)
    for c in cols2:
        print(f"  {c['column_name']:35s} {c['data_type']}")

    print("\nenergy_data 最新 2 条:")
    rows2 = await conn.fetch("SELECT * FROM energy_data ORDER BY timestamp DESC LIMIT 2")
    for r in rows2:
        print(dict(r))

    print("\n" + "=" * 60)
    print("daily_energy_summary 视图（或表）结构")
    try:
        cols3 = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name='daily_energy_summary' ORDER BY ordinal_position
        """)
        for c in cols3:
            print(f"  {c['column_name']:35s} {c['data_type']}")
        rows3 = await conn.fetch("SELECT * FROM daily_energy_summary LIMIT 2")
        for r in rows3:
            print(dict(r))
    except Exception as e:
        print(f"  出错: {e}")

    await conn.close()

asyncio.run(main())
