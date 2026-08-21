from __future__ import annotations

import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import BinaryIO, TextIO

import uvicorn

_APP_FACTORY = "virea_api.app:create_app"


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
