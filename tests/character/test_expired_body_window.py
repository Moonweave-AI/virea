import asyncio

from virea.character.behavior import BodyState, SpeechAvailability, choose_window
from virea.character.contracts import CharacterConfig


def test_ended_audio_cannot_reserve_millisecond_gesture_leases():
    choice, _ = asyncio.run(
        choose_window(
            CharacterConfig(),
            None,
            program=None,
            elapsed=0,
            body=BodyState(),
            previous="sentiavatar",
            speech=SpeechAvailability(available=True, remaining_seconds=0),
        )
    )
    assert choice.owner == "hold"
