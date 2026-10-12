"""One bounded activity journal for the setup UI and launcher terminal."""

from __future__ import annotations

import json
import re
import time
from collections import deque
from functools import lru_cache
from threading import RLock


@lru_cache(maxsize=16)
def activity_log(directory):
    return ActivityLog(directory)


ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def safe_text(value, secrets=()):
    text = ANSI.sub("", str(value))
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text)
    text = re.sub(
        r"(?i)([?&](?:token|key|signature|sig|auth|credential|x-amz-[\w-]+)=)[^\s&]+",
        r"\1[redacted]",
        text,
    )
    text = re.sub(
        r"(?i)((?:api[_-]?key|authorization|password|token)\s*[:=]\s*)(?:Bearer\s+)?[^\s,]+",
        r"\1[redacted]",
        text,
    )
    return "".join(c for c in text if c >= " " or c in "\n\t")[:1200]


class ActivityLog:
    def __init__(self, directory):
        self.path = directory / "activity.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows = deque(maxlen=400)
        try:
            with self.path.open("rb") as stream:
                lines = deque(stream, maxlen=400)
        except OSError:
            lines = ()
        damaged = False
        for line in lines:
            try:
                row = json.loads(line.decode("utf-8"))
                if (
                    isinstance(row, dict)
                    and type(row.get("sequence")) is int
                    and row["sequence"] > 0
                    and isinstance(row.get("message"), str)
                ):
                    self.rows.append(row)
                else:
                    damaged = True
            except ValueError:
                damaged = True
                continue
        if damaged:
            try:
                self.path.write_text(
                    "".join(
                        json.dumps(row, ensure_ascii=False) + "\n" for row in self.rows
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass
        self.sequence = max((row["sequence"] for row in self.rows), default=0)
        self.lock = RLock()

    def emit(self, category, message, *, status="running", job_id=None, **facts):
        with self.lock:
            return self._emit(category, message, status=status, job_id=job_id, **facts)

    def _emit(self, category, message, *, status="running", job_id=None, **facts):
        self.sequence += 1
        row = dict(
            sequence=self.sequence,
            time=time.time(),
            category=category,
            message=safe_text(message),
            status=status,
            job_id=job_id,
            **facts,
        )
        self.rows.append(row)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        if self.path.stat().st_size > 1_000_000:
            self.path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in self.rows) + "\n",
                encoding="utf-8",
            )
        return row

    def after(self, sequence=0):
        with self.lock:
            reset = bool(
                self.rows
                and sequence
                and (
                    sequence < self.rows[0]["sequence"] - 1 or sequence > self.sequence
                )
            )
            return dict(
                events=[r for r in self.rows if reset or r["sequence"] > sequence],
                cursor=self.sequence,
                reset=reset,
                server_time=time.time(),
            )
