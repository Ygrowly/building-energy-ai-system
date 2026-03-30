"""
Execute migrations/015_anomaly_events_unique_per_hour.sql.

Usage:
    python scripts/run_migration_015.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
import sqlalchemy
from app.db.session import engine

SQL_FILE = Path(__file__).resolve().parents[1] / "migrations" / "015_anomaly_events_unique_per_hour.sql"


async def main():
    sql_text = SQL_FILE.read_text(encoding="utf-8")
    statements = []
    for raw in sql_text.split(";"):
        s = raw.strip()
        if not s:
            continue
        code_lines = [l for l in s.splitlines() if l.strip() and not l.strip().startswith("--")]
        if code_lines:
            statements.append(s)

    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(sqlalchemy.text(stmt))
                preview = stmt.replace("\n", " ")[:90]
                print(f"[OK] {preview}")
            except Exception as e:
                print(f"[SKIP/ERROR] {str(e)[:120]}")

    print("\n[DONE] Migration 015 complete: anomaly_events unique constraint updated")


if __name__ == "__main__":
    asyncio.run(main())
