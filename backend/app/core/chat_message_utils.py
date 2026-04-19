from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage


def normalize_user_display_content(display_content: str | None, fallback: str) -> str:
    text = str(display_content or "").strip()
    return text or fallback


def build_human_message(content: str, display_content: str | None = None) -> HumanMessage:
    visible = normalize_user_display_content(display_content, content)
    additional_kwargs: dict[str, Any] = {}
    if visible != content:
        additional_kwargs["display_content"] = visible
    return HumanMessage(content=content, additional_kwargs=additional_kwargs)


def get_human_display_content(message: BaseMessage | HumanMessage | None) -> str:
    if isinstance(message, HumanMessage):
        display = message.additional_kwargs.get("display_content")
        if isinstance(display, str) and display.strip():
            return display.strip()
        content = message.content
        return content if isinstance(content, str) else str(content or "")

    if message is None:
        return ""

    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content or "")
