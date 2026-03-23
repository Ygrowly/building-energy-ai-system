from __future__ import annotations

import pathlib
import sys


def _ensure_import_path() -> None:
    # Allow running from repo root: `python backend/scripts/run_eval.py`
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    backend_dir = repo_root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


def main() -> int:
    _ensure_import_path()
    try:
        # Avoid Windows console (GBK) crashing on unicode chars from tool descriptions.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    from app.eval.runner import format_summary, run_sync

    results = run_sync()
    print(format_summary(results))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
