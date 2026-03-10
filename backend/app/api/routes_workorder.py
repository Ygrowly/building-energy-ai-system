"""
工单管理接口。

端点：
  POST /api/work-orders/approve       — 审批/驳回工单（从 routes_chat 迁移）
  GET  /api/work-orders               — 获取所有工单列表
  GET  /api/work-orders/{ticket_id}   — 获取单个工单详情
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/work-orders", tags=["工单"])

# ---------------------------------------------------------------------------
# 内存工单存储（演示级，生产环境应写入数据库）
# ---------------------------------------------------------------------------
_work_orders: dict[str, dict[str, Any]] = {}


def register_pending_order(order_data: dict[str, Any]) -> None:
    """从 Diagnose Agent 的 pending_action 注册待审批工单。"""
    ticket_id = order_data.get("ticket_id")
    if not ticket_id:
        return
    if ticket_id not in _work_orders:
        _work_orders[ticket_id] = {
            **order_data,
            "status": "pending_approval",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def get_pending_order(ticket_id: str) -> dict[str, Any] | None:
    return _work_orders.get(ticket_id)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class ApproveRequest(BaseModel):
    session_id: str
    ticket_id: str
    approved: bool = True
    reason: str | None = None


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@router.get("", summary="获取所有工单列表")
async def list_work_orders(
    status: str | None = Query(None, description="按状态过滤：pending_approval / approved / rejected"),
):
    """返回所有工单，支持按 status 过滤。"""
    orders = list(_work_orders.values())
    if status:
        orders = [o for o in orders if o.get("status") == status]
    orders.sort(key=lambda o: o.get("created_at", ""), reverse=True)
    return {"work_orders": orders, "total": len(orders)}


@router.get("/{ticket_id}", summary="获取单个工单详情")
async def get_work_order(ticket_id: str):
    """返回指定工单的详细信息。"""
    order = _work_orders.get(ticket_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")
    return order


@router.post("/approve", summary="审批工单")
async def approve_work_order(req: ApproveRequest):
    """
    审批/驳回工单。

    - approved=True  -> 工单状态改为 approved
    - approved=False -> 工单状态改为 rejected
    """
    from app.api.routes_chat import _sessions

    state = _sessions.get(req.session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    pending = state.get("pending_action")
    if not pending or pending.get("ticket_id") != req.ticket_id:
        order = _work_orders.get(req.ticket_id)
        if not order:
            raise HTTPException(status_code=400, detail="工单 ID 不匹配")

    now = datetime.now(timezone.utc).isoformat()

    if req.approved:
        if req.ticket_id in _work_orders:
            _work_orders[req.ticket_id]["status"] = "approved"
            _work_orders[req.ticket_id]["approved_at"] = now
        else:
            _work_orders[req.ticket_id] = {
                **(pending or {}),
                "status": "approved",
                "approved_at": now,
            }
        logger.info(
            "工单已批准 [%s]: 设备=%s, 优先级=%s",
            req.ticket_id,
            (pending or {}).get("device_id"),
            (pending or {}).get("priority"),
        )
        _sessions[req.session_id]["pending_action"] = None
        return {
            "status": "approved",
            "ticket_id": req.ticket_id,
            "message": f"工单 {req.ticket_id} 已批准，已推送至运维班组。",
        }
    else:
        if req.ticket_id in _work_orders:
            _work_orders[req.ticket_id]["status"] = "rejected"
            _work_orders[req.ticket_id]["rejected_at"] = now
            _work_orders[req.ticket_id]["reject_reason"] = req.reason
        else:
            _work_orders[req.ticket_id] = {
                **(pending or {}),
                "status": "rejected",
                "rejected_at": now,
                "reject_reason": req.reason,
            }
        _sessions[req.session_id]["pending_action"] = None
        return {
            "status": "rejected",
            "ticket_id": req.ticket_id,
            "message": f"工单 {req.ticket_id} 已驳回。",
            "reason": req.reason,
        }
