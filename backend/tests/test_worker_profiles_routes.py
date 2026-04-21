from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api import routes_worker_profiles


def test_json_list_ignores_invalid_payloads() -> None:
    assert routes_worker_profiles._json_list(None) == []
    assert routes_worker_profiles._json_list("not-json") == []
    assert routes_worker_profiles._json_list('{"a": 1}') == []
    assert routes_worker_profiles._json_list('["Office", "", "Lab"]') == ["Office", "Lab"]


def test_serialize_worker_profile_uses_defaults_without_profile() -> None:
    user = SimpleNamespace(
        id="ops-1",
        username="ops_hvac_01",
        email=None,
        phone="13800000001",
        role="ops",
        is_active=True,
        created_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
        worker_profile=None,
    )

    payload = routes_worker_profiles.serialize_worker_profile(user, active_orders=2)

    assert payload["user"]["username"] == "叶工"
    assert payload["profile_exists"] is False
    assert payload["dispatch_enabled"] is True
    assert payload["shift_status"] == "on_duty"
    assert payload["max_active_orders"] == 4
    assert payload["active_orders"] == 2
    assert payload["service_buildings"] == []


def test_serialize_worker_profile_includes_team_and_skills() -> None:
    team = SimpleNamespace(
        id="team-1",
        team_code="hvac",
        name="暖通班",
        description="暖通维修",
        service_buildings_json='["Office"]',
        is_active=True,
        created_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
    )
    skill = SimpleNamespace(
        id="skill-1",
        code="hvac",
        name="暖通",
        category="专业",
        description=None,
        is_active=True,
        created_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
    )
    profile = SimpleNamespace(
        team=team,
        team_id="team-1",
        job_title="高级维修员",
        shift_status="standby",
        dispatch_enabled=False,
        max_active_orders=5,
        accepts_emergency=False,
        service_buildings_json='["Office", "Lab"]',
        notes="只负责联调",
        skill_links=[
            SimpleNamespace(skill_id="skill-1", skill=skill, proficiency=5, is_primary=True),
        ],
        created_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
    )
    user = SimpleNamespace(
        id="ops-1",
        username="ops_hvac_01",
        email=None,
        phone=None,
        role="ops",
        is_active=True,
        created_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
        worker_profile=profile,
    )

    payload = routes_worker_profiles.serialize_worker_profile(user, active_orders=3)

    assert payload["user"]["username"] == "叶工"
    assert payload["profile_exists"] is True
    assert payload["team"]["name"] == "暖通班"
    assert payload["service_buildings"] == ["Office", "Lab"]
    assert payload["skills"][0]["name"] == "暖通"
    assert payload["skills"][0]["is_primary"] is True
    assert payload["capacity_ratio"] == 0.6


def test_worker_profile_self_update_only_allows_lightweight_fields() -> None:
    payload = routes_worker_profiles.WorkerProfileSelfUpdate(
        shift_status="busy",
        dispatch_enabled=False,
        accepts_emergency=False,
        notes="正在处理巡检，暂缓新单",
    )

    assert payload.shift_status == "busy"
    assert payload.dispatch_enabled is False
    assert payload.accepts_emergency is False

    with pytest.raises(ValidationError):
        routes_worker_profiles.WorkerProfileSelfUpdate(team_id="team-1")  # type: ignore[call-arg]
