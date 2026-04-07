from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_dispatch_integrity.py"
SPEC = importlib.util.spec_from_file_location("check_dispatch_integrity", SCRIPT_PATH)
assert SPEC and SPEC.loader
dispatch_integrity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dispatch_integrity)


def test_check_definitions_have_unique_names() -> None:
    names = [item["name"] for item in dispatch_integrity.CHECK_DEFINITIONS]
    assert len(names) == len(set(names))


def test_summarize_findings_counts_high_and_medium() -> None:
    summary = dispatch_integrity.summarize_findings(
        [
            {"name": "a", "severity": "high", "count": 2},
            {"name": "b", "severity": "medium", "count": 3},
            {"name": "c", "severity": "high", "count": 0},
        ]
    )

    assert summary == {
        "healthy": False,
        "failed_checks": 2,
        "high_severity_checks": 1,
        "medium_severity_checks": 1,
        "high_severity_rows": 2,
        "medium_severity_rows": 3,
    }


def test_build_report_lines_returns_ok_message_when_healthy() -> None:
    report = {
        "generated_at": "2026-04-06T10:00:00+00:00",
        "metrics": {
            "work_orders_total": 10,
            "anomaly_incidents_total": 8,
            "dispatch_tasks_total": 5,
            "current_dispatch_tasks_total": 2,
        },
        "summary": {
            "failed_checks": 0,
            "high_severity_checks": 0,
            "medium_severity_checks": 0,
        },
        "checks": [],
    }

    lines = dispatch_integrity.build_report_lines(report)

    assert "[OK] 未发现 current_dispatch / 派工投影脏数据。" in lines


def test_build_report_lines_includes_failed_check_and_samples() -> None:
    report = {
        "generated_at": "2026-04-06T10:00:00+00:00",
        "metrics": {
            "work_orders_total": 10,
            "anomaly_incidents_total": 8,
            "dispatch_tasks_total": 5,
            "current_dispatch_tasks_total": 2,
        },
        "summary": {
            "failed_checks": 1,
            "high_severity_checks": 1,
            "medium_severity_checks": 0,
        },
        "checks": [
            {
                "name": "broken_pointer",
                "label": "工单 current_dispatch_id 指向不存在的 dispatch_task",
                "severity": "high",
                "count": 2,
                "samples": [{"ticket_id": "WO-001"}],
            }
        ],
    }

    lines = dispatch_integrity.build_report_lines(report)

    assert any("工单 current_dispatch_id 指向不存在的 dispatch_task" in line for line in lines)
    assert any("sample:" in line for line in lines)
