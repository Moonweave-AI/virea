import asyncio
import time

import pytest
from test_playback import Sink
from test_protocol_and_pose import window

from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.desktop import DesktopTimeline
from virea.vrchat.osc import decode
from virea.vrchat.player import PerformancePlayer
from virea.vrchat.transport import reset_packet


def performance(prompt="A person waves and smiles.", seconds=1):
    return {
        "duration_seconds": seconds,
        "motions": [
            {
                "id": "greeting",
                "start_seconds": 0.1,
                "duration_seconds": seconds - 0.2,
                "prompt": prompt,
            }
        ],
        "speech": [],
    }


def test_actions_follow_motion_time_even_without_speech_and_release_in_gaps():
    timeline = DesktopTimeline(performance())
    assert timeline.sample(0)[0] == 0
    emote, face = timeline.sample(0.5)
    assert emote == 1 and face["mouthSmileLeft"] == 0.7
    assert timeline.sample(0.95)[0] == 0
    assert not any(timeline.sample(0.95)[1].values())
    assert timeline.summary(True)[0]["body_output"] == "avatar_preset:wave"
    assert timeline.summary(False)[0]["body_output"] == "not_transmitted"


@pytest.mark.parametrize(
    "prompt",
    [
        "A person does not wave.",
        "A person waves without smiling.",
        "A person nods.",
        "A person waves and claps.",
        "A person walks past a microwave.",
    ],
)
def test_unknown_negated_and_ambiguous_actions_do_not_become_wrong_emotes(prompt):
    assert DesktopTimeline(performance(prompt)).sample(0.5)[0] == 0


def test_player_checks_avatar_input_and_records_real_feedback_not_send_success():
    async def run():
        sink = Sink()
        config = BridgeConfig(desktop_emotes=True)
        player = PerformancePlayer(config, sink, [window()], performance())
        with pytest.raises(ValueError, match="writable VRCEmote"):
            await player.run()
        assert not sink.messages
        sink.protocol.query_status["writable_parameters"] = ["VRCEmote"]
        player = PerformancePlayer(config, sink, [window()], performance())
        task = asyncio.create_task(player.run())
        await asyncio.sleep(0.4)
        assert player.output_status()["emotes_sent"] == [1]
        assert player.output_status()["emotes_observed"] == []
        sink.protocol.values["VRCEmote"] = (1, time.monotonic())
        result = await task
        assert result["execution"]["emotes_observed"] == [1]
        assert result["execution"]["generated_body_transmitted"] is False
        assert result["execution"]["rendered_pose_verified"] is False
        assert result["audio_seconds"] == 0
        assert any(
            path.endswith("AI_Smile") and args[0] > 0.6 for path, args in sink.messages
        )
        emotes = [args[0] for path, args in sink.messages if path.endswith("VRCEmote")]
        assert emotes[0] == emotes[-1] == 0 and 1 in emotes
        assert sink.releases == 1

    asyncio.run(run())


def test_watchdog_always_releases_hot_enabled_emote_even_if_initially_disabled():
    values = dict(decode(reset_packet(BridgeConfig(desktop_emotes=False))))
    assert values["/avatar/parameters/VRCEmote"] == [0]
    assert "/input/Voice" not in values


def test_disabling_presets_does_not_disable_explicit_facial_cues():
    async def run():
        sink = Sink()
        result = await PerformancePlayer(
            BridgeConfig(), sink, [window()], performance()
        ).run()
        assert not result["execution"]["emotes_sent"]
        assert not any(path.endswith("VRCEmote") for path, _ in sink.messages)
        assert any(
            path.endswith("AI_Smile") and args[0] > 0.6 for path, args in sink.messages
        )

    asyncio.run(run())
