import pytest
from virea_sentiavatar.continuation import motion_prefix


def test_native_history_is_bounded_integer_codes():
    assert motion_prefix(None) == []
    assert motion_prefix([[0, 1, 2, 511]]) == [[0, 1, 2, 511]]
    for invalid in (
        [[512] * 4],
        [[-1] * 4],
        [[1.5] * 4],
        [[True] * 4],
        [[0] * 3],
        [[0] * 4] * 9,
    ):
        with pytest.raises(Exception, match="motion_prefix"):
            motion_prefix(invalid)
