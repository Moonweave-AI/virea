import pytest
from virea_flood.timeline import build_timeline, parse_user_segments


def test_single_prompt_uses_default_duration():
    result = parse_user_segments("walk forward", 5.0)
    assert len(result) == 1
    assert result[0].seconds == 5.0


def test_timed_prompts_produce_monotonic_endpoints():
    result = build_timeline(
        "2 | walk forward\n3 | turn around",
        12,
        pre_roll=False,
        neural_return=False,
    )
    assert result.prompts == ("walk forward", "turn around")
    assert result.text_end == (10, 25)
    assert result.total_tokens == 25
    assert result.expected_frames == 100


def test_pre_and_post_stand_are_added():
    result = build_timeline("2 | wave", 2, pre_roll=True, neural_return=True)
    assert len(result.prompts) == 3
    assert "stand still" in result.prompts[0]
    assert "stand still" in result.prompts[-1]


def test_max_seconds_is_enforced():
    with pytest.raises(ValueError):
        build_timeline(
            "10 | walk", 10, pre_roll=False, neural_return=False, max_seconds=5
        )


def test_mixed_timeline_and_plain_lines_are_rejected():
    with pytest.raises(ValueError):
        parse_user_segments("walk forward\n3 | turn around", 5.0)


def test_invalid_default_duration_is_rejected():
    with pytest.raises(ValueError):
        parse_user_segments("walk forward", 0.0)
