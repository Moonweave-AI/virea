"""Incremental language decoding and bounded speech units, before response EOF."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .contracts import Decision


@dataclass(frozen=True)
class LanguageUpdate:
    decision: Decision
    final: bool = False


def partial_decision(source: str) -> Decision | None:
    """Only publish speech after complete, validated control fields preceding text.

    The wire schema orders mode, intent, actions, then text. An incomplete escape
    is retained for the next delta; it must never be spoken as a literal slash.
    """
    match = re.search(r',\s*"text"\s*:\s*"', source)
    if not match:
        return None
    prefix = source[: match.start()]
    tail = source[match.end() :]
    escaped = False
    end = len(tail)
    for index, char in enumerate(tail):
        if char == '"' and not escaped:
            end = index
            break
        escaped = char == "\\" and not escaped
    text = tail[:end]
    # json.loads also checks Unicode escape boundaries; at most six chars can
    # form a trailing incomplete escape. Invalid complete JSON remains an error
    # when the provider validates its final response.
    for trim in range(min(6, len(text)) + 1):
        candidate = text[: len(text) - trim] if trim else text
        try:
            value = json.loads(prefix + ',"text":"' + candidate + '"}')
            # JSON permits a lone high surrogate while its pair is in flight.
            # Do not publish that transient, invalid Unicode string.
            if any(0xD800 <= ord(char) <= 0xDFFF for char in value.get("text", "")):
                continue
            if value.get("mode") != "SPEAK" or not value.get("text"):
                return None
            return Decision.model_validate(value)
        except (ValueError, TypeError):
            continue
    return None


class ClauseBuffer:
    """Conserve every character while releasing clauses with bounded lookahead."""

    def __init__(self, limit: int = 40):
        self.limit = limit
        self.emitted = 0

    def take(self, text: str, *, final: bool = False) -> list[str]:
        result = []
        while len(text) > self.emitted:
            pending = text[self.emitted :]
            limit = min(self.limit, 24) if not self.emitted else self.limit
            stops = list(re.finditer(r"[。！？!?；;，,\n]", pending[:limit]))
            end = next((m.end() for m in stops if m.end() >= 8), 0)
            if not end:
                if final:
                    end = min(len(pending), limit)
                elif len(pending) >= limit:
                    end = limit
                else:
                    break
            result.append(pending[:end])
            self.emitted += end
        return result
