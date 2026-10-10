"""Estimate the cropped desktop mirror projection from a small camera rotation."""

import numpy as np
from scipy.optimize import least_squares


def fit_mirror_projection(points_before, points_after, size, pitch_degrees):
    before, after = np.asarray(points_before), np.asarray(points_after)
    width, height = size
    if len(before) < 20 or before.shape != after.shape or before.shape[1:] != (2,):
        raise ValueError("画面特征不足，请看向有文字或纹理的位置再对齐")
    if not 4 <= abs(pitch_degrees) <= 12:
        raise ValueError("invalid projection calibration rotation")
    if not np.isfinite(before).all() or not np.isfinite(after).all():
        raise ValueError("invalid projection correspondences")
    if np.ptp(before[:, 0]) < width * 0.2 or np.ptp(before[:, 1]) < height * 0.2:
        raise ValueError("画面特征分布过窄，请调整视角再对齐")
    sine, cosine = np.sin(np.deg2rad(pitch_degrees)), np.cos(np.deg2rad(pitch_degrees))

    def residual(parameters):
        focal, cx, cy = parameters
        x, y = (before[:, 0] - cx) / focal, (before[:, 1] - cy) / focal
        z = cosine - y * sine
        projected = np.column_stack(
            (cx + focal * x / z, cy + focal * (y * cosine + sine) / z)
        )
        return (projected - after).ravel()

    result = least_squares(
        residual,
        [width * 0.65, width / 2, height / 2],
        bounds=(
            [width * 0.19, width * 0.4, height * 0.4],
            [width * 1.5, width * 0.6, height * 0.6],
        ),
        loss="soft_l1",
    )
    error = float(np.sqrt(np.mean(residual(result.x) ** 2)))
    focal, cx, cy = result.x
    fov = float(np.rad2deg(2 * np.arctan(width / (2 * focal))))
    if not result.success or error > 1.5 or not 40 <= fov <= 140:
        raise ValueError("画面在对齐期间发生变化，请站定后重试")
    return dict(
        horizontal_fov=fov,
        view_aspect=width / height,
        projection_center_x=float(cx * 2 / width - 1),
        projection_center_y=float(cy * 2 / height - 1),
        error_pixels=error,
        matched_points=len(before),
        width=width,
        height=height,
    )


def estimate_mirror_projection(before_jpeg, after_jpeg, pitch_degrees):
    import cv2

    before = cv2.imdecode(np.frombuffer(before_jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    after = cv2.imdecode(np.frombuffer(after_jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    if before is None or after is None or before.shape != after.shape:
        raise ValueError("画面尺寸发生变化，请等待稳定后重新对齐")
    detector = cv2.SIFT_create(nfeatures=1200)
    first, a = detector.detectAndCompute(before, None)
    second, b = detector.detectAndCompute(after, None)
    if a is None or b is None or len(b) < 2:
        raise ValueError("画面特征不足，请看向有文字或纹理的位置再对齐")
    matches = [
        pair[0]
        for pair in cv2.BFMatcher().knnMatch(a, b, k=2)
        if len(pair) == 2 and pair[0].distance < 0.65 * pair[1].distance
    ]
    if len(matches) < 20:
        raise ValueError("画面特征不足，请调整视角再对齐")
    p = np.float64([first[m.queryIdx].pt for m in matches])
    q = np.float64([second[m.trainIdx].pt for m in matches])
    _, mask = cv2.findHomography(p, q, cv2.RANSAC, 2)
    if mask is None or mask.sum() < max(20, len(matches) * 0.5):
        raise ValueError("画面变化过大，无法可靠对齐")
    selected = mask.ravel().astype(bool)
    return fit_mirror_projection(
        p[selected], q[selected], before.shape[::-1], pitch_degrees
    )
