"""Persist native samples with a source profile independent of the avatar rig."""

import io

import numpy as np
from virea_contracts.motion_ir import SkeletonDescriptor, TimeDescriptor
from virea_contracts.performance import (
    NativeMotionArtifactV1,
    SourceRepresentationProfileV1,
)

from virea.motion.codecs import SMPLX_HAND_INDEX
from virea.motion.skeleton import BODY_BONES, CANONICAL_PARENT


def native_artifact(store, backend, values, health):
    if backend not in {"motioncraft", "syntalker"}:
        raise ValueError("unknown native motion profile")
    observed = backend == "motioncraft"
    width = 322 if observed else 623
    values = np.asarray(values, dtype=np.float32)
    if (
        values.ndim != 2
        or values.shape[1] != width
        or not len(values)
        or not np.isfinite(values).all()
    ):
        raise ValueError("native performance samples do not match their source profile")
    hands = sorted(SMPLX_HAND_INDEX, key=SMPLX_HAND_INDEX.get)
    names = [*BODY_BONES, *hands, *(["jaw"] if observed else [])]
    parents = {**CANONICAL_PARENT, "hips": None, "jaw": "head"}
    indices = tuple(
        -1 if parents[n] is None else names.index(parents[n]) for n in names
    )
    skeleton_id = "motionx.smplx53.v1" if observed else "syntalker.h3d52.v1"
    profile = SourceRepresentationProfileV1(
        profile_id="motionx.smplx322.v1" if observed else "syntalker.h3d623.v1",
        skeleton=SkeletonDescriptor(
            profile_id=skeleton_id, joint_names=tuple(names), parent_indices=indices
        ),
        encoding="parent_local_axis_angle"
        if observed
        else "root_invariant_joint_positions",
        coordinate_system="right_handed_y_up",
        root_semantics="absolute_translation"
        if observed
        else "integrated_root_velocity",
        observed_dofs=("root_translation", "joint_rotations")
        if observed
        else ("joint_positions",),
        imputed_dofs=() if observed else ("axial_twist", "terminal_finger_rotation"),
    )
    output = io.BytesIO()
    np.savez_compressed(output, values=values)
    reference, digest = store.put(
        output.getvalue(), media_type="application/x-npz", name="native-motion"
    )
    return NativeMotionArtifactV1(
        artifact=reference,
        sha256=digest,
        model_id=backend,
        model_revision=health.get("source_revision"),
        checkpoint_digest=health.get("checkpoint_sha256"),
        source=profile,
        time=TimeDescriptor(frame_count=len(values), fps=30),
    )


def read_native(store, native):
    profile = {
        "motioncraft": ("motionx.smplx322.v1", 322),
        "syntalker": ("syntalker.h3d623.v1", 623),
    }.get(native.model_id)
    if profile is None or native.source.profile_id != profile[0]:
        raise ValueError("native artifact source profile and model differ")
    with np.load(
        io.BytesIO(store.read(native.artifact, native.sha256)), allow_pickle=False
    ) as data:
        values = data["values"]
    if (
        values.shape != (native.time.frame_count, profile[1])
        or native.time.fps != 30
        or not np.isfinite(values).all()
    ):
        raise ValueError("native artifact samples and time descriptor differ")
    return values
