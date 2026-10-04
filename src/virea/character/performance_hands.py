"""Reconcile independently decoded body and hand positions with a rigid palm."""

import numpy as np

from virea.motion.skeleton import BODY_BONES, DEFAULT_REST_OFFSETS


def reconcile_palms(body_positions, hands):
    """Fit five MCP anchors, then anchor the fitted palm at the body wrist.

    The body and hand VAEs can disagree about the wrist position. A similarity
    fit uses hand-internal geometry instead of that unreliable cross-part offset.
    Canonical palm proportions are an explicit retarget prior. Observed finger
    segment directions are preserved and constrained by the anatomical solver.
    """
    # API startup does not need SciPy's native libraries; import on actual use.
    from scipy.ndimage import gaussian_filter1d

    result = {name: values.copy() for name, values in hands.items()}
    fingers = ("Index", "Middle", "Ring", "Little", "Thumb")
    for side in ("left", "right"):
        anchors = [f"{side}{finger}Proximal" for finger in fingers]
        reference = np.array([DEFAULT_REST_OFFSETS[name] for name in anchors])
        centered = reference - reference.mean(axis=0)
        observations = gaussian_filter1d(
            np.stack([hands[name] for name in anchors], axis=1),
            1.5,
            axis=0,
            mode="nearest",
        )
        rotations, scales = [], []
        previous, previous_scale = np.eye(3), 1.0
        for points in observations:
            u, singular, vh = np.linalg.svd(centered.T @ (points - points.mean(axis=0)))
            # Collinear anchors cannot determine roll; retain the last observed frame.
            if singular[0] > 1e-9 and singular[1] / singular[0] > 0.015:
                reflection = np.eye(3)
                reflection[-1, -1] = np.linalg.det(u @ vh)
                previous = u @ reflection @ vh
                previous_scale = float(
                    (singular * np.diag(reflection)).sum() / (centered**2).sum()
                )
            rotations.append(previous)
            scales.append(previous_scale)
        rotations, scales = np.asarray(rotations), np.asarray(scales)
        wrist = body_positions[:, BODY_BONES.index(f"{side}Hand")]
        for index, finger in enumerate(fingers):
            target = (
                wrist
                + np.einsum("i,tij->tj", reference[index], rotations) * scales[:, None]
            )
            shift = target - hands[f"{side}{finger}Proximal"]
            for part in ("Proximal", "Intermediate", "Distal"):
                result[f"{side}{finger}{part}"] += shift
    return result
