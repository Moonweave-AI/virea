import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from virea_api.routes.vrchat import router

from virea.vrchat.client_launch import ClientLaunchConfig, ClientLauncher, client_view
from virea.vrchat.client_launch_windows import (
    NativeClient,
    WindowsClientBackend,
    bound_arguments,
    launch_identity,
)

AI = "usr_11111111-1111-1111-1111-111111111111"
OBSERVER = "usr_22222222-2222-2222-2222-222222222222"


@pytest.fixture
def config(tmp_path):
    value = dict(
        vrchat_exe=str(tmp_path / "VRChat.exe"),
        steam_exe=str(tmp_path / "steam.exe"),
        steamvr_exe=str(tmp_path / "vrstartup.exe"),
        ai=dict(
            profile=1,
            send_port=19000,
            receive_port=19001,
            vr=True,
            label="AI",
            account_id=AI,
        ),
        observer=dict(
            profile=0,
            send_port=9000,
            receive_port=9001,
            vr=False,
            label="Observer",
            account_id=OBSERVER,
        ),
    )
    path = tmp_path / "vrchat-clients.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def native(profile, pid=100, **kwargs):
    return NativeClient(
        pid, float(pid), profile.profile, profile.send_port, profile.vr, **kwargs
    )


class Backend:
    def __init__(self, clients=()):
        self.clients = list(clients)
        self.events = []
        self.ready = True
        self.fail_mute = False
        self.close_exits = True

    def scan(self):
        return self.clients.copy()

    def validate(self, config):
        self.events.append("validate")

    def mute(self):
        self.events.append("mute")
        if self.fail_mute:
            raise ValueError("mute failed")

    def dependencies(self, config, profile):
        self.events.append(("dependencies", profile.profile))

    def dependencies_ready(self, profile):
        return self.ready

    def launch(self, config, profile):
        self.events.append(("launch", profile.profile))
        self.clients.append(native(profile, 100 + profile.profile))

    def close(self, client):
        self.events.append(("close", client.pid))
        if client not in self.clients:
            raise ValueError("identity changed")
        if self.close_exits:
            self.clients.remove(client)

    def alive(self, client):
        return client in self.clients


async def fast_sleep(_):
    await asyncio.sleep(0)


def test_start_is_idempotent_and_saved_login_is_not_reported_as_success(config):
    async def scenario():
        backend = Backend()
        launcher = ClientLauncher(config, backend=backend, sleep=fast_sleep)
        await launcher.begin("ai", "start")
        await launcher.begin("ai", "start")
        await launcher.tasks["ai"]
        view = (await launcher.snapshot())["clients"]["ai"]
        assert view["stage"] == "waiting_login" and view["step"] == 3
        assert view["running"] and not view["active"]
        await launcher.begin("ai", "start")
        assert backend.events.count(("launch", 1)) == 1
        assert backend.events.index("mute") < backend.events.index(("dependencies", 1))
        assert backend.events.index(("dependencies", 1)) < backend.events.index(
            ("launch", 1)
        )
        assert "account_id" not in json.dumps(await launcher.snapshot())
        await launcher.close()
        assert len(backend.clients) == 1  # API shutdown leaves game running.

    asyncio.run(scenario())


def test_both_roles_can_queue_and_restart_only_closes_requested_identity(config):
    async def scenario():
        backend = Backend()
        launcher = ClientLauncher(config, backend=backend, sleep=fast_sleep)
        await launcher.begin("observer", "start")
        await launcher.begin("ai", "start")
        await asyncio.gather(*launcher.tasks.values())
        assert len(backend.clients) == 2
        original_observer = next(c for c in backend.clients if c.profile == 0)
        await launcher.begin("ai", "restart")
        await launcher.tasks["ai"]
        assert [
            e for e in backend.events if isinstance(e, tuple) and e[0] == "close"
        ] == [("close", 101)]
        assert original_observer in backend.clients

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["mute", "dependencies", "close"])
def test_failed_prerequisites_never_launch_another_copy(config, kind):
    async def scenario():
        profile = ClientLaunchConfig.model_validate_json(config.read_text()).ai
        backend = Backend([native(profile)] if kind == "close" else [])
        backend.fail_mute = kind == "mute"
        backend.ready = kind != "dependencies"
        backend.close_exits = kind != "close"
        now = [0]

        async def tick(_):
            now[0] += 100
            await asyncio.sleep(0)

        launcher = ClientLauncher(
            config, backend=backend, clock=lambda: now[0], sleep=tick
        )
        await launcher.begin("ai", "restart")
        await launcher.tasks["ai"]
        view = (await launcher.snapshot())["clients"]["ai"]
        assert view["stage"] == "failed"
        assert not any(
            isinstance(e, tuple) and e[0] == "launch" for e in backend.events
        )
        if kind == "mute":
            assert not any(isinstance(e, tuple) for e in backend.events)

    asyncio.run(scenario())


def test_conflicting_profile_or_port_does_not_close_any_window(config):
    async def scenario():
        cfg = ClientLaunchConfig.model_validate_json(config.read_text())
        for bad in (
            replace(native(cfg.ai), profile=0),
            replace(native(cfg.ai), send_port=9000),
            replace(native(cfg.ai), vr=False),
        ):
            backend = Backend([bad])
            launcher = ClientLauncher(config, backend=backend)
            with pytest.raises(ValueError):
                await launcher.begin("ai", "restart")
            assert backend.events == []

    asyncio.run(scenario())


def test_role_account_and_api_health_are_required_for_ready(config):
    cfg = ClientLaunchConfig.model_validate_json(config.read_text())
    base = native(
        cfg.ai,
        account=AI,
        authentication="authenticated_in_log",
        connection="online_session_in_log",
        arrived=True,
    )
    assert client_view(cfg.ai, base)["stage"] == "ready"
    assert (
        client_view(cfg.ai, replace(base, authentication="api_auth_error_in_log"))[
            "stage"
        ]
        == "auth_error"
    )
    assert (
        client_view(cfg.ai, replace(base, account=OBSERVER))["stage"] == "wrong_account"
    )
    assert (
        client_view(cfg.ai, replace(base, connection="offline_testing"))["stage"]
        == "offline_testing"
    )
    assert client_view(cfg.ai, replace(base, arrived=False))["stage"] == "loading_world"
    assert (
        client_view(cfg.ai, replace(base, authentication="unknown"))["stage"]
        == "waiting_login"
    )


def test_no_auto_restart_on_401_and_invalid_configuration_is_redacted(config):
    async def scenario():
        cfg = ClientLaunchConfig.model_validate_json(config.read_text())
        backend = Backend(
            [native(cfg.ai, account=AI, authentication="api_auth_error_in_log")]
        )
        launcher = ClientLauncher(config, backend=backend)
        for _ in range(3):
            assert (await launcher.snapshot())["clients"]["ai"]["stage"] == "auth_error"
        assert not backend.events
        data = json.loads(config.read_text())
        data["password"] = "private-test-secret"
        config.write_text(json.dumps(data))
        result = await launcher.snapshot()
        assert not result["configured"] and "private-test-secret" not in json.dumps(
            result
        )
        with pytest.raises(ValueError):
            await launcher.begin("ai", "start")
        assert not backend.events

    asyncio.run(scenario())


def test_fixed_official_launcher_arguments_keep_profiles_modes_and_no_passwords(
    config, monkeypatch
):
    cfg = ClientLaunchConfig.model_validate_json(config.read_text())
    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: calls.append((args, kw)))
    backend = WindowsClientBackend()
    for profile in (cfg.observer, cfg.ai):
        backend.launch(cfg, profile)
    for (args, kwargs), profile in zip(calls, (cfg.observer, cfg.ai)):
        assert args[0].endswith("launch.exe") and not kwargs.get("shell")
        assert launch_identity(args) == (profile.profile, profile.send_port, profile.vr)
        assert ("--no-vr" in args) != profile.vr
        assert (
            "-screen-fullscreen" in args
            and args[args.index("-screen-fullscreen") + 1] == "0"
        )
        assert profile.account_id not in " ".join(args)


def test_launch_api_is_loopback_only_and_cannot_receive_credentials_or_commands():
    calls = []

    class Launcher:
        async def snapshot(self):
            return {"clients": {}}

        async def begin(self, role, action, **kwargs):
            calls.append((role, action))
            return {"accepted": True}

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.vrchat_clients = Launcher()
    app.state.vrchat = SimpleNamespace()
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)
    ) as client:
        assert client.get("/api/v1/vrchat/clients").status_code == 200
        assert (
            client.post(
                "/api/v1/vrchat/clients/observer", json={"action": "start"}
            ).status_code
            == 202
        )
        assert (
            client.post(
                "/api/v1/vrchat/clients/ai", json={"action": "restart"}
            ).status_code
            == 202
        )
        assert client.post("/api/v1/vrchat/clients/other", json={}).status_code == 422
        assert (
            client.post(
                "/api/v1/vrchat/clients/ai", json={"password": "secret"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/vrchat/clients/ai",
                json={"action": "start", "executable": "evil.exe"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/vrchat/clients/ai",
                json={},
                headers={"Origin": "https://other.test"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/vrchat/clients/ai", json={}, headers={"Host": "attacker.test"}
            ).status_code
            == 403
        )
    with TestClient(
        app, base_url="http://127.0.0.1", client=("192.0.2.1", 1234)
    ) as client:
        assert client.post("/api/v1/vrchat/clients/ai", json={}).status_code == 403
    assert calls == [("observer", "start"), ("ai", "restart")]


def test_protected_slow_start_uses_pid_owned_port_not_other_client_log(
    tmp_path, monkeypatch
):
    from datetime import datetime

    import psutil

    root = tmp_path / "AppData/LocalLow/VRChat/VRChat"
    root.mkdir(parents=True)
    for stamp, profile, port in [(15, 1, 19000), (16, 0, 9000)]:
        (root / f"output_log_2026-10-10_17-00-{stamp}.txt").write_text(
            f"Arg: --profile={profile}\nArg: --osc={port}:127.0.0.1:{port + 1}\n"
        )
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    def denied():
        raise psutil.AccessDenied(42)

    process = SimpleNamespace(
        pid=42,
        cmdline=denied,
        create_time=lambda: datetime(2026, 10, 10, 17).timestamp(),
    )
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **_: [
            SimpleNamespace(pid=42, laddr=SimpleNamespace(port=19000)),
            SimpleNamespace(pid=43, laddr=SimpleNamespace(port=9000)),
        ],
    )
    assert launch_identity(bound_arguments(process)) == (1, 19000, True)
    monkeypatch.setattr(psutil, "net_connections", lambda **_: [])
    assert bound_arguments(process) == []


def test_unreadable_live_client_logs_do_not_report_stopped(config, monkeypatch):
    import psutil

    from virea.vrchat import client_launch_windows as windows

    monkeypatch.setattr(windows.sys, "platform", "win32")
    process = SimpleNamespace(
        pid=42,
        info={"name": "VRChat.exe"},
        create_time=lambda: 123.0,
        cmdline=lambda: ["VRChat.exe", "--profile=1", "--osc=19000:127.0.0.1:19001"],
    )
    monkeypatch.setattr(psutil, "process_iter", lambda *_: [process])

    def unreadable(_):
        raise PermissionError("log temporarily locked")

    monkeypatch.setattr(windows, "_client_log_text", unreadable)
    backend = WindowsClientBackend()
    client = backend.scan()[0]
    assert client.pid == 42 and client.profile == 1 and client.account == ""

    async def scenario():
        launcher = ClientLauncher(config, backend=backend)
        await launcher.begin("ai", "start")
        assert not launcher.tasks
        monkeypatch.setattr(windows, "bound_arguments", unreadable)
        assert backend.scan()[0].profile is None
        with pytest.raises(ValueError, match="尚未确认"):
            await launcher.begin("ai", "start")
        assert not launcher.tasks

    asyncio.run(scenario())
