from app.services.operator_ai_service import _detect_blocked_actions, _extract_ticket_id
from app.services.worker_ai_service import classify_worker_intent_by_rules


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


def test_operator_ai_blocks_write_actions():
    blocked = _detect_blocked_actions("帮我把这张单改派给张三，然后关闭")
    assert "reassign_dispatch" in blocked
    assert "close_work_order" in blocked


def test_operator_ai_extracts_ticket_id():
    assert _extract_ticket_id("查一下 wo-20260403-005 是谁接的") == "WO-20260403-005"
