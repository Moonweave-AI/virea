from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


_WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'<>|?*]+"
)
_POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![:/A-Za-z0-9_])/(?:[^/\s\"'<>]+/)*[^/\s\"'<>]*"
)
_WEB_OR_URN_TOKEN_RE = re.compile(r"(?:https?://|urn:)[^\s\"'<>]+", re.IGNORECASE)
_API_ROUTE_RE = re.compile(r"^/(?:api(?:/|$)|v[0-9]+(?:/|$))")


def _is_absolute_path(value: str) -> bool:
    return PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()


def _path_name(value: str) -> str:
    pure = PureWindowsPath(value) if PureWindowsPath(value).is_absolute() else PurePosixPath(value)
    return pure.name or "root"


def opaque_path_reference(value: str | Path) -> str:
    """Return a stable path identity that reveals no parent directory."""

    raw = str(value)
    digest = hashlib.sha256(raw.replace("\\", "/").encode("utf-8")).hexdigest()[:12]
    return f"{_path_name(raw)}@sha256-{digest}"


def portable_path_reference(value: str | Path, *, base: str | Path | None = None) -> str:
    """Serialize a file reference relative to ``base`` or as an opaque identity.

    Report consumers do not need a machine-local root. Files inside the declared
    base therefore use forward-slash relative paths. An absolute path outside the
    base is reduced to basename plus a short path-identity hash.
    """

    raw = str(value)
    if base is not None:
        base_raw = str(base)
        if PureWindowsPath(raw).is_absolute() and PureWindowsPath(base_raw).is_absolute():
            try:
                relative = PureWindowsPath(raw).relative_to(PureWindowsPath(base_raw))
            except ValueError:
                pass
            else:
                if ".." not in relative.parts:
                    return relative.as_posix() or "."
        elif PurePosixPath(raw).is_absolute() and PurePosixPath(base_raw).is_absolute():
            try:
                relative = PurePosixPath(raw).relative_to(PurePosixPath(base_raw))
            except ValueError:
                pass
            else:
                if ".." not in relative.parts:
                    return relative.as_posix() or "."
        else:
            path = Path(raw)
            try:
                root = Path(base).resolve()
                candidate = path if path.is_absolute() else root / path
                relative = candidate.resolve().relative_to(root)
            except (OSError, RuntimeError, ValueError):
                pass
            else:
                return relative.as_posix() or "."
    if _is_absolute_path(raw):
        return opaque_path_reference(raw)
    relative = PureWindowsPath(raw) if "\\" in raw else PurePosixPath(raw)
    if ".." in relative.parts or (isinstance(relative, PureWindowsPath) and relative.drive):
        return opaque_path_reference(raw)
    if isinstance(value, Path):
        return value.as_posix()
    return raw.replace("\\", "/")


def _redact_embedded_absolute_paths(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ",.;:)]}":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        return opaque_path_reference(raw) + trailing

    def redact_plain_text(segment: str) -> str:
        redacted = _WINDOWS_ABSOLUTE_PATH_RE.sub(replace, segment)
        return _POSIX_ABSOLUTE_PATH_RE.sub(replace, redacted)

    pieces: list[str] = []
    cursor = 0
    for match in _WEB_OR_URN_TOKEN_RE.finditer(value):
        pieces.append(redact_plain_text(value[cursor:match.start()]))
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(redact_plain_text(value[cursor:]))
    return "".join(pieces)


def sanitize_report_paths(value: Any, *, relative_base: str | Path | None = None) -> Any:
    """Recursively make report values portable and safe to persist or publish."""

    if isinstance(value, dict):
        return {
            key: sanitize_report_paths(item, relative_base=relative_base)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_report_paths(item, relative_base=relative_base) for item in value]
    if isinstance(value, tuple):
        return [sanitize_report_paths(item, relative_base=relative_base) for item in value]
    if isinstance(value, Path):
        return portable_path_reference(value, base=relative_base)
    if isinstance(value, str):
        if _WEB_OR_URN_TOKEN_RE.fullmatch(value) or _API_ROUTE_RE.match(value):
            return value
        if _is_absolute_path(value):
            return portable_path_reference(value, base=relative_base)
        if relative_base is not None and ("/" in value or "\\" in value or value in {".", ".."}):
            return portable_path_reference(value, base=relative_base)
        return _redact_embedded_absolute_paths(value)
    return value
