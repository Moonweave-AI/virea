import pytest
from virea_sentiavatar.continuation import planner_prefix


def test_planner_history_matches_appendix_b_audio_then_motion_order():
    assert planner_prefix(None) == ""
    assert (
        planner_prefix(
            [
                {"audio": 10, "motion": [1, 2, 3, 4]},
                {"audio": 20, "motion": [5, 6, 7, 8]},
            ]
        )
        == "[audio_10][audio_20][res_1_1][res_2_2][res_3_3][res_4_4][res_1_5][res_2_6][res_3_7][res_4_8]"
    )


@pytest.mark.parametrize(
    "history",
    [
        [{"audio": 500, "motion": [0] * 4}],
        [{"audio": True, "motion": [0] * 4}],
        [{"audio": 1, "motion": [512] * 4}],
        [{"audio": 1, "motion": [0] * 4}] * 3,
        [{"audio": 1, "motion": [0] * 4, "text": "unexpected"}],
    ],
)
def test_planner_history_rejects_out_of_vocabulary_or_unbounded_context(history):
    with pytest.raises(Exception):
        planner_prefix(history)
