"""
多智能体控制台会话管理 ORM 模型。

复用 models.py 中的 Base，对应 migrations/001_create_chat_sessions.sql 中建立的表。
该表由应用程序全权管理（读写），与只读数据表（buildings / energy_data）分离。
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, String, Text, TIMESTAMP
from sqlalchemy.sql import func

from app.db.models import Base


class ChatSession(Base):
    """
    对话会话元数据表。

    字段说明：
      messages_json    — LangChain messages_to_dict() 序列化为 JSON 字符串
                         存储 HumanMessage / AIMessage / ToolMessage 全部历史
      extra_state_json — AgentState 其余字段（intent / hop_count / building_id /
                         artifacts / context_summary 等）的 JSON 序列化
                         不可序列化的对象（如 pending_action 中的复杂嵌套）会被跳过
    """

    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True)
    title = Column(String(200), nullable=False, default="新对话")
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    message_count = Column(Integer, nullable=False, default=0)
    last_message = Column(Text, nullable=True)
    building_id = Column(String, nullable=True)
    is_archived = Column(Boolean, nullable=False, default=False)
    messages_json = Column(Text, nullable=True)
    extra_state_json = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ChatSession id={self.id!r} title={self.title!r} "
            f"message_count={self.message_count} is_archived={self.is_archived}>"
        )
