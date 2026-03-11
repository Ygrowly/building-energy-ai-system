"""
SSE 流式对话接口。

端点：
  POST /api/chat          — 发起新对话轮次，返回 SSE 流
  POST /api/chat/approve  — 人机协同：审批/驳回工单
  GET  /api/chat/history  — 获取对话历史（简化版，无持久化）

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
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field

from app.db.session import AsyncSessionLocal
from app.graph.state import initial_state
from app.graph.workflow import get_graph
from app.mcp.tools.data_query import list_available_buildings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["对话"])

# ---------------------------------------------------------------------------
# 简易内存会话存储（生产环境换 Redis）
# ---------------------------------------------------------------------------
_sessions: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    session_id: str | None = Field(None, description="会话 ID，为空则新建")


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
    """格式化为 SSE 行。"""
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


def _done_event(session_id: str, hop_count: int = 0) -> str:
    return _sse({
        "type": "done",
        "session_id": session_id,
        "hop_count": hop_count,
    })


# ---------------------------------------------------------------------------
# LangGraph 流式执行器
# ---------------------------------------------------------------------------
async def _stream_graph(
    session_id: str,
    user_message: str,
) -> AsyncGenerator[str, None]:
    """
    执行 LangGraph 图并将过程以 SSE 事件流方式推出。

    推送策略：
    - 图开始执行 → thinking 事件
    - 每个节点完成 → 对应 thinking/text 事件
    - ToolMessage → 解析 artifact，推 artifact 事件
    - AIMessage → 推 text 事件
    - 图执行完毕 → done 事件
    """
    # 取或新建会话状态（新会话时从 DB 查楼宇列表动态注入）
    if session_id not in _sessions:
        available_buildings: list[str] | None = None
        try:
            async with AsyncSessionLocal() as _db:
                result = await list_available_buildings(_db)
                available_buildings = [b.building_type for b in result.buildings]
        except Exception:
            pass  # DB 不可用时降级，RouterAgent 使用内置默认白名单
        _sessions[session_id] = initial_state(available_buildings=available_buildings)

    state = _sessions[session_id]
    state["messages"] = list(state["messages"]) + [HumanMessage(content=user_message)]

    yield _thinking_event("router", "正在分析您的请求...", hop_count=state.get("hop_count", 0))

    graph = get_graph()

    # 用于从流事件中收集最终状态（避免二次 ainvoke）
    final_state_holder: dict[str, Any] = {}

    # 性能计时器
    _t: dict[str, float] = {}
    _t["request"] = time.time()
    _tool_count = 0

    try:
        # astream_events 逐节点推流，同时从顶层 on_chain_end 捕获最终状态
        async for event in graph.astream_events(state, version="v2"):
            kind = event.get("event", "")
            name = event.get("name", "")
            data = event.get("data", {})

            # 节点开始
            if kind == "on_chain_start" and name in ("router", "data_agent", "diagnose_agent"):
                agent_label = {
                    "router": "路由分析",
                    "data_agent": "数据分析师",
                    "diagnose_agent": "故障诊断专家",
                }.get(name, name)
                _t[f"node_{name}"] = time.time()
                yield _thinking_event(name, f"{agent_label} 正在工作...", hop_count=state.get("hop_count", 0))

            # LLM 开始推理
            elif kind == "on_chat_model_start":
                agent_name = event.get("metadata", {}).get("langgraph_node", "")
                _t[f"llm_{agent_name}"] = time.time()
                if agent_name:
                    yield _thinking_event(agent_name, "正在推理...", hop_count=0)

            # LLM 推理完成（记录耗时）
            elif kind == "on_chat_model_end":
                agent_name = event.get("metadata", {}).get("langgraph_node", "")
                elapsed = time.time() - _t.pop(f"llm_{agent_name}", time.time())
                logger.info("LLM 推理完成: node=%s, 用时=%.2fs", agent_name, elapsed)

            # 工具调用开始
            elif kind == "on_tool_start":
                tool_name = name or data.get("name", "tool")
                _t[f"tool_{tool_name}_{_tool_count}"] = time.time()
                yield _thinking_event("tool", f"调用工具：{tool_name}", hop_count=0)

            # 工具调用结束 — 提取 artifact + 记录耗时
            elif kind == "on_tool_end":
                tool_key = f"tool_{name}_{_tool_count}"
                elapsed = time.time() - _t.pop(tool_key, time.time())
                _tool_count += 1
                logger.info("工具调用完成: %s, 用时=%.2fs", name, elapsed)
                raw_output = data.get("output", "")
                # 兼容 LangGraph 不同版本：output 可能是字符串、ToolMessage 或 dict
                if hasattr(raw_output, "content"):
                    output = raw_output.content  # ToolMessage 对象
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

            # 节点完成 — 只提取最后一条无工具调用的 AI 文本（避免中间推理污染最终答案）
            elif kind == "on_chain_end" and name in ("data_agent", "diagnose_agent", "router"):
                node_elapsed = time.time() - _t.pop(f"node_{name}", time.time())
                logger.info("节点完成: %s, 工具调用=%d, 用时=%.1fs", name, _tool_count, node_elapsed)
                output_messages = data.get("output", {}).get("messages", [])
                final_text: str | None = None
                for msg in reversed(output_messages):
                    if not isinstance(msg, AIMessage):
                        continue
                    # 兼容 content 为字符串或列表两种格式
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
                    # 跳过带工具调用的中间消息
                    if getattr(msg, "tool_calls", None):
                        continue
                    # 跳过路由内部标记消息
                    if name == "router" and "[Router]" in content:
                        continue
                    final_text = content
                    break
                if final_text:
                    yield _text_event(final_text, is_final=True)

            # 顶层图完成 — 捕获最终状态（name == "LangGraph" 或空字符串）
            elif kind == "on_chain_end" and name in ("LangGraph", ""):
                output = data.get("output")
                if isinstance(output, dict) and "messages" in output:
                    final_state_holder.update(output)

    except Exception as exc:
        logger.exception("图执行异常: %s", exc)
        yield _error_event(f"系统处理异常：{exc}")

    # 更新会话状态（用流中捕获的最终状态，无需二次 ainvoke）
    if final_state_holder:
        merged = dict(state)
        merged.update(final_state_holder)
        _sessions[session_id] = merged
        hop = merged.get("hop_count", 0)
        # 自动注册待审批工单到工单存储
        pa = merged.get("pending_action")
        if pa and pa.get("ticket_id"):
            from app.api.routes_workorder import register_pending_order
            register_pending_order(pa)
    else:
        # 极少数情况下未捕获到顶层事件，降级到 ainvoke（只会发生一次）
        try:
            fallback_state = await graph.ainvoke(state)
            _sessions[session_id] = fallback_state
            hop = fallback_state.get("hop_count", 0)
        except Exception as exc:
            logger.error("fallback ainvoke 失败: %s", exc)
            hop = state.get("hop_count", 0)

    total_elapsed = time.time() - _t.get("request", time.time())
    logger.info("请求完成: session=%s, 总工具调用=%d, 总用时=%.1fs", session_id, _tool_count, total_elapsed)
    yield _done_event(session_id, hop_count=hop)


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@router.post("/chat", response_class=StreamingResponse, summary="SSE 流式对话")
async def chat(req: ChatRequest):
    """
    接收用户消息，启动 LangGraph 并以 SSE 推流返回。

    前端读取示例（JavaScript）：
    ```js
    const es = new EventSource('/api/chat');
    es.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if (event.type === 'text') appendMessage(event.content);
      if (event.type === 'artifact') renderComponent(event);
      if (event.type === 'done') es.close();
    };
    ```
    """
    session_id = req.session_id or str(uuid.uuid4())

    return StreamingResponse(
        _stream_graph(session_id, req.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 禁用 Nginx 缓冲，确保实时推流
            "X-Session-Id": session_id,
        },
    )


@router.post("/chat/approve", summary="人机协同：审批工单（兼容旧路径，推荐使用 /api/work-orders/approve）")
async def approve_work_order_compat(req: ApproveRequest):
    """兼容旧接口路径，内部转发到工单模块。"""
    from app.api.routes_workorder import ApproveRequest as WOApproveReq, approve_work_order
    wo_req = WOApproveReq(
        session_id=req.session_id,
        ticket_id=req.ticket_id,
        approved=req.approved,
        reason=req.reason,
    )
    return await approve_work_order(wo_req)


@router.get("/chat/sessions/{session_id}", summary="获取会话摘要")
async def get_session(session_id: str):
    """返回指定会话的当前状态摘要（用于前端恢复上下文）。"""
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "session_id": session_id,
        "hop_count": state.get("hop_count", 0),
        "intent": state.get("intent"),
        "building_id": state.get("building_id"),
        "device_id": state.get("device_id"),
        "has_pending_action": state.get("pending_action") is not None,
        "message_count": len(state.get("messages", [])),
        "artifact_count": len(state.get("artifacts", [])),
    }


@router.get("/chat/sessions/{session_id}/messages", summary="获取对话消息历史")
async def get_session_messages(session_id: str):
    """
    返回指定会话的消息列表（role + content），供前端恢复对话上下文。
    仅返回 HumanMessage 和 AIMessage，过滤掉 ToolMessage 等内部消息。
    """
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = state.get("messages", [])
    result = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage) and msg.content:
            if "[Router]" in msg.content:
                continue
            result.append({"role": "assistant", "content": msg.content})

    return {
        "session_id": session_id,
        "messages": result,
        "total": len(result),
    }


@router.delete("/chat/sessions/{session_id}", summary="清除会话")
async def clear_session(session_id: str):
    """清除会话状态，用于重新开始对话。"""
    _sessions.pop(session_id, None)
    return {"status": "cleared", "session_id": session_id}
