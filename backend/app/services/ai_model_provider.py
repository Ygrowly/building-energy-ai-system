from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ModelProviderError(RuntimeError):
    pass


class ModelProvider:
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.2,
    ) -> str:
        raise NotImplementedError


class OpenAICompatibleProvider(ModelProvider):
    """
    OpenAI-compatible HTTP provider.

    DashScope / 阿里云百炼的 Qwen 兼容模式和 DeepSeek 这类兼容接口都可以走这里。
    业务层只依赖 ModelProvider，避免把模型厂商写死进工单逻辑。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        provider_name: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider_name = provider_name
        self.timeout_seconds = timeout_seconds

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.2,
    ) -> str:
        if not self.api_key:
            raise ModelProviderError(f"{self.provider_name} API key 未配置")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_schema:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelProviderError(f"{self.provider_name} 调用失败: {exc}") from exc

        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError(f"{self.provider_name} 返回结构异常") from exc


def get_model_provider() -> ModelProvider | None:
    settings = get_settings()
    provider = (settings.AI_PROVIDER or "").strip().lower()

    if provider in {"qwen", "qwen_dashscope", "dashscope", "aliyun"}:
        api_key = settings.AI_API_KEY or settings.DASHSCOPE_API_KEY
        if not api_key:
            return None
        return OpenAICompatibleProvider(
            api_key=api_key,
            base_url=settings.AI_BASE_URL,
            model=settings.AI_TEXT_MODEL,
            provider_name="qwen_dashscope",
        )

    if provider in {"openai", "deepseek", "openai_compatible"}:
        api_key = settings.AI_API_KEY or settings.LLM_API_KEY
        if not api_key:
            return None
        return OpenAICompatibleProvider(
            api_key=api_key,
            base_url=settings.AI_BASE_URL or settings.LLM_BASE_URL,
            model=settings.AI_TEXT_MODEL or settings.LLM_MODEL,
            provider_name=provider,
        )

    return None


def parse_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.debug("模型 JSON 解析失败: %s", raw[:200])
            return None
    return value if isinstance(value, dict) else None
