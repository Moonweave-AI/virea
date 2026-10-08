import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_service import FakeCharacters
from test_transport import socket_port

from virea.character.contracts import CharacterConfig
from virea.character.performance_contracts import PerformancePlan
from virea.character.providers.unified import UnifiedMotionProvider
from virea.vrchat.autonomy import NextStep, next_step
from virea.vrchat.contracts import BridgeConfig, ConnectRequest
from virea.vrchat.osc import message
from virea.vrchat.service import VRChatService


@pytest.mark.parametrize(
    "config",
    [
        {"send_port": 9000},
        {"send_port": 9001},
        {"receive_port": 9000},
        {"receive_port": 9001},
        {"target_role": "observer"},
        {"oscquery": True},
    ],
)
def test_observer_ports_and_discovery_cannot_be_targeted(config):
    with pytest.raises(ValidationError):
        BridgeConfig(**config)


def test_ai_binding_requires_observed_avatar_and_idle_task(tmp_path):
    async def run():
        bridge = VRChatService(FakeCharacters(tmp_path))
        await bridge.connect(
            ConnectRequest(
                config=BridgeConfig(send_port=socket_port(), receive_port=socket_port())
            )
        )
        try:
            bridge.transport.protocol.datagram_received(
                message("/avatar/change", "avtr_ai"), ("127.0.0.1", 12345)
            )
            assert not bridge.transport.ready()[0]
            with pytest.raises(ValueError, match="match feedback"):
                await bridge.bind_avatar("avtr_observer")
            await bridge.bind_avatar("avtr_ai")
            assert bridge.transport.ready()[0]
            await bridge.message("hello")
            with pytest.raises(ValueError, match="stop the current task"):
                await bridge.bind_avatar("avtr_ai")
            bridge.transport.protocol.datagram_received(
                message("/avatar/change", "avtr_changed"), ("127.0.0.1", 12345)
            )
            assert not bridge.transport.ready()[0]
        finally:
            await bridge.close()

    asyncio.run(run())


def test_followup_uses_completed_outputs_and_stops_when_goal_finished(monkeypatch):
    completed = [
        {"motions": [{"prompt": "A person waves."}], "speech": [{"text": "Hello"}]}
    ]

    async def completion(config, client, history, context, rules, schema, **kwargs):
        assert context["completed_outputs"] == completed
        assert context["original_goal"] == "Wave and say Hello"
        return {"continue_goal": False, "instruction": ""}

    monkeypatch.setattr("virea.vrchat.autonomy.structured_completion", completion)
    session = SimpleNamespace(
        config=object(), history=[{"role": "user", "content": "Wave and say Hello"}]
    )
    assert not asyncio.run(next_step(session, object(), completed, {})).continue_goal


def test_selected_step_controls_duration_without_rewriting_history(monkeypatch):
    history = [
        {
            "role": "user",
            "content": "First perform for 8 seconds; then do the next round.",
        }
    ]
    instruction = "用4秒 A person stands calmly. 说：欢迎体验。"
    plan = PerformancePlan(
        motions=[
            dict(
                id="rest",
                prompt="A person stands calmly.",
                start_seconds=0,
                duration_seconds=4,
            )
        ],
        speech=[],
    )

    async def completion(config, client, messages, context, rules, schema, **kwargs):
        assert messages[-1]["content"] == instruction
        return plan.model_dump()

    monkeypatch.setattr(
        "virea.character.providers.unified.structured_completion", completion
    )
    provider = UnifiedMotionProvider(
        CharacterConfig(motion_backend="motioncraft"), object()
    )
    result = asyncio.run(
        provider.plan(
            history,
            {
                "trigger": "context",
                "environment": "VIREA_AUTONOMOUS_STEP\n" + instruction,
            },
        )
    )
    assert result.motion_end == 4 and len(history) == 1


def test_stop_cancels_slow_followup_without_blocking_pump(tmp_path, monkeypatch):
    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def slow(*args):
            started.set()
            try:
                await asyncio.sleep(30)
            finally:
                cancelled.set()
            return NextStep(continue_goal=False, instruction="")

        monkeypatch.setattr("virea.vrchat.service.next_step", slow)
        characters = FakeCharacters(tmp_path)
        characters.client = object()
        bridge = VRChatService(characters)
        await bridge.connect(
            ConnectRequest(
                config=BridgeConfig(
                    send_port=socket_port(),
                    receive_port=socket_port(),
                    avatar_id="avtr_ai",
                )
            )
        )
        try:
            bridge.transport.protocol.datagram_received(
                message("/avatar/change", "avtr_ai"), ("127.0.0.1", 12345)
            )
            bridge.goal_active = True
            await asyncio.wait_for(started.wait(), 2)
            await asyncio.wait_for(bridge.control("interrupt"), 1)
            assert (
                cancelled.is_set() and not bridge.goal_active and not bridge.pump.done()
            )
        finally:
            await bridge.close()

    asyncio.run(run())


def test_reconnect_restores_only_explicit_conversation_history(tmp_path):
    async def run():
        characters = FakeCharacters(tmp_path)
        characters.session.history = []
        bridge = VRChatService(characters)
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        await bridge.connect(
            ConnectRequest(
                config=BridgeConfig(
                    send_port=socket_port(), receive_port=socket_port()
                ),
                history=history,
            )
        )
        try:
            assert characters.session.history == history
        finally:
            await bridge.close()

    asyncio.run(run())
