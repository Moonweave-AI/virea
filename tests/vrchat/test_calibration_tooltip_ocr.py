from virea.vrchat.menu_vision import Label, calibration_hovered


def test_observed_small_oblique_fbt_tooltip_confusion_is_specific():
    button = Label("校准", 530, 300, 40, 16)
    assert calibration_hovered([Label("校减全身追踪", 270, 474, 100, 40)], button)
    for text in (
        "校减",
        "全身追踪",
        "切换为坐姿游玩方法",
        "开始全身追踪",
        "登录",
        "校减其它追踪",
    ):
        assert not calibration_hovered([Label(text, 270, 474, 100, 40)], button)
