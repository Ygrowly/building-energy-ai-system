"""
Prepare known test accounts for dispatch-system verification.

Default behavior:
  - ensure `test1` is `manager`
  - ensure `test2` is `ops`
  - reset both passwords to a known value
  - ensure the ops user has a default worker_profile

Usage:
    python scripts/prepare_dispatch_test_users.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.core.security import hash_password
from app.db.session import engine

MANAGER_USERNAME = "test1"
OPS_USERNAME = "test2"
RESET_PASSWORD = "test1234"


async def main() -> int:
    manager_hash = hash_password(RESET_PASSWORD)
    ops_hash = hash_password(RESET_PASSWORD)

    async with engine.begin() as conn:
        manager_result = await conn.execute(
            text("SELECT id FROM users WHERE username = :username"),
            {"username": MANAGER_USERNAME},
        )
        manager_id = manager_result.scalar_one_or_none()
        if manager_id is None:
            print(f"[ERROR] manager user not found: {MANAGER_USERNAME}")
            return 1

        ops_result = await conn.execute(
            text("SELECT id FROM users WHERE username = :username"),
            {"username": OPS_USERNAME},
        )
        ops_id = ops_result.scalar_one_or_none()
        if ops_id is None:
            print(f"[ERROR] ops user not found: {OPS_USERNAME}")
            return 1

        await conn.execute(
            text(
                """
                UPDATE users
                SET role = 'manager',
                    is_active = TRUE,
                    hashed_password = :password
                WHERE id = :user_id
                """
            ),
            {"user_id": manager_id, "password": manager_hash},
        )
        print(f"[OK] manager ready: {MANAGER_USERNAME}")

        await conn.execute(
            text(
                """
                UPDATE users
                SET role = 'ops',
                    is_active = TRUE,
                    hashed_password = :password
                WHERE id = :user_id
                """
            ),
            {"user_id": ops_id, "password": ops_hash},
        )
        print(f"[OK] ops ready: {OPS_USERNAME}")

        await conn.execute(
            text(
                """
                INSERT INTO worker_profiles (
                    user_id,
                    team_id,
                    job_title,
                    shift_status,
                    dispatch_enabled,
                    max_active_orders,
                    accepts_emergency,
                    service_buildings_json,
                    notes
                )
                SELECT
                    :user_id,
                    'team_ops_general',
                    '维修工程师',
                    'on_duty',
                    TRUE,
                    4,
                    TRUE,
                    '[]',
                    '由派单联调脚本补齐默认画像'
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM worker_profiles wp
                    WHERE wp.user_id = :user_id
                )
                """
            ),
            {"user_id": ops_id},
        )
        print(f"[OK] ops worker_profile ensured: {OPS_USERNAME}")

    print("")
    print("[DONE] dispatch test users are ready")
    print(f"manager: username={MANAGER_USERNAME} password={RESET_PASSWORD}")
    print(f"ops:     username={OPS_USERNAME} password={RESET_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
