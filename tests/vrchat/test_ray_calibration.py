import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from virea.vrchat.manual import ManualState, manual_payload
from virea.vrchat.ray_calibration import (
    SAMPLES,
    apply_ray_alignment,
    detect_ray_line,
    fit_ray_alignment,
)


def calibrated_scene():
    projection = dict(
        width=960,
        height=540,
        horizontal_fov=70,
        projection_center_x=0.003,
        projection_center_y=0.002,
    )
    head_rotation = Rotation.from_euler("yx", [12, -31], degrees=True)
    head = np.r_[[0.1, 1.65, -0.03], head_rotation.as_quat()]
    direction = Rotation.from_euler("x", -37, degrees=True).apply([0, 0, -1.0])
    tip = np.array([-0.02, -0.04, 0.03])
    tip -= direction * np.dot(tip, direction)
    eye = np.array([-0.03, 0.004, 0.015])
    focal = 480 / np.tan(np.deg2rad(35))
    center = np.array([481.44, 270.54])
    observations = []
    for x, y, z, yaw, pitch in SAMPLES:
        r = head_rotation * Rotation.from_euler("yx", [yaw, pitch + 40], degrees=True)
        p = head[:3] + head_rotation.apply([x, y, z])
        world = np.array(
            [p + r.apply(tip + distance * direction) for distance in [0.1, 2]]
        )
        camera = head_rotation.inv().apply(world - head[:3]) - eye
        pixels = center + focal * camera[:, :2] * [1, -1] / -camera[:, 2:]
        line = np.cross(np.r_[pixels[0], 1], np.r_[pixels[1], 1])
        observations.append((head, np.r_[p, r.as_quat()], line))
    return observations, projection, direction, tip, eye


def test_real_ray_transform_is_separate_from_camera_projection():
    observations, projection, direction, tip, eye = calibrated_scene()
    result = fit_ray_alignment(observations, projection)
    np.testing.assert_allclose(result["direction"], direction, atol=1e-8)
    np.testing.assert_allclose(result["tip_offset"], tip, atol=1e-7)
    np.testing.assert_allclose(result["eye_offset"], eye, atol=1e-7)
    assert result["origin_error_m"] < 1e-9
    for yaw, pitch in [(0, -39), (50, 20)]:
        state = ManualState(
            head_yaw=yaw,
            head_pitch=pitch,
            pointer_x=-0.65,
            pointer_y=-0.8,
            horizontal_fov=70,
        )
        _, devices, _ = manual_payload(state, 1)
        head = devices[0].copy()
        apply_ray_alignment(devices, result)
        np.testing.assert_array_equal(head, devices[0])
        h = Rotation.from_quat(head[3:])
        r = Rotation.from_quat(devices[2, 3:])
        for distance in [0.3, 1, 5]:
            world = devices[2, :3] + r.apply(tip + distance * direction)
            camera = h.inv().apply(world - head[:3]) - eye
            xy = (
                camera[:2]
                * [1, -state.view_aspect]
                / (-camera[2] * np.tan(np.deg2rad(35)))
            )
            np.testing.assert_allclose(
                xy, [state.pointer_x, state.pointer_y], atol=2e-6
            )


def test_insufficient_and_degenerate_ray_samples_are_rejected():
    observations, projection, *_ = calibrated_scene()
    with pytest.raises(ValueError, match="足够"):
        fit_ray_alignment(observations[:3], projection)
    with pytest.raises(ValueError, match="方向"):
        fit_ray_alignment([observations[0]] * 9, projection)


def test_animated_menu_outlier_does_not_change_the_recovered_controller_ray():
    observations, projection, direction, tip, eye = calibrated_scene()
    head, controller, _ = observations[3]
    observations[3] = head, controller, np.array([0.3, 0.7, -200.0])
    result = fit_ray_alignment(observations, projection)
    assert result["rejected_samples"] == 1
    np.testing.assert_allclose(result["direction"], direction, atol=1e-7)
    np.testing.assert_allclose(result["tip_offset"], tip, atol=1e-7)
    np.testing.assert_allclose(result["eye_offset"], eye, atol=1e-7)


@pytest.mark.parametrize("color", [(240, 240, 155), (210, 215, 155)])
def test_antialiased_in_world_beam_survives_mirror_jpeg(color):
    import cv2

    before = np.full((540, 960, 3), (60, 50, 40), np.uint8)
    after = before.copy()
    cv2.line(after, (180, 420), (750, 120), color, 2, cv2.LINE_AA)

    def encode(image):
        return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()

    line = detect_ray_line(encode(before), encode(after))
    assert line is not None
    assert abs(line @ [180, 420, 1]) < 2
    assert abs(line @ [750, 120, 1]) < 2
    # A moving, bright avatar hand is not cyan and cannot authorize a click.
    after[:] = before
    cv2.line(after, (180, 420), (750, 120), (225, 240, 255), 20, cv2.LINE_AA)
    assert detect_ray_line(encode(before), encode(after)) is None


def test_game_ui_borders_are_not_a_pointer_but_diagonal_beam_is_detected():
    import cv2

    baseline = np.zeros((540, 960, 3), np.uint8)
    cv2.rectangle(baseline, (80, 80), (880, 430), (240, 240, 0), 4)
    sample = baseline.copy()
    cv2.line(sample, (200, 150), (730, 470), (255, 255, 0), 4)

    def encode(image):
        return cv2.imencode(".jpg", image)[1].tobytes()

    before = encode(baseline)
    assert detect_ray_line(before, before) is None
    line = detect_ray_line(before, encode(sample))
    for point in [[200, 150, 1], [730, 470, 1]]:
        assert abs(line @ point) < 2
