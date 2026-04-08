from __future__ import annotations

from typing import Final

BUILDING_TYPE_ORDER: Final[tuple[str, ...]] = (
    "Education",
    "Office",
    "Public services",
)

BUILDING_TYPE_LABELS: Final[dict[str, str]] = {
    "Education": "教学楼",
    "Office": "办公楼",
    "Public services": "公共楼",
}

BUILDING_TYPE_ICONS: Final[dict[str, str]] = {
    "Education": "🏫",
    "Office": "🏢",
    "Public services": "🏛️",
}

BUILDING_ID_TO_TYPE: Final[dict[str, str]] = {
    "Fox_education_Louie": "Education",
    "Fox_office_Alice": "Office",
    "Fox_public_Henry": "Public services",
}

BUILDING_TYPE_TO_ID: Final[dict[str, str]] = {
    building_type: building_id
    for building_id, building_type in BUILDING_ID_TO_TYPE.items()
}

_BUILDING_ALIASES: Final[dict[str, str]] = {
    **{building_type: building_type for building_type in BUILDING_TYPE_ORDER},
    "Public": "Public services",
    **BUILDING_ID_TO_TYPE,
    "教学楼": "Education",
    "办公楼": "Office",
    "公共楼": "Public services",
    "公共服务楼": "Public services",
    "图书馆": "Public services",
    "Louie 教学楼": "Education",
    "Alice 办公楼": "Office",
    "Henry 公共服务楼": "Public services",
}


def _normalize_alias_key(value: str) -> str:
    return " ".join(value.strip().split()).lower()


_NORMALIZED_BUILDING_ALIASES: Final[dict[str, str]] = {
    _normalize_alias_key(alias): building_type
    for alias, building_type in _BUILDING_ALIASES.items()
}


def normalize_building_type(value: str | None) -> str | None:
    if value is None:
        return None

    raw = value.strip()
    if not raw:
        return None

    return _NORMALIZED_BUILDING_ALIASES.get(_normalize_alias_key(raw))


def get_building_label(value: str | None, default: str | None = None) -> str:
    building_type = normalize_building_type(value)
    if building_type:
        return BUILDING_TYPE_LABELS[building_type]

    raw = (value or "").strip()
    if raw:
        return raw

    return default or ""


def get_building_icon(value: str | None, default: str = "🏠") -> str:
    building_type = normalize_building_type(value)
    if building_type:
        return BUILDING_TYPE_ICONS[building_type]
    return default
