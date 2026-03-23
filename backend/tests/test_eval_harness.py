from __future__ import annotations

from app.eval.runner import run_sync


def test_eval_harness_smoke():
    results = run_sync()
    assert results, "no eval results"
    failed = [r for r in results if not r.passed]
    assert not failed, "\n" + "\n".join(f"{r.type} {r.name}: {r.detail}" for r in failed)

