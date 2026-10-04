"""Pin executable upstream code, independently of worker readiness."""

import subprocess
from pathlib import Path


def verify_source(source: Path, revision: str):
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(source), *args], text=True, encoding="utf-8"
        ).strip()

    if git("rev-parse", "HEAD") != revision:
        raise ValueError(
            f"Unsupported source revision in {source}; expected {revision}"
        )
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError(f"Upstream tracked source was modified: {source}")
