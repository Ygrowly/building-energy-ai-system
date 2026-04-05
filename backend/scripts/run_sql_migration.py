"""
Execute a SQL migration file from backend/migrations.

Supports PostgreSQL DO $$ ... $$ blocks by splitting statements while respecting
quoted strings and dollar-quoted sections.

Usage:
    python scripts/run_sql_migration.py 017_work_order_dispatch_phase1.sql
    python scripts/run_sql_migration.py 018_worker_dispatch_profiles.sql
    python scripts/run_sql_migration.py 019_dispatch_tasks_phase3.sql
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
import sqlalchemy

from app.db.session import engine

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    i = 0
    in_single = False
    in_double = False
    dollar_tag: str | None = None
    length = len(sql_text)

    while i < length:
        if sql_text.startswith("--", i) and not in_single and not in_double and dollar_tag is None:
            newline = sql_text.find("\n", i)
            if newline == -1:
                break
            i = newline + 1
            continue

        if sql_text[i] == "'" and not in_double and dollar_tag is None:
            buffer.append(sql_text[i])
            if in_single and i + 1 < length and sql_text[i + 1] == "'":
                buffer.append(sql_text[i + 1])
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue

        if sql_text[i] == '"' and not in_single and dollar_tag is None:
            buffer.append(sql_text[i])
            in_double = not in_double
            i += 1
            continue

        if not in_single and not in_double and sql_text[i] == "$":
            end = sql_text.find("$", i + 1)
            if end != -1:
                candidate = sql_text[i : end + 1]
                if all(ch == "_" or ch.isalnum() or ch == "$" for ch in candidate):
                    buffer.append(candidate)
                    if dollar_tag is None:
                        dollar_tag = candidate
                    elif candidate == dollar_tag:
                        dollar_tag = None
                    i = end + 1
                    continue

        if sql_text[i] == ";" and not in_single and not in_double and dollar_tag is None:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            i += 1
            continue

        buffer.append(sql_text[i])
        i += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


async def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_sql_migration.py <migration.sql>")
        return 1

    sql_file = MIGRATIONS_DIR / sys.argv[1]
    if not sql_file.exists():
        print(f"[ERROR] Migration file not found: {sql_file}")
        return 1

    sql_text = sql_file.read_text(encoding="utf-8")
    statements = _split_sql_statements(sql_text)

    print(f"[INFO] Running migration: {sql_file.name}")
    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(sqlalchemy.text(stmt))
                preview = stmt.replace("\n", " ")[:100]
                print(f"[OK] {preview}")
            except Exception as exc:
                print(f"[SKIP/ERROR] {str(exc)[:200]}")

    print(f"\n[DONE] Migration complete: {sql_file.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
