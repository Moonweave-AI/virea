import asyncio
from datetime import datetime, timezone

import pytest

from virea.vrchat.client_status import _session_log_text
from virea.vrchat.room_invites import invitation_event, matching_invitation
from virea.vrchat.rooms import RoomClient, RoomCommands

HOST = "usr_11111111-1111-1111-1111-111111111111"
GUEST = "usr_22222222-2222-2222-2222-222222222222"
WORLD = "wrld_33333333-3333-3333-3333-333333333333"
ROOM = WORLD + f":123~private({HOST})~region(us)"
CREATED = datetime(2026, 10, 10, 10, 31, 41, tzinfo=timezone.utc).timestamp()
NOTICE = (
    f"2026.10.10 18:31:42 Debug      -  Received Notification: <Notification from username:Private Name, "
    f"sender user id:{HOST} to {GUEST} of type: invite, id: not_44444444-4444-4444-4444-444444444444, "
    f"created at: 10/10/2026 10:31:41 UTC, details: {{{{worldId={ROOM}, worldName=VRChat Home}}}}, "
    'type:invite, m seen:False, message: "private message">\n'
)


def test_real_received_record_retains_only_required_metadata(tmp_path):
    path = tmp_path / "session.txt"
    path.write_text(f"User Authenticated: Guest ({GUEST})\n" + NOTICE, encoding="utf-8")
    text = _session_log_text(path)
    assert matching_invitation(text, HOST, GUEST, ROOM, now=CREATED + 1) == {
        "worldId": ROOM
    }
    assert all(
        value not in text
        for value in ["Private Name", "private message", "VRChat Home", "not_4444"]
    )
    assert matching_invitation(text, HOST, GUEST, ROOM, now=CREATED + 601) is None
    assert matching_invitation(text, HOST, GUEST, ROOM, now=CREATED - 1) is None
    assert matching_invitation(text, GUEST, HOST, ROOM, now=CREATED + 1) is None
    assert (
        matching_invitation(text, HOST, GUEST, WORLD + ":other", now=CREATED + 1)
        is None
    )


@pytest.mark.parametrize(
    "event",
    [
        f"User Authenticated: Other ({HOST})\n",
        '"Logged out"\n',
        '"Missing Credentials"\n',
        NOTICE.replace(
            "Received Notification: ", "Remove notification from AllTime notifications:"
        ),
    ],
)
def test_deleted_invites_logout_auth_failure_and_account_switch_clear_grant(
    tmp_path, event
):
    path = tmp_path / "session.txt"
    path.write_text(f"User Authenticated: Guest ({GUEST})\n" + NOTICE, encoding="utf-8")
    assert matching_invitation(
        _session_log_text(path), HOST, GUEST, ROOM, now=CREATED + 1
    )
    with path.open("a", encoding="utf-8") as stream:
        stream.write(event)
    assert (
        matching_invitation(_session_log_text(path), HOST, GUEST, ROOM, now=CREATED + 2)
        is None
    )


@pytest.mark.parametrize(
    "line",
    [
        "[Chat] " + NOTICE,
        NOTICE.replace("type: invite,", "type: requestInvite,"),
        NOTICE.replace(
            "Received Notification:", "AcceptNotification for notification:"
        ),
    ],
)
def test_chat_request_or_old_acceptance_is_not_a_new_invitation(line):
    assert invitation_event(line) is None


@pytest.mark.parametrize("action", ["join", "accept"])
def test_game_received_invite_works_without_separate_api_cookie(action):
    async def scenario():
        current = {
            "ai": RoomClient(1, 10, HOST, ROOM),
            "observer": RoomClient(2, 20, GUEST, WORLD + ":200"),
        }

        def received(guest, host):
            assert guest == current["observer"] and host == current["ai"]
            return {"worldId": ROOM}

        async def resolve(location):
            assert location == ROOM
            return "launch-code"

        def send(pid, started, room, short):
            assert (pid, started, room, short) == (2, 20, ROOM, "launch-code")
            current["observer"] = RoomClient(2, 20, GUEST, ROOM)

        command = RoomCommands(
            pair=lambda _: current.copy(),
            received=received,
            resolve=resolve,
            send=send,
            api=lambda _: pytest.fail("use the game's verified notification"),
        )
        state = await command.run(action, "observer", 19000)
        assert (
            state["same_instance"] and state["invitation_source"] == "game_notification"
        )

    asyncio.run(scenario())
