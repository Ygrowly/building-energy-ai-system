"""
Execute migrations/016_energy_data_source_timestamp.sql.

Usage:
    python backend/scripts/run_migration_016.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
import sqlalchemy

from app.db.session import engine

SQL_FILE = Path(__file__).resolve().parents[1] / "migrations" / "016_energy_data_source_timestamp.sql"


async def main():
    sql_text = SQL_FILE.read_text(encoding="utf-8")
    statements = []
    for raw in sql_text.split(";"):
        s = raw.strip()
        if not s:
            continue
        code_lines = [line for line in s.splitlines() if line.strip() and not line.strip().startswith("--")]
        if code_lines:
            statements.append(s)

    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(sqlalchemy.text(stmt))
                preview = stmt.replace("\n", " ")[:90]
                print(f"[OK] {preview}")
            except Exception as exc:
                print(f"[SKIP/ERROR] {str(exc)[:120]}")

    print("\n[DONE] Migration 016 complete: energy_data.source_timestamp added")


if __name__ == "__main__":
    asyncio.run(main())
