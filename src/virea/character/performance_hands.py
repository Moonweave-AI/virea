"""Reconcile independently decoded body and hand positions with a rigid palm."""

import numpy as np

from virea.motion.skeleton import BODY_BONES, DEFAULT_REST_OFFSETS


def continuous_forearm_frames(core, root_rotation):
    """Parallel-transport unobserved forearm roll in position-only decoding.

    A fresh shortest-arc fit from the rest pose on every frame can spin about
    the elbow-to-wrist axis near its antipode. Positions cannot observe that
    roll. Transport the previous frame instead, preserving every body joint
    position AND the observed world palm orientation. Never use this for a
    source such as SMPL-X that actually supplies forearm rotation.
    """
    from scipy.spatial.transform import Rotation

    from virea.motion.canonical import CORE_BONES, CORE_INDEX
    from virea.motion.skeleton import CANONICAL_PARENT

    result = np.asarray(core).copy()
    world = {"hips": Rotation.from_quat(root_rotation)}
    for name in CORE_BONES:
        world[name] = world[CANONICAL_PARENT[name]] * Rotation.from_quat(
            core[:, CORE_INDEX[name]]
        )
    for side in ("left", "right"):
        arm, wrist = f"{side}LowerArm", f"{side}Hand"
        previous = world[arm][0]
        axis = np.array([1.0, 0.0, 0.0])
        directions = world[arm].apply(axis)
        frames = [previous.as_quat()]
        for before, after in zip(directions[:-1], directions[1:], strict=True):
            arc = np.r_[
                np.cross(before, after), 1 + np.clip(np.dot(before, after), -1, 1)
            ]
            if np.linalg.norm(arc) < 1e-7:
                delta = Rotation.from_rotvec(previous.apply([0.0, 1.0, 0.0]) * np.pi)
            else:
                delta = Rotation.from_quat(arc)
            previous = delta * previous
            frames.append(previous.as_quat())
        transported = Rotation.from_quat(frames)
        result[:, CORE_INDEX[arm]] = (
            world[CANONICAL_PARENT[arm]].inv() * transported
        ).as_quat()
        result[:, CORE_INDEX[wrist]] = (transported.inv() * world[wrist]).as_quat()
    return result


def stabilize_wrist(quaternions, fps):
    """Repair invalid wrist inference without converting it to a slow full spin.

    Bounds (degrees) are a conservative retarget policy in canonical local
    axes: axial roll, deviation, flexion. They are not measured source DoFs.
    Interpolate invalid components between valid generated observations in
    this bounded chart, rather than SLERPing through the +/-180-degree pole.
    A final coupled slew bound limits angular travel to 180 degrees/second.
    Valid slow articulation is unchanged; all-invalid evidence fails closed.
    """
    from scipy.spatial.transform import Rotation

    q = Rotation.from_quat(quaternions).as_quat()
    twist = q * np.array([1.0, 0.0, 0.0, 1.0])
    norm = np.linalg.norm(twist, axis=1)
    degenerate = norm < 1e-7
    twist[degenerate] = [0, 0, 0, 1]
    twist /= np.linalg.norm(twist, axis=1, keepdims=True)
    twist *= np.where(twist[:, 3:4] < 0, -1, 1)
    swing = (Rotation.from_quat(q) * Rotation.from_quat(twist).inv()).as_rotvec()
    angles = np.column_stack((2 * np.arctan2(twist[:, 0], twist[:, 3]), swing[:, 1:]))
    timeline = np.arange(len(q))
    for axis, bound in enumerate(np.deg2rad([100.0, 40.0, 85.0])):
        valid = (np.abs(angles[:, axis]) <= bound) & ~degenerate
        if not np.any(valid):
            raise ValueError(
                "generated wrist has no valid orientation evidence; regenerate the motion"
            )
        angles[:, axis] = np.interp(timeline, timeline[valid], angles[valid, axis])
    limit = np.deg2rad(180.0) / fps
    # Each step stays inside the convex anatomical chart. The final forward
    # pass establishes the bound even after smoothing in the reverse direction.
    for indices in (range(1, len(q)), range(len(q) - 2, -1, -1), range(1, len(q))):
        step = 1 if indices.step == 1 else -1
        for i in indices:
            delta = angles[i] - angles[i - step]
            travel = abs(delta[0]) + np.linalg.norm(delta[1:])
            if travel > limit:
                angles[i] = angles[i - step] + delta * (limit / travel)
    swing = np.column_stack((np.zeros(len(q)), angles[:, 1:]))
    twist = np.column_stack((angles[:, 0], np.zeros((len(q), 2))))
    return (Rotation.from_rotvec(swing) * Rotation.from_rotvec(twist)).as_quat()


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
