"""Persistent live progress for catalog installations, shared with Set Up."""

import inspect
import json
import logging
import threading
import time
from contextvars import ContextVar
from dataclasses import asdict
from functools import wraps
from uuid import uuid4

from .activity import activity_log, safe_text
from .connections import _LOCK, private_json

_current = ContextVar("model_installation_progress", default=None)
_session = uuid4().hex
_locks = {}
_guard = threading.Lock()
_logger = logging.getLogger(__name__)


def progress_path(paths, model_id):
    from virea_core.paths import safe_component

    return paths.root / "setup/model-progress" / f"{safe_component(model_id)}.json"


def read_progress(path):
    with _LOCK:
        row = json.loads(path.read_text(encoding="utf-8"))
    if row.get("status") == "running" and row.get("session") != _session:
        row.update(
            status="interrupted", message="服务已重启；已下载文件保留，可继续部署"
        )
    row.pop("session", None)
    return row


def record_installation(function):
    @wraps(function)
    def wrapped(request, control):
        if not request.apply:
            return function(request, control)
        path = progress_path(control.paths, request.model_id)
        with _guard:
            lock = _locks.setdefault(str(path.resolve()), threading.Lock())
        if not lock.acquire(blocking=False):
            from fastapi import HTTPException

            raise HTTPException(409, "该模型正在部署，请查看已有任务的进度")
        row = dict(
            model_id=request.model_id,
            status="running",
            stage="detect",
            session=_session,
            started_at=time.time(),
            message="检测模型与运行环境",
        )
        last_write = [0.0]
        warned = set()

        def warn_write_failure(sink, exc):
            if sink not in warned:
                _logger.warning(
                    "Unable to persist %s for model %s; installation continues: %s",
                    sink,
                    request.model_id,
                    safe_text(exc),
                )
                warned.add(sink)

        def publish(stage=None, message=None, **facts):
            with _LOCK:
                row.update(facts, updated_at=time.time())
                if stage:
                    row["stage"] = stage
                if message:
                    row["message"] = safe_text(message)
                if stage or time.monotonic() - last_write[0] >= 0.4:
                    try:
                        private_json(path, row)
                        warned.discard("model progress")
                    except OSError as exc:
                        warn_write_failure("model progress", exc)
                    finally:
                        # Throttle failures too: a locked file must not stall every chunk.
                        last_write[0] = time.monotonic()
                if stage:
                    try:
                        activity_log(control.paths.root / "setup").emit(
                            request.model_id, row["message"], status=row["status"]
                        )
                        warned.discard("activity log")
                    except OSError as exc:
                        warn_write_failure("activity log", exc)

        token = _current.set(publish)
        try:
            publish("detect")
            result = function(request, control)
            succeeded = result.get("state") == "READY"
            publish(
                "ready" if succeeded else "failed",
                "模型部署与真实生成验收通过"
                if succeeded
                else "部署未完成，请查看诊断信息",
                status="succeeded" if succeeded else "failed",
                result=result,
            )
            return result
        except Exception as exc:
            publish(
                "failed", safe_text(getattr(exc, "detail", str(exc))), status="failed"
            )
            raise
        finally:
            _current.reset(token)
            lock.release()

    wrapped.__signature__ = inspect.signature(function, eval_str=True)
    return wrapped


def installation_stage(stage, message):
    if publish := _current.get():
        publish(stage, message, transfer=None)


def installation_transfer(event):
    if publish := _current.get():
        publish(transfer=asdict(event))
