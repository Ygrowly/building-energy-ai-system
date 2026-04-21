from __future__ import annotations

from app.core.person_name import format_person_display_name


def test_demo_worker_aliases_use_chinese_engineer_names() -> None:
    assert format_person_display_name("test2") == "刘工"
    assert format_person_display_name("ops_controls_01") == "王工"
    assert format_person_display_name("ops_plumbing_01") == "陈工"
    assert format_person_display_name("ops_hvac_01") == "叶工"
    assert format_person_display_name("ops_electrical_01") == "宋工"
