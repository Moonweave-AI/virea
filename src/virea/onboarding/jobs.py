"""Durable, cancellable deployment jobs. Only built-in recipes may execute."""

from __future__ import annotations

import asyncio
import codecs
import json
import os
import re
import signal
import subprocess
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .activity import activity_log, safe_text
from .connections import private_json


class DeploymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe: Literal["ollama", "kokoro", "audio8", "motioncraft", "syntalker"]
    model: str = Field(
        default="qwen3:4b", pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,150}$"
    )
    device: Literal["auto", "cpu", "gpu", "cuda"] = "auto"
    accepted_license: bool = False


class DeploymentJobs:
    def __init__(self, paths, characters):
        self.paths, self.characters = paths, characters
        self.directory = paths.root / "setup" / "jobs"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.tasks, self.records, self.services = {}, {}, {}
        self.restore_task = None
        self.activity = activity_log(paths.root / "setup")
        self.output_tasks = set()
        self.services_path = paths.root / "setup" / "services.json"
        for path in sorted(
            self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime
        )[-50:]:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if value["status"] in {"queued", "running"}:
                    value.update(
                        status="interrupted",
                        message="服务重启中断了部署；点击重试会复用已下载文件",
                    )
                    private_json(path, value)
                self.records[value["id"]] = value
            except (ValueError, KeyError, OSError):
                continue

    def submit(self, request):
        for key, task in self.tasks.items():
            if not task.done():
                if self.records[key]["request"] == request.model_dump():
                    return dict(self.records[key])
                raise ValueError("已有部署正在进行，请等待完成或先取消")
        identifier = uuid4().hex
        self.records[identifier] = {
            "id": identifier,
            "request": request.model_dump(),
            "status": "queued",
            "step": 0,
            "total_steps": 6,
            "percent": 0,
            "stage_percent": None,
            "message": "正在准备部署",
            "updated_at": time.time(),
            "started_at": time.time(),
            "last_output_at": None,
            "logs": [],
            "result": None,
        }
        self.update(identifier)
        self.tasks[identifier] = asyncio.create_task(self._execute(identifier, request))
        return dict(self.records[identifier])

    def update(self, identifier, **changes):
        row = self.records[identifier]
        now = time.time()
        significant = any(
            changes.get(key, row.get(key)) != row.get(key)
            for key in ("status", "step", "message")
        )
        downloaded = changes.get("downloaded_bytes")
        if downloaded is not None:
            previous = row.get("downloaded_bytes", 0)
            delta = downloaded - previous
            elapsed = now - row.get("transfer_updated_at", now)
            if delta > 0 and elapsed > 0:
                changes["bytes_per_second"] = round(delta / elapsed)
            elif delta < 0:
                changes["bytes_per_second"] = 0
            changes["transfer_updated_at"] = now
        if "message" in changes:
            changes["message"] = safe_text(changes["message"])
        row.update(changes, updated_at=time.time())
        if significant:
            self.activity.emit(
                row.get("request", {}).get("recipe", "deployment"),
                row.get("message", ""),
                status=row.get("status", "running"),
                job_id=identifier,
                step=row.get("step", 0),
                total_steps=row.get("total_steps", 6),
                percent=row.get("percent", 0),
            )
        private_json(self.directory / f"{identifier}.json", row)

    def snapshot(self, identifier):
        row = dict(self.records[identifier])
        now = time.time()
        end = (
            row.get("updated_at", now)
            if row.get("status") not in {"running", "queued"}
            else now
        )
        row["elapsed_seconds"] = round(max(0, end - row.get("started_at", end)), 1)
        row["output_age_seconds"] = (
            round(now - row["last_output_at"], 1) if row.get("last_output_at") else None
        )
        row["server_time"] = now
        if now - row.get("transfer_updated_at", 0) > 10:
            row["bytes_per_second"] = 0
        rate = row.get("bytes_per_second", 0)
        remaining = row.get("total_bytes", 0) - row.get("downloaded_bytes", 0)
        row["eta_seconds"] = (
            round(remaining / rate) if rate > 0 and remaining > 0 else None
        )
        return row

    def output(self, identifier, line, secrets=()):
        line = safe_text(line, secrets).strip()
        if not line:
            return
        row = self.records[identifier]
        changes = {"last_output_at": time.time()}
        if line.startswith("VIREA_PROGRESS "):
            try:
                value = json.loads(line.removeprefix("VIREA_PROGRESS "))
                for key in (
                    "stage_percent",
                    "downloaded_bytes",
                    "total_bytes",
                    "file",
                    "files_done",
                    "files_total",
                ):
                    if key in value:
                        changes[key] = value[key]
                line = value.get("message", value.get("file", "Download"))
            except ValueError:
                pass
        else:
            percentages = re.findall(r"\b(\d{1,3})%", line)
            if percentages:
                changes["stage_percent"] = min(100, int(percentages[-1]))
        logs = row.setdefault("logs", [])
        if not logs or logs[-1]["message"] != line:
            logs.append({"time": time.time(), "message": line})
            del logs[:-80]
            self.activity.emit(
                row.get("request", {}).get("recipe", "deployment"),
                line,
                job_id=identifier,
                kind="output",
            )
        self.update(identifier, **changes)

    def step(self, identifier, step, message):
        self.update(
            identifier,
            step=step,
            percent=round((step - 1) / 6 * 100),
            stage_percent=None,
            downloaded_bytes=0,
            total_bytes=0,
            bytes_per_second=0,
            file=None,
            files_done=None,
            files_total=None,
            message=message,
        )

    async def _execute(self, identifier, request):
        from .recipes import deploy

        self.update(identifier, status="running")
        try:
            result = await deploy(self, identifier, request)
            if not result.get("verification", {}).get("generated"):
                raise ValueError(
                    "服务启动成功，但缺少真实生成检验结果，不能标记为部署完成"
                )
            desired = (
                json.loads(self.services_path.read_text(encoding="utf-8"))
                if self.services_path.exists()
                else {}
            )
            desired[request.recipe] = request.model_dump()
            private_json(self.services_path, desired)
            self.update(
                identifier,
                status="succeeded",
                step=6,
                percent=100,
                stage_percent=100,
                message="部署完成，真实生成检验通过；可查看检验结果",
                result=result,
            )
        except asyncio.CancelledError:
            self.update(
                identifier,
                status="cancelled",
                message="部署已取消；已下载缓存保留，可重新开始",
            )
        except Exception as exc:
            # Never publish remote response bodies, headers, or command environments.
            message = (
                str(exc)
                if isinstance(exc, (ValueError, RuntimeError))
                else type(exc).__name__
            )
            self.update(identifier, status="failed", message=message[:1600])

    async def cancel(self, identifier):
        task = self.tasks.get(identifier)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # A task cancelled before its first instruction cannot run _execute's handler.
            if self.records[identifier]["status"] in {"queued", "running"}:
                self.update(
                    identifier, status="cancelled", message="部署已取消；可重新开始"
                )
        return dict(self.records[identifier])

    async def command(self, identifier, argv, *, env, cwd, timeout=3600):
        flags = (
            {
                "creationflags": subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP
            }
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = await asyncio.create_subprocess_exec(
            *map(str, argv),
            env=env,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **flags,
        )
        tail = ""

        async def consume():
            nonlocal tail
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            pending = ""
            secrets = [
                v
                for k, v in env.items()
                if any(s in k.upper() for s in ("KEY", "TOKEN", "PASSWORD", "SECRET"))
            ]
            while block := await process.stdout.read(2048):
                pending += decoder.decode(block)
                lines = re.split(r"[\r\n]", pending)
                pending = lines.pop()
                for line in lines:
                    self.output(identifier, line, secrets)
                    tail = (tail + safe_text(line, secrets) + "\n")[-1800:]
                if len(pending) > 2048:
                    self.output(identifier, pending, secrets)
                    pending = ""
            self.output(identifier, pending + decoder.decode(b"", final=True), secrets)
            return await process.wait()

        try:
            code = await asyncio.wait_for(consume(), timeout)
            if code:
                # Installer output contains package/download diagnostics, never API keys.
                raise RuntimeError(f"安装命令退出码 {code}。{tail[-1200:]}")
        finally:
            if process.returncode is None:
                await self.terminate(process)

    async def terminate(self, process):
        if process.returncode is not None:
            return
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            await killer.wait()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), 8)
        except asyncio.TimeoutError:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            await process.wait()

    async def start_service(self, name, argv, env, cwd, identifier=None):
        previous = self.services.get(name)
        if previous and previous.returncode is None:
            return previous
        log = self.paths.logs / "setup" / f"{name}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        flags = (
            {
                "creationflags": subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP
            }
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = await asyncio.create_subprocess_exec(
            *map(str, argv),
            env=env,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **flags,
        )

        async def drain():
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            pending = ""
            secrets = [
                v
                for k, v in env.items()
                if any(s in k.upper() for s in ("KEY", "TOKEN", "PASSWORD", "SECRET"))
            ]
            with log.open("a", encoding="utf-8") as output:
                while block := await process.stdout.read(2048):
                    pending += decoder.decode(block)
                    lines = re.split(r"[\r\n]", pending)
                    pending = lines.pop()
                    if len(pending) > 2048:
                        lines.append(pending)
                        pending = ""
                    for line in lines:
                        line = safe_text(line, secrets)
                        if line.strip():
                            output.write(line + "\n")
                            output.flush()
                            if (
                                identifier
                                and self.records[identifier]["status"] == "running"
                            ):
                                self.output(identifier, line)
                if pending:
                    output.write(safe_text(pending, secrets) + "\n")
                    if identifier and self.records[identifier]["status"] == "running":
                        self.output(identifier, pending, secrets)

        task = asyncio.create_task(drain())
        self.output_tasks.add(task)
        task.add_done_callback(self.output_tasks.discard)
        self.services[name] = process
        return process

    async def close(self):
        if self.restore_task is not None:
            self.restore_task.cancel()
            await asyncio.gather(self.restore_task, return_exceptions=True)
        for identifier in list(self.tasks):
            await self.cancel(identifier)
        for process in self.services.values():
            await self.terminate(process)
        if self.output_tasks:
            await asyncio.gather(*self.output_tasks, return_exceptions=True)

    def service_status(self):
        try:
            desired = json.loads(self.services_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            desired = {}
        return [
            {
                "recipe": name,
                "auto_start": True,
                "owned_running": name in self.services
                and self.services[name].returncode is None,
            }
            for name in desired
        ]

    async def stop_service(self, name):
        if self.services_path.exists():
            desired = json.loads(self.services_path.read_text(encoding="utf-8"))
            desired.pop(name, None)
            private_json(self.services_path, desired)
        for identifier, record in list(self.records.items()):
            if record.get("request", {}).get("recipe") == name:
                await self.cancel(identifier)
        process = self.services.get(name)
        owned = process is not None and process.returncode is None
        if process is not None:
            await self.terminate(process)
        return {
            "recipe": name,
            "stopped_owned_process": owned,
            "auto_start": False,
            "message": "已停止本向导启动的服务，关闭自动恢复"
            if owned
            else "已关闭自动恢复；外部服务保持运行",
        }

    def restore(self):
        async def run():
            from .motion_services import connect_motion_services

            if self.characters is not None:
                await connect_motion_services(self.characters.config)
            if not self.services_path.exists():
                return
            try:
                desired = json.loads(self.services_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            for value in desired.values():
                try:
                    request = DeploymentRequest.model_validate(value)
                except ValueError:
                    continue
                # A user may start a job while automatic recovery is in progress.
                pending = [task for task in self.tasks.values() if not task.done()]
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                # A stop request can remove a recipe while another service is recovering.
                if request.recipe not in json.loads(
                    self.services_path.read_text(encoding="utf-8")
                ):
                    continue
                record = self.submit(request)
                await self.tasks[record["id"]]

        self.restore_task = asyncio.create_task(run())
