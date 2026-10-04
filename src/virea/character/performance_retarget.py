"""Native MotionCraft / SynTalker output to the existing VRM normalized pose."""

import numpy as np

from virea.motion.canonical import (
    CANONICAL_TO_VRM_BONE_NAME,
    CORE_BONES,
    HAND_BONES,
    pack_sequence,
    unpack_sequence,
)
from virea.motion.rotation import quat_apply_xyzw, quat_multiply_xyzw

from .performance_contracts import FPS
from .performance_hands import reconcile_palms


def smooth_native_pose(root, rotations):
    """Suppress sub-100 ms native jitter without changing the timeline length.

    Offline centered filtering is possible because a full performance is prepared.
    Quaternion hemisphere alignment prevents sign-equivalent samples cancelling.
    This is deterministic retarget postprocessing, not a second motion generator.
    """
    from scipy.ndimage import gaussian_filter1d, median_filter

    root = gaussian_filter1d(
        median_filter(root, size=(3, 1), mode="nearest"), 1.5, axis=0, mode="nearest"
    )
    root -= root[:1]
    result = {}
    for name, values in rotations.items():
        q = np.asarray(values, dtype=np.float32).copy()
        signs = np.ones(len(q), dtype=np.float32)
        signs[1:] = np.where(np.sum(q[1:] * q[:-1], axis=1) < 0, -1, 1)
        q *= np.cumprod(signs)[:, None]
        q = gaussian_filter1d(q, 1.5, axis=0, mode="nearest")
        length = np.linalg.norm(q, axis=1, keepdims=True)
        if np.any(length < 1e-6):
            raise ValueError(
                "native rotation smoothing produced a degenerate quaternion"
            )
        q /= length
        # Position-derived palm frames can flip when predicted knuckles nearly
        # cross. Bound only wrists/fingers; fast shoulder and leg actions retain
        # their generated motion. Bidirectional passes avoid a persistent lag.
        hand = name in {"leftHand", "rightHand"} or any(
            finger in name for finger in ("Thumb", "Index", "Middle", "Ring", "Little")
        )
        if hand:
            limit = np.deg2rad(450 if name.endswith("Hand") else 720) / FPS
            for indices in (range(1, len(q)), range(len(q) - 2, -1, -1)):
                step = 1 if indices.step == 1 else -1
                for i in indices:
                    previous = q[i - step]
                    dot = float(np.dot(previous, q[i]))
                    target = q[i] if dot >= 0 else -q[i]
                    theta = np.arccos(np.clip(abs(dot), 0, 1))
                    if 2 * theta > limit:
                        ratio = limit / (2 * theta)
                        q[i] = (
                            np.sin((1 - ratio) * theta) * previous
                            + np.sin(ratio * theta) * target
                        ) / np.sin(theta)
        result[name] = q
    return root, result


def recover_h3d623(values):
    """NumPy equivalent of SynTalker's official recover_from_ric(data, 52)."""
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != 623 or not np.isfinite(values).all():
        raise ValueError("SynTalker requires finite denormalized (T,623) features")
    angle = np.cumsum(np.r_[0, values[:-1, 0]])
    inverse = np.zeros((len(values), 4), dtype=np.float32)
    inverse[:, 1], inverse[:, 3] = -np.sin(angle), np.cos(angle)
    velocity = np.zeros((len(values), 3), dtype=np.float32)
    velocity[1:, 0], velocity[1:, 2] = values[:-1, 1], values[:-1, 2]
    root = np.cumsum(quat_apply_xyzw(inverse, velocity), axis=0)
    root[:, 1] = values[:, 3]
    joints = values[:, 4:157].reshape(-1, 51, 3).copy()
    joints = quat_apply_xyzw(
        np.broadcast_to(inverse[:, None], (len(values), 51, 4)), joints
    )
    joints[:, :, 0] += root[:, None, 0]
    joints[:, :, 2] += root[:, None, 2]
    return np.concatenate((root[:, None], joints), axis=1)


def canonical_motion(backend, values):
    if backend == "motioncraft":
        from virea_compat.model_adapters import smplx_fullpose_to_motion_ir

        poses = np.concatenate(
            (
                values[:, :66],
                values[:, 156:159],
                np.zeros((len(values), 6)),
                values[:, 66:156],
            ),
            axis=1,
        )
        return smplx_fullpose_to_motion_ir(
            poses, values[:, 309:312], fps=FPS
        ).canonical211
    if backend != "syntalker":
        raise ValueError("unknown performance backend")
    from virea.motion.hand_solver import HandObservationMetadata, solve_hand_constraints
    from virea.motion.retarget import fit_positions_to_vrm
    from virea.motion.skeleton import BODY_BONES

    positions = recover_h3d623(values)
    hands = {}
    for side_index, side in enumerate(("left", "right")):
        for finger_index, finger in enumerate(
            ("Index", "Middle", "Little", "Ring", "Thumb")
        ):
            for part, joint in enumerate(("Proximal", "Intermediate", "Distal")):
                hands[f"{side}{finger}{joint}"] = positions[
                    :, 22 + side_index * 15 + finger_index * 3 + part
                ]
    hands = reconcile_palms(positions[:, :22], hands)
    fitted = fit_positions_to_vrm(
        positions[:, :22], world_basis="identity_y_up", hand_positions_by_name=hands
    )["sequence"]
    sequence = unpack_sequence(fitted)
    evidence = {name: positions[:, index] for index, name in enumerate(BODY_BONES)}
    evidence.update(hands)
    constrained = solve_hand_constraints(
        sequence["hand_quats_xyzw"],
        continuity_segments=[(0, len(values))],
        observation=HandObservationMetadata.position_directions(
            source="SynTalker H3D623 RIC", fps=FPS, unobservable_policy="neutral"
        ),
        position_evidence=evidence,
    )
    # RIC joint positions cannot observe axial twist or terminal finger rotation.
    # Apply the existing anatomy/observability policy instead of inventing those DoFs.
    return pack_sequence(
        sequence["root_translation"],
        sequence["root_rotation_xyzw"],
        sequence["core_quats_xyzw"],
        constrained.quats_xyzw,
    )


def playback_windows(backend, values, plan, body):
    unpacked = unpack_sequence(canonical_motion(backend, values))
    root = unpacked["root_translation"].copy()
    # Keep the model's vertical displacement and travel, anchored once per performance.
    root -= root[:1]
    yaw = np.array([0, np.sin(body.yaw / 2), 0, np.cos(body.yaw / 2)], dtype=np.float32)
    root = quat_apply_xyzw(np.broadcast_to(yaw, (len(root), 4)), root)
    rotations = {
        "hips": quat_multiply_xyzw(
            np.broadcast_to(yaw, (len(root), 4)), unpacked["root_rotation_xyzw"]
        )
    }
    for names, key in (
        (CORE_BONES, "core_quats_xyzw"),
        (HAND_BONES, "hand_quats_xyzw"),
    ):
        for index, name in enumerate(names):
            rotations[CANONICAL_TO_VRM_BONE_NAME.get(name, name)] = unpacked[key][
                :, index
            ]
    root, rotations = smooth_native_pose(root, rotations)
    root += np.array(
        [body.position.x, body.position.y + (body.pelvis_height or 1), body.position.z]
    )
    # Include an endpoint sample; duration N/fps does not stretch N-1 intervals.
    root = np.concatenate((root, root[-1:]))
    rotations = {name: np.concatenate((q, q[-1:])) for name, q in rotations.items()}
    boundaries = {0, len(values)}
    for segment in plan.motions:
        boundaries.update(
            (
                min(len(values), round(segment.start_seconds * FPS)),
                min(
                    len(values),
                    round((segment.start_seconds + segment.duration_seconds) * FPS),
                ),
            )
        )
    points = sorted(boundaries)
    windows = []
    for start, end in zip(points, points[1:]):
        if end <= start:
            continue
        segment = next(
            (
                s
                for s in plan.motions
                if s.start_seconds
                <= (start + 0.5) / FPS
                < s.start_seconds + s.duration_seconds
            ),
            None,
        )
        windows.append(
            dict(
                sequence=len(windows),
                offset=start / FPS,
                seconds=(end - start) / FPS,
                fps=FPS,
                grounding="prevent_penetration",
                root=root[start : end + 1].tolist(),
                rotations={
                    name: q[start : end + 1].tolist() for name, q in rotations.items()
                },
                total_seconds=len(values) / FPS,
                hip_height=body.pelvis_height or 1,
                generation_seconds=0,
                continues=end < len(values),
                phase_kind="perform",
                phase_label=segment.label or segment.prompt if segment else "自然保持",
                phase_index=plan.motions.index(segment) if segment else -1,
                prompt=segment.prompt if segment else plan.idle_prompt,
            )
        )
    return windows
