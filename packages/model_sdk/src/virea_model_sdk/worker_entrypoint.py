"""Failure-reporting boundary around every installed model Worker module."""

from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Sequence

from .worker import _publish_startup_failure

_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _report_startup_failure_best_effort(exc: Exception) -> None:
    """Never let diagnostic publication replace the Worker failure itself."""

    try:
        _publish_startup_failure(exc)
    except Exception:
        pass


def run_worker_module(module_name: str, arguments: Sequence[str]) -> None:
    """Import and run one trusted Worker module inside the failure channel."""

    if not _MODULE_NAME.fullmatch(module_name):
        raise ValueError("Worker module must be a dotted Python module name")
    original_argv = sys.argv
    try:
        sys.argv = [module_name, *arguments]
        module = importlib.import_module(module_name)
        target = getattr(module, "main", None)
        if not callable(target):
            raise TypeError(f"Worker module {module_name!r} has no callable main")
        target()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            detail = str(exc.code).strip() or "non-zero SystemExit"
            _report_startup_failure_best_effort(
                RuntimeError(f"Worker entrypoint exited during startup: {detail}")
            )
        raise
    except Exception as exc:
        _report_startup_failure_best_effort(exc)
        raise
    finally:
        sys.argv = original_argv


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: python -m virea_model_sdk.worker_entrypoint "
            "WORKER_MODULE [WORKER_ARGUMENT ...]"
        )
    run_worker_module(sys.argv[1], sys.argv[2:])


if __name__ == "__main__":
    main()
