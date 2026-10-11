"""Calibrate the game's rendered pointer, independently of the mirror camera."""

from itertools import combinations

import numpy as np
from scipy.spatial.transform import Rotation

from virea.motion.rotation import (
    quat_apply_xyzw,
    quat_from_two_vectors_xyzw,
    quat_multiply_xyzw,
)

# Diverse controller positions make camera offset distinguishable from tip offset.
# The 40 degree search seed only brings the VIREA hand's ray into the image;
# the fitted direction below, not this seed, drives subsequent pointing.
SAMPLES = (
    (0.15, -0.12, -0.5, -20, 15),
    (0.3, -0.15, -0.45, -10, 8),
    (0.25, -0.1, -0.6, -15, -5),
    (-0.25, -0.12, -0.5, 20, 15),
    (-0.3, -0.05, -0.45, 10, -8),
    (-0.2, -0.15, -0.6, 15, 5),
    (0.3, 0.15, -0.5, -20, -10),
    (-0.3, 0.15, -0.5, 20, -10),
    (0.2, 0.1, -0.6, -10, 0),
)


def detect_ray_line(baseline_jpeg, sample_jpeg):
    """Return the actual cyan beam's image line, never a browser overlay."""
    import cv2

    baseline = cv2.imdecode(np.frombuffer(baseline_jpeg, np.uint8), cv2.IMREAD_COLOR)
    sample = cv2.imdecode(np.frombuffer(sample_jpeg, np.uint8), cv2.IMREAD_COLOR)
    if baseline is None or sample is None or baseline.shape != sample.shape:
        raise ValueError("射线校准期间画面尺寸发生变化")
    blue, green, red = cv2.split(sample.astype(float))
    change = np.max(cv2.absdiff(sample, baseline), axis=2)
    # In-world beams are pale and only 1–2 mirror pixels wide. JPEG and
    # antialiasing mix them with the menu background; login-screen neon-only
    # thresholds discard every ray. Keep cyan chroma, temporal change and
    # geometric consensus rather than requiring near-zero red.
    mask = (
        (blue > 140)
        & (green > 140)
        & (red < 220)
        & (green - red > 35)
        & (blue - red > 35)
        & (change > 40)
    ).astype(np.uint8) * 255
    segments = cv2.HoughLinesP(mask, 1, np.pi / 720, 30, minLineLength=50, maxLineGap=8)
    candidates = []
    for x1, y1, x2, y2 in [] if segments is None else segments.reshape(-1, 4):
        length = np.hypot(float(x2 - x1), float(y2 - y1))
        # Axis-aligned UI borders are not evidence of a controller ray.
        if min(abs(x2 - x1), abs(y2 - y1)) < 0.15 * length:
            continue
        candidates.append((length, (x1, y1, x2, y2)))
    if not candidates:
        return None
    _, (x1, y1, x2, y2) = max(candidates)
    line = np.cross([x1, y1, 1.0], [x2, y2, 1.0])
    line /= np.linalg.norm(line[:2])
    ys, xs = np.where(mask > 0)
    near = abs(line[0] * xs + line[1] * ys + line[2]) < 4
    points = np.column_stack((xs[near], ys[near])).astype(np.float32)
    vx, vy, x, y = cv2.fitLine(points, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    return np.array([-vy, vx, vy * x - vx * y])


def fit_ray_alignment(samples, projection):
    """Fit a controller-local ray and mirror-eye offset from projected lines.

    Each observed line back-projects to a plane containing the real ray. The
    direction must lie in every such plane. The origins then solve a separate
    linear system; the unobservable translation along the ray is fixed to zero.
    """
    width, height = projection["width"], projection["height"]
    focal = width / (2 * np.tan(np.deg2rad(projection["horizontal_fov"]) / 2))
    camera = np.array(
        [
            [focal, 0, -(1 + projection["projection_center_x"]) * width / 2],
            [0, -focal, -(1 + projection["projection_center_y"]) * height / 2],
            [0, 0, -1],
        ]
    )
    direction_rows, origin_rows, origin_targets = [], [], []
    for head, controller, line in samples:
        normal = camera.T @ np.asarray(line)
        normal /= np.linalg.norm(normal)
        head_rotation = Rotation.from_quat(head[3:]).as_matrix()
        relative = head_rotation.T @ Rotation.from_quat(controller[3:]).as_matrix()
        direction_rows.append(normal @ relative)
        origin_rows.append(np.r_[normal @ relative, -normal])
        origin_targets.append(-normal @ head_rotation.T @ (controller[:3] - head[:3]))
    if len(direction_rows) < 6 or not np.isfinite(direction_rows).all():
        raise ValueError("未识别到足够的游戏射线，请看向 VRChat 菜单再对齐")
    direction_rows, origin_rows, origin_targets = map(
        np.asarray, (direction_rows, origin_rows, origin_targets)
    )
    # Animated menu banners can contribute a cyan edge to one sample. Keep a
    # strict six-view geometric consensus instead of fitting that edge as a
    # ray, or weakening the direction/origin residual limits.
    minimum = max(6, int(np.ceil(len(samples) * 2 / 3)))
    chosen = None
    for count in range(len(samples), minimum - 1, -1):
        candidates = []
        for subset in combinations(range(len(samples)), count):
            indices = list(subset)
            _, singular, vectors = np.linalg.svd(direction_rows[indices])
            direction = vectors[-1] * (-1 if vectors[-1, 2] > 0 else 1)
            direction_error = float(singular[-1] / np.sqrt(count))
            if singular[1] < 0.1 or direction_error > 0.02:
                continue
            rows = np.vstack((origin_rows[indices], np.r_[direction, 0.0, 0.0, 0.0]))
            targets = np.r_[origin_targets[indices], 0.0]
            offsets, _, rank, values = np.linalg.lstsq(rows, targets, rcond=None)
            error = float(np.sqrt(np.mean((rows @ offsets - targets) ** 2)))
            if (
                rank < 6
                or values[-1] < 0.005
                or error > 0.004
                or np.max(abs(offsets)) > 0.25
            ):
                continue
            candidates.append(
                (direction_error + error, direction, offsets, error, direction_error)
            )
        if candidates:
            chosen = min(candidates, key=lambda item: item[0])
            break
    if chosen is None:
        raise ValueError("游戏射线方向或起点不一致，无法可靠校准，请保持菜单静止后重试")
    _, direction, offsets, error, direction_error = chosen
    return dict(
        direction=direction.tolist(),
        tip_offset=offsets[:3].tolist(),
        eye_offset=offsets[3:].tolist(),
        samples=count,
        rejected_samples=len(samples) - count,
        origin_error_m=error,
        direction_error=direction_error,
    )


def apply_ray_alignment(devices, alignment):
    """Put the actual game ray on the requested eye ray at any target depth."""
    aim = devices[2, 3:].copy()
    forward = np.array([0.0, 0.0, -1.0])
    direction = quat_apply_xyzw(aim, forward)
    correction = quat_from_two_vectors_xyzw(np.asarray(alignment["direction"]), forward)
    devices[2, 3:] = quat_multiply_xyzw(aim, correction)
    eye = devices[0, :3] + quat_apply_xyzw(
        devices[0, 3:], np.asarray(alignment["eye_offset"])
    )
    devices[2, :3] = (
        eye
        + 0.3 * direction
        - quat_apply_xyzw(devices[2, 3:], np.asarray(alignment["tip_offset"]))
    )
