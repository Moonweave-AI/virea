from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, TextIO

import uvicorn

from virea.resources import discover_resources

_APP_FACTORY = "virea_api.app:create_app"


def _web_source_files(repository_root: Path) -> tuple[Path, ...]:
    project_root = repository_root / "apps" / "web"
    fixed = (
        project_root / "index.html",
        project_root / "package.json",
        project_root / "tsconfig.json",
        project_root / "vite.config.ts",
        repository_root / "pnpm-lock.yaml",
        repository_root / "pnpm-workspace.yaml",
    )
    trees = (project_root / "src", project_root / "public")
    return tuple(
        sorted(
            (
                *(path for path in fixed if path.is_file()),
                *(
                    path
                    for tree in trees
                    if tree.is_dir()
                    for path in tree.rglob("*")
                    if path.is_file()
                ),
            ),
            key=lambda path: path.as_posix(),
        )
    )


def _web_distribution_is_current(repository_root: Path) -> bool:
    sources = _web_source_files(repository_root)
    distribution = repository_root / "apps" / "web" / "dist"
    index = distribution / "index.html"
    assets = distribution / "assets"
    if not sources or not index.is_file() or not assets.is_dir():
        return False
    outputs = (index, *(path for path in assets.iterdir() if path.is_file()))
    if len(outputs) == 1:
        return False
    newest_source = max(path.stat().st_mtime_ns for path in sources)
    oldest_output = min(path.stat().st_mtime_ns for path in outputs)
    return oldest_output >= newest_source


def _prepare_web_distribution() -> None:
    """Build a source checkout's ignored Web dist before it can become stale UI."""

    if os.getenv("VIREA_WEB_DIST"):
        return
    resources = discover_resources()
    if resources.origin != "source-tree" or _web_distribution_is_current(
        resources.root
    ):
        return
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise SystemExit(
            "VIREA Web sources changed but pnpm is unavailable / Web 源码已更新但找不到 pnpm；"
            "install the documented Node.js 24 + pnpm 10 toolchain, then run "
            "`uv run virea serve` again / 请安装文档要求的 Node.js 24 + pnpm 10 后重试"
        )
    print("VIREA Web / Web 前端: rebuilding the current source checkout...")
    completed = subprocess.run(
        [pnpm, "--dir", str(resources.root / "apps" / "web"), "build"],
        cwd=resources.root,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "VIREA Web build failed / Web 前端构建失败；review the pnpm output above "
            "and retry / 请检查上方 pnpm 输出后重试"
        )
    print("VIREA Web / Web 前端: current production bundle is ready.")


def _request_shutdown_on_stdin_eof(
    server: uvicorn.Server, stream: BinaryIO | TextIO
) -> None:
    """Request normal ASGI shutdown when a managed parent's stdin pipe closes."""

    try:
        while stream.read(1) not in (b"", ""):
            pass
    finally:
        # A pipe EOF is portable to Windows and also fires if the parent
        # crashes. Uvicorn can then run the application lifespan cleanup,
        # including exact Worker/resource/control-plane ownership release.
        server.should_exit = True


def _run_until_stdin_eof(*, host: str, port: int) -> None:
    config = uvicorn.Config(
        _APP_FACTORY,
        factory=True,
        host=host,
        port=port,
        reload=False,
    )
    server = uvicorn.Server(config)
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    watcher = threading.Thread(
        target=_request_shutdown_on_stdin_eof,
        args=(server, stream),
        name="virea-serve-stdin-eof",
        daemon=True,
    )
    watcher.start()
    server.run()


@contextmanager
def _temporary_environment(updates: dict[str, str]) -> Iterator[None]:
    """Apply CLI process configuration only while the server is running."""

    missing = object()
    previous: dict[str, str | object] = {
        key: os.environ.get(key, missing) for key in updates
    }
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is missing:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)


def run(args) -> int:
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            "VIREA 0.4.0 local mode only binds loopback; remote mode is not enabled"
        )

    _prepare_web_distribution()

    environment: dict[str, str] = {}
    if args.virea_home:
        environment["VIREA_HOME"] = str(args.virea_home)
    data_source = getattr(args, "data_source", None)
    if data_source:
        print(
            "virea: warning: serve --data-source is deprecated and only configures "
            "legacy preview routes; use VIREA_DATA_SOURCE or a per-request "
            "data_source parameter instead",
            file=sys.stderr,
        )
        environment["VIREA_DATA_SOURCE"] = str(data_source)

    with _temporary_environment(environment):
        # The factory resolves VIREA_HOME after the CLI environment is applied.  A
        # package import may already have constructed the compatibility `app`
        # object, so targeting that global would bind the wrong user home.
        if getattr(args, "shutdown_on_stdin_eof", False):
            if args.reload:
                raise SystemExit(
                    "--shutdown-on-stdin-eof cannot be combined with --reload"
                )
            _run_until_stdin_eof(host=args.host, port=args.port)
        else:
            uvicorn.run(
                _APP_FACTORY,
                factory=True,
                host=args.host,
                port=args.port,
                reload=args.reload,
            )
    return 0
