import pytest

from app.services.operator_ai_service import _detect_blocked_actions, _extract_ticket_id
from app.services import worker_ai_service
from app.services.worker_ai_service import (
    _generate_worker_chat_reply_with_model,
    classify_worker_intent,
    classify_worker_intent_by_rules,
)


def test_worker_ai_rule_intent_accept_and_reason():
    intent = classify_worker_intent_by_rules("确认接单")
    assert intent.action == "accept"
    assert intent.confidence >= 0.8

    support_intent = classify_worker_intent_by_rules("请求协同，因为需要电气班组支援")
    assert support_intent.action == "request_support"
    assert support_intent.reason == "需要电气班组支援"


def test_worker_ai_rule_intent_complete_false_alarm():
    intent = classify_worker_intent_by_rules("处理完成，是误报")
    assert intent.action == "complete"
    assert intent.result == "false_alarm"


@pytest.mark.asyncio
async def test_worker_ai_guidance_question_is_not_action():
    intent = await classify_worker_intent("那我下一步要做些什么")

    assert intent.action is None
    assert intent.confidence >= 0.9


@pytest.mark.asyncio
async def test_worker_ai_bare_ack_is_not_action_without_pending_confirmation():
    intent = await classify_worker_intent("可以")

    assert intent.action is None
    assert intent.reply is None


@pytest.mark.asyncio
async def test_worker_ai_greeting_is_not_answered_by_intent_classifier():
    intent = await classify_worker_intent("你好")

    assert intent.action is None
    assert intent.reply is None


@pytest.mark.asyncio
async def test_worker_ai_natural_chat_uses_model_reply(monkeypatch: pytest.MonkeyPatch):
    class FakeProvider:
        async def chat(self, messages, **kwargs):
            assert "新手" in messages[1]["content"]
            return '{"answer":"没关系，我们从零开始。你先告诉我现在到现场了吗，能不能看到控制屏？如果已经到了，先拍一张屏幕或设备铭牌给我。"}'

    monkeypatch.setattr(worker_ai_service, "get_model_provider", lambda: FakeProvider())

    answer = await _generate_worker_chat_reply_with_model(
        message="我还没开始执行，我是一个新手，我应该做哪些步骤呢",
        work_order=None,
        dispatch_task=None,
        hall_entry=None,
        client_context={},
    )

    assert answer is not None
    assert "从零开始" in answer
    assert "后端" not in answer
    assert "状态机" not in answer


def test_operator_ai_blocks_write_actions():
    blocked = _detect_blocked_actions("帮我把这张单改派给张三，然后关闭")
    assert "reassign_dispatch" in blocked
    assert "close_work_order" in blocked


def test_operator_ai_extracts_ticket_id():
    assert _extract_ticket_id("查一下 wo-20260403-005 是谁接的") == "WO-20260403-005"
