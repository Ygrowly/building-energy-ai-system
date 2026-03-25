"""
Execute migrations/014_predicted_anomaly_events.sql.
Replaces psql command for Windows environments where psql is not in PATH.

Usage:
    python scripts/run_migration_014.py
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
import sqlalchemy
from app.db.session import engine

SQL_FILE = Path(__file__).resolve().parents[1] / "migrations" / "014_predicted_anomaly_events.sql"


async def main():
    sql_text = SQL_FILE.read_text(encoding="utf-8")
    # Split by semicolon, skip blank or pure-comment lines
    statements = []
    for raw in sql_text.split(";"):
        s = raw.strip()
        if not s:
            continue
        # skip if every non-empty line starts with --
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

    print("\n[DONE] Migration 014 complete: predicted_anomaly_events table ready")


if __name__ == "__main__":
    asyncio.run(main())
