from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def atomic_write_bytes(path: str | Path, payload: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def atomic_create_bytes(path: str | Path, payload: bytes) -> Path:
    """Atomically create an immutable file, failing if it already exists."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def atomic_write_json(path: str | Path, value: Any) -> Path:
    return atomic_write_bytes(path, _json_bytes(value))


def atomic_create_json(path: str | Path, value: Any) -> Path:
    return atomic_create_bytes(path, _json_bytes(value))
