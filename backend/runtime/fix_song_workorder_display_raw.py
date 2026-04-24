from __future__ import annotations

import asyncio
import json
from pathlib import Path

import asyncpg


ROOT = Path(__file__).resolve().parents[1]
TICKET_ID = "WO-20260422-084055-705EB6"
EVENT_ID = "ef3364de-d04d-4fc6-b1e1-e17da2f09ba3"

ISSUE_DESCRIPTION = (
    "[办公楼] 2026-04-22 08:40 检测到空调能耗异常："
    "供回水温差偏小，疑似水力失调或末端阀门开度异常；"
    "实际=98.2 kWh，预期=42.5 kWh，偏差 +131.1%。"
)
SUGGESTED_ACTION = (
    "按 B_small_deltaT / valve_operation_issue 经验处理："
    "核对水泵运行频率与末端阀门开度，检查压差旁通阀控制逻辑，"
    "排查末端过滤器/水阀堵塞，处理后复测供回水温差。"
)
EVENT_MESSAGE = (
    "办公楼当前空调能耗异常，实际 98.20 kWh，期望 42.50 kWh"
    "（偏差 +131.06%），异常类型：供回水小温差/水力失调。"
)
ASSIGN_NOTE = (
    "指定派给宋工：供回水小温差/末端阀门开度异常相关，"
    "对应经验库的 B_small_deltaT 和 valve_operation_issue。"
)


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _dsn() -> str:
    env = _load_env()
    dsn = env.get("SYNC_DATABASE_URL") or env.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("backend/.env 缺少 DATABASE_URL")
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def _payload(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def main() -> None:
    conn = await asyncpg.connect(dsn=_dsn(), timeout=20, command_timeout=20)
    try:
        await conn.execute("set lock_timeout = '3s'")
        await conn.execute("set statement_timeout = '15s'")

        async def fetchrow_step(name: str, sql: str, *args):
            try:
                return await asyncio.wait_for(conn.fetchrow(sql, *args), timeout=20)
            except Exception as exc:
                raise RuntimeError(f"{name} 失败：{exc}") from exc

        async def fetch_step(name: str, sql: str, *args) -> list[asyncpg.Record]:
            try:
                rows = await asyncio.wait_for(conn.fetch(sql, *args), timeout=20)
                print(f"[ok] {name}: {len(rows)}")
                return list(rows)
            except Exception as exc:
                print(f"[skip] {name}: {exc}")
                return []

        async def execute_step(name: str, sql: str, *args, required: bool = False) -> bool:
            try:
                status = await asyncio.wait_for(conn.execute(sql, *args), timeout=20)
                print(f"[ok] {name}: {status}")
                return True
            except Exception as exc:
                if required:
                    raise RuntimeError(f"{name} 失败：{exc}") from exc
                print(f"[skip] {name}: {exc}")
                return False

        work_order = await fetchrow_step(
            "查询工单",
            "select id, incident_id from work_orders where ticket_id = $1",
            TICKET_ID,
        )
        if not work_order:
            raise RuntimeError(f"未找到工单：{TICKET_ID}")

        work_order_id = work_order["id"]
        incident_id = work_order["incident_id"]

        await execute_step(
            "修复工单描述",
            """
            update work_orders
               set issue_description = $1,
                   suggested_action = $2,
                   worker_notes = $3,
                   updated_at = now()
             where id = $4
            """,
            ISSUE_DESCRIPTION,
            SUGGESTED_ACTION,
            ASSIGN_NOTE,
            work_order_id,
            required=True,
        )
        await execute_step(
            "修复 incident 摘要",
            """
            update anomaly_incidents
               set summary_text = $1,
                   latest_dispatch_note = $2,
                   updated_at = now()
             where id = $3
            """,
            ISSUE_DESCRIPTION,
            ASSIGN_NOTE,
            incident_id,
        )
        await execute_step(
            "修复异常事件消息",
            "update anomaly_events set message = $1 where id = $2::uuid",
            EVENT_MESSAGE,
            EVENT_ID,
        )
        await execute_step(
            "修复派工说明",
            """
            update dispatch_tasks
               set selection_reason = $1,
                   latest_note = $1,
                   updated_at = now()
             where work_order_id = $2
            """,
            ASSIGN_NOTE,
            work_order_id,
        )

        dispatch_rows = await fetch_step(
            "查询派工快照",
            "select id, candidate_snapshot_json from dispatch_tasks where work_order_id = $1",
            work_order_id,
        )
        for row in dispatch_rows:
            snapshot = _payload(row["candidate_snapshot_json"])
            if snapshot:
                snapshot["selection_reason"] = ASSIGN_NOTE
                snapshot["recommended_assignee"] = "宋工"
                await execute_step(
                    "修复派工快照",
                    "update dispatch_tasks set candidate_snapshot_json = $1 where id = $2",
                    json.dumps(snapshot, ensure_ascii=False),
                    row["id"],
                )

        notification_rows = await fetch_step(
            "查询通知",
            """
            select id, event_type, title, body, payload_json
              from notification_records
             where aggregate_type = 'work_order'
               and aggregate_id = $1
            """,
            work_order_id,
        )
        for row in notification_rows:
            payload = _payload(row["payload_json"])
            payload["ticket_id"] = TICKET_ID
            payload["work_order_id"] = work_order_id
            cta_params = payload.get("cta_params")
            if isinstance(cta_params, dict):
                cta_params["ticket_id"] = TICKET_ID

            title = row["title"]
            body = row["body"]
            if row["event_type"] == "create" or "待审核" in title:
                title = f"{TICKET_ID} 待审核"
                body = f"工单 {TICKET_ID} 已创建，等待审核。"
            elif row["event_type"] in {"assigned", "auto_assigned"} or "已派单" in title:
                title = f"{TICKET_ID} 已派单"
                body = "工单已派发给 宋工。"

            await execute_step(
                "修复通知",
                """
                update notification_records
                   set title = $1,
                       body = $2,
                       payload_json = $3
                 where id = $4
                """,
                title,
                body,
                json.dumps(payload, ensure_ascii=False),
                row["id"],
            )

        check = await conn.fetchrow(
            """
            select issue_description, status, priority
              from work_orders
             where ticket_id = $1
            """,
            TICKET_ID,
        )
        dispatch = await conn.fetchrow(
            """
            select dispatch_status
              from dispatch_tasks
             where work_order_id = (
                select id from work_orders where ticket_id = $1
             )
               and is_current = true
            """,
            TICKET_ID,
        )
        print(f"问题描述：{check['issue_description']}")
        print("摘要预览：")
        print(f"工单 {TICKET_ID} 当前状态为 已派单，优先级为 高。")
        print(f"当前派工：第 1 次，状态 待接单，责任人 宋工。")
        print(f"raw_status={check['status']} raw_priority={check['priority']} raw_dispatch={dispatch['dispatch_status']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
