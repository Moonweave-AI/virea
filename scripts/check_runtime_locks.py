"""Verify every isolated model Runtime lockfile without mutating it."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("uv is required to verify model Runtime lockfiles", file=sys.stderr)
        return 2

    locks = sorted((ROOT / "plugins" / "models").glob("*/runtime*/uv.lock"))
    if not locks:
        print("no model Runtime lockfiles found", file=sys.stderr)
        return 2

    failed: list[str] = []
    for lock in locks:
        project = lock.parent
        if not (project / "pyproject.toml").is_file():
            failed.append(f"{project.relative_to(ROOT)}: missing pyproject.toml")
            continue
        completed = subprocess.run(
            (uv, "lock", "--check", "--project", str(project)),
            cwd=ROOT,
            check=False,
        )
        if completed.returncode != 0:
            failed.append(
                f"{project.relative_to(ROOT)}: uv lock --check returned "
                f"{completed.returncode}"
            )

    if failed:
        print("Runtime lock verification failed:", file=sys.stderr)
        for item in failed:
            print(f"- {item}", file=sys.stderr)
        return 1
    print(f"Runtime lock verification passed: {len(locks)} projects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
