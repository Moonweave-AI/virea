"""Recover historical REST failures only from a newer authenticated API write."""

from collections import OrderedDict
from datetime import datetime, timezone

import pytest

from virea.vrchat import client_status as status
from virea.vrchat.room_invites import invitation_event

AI = "usr_11111111-1111-1111-1111-111111111111"
OBSERVER = "usr_22222222-2222-2222-2222-222222222222"
BASE = datetime(2026, 10, 11, tzinfo=timezone.utc).timestamp()


def native_line(offset, text):
    stamp = datetime.fromtimestamp(BASE + offset).strftime("%Y.%m.%d %H:%M:%S")
    return f"{stamp} Debug      -  {text}\n"


def receipt(offset=30, *, sender=AI, recipient=OBSERVER, kind="invite", received=None):
    created = datetime.fromtimestamp(BASE + offset, timezone.utc).strftime(
        "%m/%d/%Y %H:%M:%S"
    )
    return native_line(
        offset if received is None else received,
        f"Received Notification: <Notification from username:Private Name, sender user id:{sender} "
        f"to {recipient} of type: {kind}, id: not_33333333-3333-3333-3333-333333333333, "
        f"created at: {created} UTC, details: {{{{worldId=wrld_44444444-4444-4444-4444-444444444444:1}}}}, "
        'message: "private text">',
    )


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "_LOG_CURSORS", OrderedDict())
    paths = [tmp_path / name for name in ("ai.log", "observer.log")]
    for path, account in zip(paths, (AI, OBSERVER)):
        path.write_text(
            native_line(-100, f"User Authenticated: Name ({account})")
            + native_line(0, '"Missing Credentials"'),
            encoding="utf-8",
        )
        status._session_log_text(path)
    return paths


def append(path, text):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(text)
    return status._session_log_text(path)


def test_delivered_invite_recovers_sender_only_and_new_401_revokes_it(pair):
    ai, observer = pair
    text = append(observer, receipt())
    assert status.authentication_status(text) == "api_auth_error_in_log"
    assert (
        status.authentication_status(status._session_log_text(ai))
        == "authenticated_in_log"
    )
    assert "private text" not in status._session_log_text(ai)
    assert (
        status.authentication_status(
            append(ai, native_line(60, '"Missing Credentials"'))
        )
        == "api_auth_error_in_log"
    )
    append(
        observer, receipt(received=65)
    )  # Replayed old notification is not a new API write.
    assert (
        status.authentication_status(status._session_log_text(ai))
        == "api_auth_error_in_log"
    )


@pytest.mark.parametrize("kind", ["invite", "requestInvite"])
def test_both_native_invitation_writes_can_recover_api_without_relogin(pair, kind):
    ai, observer = pair
    append(observer, receipt(kind=kind))
    assert (
        status.authentication_status(status._session_log_text(ai))
        == "authenticated_in_log"
    )
    if kind == "requestInvite":
        assert invitation_event(receipt(kind=kind)) is None  # Never an entry grant.


@pytest.mark.parametrize(
    "record",
    [
        receipt(offset=-30),
        receipt(recipient=AI),
        receipt(sender=OBSERVER),
        "[Chat] " + receipt(),
        receipt(kind="friendRequest"),
        receipt(received=1000),
        receipt(received=-30),
        receipt().replace(
            "Received Notification:", "Remove notification from AllTime notifications:"
        ),
    ],
)
def test_unrelated_stale_forged_or_removed_notifications_cannot_clear_401(pair, record):
    ai, observer = pair
    append(observer, record)
    assert (
        status.authentication_status(status._session_log_text(ai))
        == "api_auth_error_in_log"
    )


def test_logout_and_undated_failure_never_recover_from_peer_receipts(pair):
    ai, observer = pair
    append(ai, native_line(5, '"Logged out"'))
    append(observer, receipt())
    assert (
        status.authentication_status(status._session_log_text(ai))
        == "signed_out_in_log"
    )
    append(ai, '"Missing Credentials"\n')
    assert (
        status.authentication_status(status._session_log_text(ai))
        == "api_auth_error_in_log"
    )


def test_room_connection_and_incoming_pipeline_do_not_clear_api_failure(pair):
    ai, observer = pair
    append(
        ai,
        native_line(20, "Connected to master in usw")
        + receipt(sender=OBSERVER, recipient=AI),
    )
    assert (
        status.authentication_status(status._session_log_text(ai))
        == "api_auth_error_in_log"
    )
    assert (
        status.authentication_status(status._session_log_text(observer))
        == "authenticated_in_log"
    )


def test_room_pair_cold_start_reads_both_receipts_before_rejecting_either_account(
    pair, monkeypatch
):
    from types import SimpleNamespace

    import psutil

    from virea.vrchat import rooms

    ai, observer = pair
    append(observer, receipt())
    append(ai, receipt(sender=OBSERVER, recipient=AI, kind="requestInvite"))
    for path, account in zip(pair, (AI, OBSERVER)):
        append(
            path,
            native_line(
                40, "[Behaviour] Joining wrld_44444444-4444-4444-4444-444444444444:1"
            )
            + native_line(41, f"OnPlayerJoined Name ({account})"),
        )
    status._LOG_CURSORS.clear()
    monkeypatch.setattr(rooms, "vrchat_windows", lambda: [])
    targets = {
        role: SimpleNamespace(pid=i, started=i * 10)
        for i, role in enumerate(("ai", "observer"), 1)
    }
    monkeypatch.setattr(rooms, "select_target", lambda _, role, port: targets[role])
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: SimpleNamespace(pid=pid, create_time=lambda: pid * 10),
    )
    monkeypatch.setattr(
        rooms,
        "_client_log_text",
        lambda process: status._session_log_text(pair[process.pid - 1]),
    )
    clients = rooms.local_pair(19000)
    assert clients["ai"].account == AI and clients["observer"].account == OBSERVER


def test_confirmed_arrival_does_not_keep_stale_relogin_instructions():
    from virea.vrchat.rooms import RoomCommands

    rooms = RoomCommands()
    rooms.state.update(
        stage="authentication_required",
        recovery="restore_game_session",
        affected_roles=["ai"],
    )
    result = rooms.snapshot(live_same_instance=True)
    assert result["stage"] == "arrived"
    assert "recovery" not in result and "affected_roles" not in result
