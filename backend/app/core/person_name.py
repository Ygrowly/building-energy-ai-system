from __future__ import annotations

import hashlib
import re
from typing import Any

_COMPOUND_SURNAMES: tuple[str, ...] = (
    "欧阳",
    "司马",
    "上官",
    "诸葛",
    "东方",
    "南宫",
    "夏侯",
    "尉迟",
    "公孙",
    "司徒",
    "令狐",
    "皇甫",
    "长孙",
    "慕容",
    "宇文",
    "司空",
    "申屠",
    "端木",
)

_DEMO_PERSON_ALIAS_OVERRIDES: dict[str, str] = {
    "test2": "刘工",
    "ops_hvac_01": "叶工",
    "ops_electrical_01": "宋工",
    "ops_plumbing_01": "陈工",
    "ops_controls_01": "王工",
    "ops_general_02": "李工",
}

_FALLBACK_SURNAMES: tuple[str, ...] = (
    "刘",
    "叶",
    "宋",
    "张",
    "陈",
    "王",
    "李",
    "赵",
    "周",
    "吴",
    "孙",
    "朱",
    "黄",
    "林",
    "何",
    "郭",
    "马",
    "罗",
    "梁",
)

_PERSON_NAME_KEYS: frozenset[str] = frozenset(
    {
        "username",
        "user_name",
        "worker_name",
        "assignee_name",
        "support_assignee_name",
        "assigned_to_name",
        "new_assigned_to_name",
        "assigned_by_name",
        "created_by_name",
        "applicant_username",
        "handled_by_username",
        "current_assignee_name",
    }
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ENGINEER_ALIAS_RE = re.compile(r"^[\u4e00-\u9fff]{1,2}工$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _fallback_alias(seed: str) -> str:
    digest = hashlib.sha1(seed.lower().encode("utf-8")).digest()[0]
    return f"{_FALLBACK_SURNAMES[digest % len(_FALLBACK_SURNAMES)]}工"


def format_person_display_name(name: str | None) -> str | None:
    normalized = _normalize_text(name)
    if not normalized:
        return None

    override = _DEMO_PERSON_ALIAS_OVERRIDES.get(normalized.lower())
    if override:
        return override
    if _ENGINEER_ALIAS_RE.fullmatch(normalized):
        return normalized

    chinese_chars = "".join(_CJK_RE.findall(normalized))
    if chinese_chars:
        for surname in _COMPOUND_SURNAMES:
            if chinese_chars.startswith(surname):
                return f"{surname}工"
        return f"{chinese_chars[0]}工"

    if _IDENTIFIER_RE.fullmatch(normalized):
        return _fallback_alias(normalized)
    return _fallback_alias(normalized)


def replace_person_names_in_text(text: str | None) -> str | None:
    if text is None:
        return None
    result = str(text)
    if not result.strip():
        return result

    for raw, alias in sorted(_DEMO_PERSON_ALIAS_OVERRIDES.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(raw)}(?![A-Za-z0-9_])",
            flags=re.IGNORECASE,
        )
        result = pattern.sub(alias, result)
    return result


def sanitize_person_display_payload(value: Any, *, field_name: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_person_display_payload(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_person_display_payload(item, field_name=field_name) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_person_display_payload(item, field_name=field_name) for item in value)
    if isinstance(value, str):
        if field_name in _PERSON_NAME_KEYS:
            return format_person_display_name(value) or value
        return replace_person_names_in_text(value) or value
    return value
