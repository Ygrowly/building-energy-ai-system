from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import dispatch_hall_service


def _make_viewer(
    *,
    user_id: str,
    team_id: str = "team-1",
    skill_codes: list[str] | None = None,
):
    links = [
        SimpleNamespace(skill=SimpleNamespace(code=code))
        for code in (skill_codes or [])
    ]
    return SimpleNamespace(
        id=user_id,
        role="ops",
        worker_profile=SimpleNamespace(
            team_id=team_id,
            team=SimpleNamespace(id=team_id, name="测试班组"),
            skill_links=links,
        ),
    )


def _make_open_entry(
    *,
    entry_type: str = "support_request",
    visibility_scope: str = "all_ops",
    created_by: str | None = None,
    target_team_ids_json: str | None = None,
    target_skill_tags_json: str | None = None,
    target_user_ids_json: str | None = None,
):
    return SimpleNamespace(
        id="hall-1",
        entry_type=entry_type,
        status="open",
        visibility_scope=visibility_scope,
        created_by=created_by,
        assigned_to=None,
        target_team_ids_json=target_team_ids_json,
        target_skill_tags_json=target_skill_tags_json,
        target_user_ids_json=target_user_ids_json,
    )


class _FakeHallDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_derive_dispatch_hall_targets_prefers_combined_visibility(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dispatch_hall_service,
        "_load_hall_recommendation_context",
        AsyncMock(
            return_value={
                "requirement": {
                    "required_skills": ["hvac"],
                    "preferred_team_name": "暖通班",
                },
                "candidates": [
                    {
                        "user_id": "ops-main",
                        "username": "当前主责",
                        "team_id": "team-main",
                        "team_name": "暖通班",
                        "dispatch_enabled": True,
                        "score": 92,
                    },
                    {
                        "user_id": "ops-backup",
                        "username": "李工",
                        "team_id": "team-hvac",
                        "team_name": "暖通班",
                        "dispatch_enabled": True,
                        "score": 88,
                    },
                    {
                        "user_id": "ops-support",
                        "username": "王工",
                        "team_id": "team-general",
                        "team_name": "综合运维班",
                        "dispatch_enabled": True,
                        "score": 72,
                    },
                ],
            }
        ),
    )

    payload = await dispatch_hall_service.derive_dispatch_hall_targets(
        SimpleNamespace(),
        work_order=SimpleNamespace(
            id="wo-1",
            incident_id="incident-1",
            building_id="B-01",
            priority="high",
            issue_description="空调送风异常",
            suggested_action="优先安排暖通班支援",
        ),
        entry_type="support_request",
        source_assignee_id="ops-main",
    )

    assert payload["visibility_scope"] == "team_skill_or_recommended"
    assert payload["target_team_ids"] == ["team-hvac"]
    assert payload["target_skill_tags"] == ["hvac"]
    assert payload["target_user_ids"] == ["ops-backup", "ops-support"]


@pytest.mark.asyncio
async def test_derive_dispatch_hall_targets_keeps_explicit_support_team_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dispatch_hall_service,
        "_load_hall_recommendation_context",
        AsyncMock(side_effect=AssertionError("不应在定向班组协同时查询推荐上下文")),
    )

    payload = await dispatch_hall_service.derive_dispatch_hall_targets(
        SimpleNamespace(),
        work_order=SimpleNamespace(id="wo-1", incident_id="incident-1"),
        entry_type="support_request",
        target_team_ids=["team-electrical"],
    )

    assert payload["visibility_scope"] == "team_only"
    assert payload["target_team_ids"] == ["team-electrical"]
    assert payload["target_skill_tags"] == []
    assert payload["target_user_ids"] == []


def test_can_view_dispatch_hall_entry_support_request_hides_creator() -> None:
    entry = _make_open_entry(
        entry_type="support_request",
        visibility_scope="team_or_recommended",
        created_by="ops-1",
        target_team_ids_json='["team-1"]',
        target_user_ids_json='["ops-2"]',
    )

    assert dispatch_hall_service.can_view_dispatch_hall_entry(entry, _make_viewer(user_id="ops-1")) is False
    assert dispatch_hall_service.can_view_dispatch_hall_entry(entry, _make_viewer(user_id="ops-2", team_id="team-2")) is True


def test_can_view_dispatch_hall_entry_matches_combined_scope() -> None:
    entry = _make_open_entry(
        entry_type="takeover_candidate",
        visibility_scope="team_skill_or_recommended",
        target_team_ids_json='["team-hvac"]',
        target_skill_tags_json='["controls"]',
        target_user_ids_json='["ops-target"]',
    )

    assert dispatch_hall_service.can_view_dispatch_hall_entry(
        entry,
        _make_viewer(user_id="ops-team", team_id="team-hvac"),
    ) is True
    assert dispatch_hall_service.can_view_dispatch_hall_entry(
        entry,
        _make_viewer(user_id="ops-skill", team_id="team-other", skill_codes=["controls"]),
    ) is True
    assert dispatch_hall_service.can_view_dispatch_hall_entry(
        entry,
        _make_viewer(user_id="ops-target", team_id="team-other"),
    ) is True
    assert dispatch_hall_service.can_view_dispatch_hall_entry(
        entry,
        _make_viewer(user_id="ops-miss", team_id="team-other", skill_codes=["plumbing"]),
    ) is False


@pytest.mark.asyncio
async def test_create_or_reopen_takeover_hall_entry_applies_derived_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dispatch_hall_service,
        "derive_dispatch_hall_targets",
        AsyncMock(
            return_value={
                "visibility_scope": "team_or_recommended",
                "target_team_ids": ["team-hvac"],
                "target_skill_tags": [],
                "target_user_ids": ["ops-2", "ops-3"],
            }
        ),
    )
    monkeypatch.setattr(
        dispatch_hall_service,
        "_find_latest_hall_entry",
        AsyncMock(return_value=None),
    )

    db = _FakeHallDb()
    work_order = SimpleNamespace(
        id="wo-1",
        incident_id="incident-1",
    )

    entry = await dispatch_hall_service.create_or_reopen_takeover_hall_entry(
        db,
        work_order=work_order,
        source_dispatch_id="dispatch-1",
        source_assignee_id="ops-main",
        reason="接单超时，进入待接管池",
        sla_stage="assigned",
        overdue_level="overdue",
    )

    assert entry.visibility_scope == "team_or_recommended"
    assert entry.target_team_ids_json == '["team-hvac"]'
    assert entry.target_user_ids_json == '["ops-2", "ops-3"]'
    assert entry.sla_stage == "assigned"
    assert entry.overdue_level == "overdue"
    assert db.added[0] is entry
    dispatch_hall_service.derive_dispatch_hall_targets.assert_awaited_once()


@pytest.mark.asyncio
async def test_withdraw_dispatch_hall_application_marks_withdrawn() -> None:
    now = datetime.now(timezone.utc)
    application = SimpleNamespace(
        id="app-1",
        hall_entry_id="hall-1",
        applicant_user_id="ops-1",
        status="pending",
        handled_by=None,
        handled_at=None,
        handle_note=None,
        updated_at=now,
    )
    hall_entry = SimpleNamespace(id="hall-1", updated_at=now)

    class _FakeDb:
        async def get(self, model, obj_id):
            assert obj_id == "hall-1"
            return hall_entry

        async def flush(self):
            return None

    await dispatch_hall_service.withdraw_dispatch_hall_application(
        _FakeDb(),
        application=application,
        actor_id="ops-1",
    )

    assert application.status == "withdrawn"
    assert application.handled_by == "ops-1"
    assert application.handle_note == "维修人员已主动撤回申请"
    assert hall_entry.updated_at >= now
