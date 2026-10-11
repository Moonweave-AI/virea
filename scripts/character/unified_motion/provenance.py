"""Pin executable upstream code, independently of worker readiness."""

import subprocess
from pathlib import Path


def verify_source(source: Path, revision: str):
    if not (source / ".git").exists() and (source / ".virea-source.json").is_file():
        from .source_archive import verify_archive

        verify_archive(source, revision)
        return

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
