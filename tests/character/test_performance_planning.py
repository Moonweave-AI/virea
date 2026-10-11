import asyncio

import pytest

from virea.character.contracts import CharacterConfig
from virea.character.performance_planning import requested_motion_duration
from virea.character.providers.unified import UnifiedMotionProvider


def test_later_round_duration_is_not_applied_to_the_current_performance():
    for text in (
        "第一轮做8秒欢迎介绍，下一轮用4秒站立。现在只规划第一轮。",
        "First round: wave 8 seconds. Next round: stand for 4 seconds.",
        "用8秒挥手，再用4秒站立。",
    ):
        assert requested_motion_duration([{"role": "user", "content": text}]) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("用约35秒表演花园故事，第6秒说你好。", 35),
        ("表演34秒的服装展示，第7秒开始说话。", 34),
        ("Perform a 32-second greeting.", 32),
        ("第5秒说你好，先抬手3秒。", None),
        ("完成约36秒或进行约42秒的演出。", None),
    ],
)
def test_only_unambiguous_total_durations_are_extracted(text, expected):
    assert requested_motion_duration([{"role": "user", "content": text}]) == expected


def test_planner_repairs_short_action_track_instead_of_stretching_it(monkeypatch):
    calls = []

    async def completion(config, client, history, context, *args, **kwargs):
        calls.append(context)
        duration = 25 if len(calls) == 1 else 35
        return {
            "motions": [
                {
                    "id": "walk",
                    "prompt": "A person walks slowly.",
                    "start_seconds": 0,
                    "duration_seconds": duration,
                }
            ],
            "speech": [],
        }

    monkeypatch.setattr(
        "virea.character.providers.unified.structured_completion", completion
    )
    provider = UnifiedMotionProvider(
        CharacterConfig(motion_backend="motioncraft"), object()
    )
    result = asyncio.run(
        provider.plan([{"role": "user", "content": "用约35秒表演一个故事。"}], {})
    )
    assert result.motion_end == 35
    assert (
        len(calls) == 2 and "last action ends at 25" in calls[1]["validation_feedback"]
    )
