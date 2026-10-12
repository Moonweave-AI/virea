"""Shared, dependency-free launch contract for the CLI, bootstrap and API."""

from __future__ import annotations

import hashlib
from pathlib import Path

WORKSPACES = (
    ("Set Up", "setup.html"),
    ("Motion Lab", "index.html"),
    ("Character Studio", "character.html"),
    ("VRChat Studio", "vrchat.html"),
)


def workspace_links(port: int = 8000, host: str = "127.0.0.1") -> dict[str, str]:
    address = f"[{host}]" if ":" in host else host
    base = f"http://{address}:{port}/app/"
    return {
        name: base + ("" if file == "index.html" else file) for name, file in WORKSPACES
    }


def web_source_files(root: Path) -> tuple[Path, ...]:
    web = root / "apps/web"
    fixed = [web / file for _, file in WORKSPACES] + [
        web / "package.json",
        web / "tsconfig.json",
        web / "vite.config.ts",
        root / "pnpm-lock.yaml",
        root / "pnpm-workspace.yaml",
    ]
    trees = (web / "src", web / "public")
    return tuple(
        sorted(
            [path for path in fixed if path.is_file()]
            + [path for tree in trees for path in tree.rglob("*") if path.is_file()],
            key=lambda path: path.as_posix(),
        )
    )


def web_distribution_is_current(root: Path) -> bool:
    sources = web_source_files(root)
    dist = root / "apps/web/dist"
    pages = [dist / file for _, file in WORKSPACES]
    assets = list((dist / "assets").glob("*"))
    assets = [path for path in assets if path.is_file()]
    if not sources or not assets or not all(path.is_file() for path in pages):
        return False
    return min(path.stat().st_mtime_ns for path in [*pages, *assets]) >= max(
        path.stat().st_mtime_ns for path in sources
    )


def source_revision(root: Path) -> str:
    """Identify running code, not just its unchanged package version or health."""
    paths = set(web_source_files(root))
    for directory in (
        "src",
        "apps/api/src",
        "apps/cli/src",
        "packages",
        "scripts/setup",
    ):
        paths.update((root / directory).rglob("*.py"))
    paths.update(root / file for file in ("pyproject.toml", "uv.lock"))
    digest = hashlib.sha256()
    for path in sorted(paths):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def home_identity(home: Path) -> str:
    return hashlib.sha256(str(home.resolve()).encode()).hexdigest()
