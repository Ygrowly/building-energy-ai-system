"""
工单审计日志服务。

这里集中处理 work_order_audit_log 的写入，避免审批、派工、大厅等流程各自
手写审计记录。调用方仍负责 commit/rollback。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkOrderAuditLog


async def write_work_order_audit_log(
    db: AsyncSession,
    *,
    work_order_id: str,
    action: str,
    old_status: str | None,
    new_status: str,
    actor_type: str,
    actor_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> WorkOrderAuditLog:
    log_entry = WorkOrderAuditLog(
        work_order_id=work_order_id,
        action=action,
        old_status=old_status,
        new_status=new_status,
        actor_type=actor_type,
        actor_id=actor_id,
        detail_json=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
    )
    db.add(log_entry)
    return log_entry
