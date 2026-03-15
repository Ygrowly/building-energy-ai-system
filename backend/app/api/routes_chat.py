"""
SSE 流式对话接口 + 会话生命周期管理。

端点总览：
  POST   /api/chat                          — 发起新对话轮次，返回 SSE 流
  POST   /api/chat/approve                  — 人机协同：审批/驳回工单
  GET    /api/chat/sessions                 — 列出所有会话（支持归档过滤）
  POST   /api/chat/sessions                 — 预建命名会话
  GET    /api/chat/sessions/{id}            — 获取会话摘要（内存优先，DB 兜底）
  PATCH  /api/chat/sessions/{id}            — 重命名或更新绑定楼宇
  POST   /api/chat/sessions/{id}/archive    — 归档会话（软删除）
  DELETE /api/chat/sessions/{id}            — 物理删除会话
  GET    /api/chat/sessions/{id}/messages   — 获取消息历史

SSE 事件格式遵循 genui_protocol.py 规范：
  data: {"type": "thinking", ...}
  data: {"type": "text", ...}
  data: {"type": "artifact", ...}
  data: {"type": "error", ...}
  data: {"type": "done", ...}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import OrderedDict
from typing import Any, AsyncGenerator

import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings
from app.core.security import get_current_user_optional
from app.db.session import AsyncSessionLocal
from app.db.session_store import session_store
from app.graph.state import initial_state
from app.graph.workflow import get_graph
from app.mcp.tools.data_query import list_available_buildings
from app.schemas.genui_protocol import (
    SessionInfo,
    SessionListResponse,
    SessionCreateRequest,
    SessionUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["对话"])

# ---------------------------------------------------------------------------
# 有界会话缓存（LRU，防止内存无限增长）
# ---------------------------------------------------------------------------

class BoundedSessionCache:
    """LRU 会话缓存，超过 max_size 时淘汰最久未访问的条目。"""

    def __init__(self, max_size: int = 2000):
        self._data: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_size = max(max_size, 1)

    def get(self, key: str) -> dict[str, Any] | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __setitem__(self, key: str, value: dict[str, Any]) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        else:
            while len(self._data) >= self._max_size:
                self._data.popitem(last=False)
        self._data[key] = value

    def pop(self, key: str, default: Any = None) -> Any:
        return self._data.pop(key, default)

    def __getitem__(self, key: str) -> dict[str, Any]:
        if key not in self._data:
            raise KeyError(key)
        self._data.move_to_end(key)
        return self._data[key]


_sessions: BoundedSessionCache = BoundedSessionCache(max_size=2000)

# P3：简单内存限流（按 IP/用户，每分钟请求数）
_RATE_LIMIT_WINDOW = 60.0   # 秒
_RATE_LIMIT_MAX_PER_WINDOW = 30
_rate_limit_timestamps: dict[str, list[float]] = {}
_rate_limit_lock = asyncio.Lock()


async def _check_chat_rate_limit(request: Request, current_user: Any) -> None:
    """对话接口限流：同一用户/IP 每分钟最多 _RATE_LIMIT_MAX_PER_WINDOW 次。"""
    key = current_user.id if current_user else (request.client.host or "unknown")
    now = time.time()
    async with _rate_limit_lock:
        if key not in _rate_limit_timestamps:
            _rate_limit_timestamps[key] = []
        ts_list = _rate_limit_timestamps[key]
        ts_list.append(now)
        # 只保留窗口内的
        cutoff = now - _RATE_LIMIT_WINDOW
        _rate_limit_timestamps[key] = [t for t in ts_list if t > cutoff]
        if len(_rate_limit_timestamps[key]) > _RATE_LIMIT_MAX_PER_WINDOW:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"请求过于频繁，请 {int(_RATE_LIMIT_WINDOW)} 秒后再试",
            )


def _require_auth_in_production(current_user: Any) -> None:
    """生产环境下未登录则 401。"""
    if get_settings().APP_ENV == "production" and current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _check_session_access(row: Any, current_user: Any) -> None:
    """校验会话归属：有 current_user 时仅允许访问自己的会话或无主会话（user_id 为空）。"""
    if current_user is None:
        return
    if row is None:
        return
    session_user_id = getattr(row, "user_id", None)
    if session_user_id is None:
        return  # 历史无主会话允许访问
    if session_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该会话",
        )


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

# P3：session_id 格式与长度约束（与 DB chat_sessions.id 一致）
_SESSION_ID_MAX_LEN = 64
_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_session_id(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if len(v) > _SESSION_ID_MAX_LEN:
        raise ValueError(f"session_id 长度不得超过 {_SESSION_ID_MAX_LEN}")
    if not _SESSION_ID_PATTERN.match(v):
        raise ValueError("session_id 仅允许字母、数字、下划线、连字符")
    return v


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    session_id: str | None = Field(None, description="会话 ID，为空则新建")

    @field_validator("session_id")
    @classmethod
    def check_session_id(cls, v: str | None) -> str | None:
        return _validate_session_id(v)


class ApproveRequest(BaseModel):
    session_id: str
    ticket_id: str
    approved: bool = True
    reason: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    message: str = "流式响应已启动"


# ---------------------------------------------------------------------------
# SSE 事件构建工具
# ---------------------------------------------------------------------------

def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _thinking_event(agent: str, message: str, hop_count: int = 0) -> str:
    return _sse({
        "type": "thinking",
        "agent": agent,
        "message": message,
        "hop_count": hop_count,
    })


def _text_event(content: str, is_final: bool = False) -> str:
    return _sse({
        "type": "text",
        "content": content,
        "is_final": is_final,
    })


def _artifact_event(artifact: dict[str, Any]) -> str:
    return _sse({
        "type": "artifact",
        **artifact,
    })


def _error_event(message: str, tool_name: str | None = None) -> str:
    return _sse({
        "type": "error",
        "message": message,
        "tool_name": tool_name,
        "recoverable": True,
    })


def _done_event(session_id: str, hop_count: int = 0, request_id: str | None = None) -> str:
    payload: dict[str, Any] = {
        "type": "done",
        "session_id": session_id,
        "hop_count": hop_count,
    }
    if request_id:
        payload["request_id"] = request_id
    return _sse(payload)


# ---------------------------------------------------------------------------
# 内部：从内存/DB 加载或新建会话
# ---------------------------------------------------------------------------

async def _get_or_create_state(session_id: str) -> dict[str, Any]:
    """
    缓存优先策略：
      1. 内存命中 → 直接返回
      2. 内存未命中 → 尝试从 DB 恢复
      3. DB 无记录 → 新建初始状态并写入缓存
    """
    if session_id in _sessions:
        return _sessions[session_id]

    # 尝试从 DB 恢复
    recovered = await session_store.load_state(session_id)
    if recovered is not None:
        _sessions[session_id] = recovered
        logger.info("会话已从 DB 恢复: %s", session_id)
        return recovered

    # 全新会话：从 DB 查楼宇列表动态注入白名单
    available_buildings: list[str] | None = None
    try:
        async with AsyncSessionLocal() as _db:
            result = await list_available_buildings(_db)
            available_buildings = [b.building_type for b in result.buildings]
    except Exception:
        pass

    state = initial_state(available_buildings=available_buildings)
    _sessions[session_id] = state
    return state


def _build_session_info(row: Any, in_memory_state: dict[str, Any] | None = None) -> SessionInfo:
    """将 ChatSession ORM 行 + 可选内存状态组合为 SessionInfo。"""
    has_pending = False
    if in_memory_state:
        pa = in_memory_state.get("pending_action")
        has_pending = pa is not None and bool(pa.get("ticket_id"))

    return SessionInfo(
        session_id=row.id,
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
        message_count=row.message_count,
        last_message=row.last_message,
        building_id=row.building_id,
        is_archived=row.is_archived,
        has_pending_action=has_pending,
    )


# ---------------------------------------------------------------------------
# LangGraph 流式执行器
# ---------------------------------------------------------------------------

async def _stream_graph(
    session_id: str,
    user_message: str,
    user_id: str | None = None,
    request_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    执行 LangGraph 图并将过程以 SSE 事件流方式推出。
    每轮结束后异步持久化会话状态到 PostgreSQL。
    user_id：当前用户 ID，首次创建会话时写入归属。
    request_id：本请求追踪 ID，用于日志与 done 事件（P3 可观测性）。
    """
    request_id = request_id or str(uuid.uuid4())
    state = await _get_or_create_state(session_id)

    # 确保 DB 中存在该会话记录（首次发送消息时自动创建）
    db_row = await session_store.get(session_id)
    if db_row is None:
        await session_store.create(session_id, title="新对话", user_id=user_id)

    is_first_message = len(state.get("messages", [])) == 0

    state["messages"] = list(state["messages"]) + [HumanMessage(content=user_message)]

    yield _thinking_event("router", "正在分析您的请求...", hop_count=state.get("hop_count", 0))

    graph = get_graph()

    final_state_holder: dict[str, Any] = {}
    _t: dict[str, float] = {}
    _t["request"] = time.time()
    _tool_count = 0

    try:
        async for event in graph.astream_events(state, version="v2"):
            kind = event.get("event", "")
            name = event.get("name", "")
            data = event.get("data", {})

            if kind == "on_chain_start" and name in ("router", "data_agent", "diagnose_agent"):
                agent_label = {
                    "router": "路由分析",
                    "data_agent": "数据分析师",
                    "diagnose_agent": "故障诊断专家",
                }.get(name, name)
                _t[f"node_{name}"] = time.time()
                yield _thinking_event(name, f"{agent_label} 正在工作...", hop_count=state.get("hop_count", 0))

            elif kind == "on_chat_model_start":
                agent_name = event.get("metadata", {}).get("langgraph_node", "")
                _t[f"llm_{agent_name}"] = time.time()
                if agent_name:
                    yield _thinking_event(agent_name, "正在推理...", hop_count=0)

            elif kind == "on_chat_model_end":
                agent_name = event.get("metadata", {}).get("langgraph_node", "")
                elapsed = time.time() - _t.pop(f"llm_{agent_name}", time.time())
                logger.info("LLM 推理完成: node=%s, 用时=%.2fs", agent_name, elapsed)

            elif kind == "on_tool_start":
                tool_name = name or data.get("name", "tool")
                _t[f"tool_{tool_name}_{_tool_count}"] = time.time()
                yield _thinking_event("tool", f"调用工具：{tool_name}", hop_count=0)

            elif kind == "on_tool_end":
                tool_key = f"tool_{name}_{_tool_count}"
                elapsed = time.time() - _t.pop(tool_key, time.time())
                _tool_count += 1
                logger.info("工具调用完成: %s, 用时=%.2fs", name, elapsed)
                raw_output = data.get("output", "")
                if hasattr(raw_output, "content"):
                    output = raw_output.content
                elif isinstance(raw_output, dict):
                    try:
                        output = json.dumps(raw_output, ensure_ascii=False, default=str)
                    except Exception:
                        output = ""
                else:
                    output = str(raw_output) if raw_output else ""
                if output:
                    try:
                        parsed = json.loads(output)
                        if "component_type" in parsed or "widget" in parsed:
                            yield _artifact_event(parsed)
                        elif parsed.get("status") == "pending_approval":
                            yield _artifact_event({
                                "widget": "WorkOrderCard",
                                "component_type": "WorkOrderCard",
                                "title": "维修工单待确认",
                                "data_payload": parsed,
                                "source_info": {"tool": "create_work_order_draft"},
                            })
                    except (json.JSONDecodeError, TypeError):
                        pass

            elif kind == "on_chain_end" and name in ("data_agent", "diagnose_agent", "router"):
                node_elapsed = time.time() - _t.pop(f"node_{name}", time.time())
                logger.info("节点完成: %s, 工具调用=%d, 用时=%.1fs", name, _tool_count, node_elapsed)
                output_messages = data.get("output", {}).get("messages", [])
                final_text: str | None = None
                for msg in reversed(output_messages):
                    if not isinstance(msg, AIMessage):
                        continue
                    if isinstance(msg.content, str):
                        content = msg.content
                    elif isinstance(msg.content, list):
                        content = "".join(
                            c.get("text", "") for c in msg.content if isinstance(c, dict)
                        )
                    else:
                        content = ""
                    if not content.strip():
                        continue
                    if getattr(msg, "tool_calls", None):
                        continue
                    if name == "router" and "[Router]" in content:
                        continue
                    final_text = content
                    break
                if final_text:
                    yield _text_event(final_text, is_final=True)

            elif kind == "on_chain_end" and name in ("LangGraph", ""):
                output = data.get("output")
                if isinstance(output, dict) and "messages" in output:
                    final_state_holder.update(output)

    except Exception as exc:
        logger.exception("图执行异常: %s", exc)
        # 生产安全：不向客户端回传内部错误详情，仅写日志
        yield _error_event("系统处理异常，请稍后重试")

    # 更新内存会话状态
    if final_state_holder:
        merged = dict(state)
        merged.update(final_state_holder)
        _sessions[session_id] = merged
        hop = merged.get("hop_count", 0)
        pa = merged.get("pending_action")
        if pa and pa.get("ticket_id"):
            from app.api.routes_workorder import register_pending_order
            register_pending_order(pa)
    else:
        try:
            fallback_state = await graph.ainvoke(state)
            _sessions[session_id] = fallback_state
            merged = fallback_state
            hop = fallback_state.get("hop_count", 0)
        except Exception as exc:
            logger.error("fallback ainvoke 失败: %s", exc)
            merged = state
            hop = state.get("hop_count", 0)

    total_elapsed = time.time() - _t.get("request", time.time())
    logger.info(
        "请求完成: request_id=%s session=%s 工具调用=%d 用时=%.1fs",
        request_id, session_id, _tool_count, total_elapsed,
    )

    # 异步持久化（不阻塞 SSE 流，P2：done_callback 记录异常避免静默失败）
    _persist_task = asyncio.create_task(_persist_session(
        session_id=session_id,
        state=merged,
        user_message=user_message,
        is_first_message=is_first_message,
    ))
    def _on_persist_done(t: asyncio.Task[None]) -> None:
        try:
            t.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("会话持久化后台任务异常: session=%s, error=%s", session_id, exc)
    _persist_task.add_done_callback(_on_persist_done)

    yield _done_event(session_id, hop_count=hop, request_id=request_id)


async def _persist_session(
    session_id: str,
    state: dict[str, Any],
    user_message: str,
    is_first_message: bool,
) -> None:
    """
    将会话状态持久化到 DB，并在首条消息时自动生成标题。
    作为后台任务执行，不影响 SSE 推流延迟。
    """
    try:
        await session_store.save_state(
            session_id=session_id,
            state=state,
            last_message=user_message,
        )
        # 首条消息：自动用消息摘要作为会话标题
        if is_first_message:
            auto_title = user_message[:30] + ("…" if len(user_message) > 30 else "")
            await session_store.update(session_id, title=auto_title)
            logger.debug("会话标题自动更新: %s → %s", session_id, auto_title)
    except Exception as exc:
        logger.error("会话持久化任务失败 %s: %s", session_id, exc)


# ---------------------------------------------------------------------------
# 路由：对话核心
# ---------------------------------------------------------------------------

@router.post("/chat", response_class=StreamingResponse, summary="SSE 流式对话")
async def chat(
    request: Request,
    req: ChatRequest,
    current_user: Any = Depends(get_current_user_optional),
):
    """
    接收用户消息，启动 LangGraph 并以 SSE 推流返回。
    生产环境需登录；开发环境可不带 Token。限流：同一用户/IP 每分钟最多 30 次。
    """
    _require_auth_in_production(current_user)
    await _check_chat_rate_limit(request, current_user)
    session_id = req.session_id or str(uuid.uuid4())
    user_id = current_user.id if current_user else None
    request_id = str(uuid.uuid4())

    return StreamingResponse(
        _stream_graph(session_id, req.message, user_id=user_id, request_id=request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session_id,
        },
    )


@router.post("/chat/approve", summary="人机协同：审批工单（兼容旧路径）")
async def approve_work_order_compat(
    req: ApproveRequest,
    current_user: Any = Depends(get_current_user_optional),
):
    """兼容旧接口路径，内部转发到工单模块。生产环境需登录并校验会话归属。"""
    _require_auth_in_production(current_user)
    row = await session_store.get(req.session_id)
    _check_session_access(row, current_user)
    from app.api.routes_workorder import ApproveRequest as WOApproveReq, approve_work_order
    wo_req = WOApproveReq(
        session_id=req.session_id,
        ticket_id=req.ticket_id,
        approved=req.approved,
        reason=req.reason,
    )
    return await approve_work_order(wo_req)


# ---------------------------------------------------------------------------
# 路由：会话列表与管理
# ---------------------------------------------------------------------------

@router.get("/chat/sessions", response_model=SessionListResponse, summary="列出所有会话")
async def list_sessions(
    include_archived: bool = Query(False, description="是否包含已归档的会话"),
    current_user: Any = Depends(get_current_user_optional),
):
    """
    返回当前用户的会话列表（生产环境需登录，仅返回归属本人的会话）。
    """
    _require_auth_in_production(current_user)
    user_id = current_user.id if current_user else None
    rows = await session_store.list_all(include_archived=include_archived, user_id=user_id)
    sessions = [
        _build_session_info(row, _sessions.get(row.id))
        for row in rows
    ]
    return SessionListResponse(sessions=sessions, total=len(sessions))


@router.post("/chat/sessions", response_model=SessionInfo, summary="预建命名会话")
async def create_session(
    req: SessionCreateRequest,
    current_user: Any = Depends(get_current_user_optional),
):
    """
    预先创建一个命名会话。生产环境需登录，会话归属当前用户。
    """
    _require_auth_in_production(current_user)
    session_id = str(uuid.uuid4())
    title = req.title or "新对话"
    user_id = current_user.id if current_user else None
    row = await session_store.create(session_id, title=title, user_id=user_id)
    if row is None:
        raise HTTPException(status_code=500, detail="会话创建失败，请检查数据库连接")
    return _build_session_info(row)


@router.get("/chat/sessions/{session_id}", summary="获取会话摘要")
async def get_session(
    session_id: str = Path(..., max_length=_SESSION_ID_MAX_LEN, pattern=r"^[a-zA-Z0-9_-]+$"),
    current_user: Any = Depends(get_current_user_optional),
):
    """
    返回指定会话的元数据摘要。生产环境需登录且仅能访问本人会话。
    """
    _require_auth_in_production(current_user)
    row = await session_store.get(session_id)
    _check_session_access(row, current_user)
    in_memory = _sessions.get(session_id)

    if row is None and in_memory is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    if row is not None:
        return _build_session_info(row, in_memory)

    # 仅在内存中（还未持久化的极短会话），降级返回内存摘要
    return {
        "session_id": session_id,
        "title": "新对话",
        "hop_count": in_memory.get("hop_count", 0),
        "intent": in_memory.get("intent"),
        "building_id": in_memory.get("building_id"),
        "has_pending_action": in_memory.get("pending_action") is not None,
        "message_count": len(in_memory.get("messages", [])),
        "artifact_count": len(in_memory.get("artifacts", [])),
        "is_archived": False,
    }


@router.patch("/chat/sessions/{session_id}", response_model=SessionInfo, summary="重命名或更新会话")
async def update_session(
    session_id: str = Path(..., max_length=_SESSION_ID_MAX_LEN, pattern=r"^[a-zA-Z0-9_-]+$"),
    req: SessionUpdateRequest,
    current_user: Any = Depends(get_current_user_optional),
):
    """
    更新会话元数据。生产环境需登录且仅能操作本人会话。
    """
    _require_auth_in_production(current_user)
    row = await session_store.get(session_id)
    _check_session_access(row, current_user)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    # 处理 building_id 空字符串（表示清除绑定）
    building_id = req.building_id
    if building_id == "":
        building_id = None

    row = await session_store.update(
        session_id,
        title=req.title,
        building_id=building_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 若内存中存在且传入了 building_id，同步更新内存状态
    if req.building_id is not None and session_id in _sessions:
        _sessions[session_id]["building_id"] = building_id or _sessions[session_id].get("building_id")

    return _build_session_info(row, _sessions.get(session_id))


@router.post("/chat/sessions/{session_id}/archive", response_model=SessionInfo, summary="归档会话")
async def archive_session(
    session_id: str = Path(..., max_length=_SESSION_ID_MAX_LEN, pattern=r"^[a-zA-Z0-9_-]+$"),
    current_user: Any = Depends(get_current_user_optional),
):
    """
    软删除会话。生产环境需登录且仅能操作本人会话。
    """
    _require_auth_in_production(current_user)
    row = await session_store.get(session_id)
    _check_session_access(row, current_user)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    row = await session_store.archive(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 从内存缓存移除，释放资源
    _sessions.pop(session_id, None)

    return _build_session_info(row)


@router.delete("/chat/sessions/{session_id}", summary="物理删除会话")
async def clear_session(
    session_id: str = Path(..., max_length=_SESSION_ID_MAX_LEN, pattern=r"^[a-zA-Z0-9_-]+$"),
    current_user: Any = Depends(get_current_user_optional),
):
    """
    物理删除会话。生产环境需登录且仅能操作本人会话。
    """
    _require_auth_in_production(current_user)
    row = await session_store.get(session_id)
    _check_session_access(row, current_user)
    # 允许删除无 DB 记录的会话（仅内存或已过期）
    _sessions.pop(session_id, None)
    await session_store.delete(session_id)
    return {"status": "deleted", "session_id": session_id}


@router.get("/chat/sessions/{session_id}/messages", summary="获取对话消息历史")
async def get_session_messages(
    session_id: str = Path(..., max_length=_SESSION_ID_MAX_LEN, pattern=r"^[a-zA-Z0-9_-]+$"),
    current_user: Any = Depends(get_current_user_optional),
):
    """
    返回指定会话的消息列表。生产环境需登录且仅能访问本人会话。
    """
    _require_auth_in_production(current_user)
    row = await session_store.get(session_id)
    _check_session_access(row, current_user)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    state = _sessions.get(session_id)
    if state is None:
        state = await session_store.load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = state.get("messages", [])
    result = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage) and msg.content:
            if "[Router]" in str(msg.content):
                continue
            result.append({"role": "assistant", "content": msg.content})

    return {
        "session_id": session_id,
        "messages": result,
        "total": len(result),
    }
