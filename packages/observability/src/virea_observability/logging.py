from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
}
_PRIVATE_BY_DEFAULT = {"audio", "prompt", "text_prompt", "username"}


def redact(value: Any, *, key: str | None = None) -> Any:
    normalized = (key or "").casefold().replace("-", "_")
    if any(part in normalized for part in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if normalized in _PRIVATE_BY_DEFAULT:
        return "[PRIVATE]"
    if isinstance(value, dict):
        return {
            str(item_key): redact(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, key=key) for item in value]
    if isinstance(value, Path):
        return value.name
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"<{type(value).__name__}>"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload["fields"] = redact(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(
            redact(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
