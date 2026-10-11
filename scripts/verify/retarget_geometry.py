"""Compare one native MotionCraft sample with an explicitly supplied source rig.

python -m scripts.verify.retarget_geometry --native native.npz --source-rig model.npz --output report.json
Model assets stay local. This command performs no generation or device playback.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation
from virea_compat.model_adapters import smplx_fullpose_to_motion_ir
from virea_retarget import retarget_motion_ir

from virea.motion.canonical import unpack_sequence
from virea.motion.codecs import SMPLX_HAND_INDEX
from virea.motion.rotation_filter import gaussian_rotation_mean
from virea.motion.skeleton import BODY_BONES, FK_BONES, canonical_geometry
from virea.motion.source_rig import load_smplx_rig


def compare(native_path, source_rig_path):
    native_path = Path(native_path)
    digest = hashlib.sha256(native_path.read_bytes()).hexdigest()
    with np.load(native_path, allow_pickle=False) as archive:
        values = archive["values"]
    if (
        values.ndim != 2
        or values.shape[1] != 322
        or len(values) < 2
        or not np.isfinite(values).all()
    ):
        raise ValueError(
            "comparison requires at least two finite MotionCraft 322D frames"
        )
    pose = np.concatenate(
        (
            values[:, :66],
            values[:, 156:159],
            np.zeros((len(values), 6)),
            values[:, 66:156],
        ),
        axis=1,
    )
    source = load_smplx_rig(source_rig_path)
    source_rig, target = canonical_geometry(source.offsets), canonical_geometry()
    indices = {**{n: i for i, n in enumerate(BODY_BONES)}, **SMPLX_HAND_INDEX}
    q = (
        Rotation.from_rotvec(pose.reshape(-1, 3))
        .as_quat()
        .reshape(len(values), 55, 4)[:, [indices[n] for n in FK_BONES]]
    )
    root = np.zeros((len(values), 3))
    old_p, _ = target.forward(root, q)
    source_p, _ = source_rig.forward(root, q)
    motion = smplx_fullpose_to_motion_ir(
        pose,
        values[:, 309:312],
        fps=30,
        source_rest_offsets=source.offsets,
        source_geometry_sha256=source.sha256,
    ).motion_ir
    canonical = unpack_sequence(retarget_motion_ir(motion).actors[0].canonical211)
    new_q = np.concatenate(
        (
            canonical["root_rotation_xyzw"][:, None],
            canonical["core_quats_xyzw"],
            canonical["hand_quats_xyzw"],
        ),
        axis=1,
    )
    new_p, _ = target.forward(root, new_q)
    filtered = gaussian_rotation_mean(new_q, 3.5)

    def steps(rotations):
        a = Rotation.from_quat(rotations[:-1].reshape(-1, 4))
        b = Rotation.from_quat(rotations[1:].reshape(-1, 4))
        return np.rad2deg((a.inv() * b).magnitude()).reshape(len(rotations) - 1, -1)

    def errors(positions):
        parents = np.array(target.parents[1:])
        a = source_p[:, 1:] - source_p[:, parents]
        b = positions[:, 1:] - positions[:, parents]
        dot = (
            np.sum(a * b, axis=-1)
            / np.linalg.norm(a, axis=-1)
            / np.linalg.norm(b, axis=-1)
        )
        return np.rad2deg(np.arccos(np.clip(dot, -1, 1)))

    single = [
        i - 1
        for i, p in enumerate(target.parents)
        if p >= 0 and sum(x == p for x in target.parents) == 1
    ]
    body = [FK_BONES.index(n) for n in BODY_BONES]
    return {
        "native_sha256": digest,
        "source_geometry_sha256": source.sha256,
        "frames": len(values),
        "sample_regenerated": False,
        "hand_mean_applied": False,
        "source_rig_direction_error_degrees": {
            "before_mean": float(errors(old_p).mean()),
            "after_mean": float(errors(new_p).mean()),
            "single_child_before_max": float(errors(old_p)[:, single].max()),
            "single_child_after_max": float(errors(new_p)[:, single].max()),
        },
        "body_max_interframe_degrees": {
            name: float(steps(rotations)[:, body].max())
            for name, rotations in (
                ("native", q),
                ("rebound", new_q),
                ("conditioned", filtered),
            )
        },
        "body_rotation_filter_change_degrees": float(
            np.rad2deg(
                (
                    Rotation.from_quat(new_q[:, body].reshape(-1, 4)).inv()
                    * Rotation.from_quat(filtered[:, body].reshape(-1, 4))
                ).magnitude()
            ).max()
        ),
        "native_unchanged": hashlib.sha256(native_path.read_bytes()).hexdigest()
        == digest,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--source-rig", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = compare(args.native, args.source_rig)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
