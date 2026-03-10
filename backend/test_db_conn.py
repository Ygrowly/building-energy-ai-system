"""临时测试脚本：验证 Supabase Session Pooler 连接"""
import asyncio
import ssl
import asyncpg

POOL_URL = (
    "postgresql://postgres.qbtwwbkqlwwhchlbzwis:bhzd!FWWB!01"
    "@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"
)

async def main():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    print("正在连接 Supabase Session Pooler ...")
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(POOL_URL, ssl=ctx),
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
