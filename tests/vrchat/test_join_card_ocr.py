import pytest

from virea.vrchat.menu_vision import Label, LabelNotFound, join_label

ROOM = "wrld_11111111-1111-1111-1111-111111111111:00659~private(usr_a)"
BUTTON = Label("加入", 427, 243.5, 22, 13.5)


@pytest.mark.parametrize("prefix", ["#", "＃", "$", "办", ""])
def test_real_chinese_card_keeps_exact_digits_despite_hash_glyph_ocr(prefix):
    labels = [
        Label(prefix + "00659", 370, 172, 57.5, 14.5),
        BUTTON,
        Label("$00659", 664, 206, 35.5, 11),
    ]
    assert join_label(labels, ROOM) == BUTTON


@pytest.mark.parametrize("number", ["#00658", "#659", "#OO659", "房间00659", "#006590"])
def test_sidebar_target_cannot_authorize_wrong_selected_card(number):
    labels = [
        Label(number, 370, 172, 57.5, 14.5),
        BUTTON,
        Label("#00659", 664, 206, 35.5, 11),
    ]
    with pytest.raises(LabelNotFound):
        join_label(labels, ROOM)


def test_target_below_join_or_in_unrelated_distant_text_is_not_accepted():
    for heading in [
        Label("#00659", 370, 270, 57.5, 14.5),
        Label("#00659", 20, 40, 57.5, 14.5),
    ]:
        with pytest.raises(LabelNotFound):
            join_label([heading, BUTTON], ROOM)
