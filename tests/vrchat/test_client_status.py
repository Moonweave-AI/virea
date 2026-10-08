from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from virea_api.routes.vrchat import router

from virea.vrchat import client_status
from virea.vrchat.client_status import authentication_status, connection_status


def test_session_evidence_survives_large_logs_and_observes_appended_departure(tmp_path):
    account = "usr_11111111-1111-1111-1111-111111111111"
    room = "wrld_22222222-2222-2222-2222-222222222222:123~private(secret)"
    path = tmp_path / "session.txt"
    path.write_text(
        f"User Authenticated: Private ({account})\nConnected to master in usw\n"
        f"[Behaviour] Joining {room}\nOnPlayerJoined Private ({account})\n"
        + "unrelated diagnostics\n"
        * 20000,
        encoding="utf-8",
    )
    for _ in range(2):
        text = client_status._session_log_text(path)
        assert client_status.room_evidence(text) == (account, room)
        assert connection_status(text) == "online_session_in_log"
        assert "unrelated" not in text
        assert "Private" not in text
    with path.open("a", encoding="utf-8") as stream:
        stream.write("OnDisconnected: Timeout\n")
    text = client_status._session_log_text(path)
    assert client_status.room_evidence(text) is None
    assert connection_status(text) == "disconnected_in_log"
    path.write_text("You are in offline testing mode\n", encoding="utf-8")
    text = client_status._session_log_text(path)
    assert authentication_status(text) == "unknown"
    assert connection_status(text) == "offline_testing"


def test_partial_log_event_is_not_promoted_until_complete(tmp_path):
    path = tmp_path / "session.txt"
    path.write_bytes(b"Connected to master in ")
    assert client_status._session_log_text(path) == ""
    with path.open("ab") as stream:
        stream.write(b"usw\n")
    assert (
        connection_status(client_status._session_log_text(path))
        == "online_session_in_log"
    )


def test_room_evidence_requires_arrival_and_resets_after_departure():
    account = "usr_11111111-1111-1111-1111-111111111111"
    room = "wrld_22222222-2222-2222-2222-222222222222:123~private(secret)"
    prefix = (
        f"User Authenticated: Private Name ({account})\n[Behaviour] Joining {room}\n"
    )
    assert client_status.room_evidence(prefix) is None
    arrived = prefix + f"OnPlayerJoined Private Name ({account})\n"
    assert client_status.room_evidence(arrived) == (account, room)
    for event in ["OnLeftRoom", "OnDisconnected: Timeout", '"Logged out"']:
        assert client_status.room_evidence(arrived + event) is None
    assert (
        client_status.room_evidence(arrived + "[Behaviour] Joining wrld_other:456")
        is None
    )


def test_live_client_room_comparison_only_returns_diagnostic_states(monkeypatch):
    import sys

    account1 = "usr_11111111-1111-1111-1111-111111111111"
    account2 = "usr_22222222-2222-2222-2222-222222222222"
    room = "wrld_33333333-3333-3333-3333-333333333333:123~private(secret)"
    texts = {
        pid: f"User Authenticated: Hidden ({account})\nConnected to master in usw\n"
        f"[Behaviour] Joining {room}\nOnPlayerJoined Hidden ({account})\n"
        for pid, account in [(1, account1), (2, account2)]
    }
    processes = [
        SimpleNamespace(pid=pid, info={"name": "VRChat.exe"}, name=lambda: "VRChat.exe")
        for pid in (1, 2)
    ]
    monkeypatch.setattr(client_status, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        client_status, "_client_log_text", lambda process: texts[process.pid]
    )
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(
            Process=lambda pid: processes[pid - 1],
            process_iter=lambda fields: processes,
            Error=RuntimeError,
        ),
    )
    assert client_status.selected_client_status(1) == {
        "authentication": "authenticated_in_log",
        "connection": "online_session_in_log",
        "same_instance": "matched_in_live_client_logs",
    }
    original_peer = texts[2]
    for changed in [
        original_peer + "OnLeftRoom",
        original_peer.replace(":123", ":456"),
        original_peer.replace(account2, account1),
    ]:
        texts[2] = changed
        assert client_status.selected_client_status(1)["same_instance"] == "unverified"


def test_log_matching_refuses_two_candidates_for_one_process(tmp_path, monkeypatch):
    from datetime import datetime

    root = tmp_path / "AppData/LocalLow/VRChat/VRChat"
    root.mkdir(parents=True)
    for stamp in ["2026-10-08_17-00-01", "2026-10-08_17-00-02"]:
        (root / f"output_log_{stamp}.txt").write_text("private", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    process = SimpleNamespace(create_time=lambda: datetime(2026, 10, 8, 17).timestamp())
    assert client_status._client_log_text(process) == ""


def test_connection_diagnostic_requires_explicit_network_evidence():
    assert (
        connection_status(
            "User Authenticated: private\nAntiCheat Session Begin: Success"
        )
        == "unknown"
    )
    assert (
        connection_status(
            "You are in offline testing mode, and cannot travel to online worlds."
        )
        == "offline_testing"
    )
    assert (
        connection_status("Connected to master in usw\nOnDisconnected: Timeout")
        == "disconnected_in_log"
    )
    assert (
        connection_status(
            "OnDisconnected: DisconnectByClientLogic\nConnected to master in usw"
        )
        == "online_session_in_log"
    )
    assert (
        connection_status('Connected to master in usw\n"Missing Credentials"')
        == "online_session_in_log"
    )


def test_authentication_diagnostic_is_ordered_and_never_exposes_credentials():
    assert (
        authentication_status(
            'User Authenticated: private-account\n"Missing Credentials"'
        )
        == "api_auth_error_in_log"
    )
    assert (
        authentication_status(
            '"Missing Credentials"\nUser Authenticated: private-account'
        )
        == "authenticated_in_log"
    )
    assert authentication_status("Unrelated log with token=private") == "unknown"
    assert authentication_status('"Logged out"') == "signed_out_in_log"


def test_avatar_preview_serves_only_the_fixed_local_model(tmp_path):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.control_plane = SimpleNamespace(paths=SimpleNamespace(avatars=tmp_path))
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)
    ) as client:
        assert client.get("/api/v1/vrchat/avatar-preview").status_code == 404
        (tmp_path / "vrchat.vrm").write_bytes(b"glTF-preview")
        response = client.get("/api/v1/vrchat/avatar-preview")
        assert response.status_code == 200
        assert response.content == b"glTF-preview"
        assert response.headers["cache-control"] == "no-cache"
        assert (
            client.get(
                "/api/v1/vrchat/avatar-preview",
                headers={"Origin": "https://other.example"},
            ).status_code
            == 403
        )
    with TestClient(
        app, base_url="http://127.0.0.1", client=("192.0.2.1", 1234)
    ) as client:
        assert client.get("/api/v1/vrchat/avatar-preview").status_code == 403
