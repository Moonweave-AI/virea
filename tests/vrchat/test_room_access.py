"""Private-instance navigation needs a grant, and live scenes can have expired auth."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from virea.vrchat import rooms

WORLD = "wrld_11111111-1111-1111-1111-111111111111"
AI = "usr_11111111-1111-1111-1111-111111111111"
OBSERVER = "usr_22222222-2222-2222-2222-222222222222"
PRIVATE = WORLD + f":123~private({AI})~region(us)"
PAIR = {
    "ai": rooms.RoomClient(1, 10, AI, PRIVATE),
    "observer": rooms.RoomClient(2, 20, OBSERVER, WORLD + ":200"),
}


def invite(**updates):
    return {
        "type": "invite",
        "senderUserId": AI,
        "receiverUserId": OBSERVER,
        "details": {"worldId": PRIVATE},
        **updates,
    }


@pytest.mark.parametrize("invalid", [("ai",), ("observer",), ("ai", "observer")])
def test_401_after_arrival_blocks_room_commands_for_exact_affected_accounts(
    monkeypatch, invalid
):
    import psutil

    monkeypatch.setattr(rooms, "vrchat_windows", lambda: [])
    monkeypatch.setattr(rooms, "select_target", lambda _, role, port: PAIR[role])
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: SimpleNamespace(pid=pid, create_time=lambda: pid * 10),
    )

    def log(process):
        role = "ai" if process.pid == 1 else "observer"
        client = PAIR[role]
        return (
            f"User Authenticated: name ({client.account})\n[Behaviour] Joining {client.room}\n"
            f"OnPlayerJoined name ({client.account})\n"
            + ('"Missing Credentials"' if role in invalid else "")
        )

    monkeypatch.setattr(rooms, "_client_log_text", log)
    with pytest.raises(rooms.RoomAuthenticationError) as error:
        rooms.local_pair(19000)
    assert error.value.roles == list(invalid)


def test_game_auth_error_stops_before_pipe_selection_or_invitation():
    async def scenario():
        def pair(_):
            raise rooms.RoomAuthenticationError(["observer"])

        def unexpected(*_):
            pytest.fail("auth failure cannot send any input")

        command = rooms.RoomCommands(
            pair=pair, select=unexpected, api=unexpected, send=unexpected
        )
        with pytest.raises(rooms.RoomAuthenticationError):
            await command.run("join", "auto", 19000)
        assert command.state["stage"] == "authentication_required"
        assert command.state["affected_roles"] == ["observer"]
        assert command.state["same_instance"] is False

    asyncio.run(scenario())


def test_private_join_without_api_session_never_uses_anonymous_short_code(monkeypatch):
    monkeypatch.delenv("VIREA_VRCHAT_AI_AUTH", raising=False)

    async def scenario():
        async def resolve(_):
            pytest.fail("a short code is not an invitation")

        command = rooms.RoomCommands(
            pair=lambda _: PAIR,
            resolve=resolve,
            send=lambda *_: pytest.fail("not authorized"),
        )
        with pytest.raises(rooms.RoomInvitationRequired):
            await command.run("join", "observer", 19000)
        assert command.state["stage"] == "invitation_required"
        assert not command.state["same_instance"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        invite(senderUserId=OBSERVER),
        invite(receiverUserId="usr_unrelated"),
        invite(details={"worldId": WORLD + ":old"}),
    ],
)
def test_wrong_or_missing_invitation_receipt_prevents_launch(response):
    async def scenario():
        class API:
            async def verify(self, account):
                assert account == AI

            async def request(self, *args, **kwargs):
                return response

        command = rooms.RoomCommands(
            pair=lambda _: PAIR,
            api=lambda _: API(),
            send=lambda *_: pytest.fail("no valid receipt"),
        )
        with pytest.raises(ValueError, match="未确认"):
            await command.run("join", "observer", 19000)

    asyncio.run(scenario())


def test_successful_invite_is_reused_for_join_without_duplicate_post():
    async def scenario():
        current = PAIR.copy()
        calls = []

        class API:
            async def verify(self, account):
                assert account == AI

            async def request(self, *args, **kwargs):
                calls.append("invite")
                return invite(
                    details={"worldId": PRIVATE, "shortName": "valid-short-name"}
                )

        def send(pid, started, location, code):
            assert (pid, started, location, code) == (
                2,
                20,
                PRIVATE,
                "valid-short-name",
            )
            assert calls == ["invite"]
            calls.append("join")
            current["observer"] = rooms.RoomClient(2, 20, OBSERVER, PRIVATE)

        command = rooms.RoomCommands(
            pair=lambda _: current.copy(), api=lambda _: API(), send=send
        )
        assert (await command.run("invite", "observer", 19000))[
            "stage"
        ] == "invitation_sent"
        assert (await command.run("join", "observer", 19000))["same_instance"]
        assert calls == ["invite", "join"]

    asyncio.run(scenario())


def test_uncertain_invite_is_not_repeated_or_treated_as_permission():
    async def scenario():
        calls = []

        class API:
            async def verify(self, account):
                pass

            async def request(self, *args, **kwargs):
                calls.append("post")
                raise httpx.ReadTimeout("uncertain")

        command = rooms.RoomCommands(
            pair=lambda _: PAIR,
            api=lambda _: API(),
            send=lambda *_: pytest.fail("uncertain invitation"),
        )
        with pytest.raises(httpx.ReadTimeout):
            await command.run("join", "observer", 19000)
        with pytest.raises(ValueError, match="未重复发送"):
            await command.run("join", "observer", 19000)
        assert calls == ["post"]

    asyncio.run(scenario())


def test_host_room_change_during_api_verification_prevents_invitation():
    async def scenario():
        current = PAIR.copy()

        class API:
            async def verify(self, account):
                current["ai"] = rooms.RoomClient(1, 10, AI, WORLD + ":new")

            async def request(self, *args, **kwargs):
                pytest.fail("host moved before POST")

        command = rooms.RoomCommands(pair=lambda _: current.copy(), api=lambda _: API())
        with pytest.raises(ValueError, match="邀请操作停止"):
            await command.run("join", "observer", 19000)

    asyncio.run(scenario())


def test_authentication_loss_while_loading_stops_waiting_immediately():
    async def scenario():
        sent = False

        def pair(_):
            if sent:
                raise rooms.RoomAuthenticationError(["observer"])
            return {**PAIR, "ai": rooms.RoomClient(1, 10, AI, WORLD + ":public")}

        def send(*_):
            nonlocal sent
            sent = True

        command = rooms.RoomCommands(pair=pair, send=send)
        with pytest.raises(rooms.RoomAuthenticationError):
            await command.run("join", "observer", 19000)
        assert command.state["stage"] == "authentication_required"

    asyncio.run(scenario())


def test_prefer_invitation_short_name_over_secure_name():
    def reply(request):
        return httpx.Response(
            200, json={"shortName": "short-name", "secureName": "fallback"}
        )

    assert (
        asyncio.run(
            rooms.instance_short_name(PRIVATE, client=httpx.MockTransport(reply))
        )
        == "short-name"
    )
