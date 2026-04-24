from __future__ import annotations

from app.core.person_name import extract_person_display_aliases, format_person_display_name, looks_like_person_display_name


def test_demo_worker_aliases_use_chinese_engineer_names() -> None:
    assert format_person_display_name("test2") == "刘工"
    assert format_person_display_name("ops_controls_01") == "王工"
    assert format_person_display_name("ops_plumbing_01") == "陈工"
    assert format_person_display_name("ops_hvac_01") == "叶工"
    assert format_person_display_name("ops_electrical_01") == "宋工"


def test_looks_like_person_display_name_filters_fake_engineer_aliases() -> None:
    assert looks_like_person_display_name("宋工") is True
    assert looks_like_person_display_name("欧阳工") is True
    assert looks_like_person_display_name("一条的工") is False
    assert looks_like_person_display_name("的工") is False


def test_extract_person_display_aliases_ignores_query_fragments_and_keeps_real_aliases() -> None:
    assert extract_person_display_aliases("最近一条的工单的完整流转链路") == []
    assert extract_person_display_aliases("宋工最近的工单全流程") == ["宋工"]
