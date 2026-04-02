"""
会话持久化服务（Session Store）。

职责：将 LangGraph AgentState 序列化/反序列化，与 PostgreSQL chat_sessions 表交互。
所有方法均为 async，内部使用 AsyncSessionLocal 独立管理事务，不依赖外部 DB Session。

调用方（routes_chat.py）不需要感知 DB 细节，只需：
    store = SessionStore()
    await store.save_state(session_id, state, last_message="用户说了什么")
    state = await store.load_state(session_id)  # 返回 None 表示不存在
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, delete
from langchain_core.messages import messages_to_dict, messages_from_dict

from app.db.chat_models import ChatSession
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# AgentState 中可直接 JSON 序列化的字段（跳过 messages，单独处理）
_SERIALIZABLE_STATE_KEYS = (
    "current_agent",
    "intent",
    "confidence",
    "hop_count",
    "building_id",
    "time_context",
    "device_id",
    "evidence",
    "artifacts",
    "available_buildings",
    "context_summary",
    "chart_manifest",
    "react_data_summary",
    "thinking_mode",
    "enable_web_search",
    "needs_diagnosis",
    "error",
)


def _serialize_state(state: dict[str, Any]) -> tuple[str, str]:
    """
    将 AgentState 拆成两部分序列化：
      - messages_json: LangChain messages_to_dict() 结果
      - extra_state_json: 其余可序列化字段

    返回 (messages_json, extra_state_json)
    """
    # 消息序列化
    try:
        msgs = messages_to_dict(state.get("messages", []))
        messages_json = json.dumps(msgs, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.warning("消息序列化失败，降级为空消息: %s", exc)
        messages_json = "[]"

    # 其余状态字段
    extra: dict[str, Any] = {}
    for key in _SERIALIZABLE_STATE_KEYS:
        val = state.get(key)
        if val is not None:
            try:
                json.dumps(val, default=str)  # 可序列化性预检
                extra[key] = val
            except Exception:
                pass  # 跳过不可序列化字段

    # pending_action 单独尝试
    pa = state.get("pending_action")
    if pa:
        try:
            json.dumps(pa, default=str)
            extra["pending_action"] = pa
        except Exception:
            pass

    extra_state_json = json.dumps(extra, ensure_ascii=False, default=str)
    return messages_json, extra_state_json


def _deserialize_state(messages_json: str | None, extra_state_json: str | None) -> dict[str, Any]:
    """
    从数据库存储的 JSON 字符串恢复 AgentState。
    """
    from app.graph.state import initial_state

    state = initial_state()

    # 恢复消息
    if messages_json:
        try:
            msgs_dict = json.loads(messages_json)
            state["messages"] = messages_from_dict(msgs_dict)
        except Exception as exc:
            logger.warning("消息反序列化失败，使用空消息: %s", exc)

    # 恢复其余状态
    if extra_state_json:
        try:
            extra = json.loads(extra_state_json)
            for key, val in extra.items():
                state[key] = val
        except Exception as exc:
            logger.warning("额外状态反序列化失败: %s", exc)

    return state


class SessionStore:
    """
    多智能体会话的持久化 CRUD 服务。

    所有方法静默处理 DB 异常（记录日志后返回 None/False），
    确保持久化层故障不影响核心对话流程。
    """

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    async def create(
        self,
        session_id: str,
        title: str = "新对话",
        user_id: str | None = None,
    ) -> ChatSession | None:
        """在数据库中预建一条会话记录。user_id 为归属用户，生产环境鉴权用。"""
        try:
            async with AsyncSessionLocal() as db:
                row = ChatSession(id=session_id, title=title, user_id=user_id)
                db.add(row)
                await db.commit()
                await db.refresh(row)
                logger.info("会话已创建: %s title=%s", session_id, title)
                return row
        except Exception as exc:
            logger.error("创建会话失败 %s: %s", session_id, exc)
            return None

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    async def get(self, session_id: str) -> ChatSession | None:
        """按 ID 查询会话元数据（不含消息内容）。"""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ChatSession).where(ChatSession.id == session_id)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            logger.error("查询会话失败 %s: %s", session_id, exc)
            return None

    async def list_all(
        self,
        include_archived: bool = False,
        user_id: str | None = None,
    ) -> list[ChatSession]:
        """
        列出会话，按 updated_at 倒序。
        include_archived=False 时过滤归档会话。
        user_id 非空时仅返回该用户的会话（生产环境鉴权）；为 None 时返回全部（兼容开发环境）。
        """
        try:
            async with AsyncSessionLocal() as db:
                stmt = select(ChatSession).order_by(ChatSession.updated_at.desc())
                if not include_archived:
                    stmt = stmt.where(ChatSession.is_archived.is_(False))
                if user_id is not None:
                    stmt = stmt.where(ChatSession.user_id == user_id)
                result = await db.execute(stmt)
                return list(result.scalars().all())
        except Exception as exc:
            logger.error("列举会话失败: %s", exc)
            return []

    # ------------------------------------------------------------------
    # 更新元数据
    # ------------------------------------------------------------------

    async def update(
        self,
        session_id: str,
        title: str | None = None,
        building_id: str | None = None,
    ) -> ChatSession | None:
        """
        更新会话的展示性元数据（标题、绑定楼宇）。
        只更新传入的非 None 字段。
        """
        fields: dict[str, Any] = {
            "updated_at": datetime.now(timezone.utc),
        }
        if title is not None:
            fields["title"] = title
        if building_id is not None:
            fields["building_id"] = building_id

        if len(fields) == 1:  # 只有 updated_at，无实际变更
            return await self.get(session_id)

        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ChatSession)
                    .where(ChatSession.id == session_id)
                    .values(**fields)
                )
                await db.commit()
            return await self.get(session_id)
        except Exception as exc:
            logger.error("更新会话元数据失败 %s: %s", session_id, exc)
            return None

    # ------------------------------------------------------------------
    # 状态持久化（消息 + AgentState）
    # ------------------------------------------------------------------

    async def save_state(
        self,
        session_id: str,
        state: dict[str, Any],
        last_message: str | None = None,
    ) -> None:
        """
        将 AgentState 序列化并写入数据库。
        会同时更新 message_count / last_message / building_id / updated_at。
        若会话记录不存在，先自动创建再写入（幂等）。
        """
        try:
            messages_json, extra_state_json = _serialize_state(state)
            message_count = len(state.get("messages", []))
            building_id = state.get("building_id")

            async with AsyncSessionLocal() as db:
                # 检查记录是否存在
                result = await db.execute(
                    select(ChatSession.id).where(ChatSession.id == session_id)
                )
                exists = result.scalar_one_or_none() is not None

                fields: dict[str, Any] = {
                    "messages_json": messages_json,
                    "extra_state_json": extra_state_json,
                    "message_count": message_count,
                    "updated_at": datetime.now(timezone.utc),
                }
                if last_message is not None:
                    fields["last_message"] = last_message[:200]  # 截断防溢出
                if building_id is not None:
                    fields["building_id"] = building_id

                if exists:
                    await db.execute(
                        update(ChatSession)
                        .where(ChatSession.id == session_id)
                        .values(**fields)
                    )
                else:
                    # 首次：自动建行（session_id 由路由层预先生成）
                    row = ChatSession(id=session_id, **fields)
                    db.add(row)

                await db.commit()
                logger.debug("会话状态已持久化: %s message_count=%d", session_id, message_count)

        except Exception as exc:
            logger.error("保存会话状态失败 %s: %s", session_id, exc)

    async def load_state(self, session_id: str) -> dict[str, Any] | None:
        """
        从数据库恢复 AgentState。
        返回 None 表示会话不存在或恢复失败。
        """
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ChatSession).where(ChatSession.id == session_id)
                )
                row = result.scalar_one_or_none()

            if row is None:
                return None

            return _deserialize_state(row.messages_json, row.extra_state_json)

        except Exception as exc:
            logger.error("加载会话状态失败 %s: %s", session_id, exc)
            return None

    # ------------------------------------------------------------------
    # 归档 / 删除
    # ------------------------------------------------------------------

    async def archive(self, session_id: str) -> ChatSession | None:
        """软删除：设置 is_archived=True。"""
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ChatSession)
                    .where(ChatSession.id == session_id)
                    .values(
                        is_archived=True,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
            return await self.get(session_id)
        except Exception as exc:
            logger.error("归档会话失败 %s: %s", session_id, exc)
            return None

    async def delete(self, session_id: str) -> bool:
        """物理删除会话（含消息历史）。"""
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(ChatSession).where(ChatSession.id == session_id)
                )
                await db.commit()
            logger.info("会话已删除: %s", session_id)
            return True
        except Exception as exc:
            logger.error("删除会话失败 %s: %s", session_id, exc)
            return False


# 模块级单例（路由层直接 import 使用）
session_store = SessionStore()
