"""Role-bound client lifecycle; saved game sessions remain owned by VRChat."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path

from pydantic import Field, model_validator

from .contracts import StrictModel


class ClientProfile(StrictModel):
    profile: int = Field(ge=0, le=99)
    send_port: int = Field(ge=1024, le=65535)
    receive_port: int = Field(ge=1024, le=65535)
    vr: bool
    label: str = Field(min_length=1, max_length=80)
    account_id: str = Field(pattern=r"^usr_[0-9a-f-]{36}$")


class ClientLaunchConfig(StrictModel):
    vrchat_exe: Path
    steam_exe: Path
    steamvr_exe: Path
    observer: ClientProfile
    ai: ClientProfile

    @model_validator(mode="after")
    def separate_accounts(self):
        if (
            self.observer.profile == self.ai.profile
            or self.observer.account_id == self.ai.account_id
        ):
            raise ValueError("观察者与 AI 必须使用不同的 Profile 和账号")
        ports = [
            c for p in (self.observer, self.ai) for c in (p.send_port, p.receive_port)
        ]
        if len(set(ports)) != 4 or ports[:2] != [9000, 9001]:
            raise ValueError("观察者固定使用 9000/9001；AI 必须使用独立端口")
        if self.observer.vr or not self.ai.vr:
            raise ValueError("观察者使用桌面模式，AI 使用虚拟 VR 全身模式")
        return self


def client_view(profile, client):
    """Process existence and a remembered identity do not prove API health."""
    view = dict(
        label=profile.label,
        profile=profile.profile,
        mode="vr" if profile.vr else "desktop",
        running=client is not None,
        active=False,
        step=0,
        total_steps=5,
        stage="stopped",
        detail="尚未启动",
        pid=None,
        started=None,
    )
    if client is None:
        return view
    view.update(pid=client.pid, started=client.started, step=3)
    if client.account and client.account != profile.account_id:
        view.update(
            stage="wrong_account",
            detail="当前 Profile 登录了另一个账号，请在这个窗口切换到绑定账号。",
        )
    elif client.authentication == "api_auth_error_in_log":
        view.update(
            stage="auth_error",
            detail="游戏窗口仍在运行，但 API 出现 401。可单独重启此窗口恢复已保存会话；可能仍需登录验证。",
        )
    elif client.connection == "offline_testing":
        view.update(
            stage="offline_testing",
            detail="当前窗口处于离线测试模式，请用这里的重启按钮启动官方客户端。",
        )
    elif not client.account or client.authentication != "authenticated_in_log":
        view.update(
            stage="waiting_login",
            detail="等待游戏恢复已保存的登录；若出现登录或验证码页面，请在此窗口完成验证。",
        )
    elif client.arrived and client.connection == "online_session_in_log":
        view.update(
            stage="ready", step=5, detail="已核对绑定账号，并收到在线场景到达记录。"
        )
    else:
        view.update(
            stage="loading_world", step=4, detail="已识别绑定账号，等待场景加载。"
        )
    return view


class ClientLauncher:
    def __init__(
        self, config_path, *, backend=None, clock=time.monotonic, sleep=asyncio.sleep
    ):
        if backend is None:
            from .client_launch_windows import WindowsClientBackend

            backend = WindowsClientBackend()
        self.config_path = Path(config_path)
        self.backend, self.clock, self.sleep = backend, clock, sleep
        self.lock = asyncio.Lock()
        self.boot_lock = asyncio.Lock()
        self.tasks = {}
        self.progress = {}

    def config(self):
        if not self.config_path.is_file():
            raise ValueError(
                "尚未配置本机 VRChat 启动器：请配置 VIREA_HOME/config/vrchat-clients.json"
            )
        try:
            return ClientLaunchConfig.model_validate_json(
                self.config_path.read_text(encoding="utf-8-sig")
            )
        except (ValueError, OSError) as exc:
            # Pydantic error payloads may contain the original configuration.
            raise ValueError(
                "本机 VRChat 启动配置无效，请检查路径、独立 Profile、账号与端口"
            ) from exc

    def _select(self, profile, clients):
        matches = [
            c
            for c in clients
            if c.profile == profile.profile or c.send_port == profile.send_port
        ]
        if len(matches) > 1 or any(
            c.profile != profile.profile or c.send_port != profile.send_port
            for c in matches
        ):
            raise ValueError("Profile 或端口与其他客户端冲突；未关闭任何窗口")
        if matches and matches[0].vr != profile.vr:
            raise ValueError("现有客户端的 VR/桌面模式与绑定配置不同；请先关闭该窗口")
        return matches[0] if matches else None

    async def snapshot(self):
        try:
            config = self.config()
            clients = await asyncio.to_thread(self.backend.scan)
        except (ValueError, OSError, RuntimeError) as exc:
            return {"configured": False, "error": str(exc), "clients": {}}
        result = {}
        for role in ("observer", "ai"):
            profile = getattr(config, role)
            try:
                view = client_view(profile, self._select(profile, clients))
            except ValueError as exc:
                view = {
                    **client_view(profile, None),
                    "stage": "conflict",
                    "detail": str(exc),
                }
            operation = self.progress.get(role, {})
            if self.tasks.get(role) and not self.tasks[role].done():
                view.update(operation, active=True)
            elif operation.get("stage") == "failed":
                view.update(operation)
            result[role] = view
        return {"configured": True, "clients": result}

    async def begin(self, role, action, *, prepare=None):
        if role not in {"observer", "ai"} or action not in {"start", "restart"}:
            raise ValueError("invalid client launch command")
        async with self.lock:
            # Repeated clicks reuse this role's task. The other role may queue.
            if role in self.tasks and not self.tasks[role].done():
                return await self.snapshot()
            config = self.config()
            profile = getattr(config, role)
            clients = await asyncio.to_thread(self.backend.scan)
            current = self._select(profile, clients)
            if current and action == "start":
                self.progress.pop(role, None)
                return await self.snapshot()
            if any(c.profile is None or c.send_port is None for c in clients):
                raise ValueError(
                    "有 VRChat 进程尚未确认 Profile/端口，请等待其启动完成后重试"
                )
            # Validate dependencies before closing a working window.
            await asyncio.to_thread(self.backend.validate, config)
            self.progress[role] = dict(
                stage="preparing", step=0, detail="正在等待启动环境并检查静音…"
            )
            self.tasks[role] = asyncio.create_task(
                self._queued_run(role, config, current, prepare)
            )
        return await self.snapshot()

    async def _queued_run(self, role, config, current, prepare):
        async with self.boot_lock:
            try:
                if prepare:
                    await prepare(role)
                await self._run(role, config, current)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.progress[role].update(stage="failed", detail=str(exc))

    async def _run(self, role, config, current):
        profile = getattr(config, role)
        try:
            # Public-area operation: mute before SteamVR or VRChat can emit audio.
            await asyncio.to_thread(self.backend.mute)
            if current:
                self.progress[role].update(
                    stage="closing",
                    step=1,
                    detail="正在关闭此账号窗口，另一个窗口保持运行…",
                )
                await asyncio.to_thread(self.backend.close, current)
                deadline = self.clock() + 30
                while await asyncio.to_thread(self.backend.alive, current):
                    if self.clock() >= deadline:
                        raise ValueError(
                            "此窗口尚未退出；未强制结束进程，也未重复启动。请处理游戏内的关闭提示后重试。"
                        )
                    await self.sleep(0.5)
            self.progress[role].update(
                stage="dependencies", step=1, detail="正在准备 Steam 与虚拟 VR 环境…"
            )
            await asyncio.to_thread(self.backend.dependencies, config, profile)
            deadline = self.clock() + 60
            while not await asyncio.to_thread(self.backend.dependencies_ready, profile):
                if self.clock() >= deadline:
                    raise ValueError(
                        "Steam/SteamVR 未在 60 秒内就绪；未启动错误模式的 VRChat，请检查对应程序的提示。"
                    )
                await self.sleep(2)
                await asyncio.to_thread(self.backend.mute)
            await asyncio.to_thread(self.backend.mute)
            # Another launcher could have started this profile during shutdown.
            clients = await asyncio.to_thread(self.backend.scan)
            if self._select(profile, clients) or any(
                c.profile is None or c.send_port is None for c in clients
            ):
                raise ValueError("检测到客户端启动状态已变化；未重复启动，请刷新状态")
            self.progress[role].update(
                stage="launching", step=2, detail="正在启动官方 VRChat 客户端…"
            )
            await asyncio.to_thread(self.backend.launch, config, profile)
            deadline = self.clock() + 150
            while self.clock() < deadline:
                await self.sleep(2)
                await asyncio.to_thread(self.backend.mute)
                client = self._select(
                    profile, await asyncio.to_thread(self.backend.scan)
                )
                if client:
                    view = client_view(profile, client)
                    self.progress[role].update(
                        {k: view[k] for k in ("stage", "step", "detail")}
                    )
                    if view["stage"] in {
                        "ready",
                        "auth_error",
                        "wrong_account",
                        "offline_testing",
                    }:
                        return
                    # Let the user log in without holding the other launch button.
                    if view["stage"] == "waiting_login":
                        return
            if not self._select(profile, await asyncio.to_thread(self.backend.scan)):
                raise ValueError(
                    "官方启动器已运行，但 150 秒内未识别到此 Profile 的窗口；请查看游戏或反作弊启动提示。"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.progress[role].update(stage="failed", detail=str(exc))

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        for task in self.tasks.values():
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # Closing the web service never closes a game client.
