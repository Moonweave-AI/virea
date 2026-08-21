from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np

from virea.data.types import RawClip
from virea.motion.canonical import (
    CANONICAL_ROTATION_SEMANTICS,
    CANONICAL_SKELETON_ID,
    CORE_INDEX,
    HAND_BONES,
    HAND_INDEX,
    identity_quats,
    pack_sequence,
)
from virea.motion.hand_solver import HandObservationMetadata
from virea.motion.retarget import (
    body_positions_from_fk_positions,
    fit_positions_to_vrm,
    retarget_named_quats_to_vrm,
    target_scale_from_rest_offsets,
)
from virea.motion.rotation import (
    axis_angle_to_quat_xyzw,
    normalize_quat_xyzw,
    quat_apply_xyzw,
    quat_inverse_xyzw,
    quat_multiply_xyzw,
    sixd_rows_to_quat_xyzw,
    sixd_to_quat_xyzw,
)
from virea.motion.skeleton import (
    BODY_BONES,
    BODY_EDGES,
    BODY_INDEX,
    CANONICAL_BODY_WITH_ROOT,
    CANONICAL_PARENT,
    DEFAULT_REST_OFFSETS,
    FK_BONES,
    FK_EDGES,
)
from virea.motion.snapshot import SourceSnapshot
from virea.motion.source_fk import (
    center_positions_at_root,
    source_fk_from_body_quats,
    source_positions_normalized,
)


@dataclass
class CanonicalResult:
    sequence: np.ndarray
    positions: np.ndarray
    joint_names: list[str]
    edges: list[tuple[int, int]]
    metadata: dict[str, Any]
    retarget_source_positions: np.ndarray | None = None
    retarget_source_joint_names: list[str] | None = None
    hand_observation: HandObservationMetadata | None = None
    hand_position_evidence: dict[str, np.ndarray] | None = None
    pre_solver_hand_quaternions: np.ndarray | None = None


class MotionCodec:
    key = "base"

    def extract_source(self, clip: RawClip) -> SourceSnapshot:
        raise NotImplementedError

    def to_canonical(self, clip: RawClip) -> CanonicalResult:
        raise NotImplementedError


class AxisAngleBody22Codec(MotionCodec):
    key = "axis_angle_body22"

    def __init__(
        self,
        source_rest_offsets: dict[str, list[float]] | None = None,
        source_profile: str = "smplh_body22",
        world_basis: str = "z_up_to_y_up",
        root_rotation_semantics: str = "local_to_world",
    ) -> None:
        self.source_rest_offsets = source_rest_offsets or DEFAULT_REST_OFFSETS
        self.source_profile = source_profile
        self.world_basis = world_basis
        self.root_rotation_semantics = root_rotation_semantics

    def _body_quats(self, poses: np.ndarray) -> np.ndarray:
        arr = np.asarray(poses, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] < 22 * 3:
            raise ValueError(
                f"expected body axis-angle block with at least 66 dims, got {arr.shape}"
            )
        return axis_angle_to_quat_xyzw(arr[:, : 22 * 3].reshape(arr.shape[0], 22, 3))

    def _pack(self, body_quats: np.ndarray, translation: np.ndarray) -> np.ndarray:
        frame_count = body_quats.shape[0]
        core = identity_quats(frame_count, len(CORE_INDEX))
        for body_index, bone_name in enumerate(CANONICAL_BODY_WITH_ROOT):
            if bone_name == "hips" or bone_name not in CORE_INDEX:
                continue
            core[:, CORE_INDEX[bone_name]] = body_quats[:, body_index]
        return pack_sequence(
            root_translation=translation,
            root_rotation_xyzw=body_quats[:, BODY_INDEX["hips"]],
            core_quats_xyzw=core,
        )

    def _rest_contract(
        self,
        clip: RawClip,
    ) -> tuple[dict[str, list[float] | np.ndarray], dict[str, np.ndarray] | None, str]:
        payload = clip.motion.get("source_rest_offsets")
        if payload is None:
            return self.source_rest_offsets, {}, "identity_canonical_parameter_frames"
        if not isinstance(payload, dict):
            raise ValueError("source_rest_offsets must be a bone-name mapping")
        offsets: dict[str, list[float] | np.ndarray] = {}
        for name, value in payload.items():
            offset = np.asarray(value, dtype=np.float32)
            if offset.shape != (3,) or not np.all(np.isfinite(offset)):
                raise ValueError(f"source rest offset {name} must be a finite vec3")
            offsets[str(name)] = offset
        missing = sorted(set(BODY_BONES[1:]) - set(offsets))
        if missing:
            raise ValueError(
                f"source rest offsets are missing body bones: {', '.join(missing)}"
            )
        policy = str(clip.motion.get("rest_frame_correction_policy", ""))
        if policy == "identity_world_aligned_bvh_axes":
            return offsets, {}, policy
        raise ValueError(
            "adapter-provided source rest geometry requires an explicit, supported "
            "rest_frame_correction_policy"
        )

    def to_canonical(self, clip: RawClip) -> CanonicalResult:
        poses = np.asarray(clip.motion["poses"], dtype=np.float32)
        translation = np.asarray(clip.motion.get("translation"), dtype=np.float32)
        if translation.ndim != 2 or translation.shape[0] != poses.shape[0]:
            translation = np.zeros((poses.shape[0], 3), dtype=np.float32)
        body_quats = self._body_quats(poses)
        source_rest_offsets, body_rest_frame_corrections, rest_frame_policy = (
            self._rest_contract(clip)
        )
        hand_quats = clip.motion.get("hand_quaternions_xyzw")
        hand_quats_by_name: dict[str, np.ndarray] | None = None
        if hand_quats is not None:
            hand_quats = np.asarray(hand_quats, dtype=np.float32)
            if hand_quats.shape != (poses.shape[0], len(HAND_BONES), 4):
                raise ValueError(
                    "native hand quaternions must have shape "
                    f"{(poses.shape[0], len(HAND_BONES), 4)}, got {hand_quats.shape}"
                )
            hand_quats = normalize_quat_xyzw(hand_quats)
            hand_quats_by_name = {
                name: hand_quats[:, index] for index, name in enumerate(HAND_BONES)
            }
        retarget = retarget_named_quats_to_vrm(
            root_translation=translation,
            root_rotation_xyzw=body_quats[:, BODY_INDEX["hips"]],
            local_quats_by_name={
                name: body_quats[:, idx]
                for idx, name in enumerate(BODY_BONES)
                if name != "hips"
            },
            source_body_rest_offsets=source_rest_offsets,
            hand_quats_by_name=hand_quats_by_name,
            source_hand_rest_offsets=source_rest_offsets,
            body_rest_frame_corrections=body_rest_frame_corrections,
            hand_rest_frame_corrections=(
                {}
                if rest_frame_policy
                in {
                    "identity_world_aligned_bvh_axes",
                    "identity_canonical_parameter_frames",
                }
                else None
            ),
            world_basis=self.world_basis,
            root_rotation_semantics=self.root_rotation_semantics,
        )
        native_source_positions = clip.motion.get("source_positions")
        native_full_source_positions = clip.motion.get("source_full_positions")
        if native_full_source_positions is not None:
            native_full_source_positions = np.asarray(
                native_full_source_positions,
                dtype=np.float32,
            )
            if native_full_source_positions.shape != (
                poses.shape[0],
                len(FK_BONES),
                3,
            ):
                raise ValueError(
                    "native full source positions must have shape "
                    f"{(poses.shape[0], len(FK_BONES), 3)}, got "
                    f"{native_full_source_positions.shape}"
                )
            if not np.all(np.isfinite(native_full_source_positions)):
                raise ValueError("native full source positions must be finite")
            native_full_source_positions = native_full_source_positions * np.float32(
                retarget["scale"]
            )
        if native_source_positions is not None:
            native_source_positions = np.asarray(
                native_source_positions, dtype=np.float32
            )
            if native_source_positions.shape != (poses.shape[0], len(BODY_BONES), 3):
                raise ValueError(
                    "native source positions must have shape "
                    f"{(poses.shape[0], len(BODY_BONES), 3)}, got {native_source_positions.shape}"
                )
            if not np.all(np.isfinite(native_source_positions)):
                raise ValueError("native source positions must be finite")
            native_source_positions = native_source_positions * np.float32(
                retarget["scale"]
            )
        return CanonicalResult(
            sequence=retarget["sequence"],
            positions=retarget["positions"],
            joint_names=FK_BONES,
            edges=FK_EDGES,
            metadata={
                **dict(clip.motion.get("source_metadata", {})),
                "codec": self.key,
                "source_profile": self.source_profile,
                "canonical_skeleton": CANONICAL_SKELETON_ID,
                "rotation_semantics": CANONICAL_ROTATION_SEMANTICS,
                "target_skeleton": "vrm1_humanoid",
                "retarget_mode": retarget["mode"],
                "root_rotation_semantics": retarget["root_rotation_semantics"],
                "retarget_scale": retarget["scale"],
                "declared_world_basis": self.world_basis,
                "world_basis": retarget.get("world_basis", {}),
                "source_geometry": (
                    "adapter_native_fk"
                    if native_source_positions is not None
                    else "codec_rest_fk"
                ),
                "hand_channels": (
                    "adapter_native_parent_path_collapsed"
                    if hand_quats_by_name is not None
                    else "unavailable_identity"
                ),
                "rest_frame_correction_policy": rest_frame_policy,
            },
            retarget_source_positions=(
                native_full_source_positions
                if native_full_source_positions is not None
                else (
                    native_source_positions
                    if native_source_positions is not None
                    else retarget.get("source_positions")
                )
            ),
            retarget_source_joint_names=(
                list(FK_BONES)
                if native_full_source_positions is not None
                else list(BODY_BONES)
            ),
            hand_observation=(
                HandObservationMetadata.all_observed(
                    source=f"{self.source_profile}:parent_local_hand_rotations",
                    fps=float(clip.motion.get("fps", clip.sample.fps or 30.0)),
                )
                if hand_quats_by_name is not None
                else HandObservationMetadata.identity_only(
                    source=f"{self.source_profile}:hand_evidence_absent",
                    fps=float(clip.motion.get("fps", clip.sample.fps or 30.0)),
                )
            ),
        )

    def extract_source(self, clip: RawClip) -> SourceSnapshot:
        poses = np.asarray(clip.motion["poses"], dtype=np.float32)
        translation = np.asarray(clip.motion.get("translation"), dtype=np.float32)
        if translation.ndim != 2 or translation.shape[0] != poses.shape[0]:
            translation = np.zeros((poses.shape[0], 3), dtype=np.float32)
        body_quats = self._body_quats(poses)
        source_rest_offsets, _, rest_frame_policy = self._rest_contract(clip)
        source_scale = target_scale_from_rest_offsets(source_rest_offsets)
        native_source_positions = clip.motion.get("source_positions")
        native_full_source_positions = clip.motion.get("source_full_positions")
        if native_full_source_positions is not None:
            positions = np.asarray(native_full_source_positions, dtype=np.float32)
            if positions.shape != (poses.shape[0], len(FK_BONES), 3) or not np.all(
                np.isfinite(positions)
            ):
                raise ValueError(
                    "native full source positions must be finite canonical body+hand positions"
                )
            positions = positions * np.float32(source_scale)
            names = list(FK_BONES)
            edges = list(FK_EDGES)
        elif native_source_positions is not None:
            positions = np.asarray(native_source_positions, dtype=np.float32)
            if positions.shape != (poses.shape[0], len(BODY_BONES), 3) or not np.all(
                np.isfinite(positions)
            ):
                raise ValueError(
                    "native source positions must be finite body22 positions"
                )
            positions = positions * np.float32(source_scale)
            names = list(BODY_BONES)
            edges = list(BODY_EDGES)
        else:
            positions, names, edges = source_fk_from_body_quats(
                translation,
                body_quats[:, BODY_INDEX["hips"]],
                {
                    name: body_quats[:, idx]
                    for idx, name in enumerate(BODY_BONES)
                    if name != "hips"
                },
                source_rest_offsets,
                normalize_world=True,
                world_basis=self.world_basis,
            )
        return SourceSnapshot(
            positions=positions,
            joint_names=names,
            edges=edges,
            fps=float(clip.motion.get("fps", clip.sample.fps or 30.0)),
            coordinate_system="world_normalized",
            metadata={
                **dict(clip.motion.get("source_metadata", {})),
                "codec": self.key,
                "source_profile": self.source_profile,
                "declared_world_basis": self.world_basis,
                "source_geometry": (
                    "adapter_native_fk"
                    if native_source_positions is not None
                    or native_full_source_positions is not None
                    else "codec_rest_fk"
                ),
                "rest_frame_correction_policy": rest_frame_policy,
                "source_to_canonical_scale": source_scale,
            },
        )


SMPLX_HAND_INDEX = {
    "leftIndexProximal": 25,
    "leftIndexIntermediate": 26,
    "leftIndexDistal": 27,
    "leftMiddleProximal": 28,
    "leftMiddleIntermediate": 29,
    "leftMiddleDistal": 30,
    "leftLittleProximal": 31,
    "leftLittleIntermediate": 32,
    "leftLittleDistal": 33,
    "leftRingProximal": 34,
    "leftRingIntermediate": 35,
    "leftRingDistal": 36,
    "leftThumbProximal": 37,
    "leftThumbIntermediate": 38,
    "leftThumbDistal": 39,
    "rightIndexProximal": 40,
    "rightIndexIntermediate": 41,
    "rightIndexDistal": 42,
    "rightMiddleProximal": 43,
    "rightMiddleIntermediate": 44,
    "rightMiddleDistal": 45,
    "rightLittleProximal": 46,
    "rightLittleIntermediate": 47,
    "rightLittleDistal": 48,
    "rightRingProximal": 49,
    "rightRingIntermediate": 50,
    "rightRingDistal": 51,
    "rightThumbProximal": 52,
    "rightThumbIntermediate": 53,
    "rightThumbDistal": 54,
}

SMPLH_HAND_INDEX = {
    name: source_index - 25 for name, source_index in SMPLX_HAND_INDEX.items()
}


class SMPLHBodyHandsCodec(AxisAngleBody22Codec):
    """AMASS/BABEL SMPL-H: root+body 66D followed by two 15-joint hands."""

    key = "smplh_body_hands"

    def __init__(
        self,
        source_profile: str = "smplh_body22_hands30",
        root_rotation_semantics: str = "local_to_world",
    ) -> None:
        super().__init__(
            source_rest_offsets=DEFAULT_REST_OFFSETS,
            source_profile=source_profile,
            world_basis="z_up_to_y_up",
            root_rotation_semantics=root_rotation_semantics,
        )

    def to_canonical(self, clip: RawClip) -> CanonicalResult:
        poses = np.asarray(clip.motion["poses"], dtype=np.float32)
        if poses.ndim != 2 or poses.shape[1] < 156:
            raise ValueError(
                f"expected SMPL-H pose block with at least 156 dims, got {poses.shape}"
            )
        translation = np.asarray(clip.motion.get("translation"), dtype=np.float32)
        if translation.ndim != 2 or translation.shape[0] != poses.shape[0]:
            translation = np.zeros((poses.shape[0], 3), dtype=np.float32)
        body_quats = self._body_quats(poses)
        hand_quats = axis_angle_to_quat_xyzw(
            poses[:, 66:156].reshape(poses.shape[0], 30, 3)
        )
        retarget = retarget_named_quats_to_vrm(
            root_translation=translation,
            root_rotation_xyzw=body_quats[:, BODY_INDEX["hips"]],
            local_quats_by_name={
                name: body_quats[:, index]
                for index, name in enumerate(BODY_BONES)
                if name != "hips"
            },
            source_body_rest_offsets=self.source_rest_offsets,
            hand_quats_by_name={
                name: hand_quats[:, index] for name, index in SMPLH_HAND_INDEX.items()
            },
            source_hand_rest_offsets=DEFAULT_REST_OFFSETS,
            body_rest_frame_corrections={},
            hand_rest_frame_corrections={},
            world_basis=self.world_basis,
            root_rotation_semantics=self.root_rotation_semantics,
        )
        return CanonicalResult(
            sequence=retarget["sequence"],
            positions=retarget["positions"],
            joint_names=FK_BONES,
            edges=FK_EDGES,
            metadata={
                **dict(clip.motion.get("source_metadata", {})),
                "codec": self.key,
                "source_profile": self.source_profile,
                "canonical_skeleton": CANONICAL_SKELETON_ID,
                "rotation_semantics": CANONICAL_ROTATION_SEMANTICS,
                "target_skeleton": "vrm1_humanoid",
                "retarget_mode": retarget["mode"],
                "root_rotation_semantics": retarget["root_rotation_semantics"],
                "retarget_scale": retarget["scale"],
                "declared_world_basis": self.world_basis,
                "world_basis": retarget.get("world_basis", {}),
                "hand_channels": "native_smplh_axis_angle_30",
            },
            retarget_source_positions=retarget.get("source_positions"),
            retarget_source_joint_names=list(BODY_BONES),
            hand_observation=HandObservationMetadata.all_observed(
                source=f"{self.source_profile}:parent_local_hand_rotations",
                fps=float(clip.motion.get("fps", clip.sample.fps or 30.0)),
            ),
        )


class SMPLXFullposeCodec(MotionCodec):
    key = "smplx_fullpose"

    def __init__(self, root_rotation_semantics: str = "local_to_world") -> None:
        # SMPL-X global_orient maps the unchanged body-local template into
        # source world coordinates. It is therefore local_to_world unless a
        # separately configured source codec proves another representation.
        self.root_rotation_semantics = root_rotation_semantics

    @staticmethod
    def _source_profile_for_clip(clip: RawClip) -> str:
        metadata = dict(clip.motion.get("source_metadata", {}))
        return str(
            metadata.get("dataset_profile")
            or metadata.get("source_profile")
            or ("grab_smplx55" if clip.sample.dataset == "grab" else "smplx_fullpose55")
        )

    def _world_basis_for_clip(self, clip: RawClip) -> str:
        metadata = dict(clip.motion.get("source_metadata", {}))
        if metadata.get("declared_world_basis"):
            return str(metadata["declared_world_basis"])
        if metadata.get("world_basis") and isinstance(metadata["world_basis"], str):
            return str(metadata["world_basis"])
        if clip.sample.dataset == "grab":
            return "z_up_to_y_up"
        return "identity_y_up"

    def to_canonical(self, clip: RawClip) -> CanonicalResult:
        fullpose = np.asarray(clip.motion["fullpose"], dtype=np.float32)
        if fullpose.ndim != 2 or fullpose.shape[1] < 165:
            raise ValueError(
                f"expected SMPL-X fullpose block with at least 165 dims, got {fullpose.shape}"
            )
        translation = np.asarray(clip.motion.get("translation"), dtype=np.float32)
        if translation.ndim != 2 or translation.shape[0] != fullpose.shape[0]:
            translation = np.zeros((fullpose.shape[0], 3), dtype=np.float32)
        world_basis = self._world_basis_for_clip(clip)
        quats = axis_angle_to_quat_xyzw(
            fullpose[:, :165].reshape(fullpose.shape[0], 55, 3)
        )
        frame_count = quats.shape[0]
        core = identity_quats(frame_count, len(CORE_INDEX))
        hands = identity_quats(frame_count, len(HAND_INDEX))
        for body_index, bone_name in enumerate(CANONICAL_BODY_WITH_ROOT):
            if bone_name == "hips" or bone_name not in CORE_INDEX:
                continue
            core[:, CORE_INDEX[bone_name]] = quats[:, body_index]
        for bone_name, source_index in SMPLX_HAND_INDEX.items():
            if source_index < quats.shape[1] and bone_name in HAND_INDEX:
                hands[:, HAND_INDEX[bone_name]] = quats[:, source_index]
        retarget = retarget_named_quats_to_vrm(
            root_translation=translation,
            root_rotation_xyzw=quats[:, BODY_INDEX["hips"]],
            local_quats_by_name={
                name: quats[:, idx]
                for idx, name in enumerate(BODY_BONES)
                if name != "hips"
            },
            source_body_rest_offsets=DEFAULT_REST_OFFSETS,
            hand_quats_by_name={
                name: hands[:, idx] for idx, name in enumerate(HAND_INDEX)
            },
            source_hand_rest_offsets=DEFAULT_REST_OFFSETS,
            body_rest_frame_corrections={},
            hand_rest_frame_corrections={},
            world_basis=world_basis,
            root_rotation_semantics=self.root_rotation_semantics,
        )
        return CanonicalResult(
            sequence=retarget["sequence"],
            positions=retarget["positions"],
            joint_names=FK_BONES,
            edges=FK_EDGES,
            metadata={
                "codec": self.key,
                "source_profile": self._source_profile_for_clip(clip),
                "canonical_skeleton": CANONICAL_SKELETON_ID,
                "rotation_semantics": CANONICAL_ROTATION_SEMANTICS,
                "target_skeleton": "vrm1_humanoid",
                "retarget_mode": retarget["mode"],
                "root_rotation_semantics": retarget["root_rotation_semantics"],
                "retarget_scale": retarget["scale"],
                **dict(clip.motion.get("source_metadata", {})),
                "declared_world_basis": world_basis,
                "world_basis": retarget.get("world_basis", {}),
            },
            retarget_source_positions=retarget.get("source_positions"),
            retarget_source_joint_names=list(BODY_BONES),
            hand_observation=HandObservationMetadata.all_observed(
                source=f"{self._source_profile_for_clip(clip)}:parent_local_hand_rotations",
                fps=float(clip.motion.get("fps", clip.sample.fps or 30.0)),
            ),
        )

    def extract_source(self, clip: RawClip) -> SourceSnapshot:
        fullpose = np.asarray(clip.motion["fullpose"], dtype=np.float32)
        translation = np.asarray(clip.motion.get("translation"), dtype=np.float32)
        if translation.ndim != 2 or translation.shape[0] != fullpose.shape[0]:
            translation = np.zeros((fullpose.shape[0], 3), dtype=np.float32)
        world_basis = self._world_basis_for_clip(clip)
        quats = axis_angle_to_quat_xyzw(
            fullpose[:, :165].reshape(fullpose.shape[0], 55, 3)
        )
        positions, names, edges = source_fk_from_body_quats(
            translation,
            quats[:, BODY_INDEX["hips"]],
            {
                name: quats[:, idx]
                for idx, name in enumerate(BODY_BONES)
                if name != "hips"
            },
            DEFAULT_REST_OFFSETS,
            normalize_world=True,
            world_basis=world_basis,
        )
        return SourceSnapshot(
            positions=positions,
            joint_names=names,
            edges=edges,
            fps=float(clip.motion.get("fps", clip.sample.fps or 30.0)),
            coordinate_system="world_normalized",
            metadata={
                "codec": self.key,
                "source_profile": self._source_profile_for_clip(clip),
                "declared_world_basis": world_basis,
                **dict(clip.motion.get("source_metadata", {})),
            },
        )


SMPL24_NAMES = [
    "pelvis",
    "left_hip",
    "right_hip",
    "spine1",
    "left_knee",
    "right_knee",
    "spine2",
    "left_ankle",
    "right_ankle",
    "spine3",
    "left_foot",
    "right_foot",
    "neck",
    "left_collar",
    "right_collar",
    "head",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hand",
    "right_hand",
]

GUOH3D_TO_CANONICAL = {
    "pelvis": "hips",
    "left_hip": "leftUpperLeg",
    "right_hip": "rightUpperLeg",
    "spine1": "spine",
    "left_knee": "leftLowerLeg",
    "right_knee": "rightLowerLeg",
    "spine2": "chest",
    "left_ankle": "leftFoot",
    "right_ankle": "rightFoot",
    "spine3": "upperChest",
    "left_foot": "leftToes",
    "right_foot": "rightToes",
    "neck": "neck",
    "left_collar": "leftShoulder",
    "right_collar": "rightShoulder",
    "head": "head",
    "left_shoulder": "leftUpperArm",
    "right_shoulder": "rightUpperArm",
    "left_elbow": "leftLowerArm",
    "right_elbow": "rightLowerArm",
    "left_wrist": "leftHand",
    "right_wrist": "rightHand",
}


def _canonical_edges_for_names(joint_names: list[str]) -> list[tuple[int, int]]:
    joint_index = {name: index for index, name in enumerate(joint_names)}
    return [
        (joint_index[parent], joint_index[child])
        for child in joint_names
        if child != "hips"
        for parent in [CANONICAL_PARENT.get(child)]
        if parent in joint_index
    ]


class PositionSequenceCodec(MotionCodec):
    key = "position_sequence"

    def __init__(
        self,
        default_joint_names: list[str] | None = None,
        source_profile: str = "position_sequence",
        world_basis: str = "z_up_to_y_up",
    ) -> None:
        self.default_joint_names = default_joint_names or SMPL24_NAMES
        self.source_profile = source_profile
        self.world_basis = world_basis

    def to_canonical(self, clip: RawClip) -> CanonicalResult:
        source_positions = np.asarray(clip.motion["positions"], dtype=np.float32)
        source_names = (
            clip.source_joint_names
            or self.default_joint_names[: source_positions.shape[1]]
        )
        mapped_names: list[str] = []
        mapped_positions: list[np.ndarray] = []
        seen: set[str] = set()
        for source_index, source_name in enumerate(source_names):
            canonical = GUOH3D_TO_CANONICAL.get(source_name, source_name)
            if canonical in FK_BONES and canonical not in seen:
                mapped_names.append(canonical)
                mapped_positions.append(source_positions[:, source_index])
                seen.add(canonical)
        if mapped_positions:
            target = np.stack(mapped_positions, axis=1).astype(np.float32)
        else:
            mapped_names = ["hips"]
            target = np.zeros((source_positions.shape[0], 1, 3), dtype=np.float32)
        target = target.copy()
        source_edges = _canonical_edges_for_names(mapped_names)
        body_positions = body_positions_from_fk_positions(target, mapped_names)
        retarget = fit_positions_to_vrm(body_positions, world_basis=self.world_basis)
        return CanonicalResult(
            sequence=retarget["sequence"],
            positions=retarget["positions"],
            joint_names=FK_BONES,
            edges=FK_EDGES,
            metadata={
                "codec": self.key,
                "source_profile": self.source_profile,
                "canonical_skeleton": CANONICAL_SKELETON_ID,
                "rotation_semantics": CANONICAL_ROTATION_SEMANTICS,
                "position_to_rotation": retarget["mode"],
                "position_only_preview": False,
                "source_coordinates_preserved": False,
                "mapped_joint_count": len(mapped_names),
                "unmapped_canonical_joint_count": len(FK_BONES) - len(mapped_names),
                "original_source_joint_count": int(source_positions.shape[1]),
                "source_joint_names": BODY_BONES,
                "source_edges": BODY_EDGES,
                "native_mapped_joint_names": mapped_names,
                "native_mapped_edges": source_edges,
                "retarget_scale": retarget["scale"],
                "declared_world_basis": self.world_basis,
                "world_basis": retarget.get("world_basis", {}),
                "root_rotation_semantics": "not_applicable",
                "root_orientation_recovery": retarget.get("root_orientation_recovery"),
                "upper_chest_orientation_recovery": retarget.get(
                    "upper_chest_orientation_recovery"
                ),
                "rotation_observability": retarget.get("rotation_observability", {}),
                "hand_biomechanics": retarget.get("hand_biomechanics"),
            },
            retarget_source_positions=retarget.get("source_positions"),
            retarget_source_joint_names=list(BODY_BONES),
            hand_observation=HandObservationMetadata.identity_only(
                source=f"{self.source_profile}:hand_evidence_absent",
                fps=float(clip.motion.get("fps", clip.sample.fps or 20.0)),
            ),
        )

    def extract_source(self, clip: RawClip) -> SourceSnapshot:
        source_positions = np.asarray(clip.motion["positions"], dtype=np.float32)
        source_names = (
            clip.source_joint_names
            or self.default_joint_names[: source_positions.shape[1]]
        )
        mapped_names: list[str] = []
        mapped_positions: list[np.ndarray] = []
        seen: set[str] = set()
        for source_index, source_name in enumerate(source_names):
            canonical = GUOH3D_TO_CANONICAL.get(source_name, source_name)
            if canonical in BODY_BONES and canonical not in seen:
                mapped_names.append(canonical)
                mapped_positions.append(source_positions[:, source_index])
                seen.add(canonical)
        if mapped_positions:
            body_pos = body_positions_from_fk_positions(
                np.stack(mapped_positions, axis=1).astype(np.float32), mapped_names
            )
            positions = source_positions_normalized(
                body_pos, BODY_BONES, world_basis=self.world_basis
            )
        else:
            positions = center_positions_at_root(source_positions.copy())
        return SourceSnapshot(
            positions=positions,
            joint_names=list(BODY_BONES),
            edges=list(BODY_EDGES),
            fps=float(clip.motion.get("fps", clip.sample.fps or 20.0)),
            coordinate_system="world_normalized",
            metadata={
                "codec": self.key,
                "source_profile": self.source_profile,
                "declared_world_basis": self.world_basis,
            },
        )


class HumanML3D263Codec(PositionSequenceCodec):
    key = "humanml3d_263d"

    def __init__(self) -> None:
        super().__init__(
            default_joint_names=SMPL24_NAMES[:22],
            source_profile="humanml3d_263d",
            world_basis="identity_y_up",
        )

    def _decode_positions(
        self, motion: np.ndarray
    ) -> tuple[np.ndarray, list[str], dict[str, Any]]:
        """Recover 22 joints from HumanML3D's root + RIC channels.

        This is the NumPy equivalent of the dataset's published
        ``recover_root_rot_pos`` and ``recover_from_ric`` functions.  Only the
        first 67 features are consumed: root angular velocity, root planar
        velocity, root height, and 21 root-relative joint positions.  Decoder
        errors are fatal; emitting a plausible rest pose would fabricate motion.
        """

        data = np.asarray(motion, dtype=np.float32)
        joint_count = 22
        ric_end = 4 + (joint_count - 1) * 3
        rotation_end = ric_end + (joint_count - 1) * 6
        required_width = 263
        if data.ndim != 2 or data.shape[0] < 1 or data.shape[1] < required_width:
            raise ValueError(
                f"HumanML3D 263D motion must have shape (T, >= {required_width}), got {data.shape}"
            )
        if not np.all(np.isfinite(data[:, :required_width])):
            raise ValueError("HumanML3D 263D features contain non-finite values")

        # The 126D block is the official first-two-columns 6D representation,
        # but HumanML3D's Skeleton applies each entry before translating the
        # *child* edge.  That is not glTF/VRM node-local semantics.  Validate
        # the native channel so corruption cannot pass silently, while using
        # the independently recoverable RIC positions for the target motion.
        sixd_to_quat_xyzw(
            data[:, ric_end:rotation_end].reshape(data.shape[0], joint_count - 1, 6)
        )

        frame_count = data.shape[0]
        half_yaw = np.zeros((frame_count,), dtype=np.float32)
        half_yaw[1:] = data[:-1, 0]
        half_yaw = np.cumsum(half_yaw, axis=0, dtype=np.float32)
        root_quat = np.zeros((frame_count, 4), dtype=np.float32)
        root_quat[:, 1] = np.sin(half_yaw)
        root_quat[:, 3] = np.cos(half_yaw)

        root_position = np.zeros((frame_count, 3), dtype=np.float32)
        root_position[1:, [0, 2]] = data[:-1, 1:3]
        root_position = quat_apply_xyzw(quat_inverse_xyzw(root_quat), root_position)
        root_position = np.cumsum(root_position, axis=0, dtype=np.float32)
        root_position[:, 1] = data[:, 3]

        local = data[:, 4:ric_end].reshape(frame_count, joint_count - 1, 3)
        inverse_root = np.broadcast_to(
            quat_inverse_xyzw(root_quat)[:, None, :],
            (frame_count, joint_count - 1, 4),
        )
        positions = quat_apply_xyzw(inverse_root, local)
        positions[..., 0] += root_position[:, None, 0]
        positions[..., 2] += root_position[:, None, 2]
        positions = np.concatenate(
            [root_position[:, None, :], positions], axis=1
        ).astype(np.float32)
        return (
            positions,
            SMPL24_NAMES[:joint_count],
            {
                "humanml_decoder": "official_recover_from_ric_numpy",
                "humanml_consumed_features": "root4_plus_ric63",
                "humanml_validated_not_applied_features": "child_edge_rotation6d126",
                "humanml_ignored_features": "velocity66_contact4",
                "humanml_rotation_semantics": "child_incoming_edge_rotation_before_translation",
                "humanml_rotation_target_policy": "do_not_map_directly_to_gltf_node_local",
                "humanml_rotation_observability": (
                    "native_6d_is_position_ik_derived_and_does_not_restore_independent_physical_twist"
                ),
            },
        )

    def to_canonical(self, clip: RawClip) -> CanonicalResult:
        motion = np.asarray(clip.motion["motion"], dtype=np.float32)
        positions, names, decoder_meta = self._decode_positions(motion)
        position_clip = RawClip(
            sample=clip.sample,
            motion={"positions": positions, "fps": clip.motion.get("fps", 20.0)},
            annotations=clip.annotations,
            source_joint_names=names,
            source_edges=BODY_EDGES,
        )
        result = super().to_canonical(position_clip)
        mapped_names = list(result.metadata.get("source_joint_names", []))
        mapped_edges = [tuple(edge) for edge in result.metadata.get("source_edges", [])]
        result.metadata.update(decoder_meta)
        result.metadata["codec"] = self.key
        result.metadata["native_joint_names"] = names
        result.metadata["source_joint_names"] = mapped_names
        result.metadata["source_edges"] = mapped_edges
        return result

    def extract_source(self, clip: RawClip) -> SourceSnapshot:
        motion = np.asarray(clip.motion["motion"], dtype=np.float32)
        positions, names, decoder_meta = self._decode_positions(motion)
        canonical_names = [GUOH3D_TO_CANONICAL.get(n, n) for n in names]
        body_pos = body_positions_from_fk_positions(
            np.asarray(positions, dtype=np.float32), canonical_names
        )
        normalized = source_positions_normalized(
            body_pos, BODY_BONES, world_basis=self.world_basis
        )
        return SourceSnapshot(
            positions=normalized,
            joint_names=list(BODY_BONES),
            edges=list(BODY_EDGES),
            fps=float(clip.motion.get("fps", clip.sample.fps or 20.0)),
            coordinate_system="world_normalized",
            metadata={
                "codec": self.key,
                "source_profile": "humanml3d_263d",
                "declared_world_basis": self.world_basis,
                **decoder_meta,
            },
        )


SUSU_BODY_NAMES = [
    "pelvis",
    "thigh_r",
    "calf_r",
    "foot_r",
    "ball_r",
    "thigh_l",
    "calf_l",
    "foot_l",
    "ball_l",
    "spine_01",
    "spine_02",
    "spine_03",
    "spine_04",
    "spine_05",
    "neck_01",
    "neck_02",
    "head",
    "clavicle_l",
    "upperarm_l",
    "lowerarm_l",
    "clavicle_r",
    "upperarm_r",
    "lowerarm_r",
    "hand_l",
    "hand_r",
]
SUSU_BODY_TO_CANONICAL = {
    "pelvis": "hips",
    "thigh_l": "leftUpperLeg",
    "calf_l": "leftLowerLeg",
    "foot_l": "leftFoot",
    "ball_l": "leftToes",
    "thigh_r": "rightUpperLeg",
    "calf_r": "rightLowerLeg",
    "foot_r": "rightFoot",
    "ball_r": "rightToes",
    "spine_01": "spine",
    "spine_03": "chest",
    "spine_05": "upperChest",
    "neck_01": "neck",
    "head": "head",
    "clavicle_l": "leftShoulder",
    "upperarm_l": "leftUpperArm",
    "lowerarm_l": "leftLowerArm",
    "hand_l": "leftHand",
    "clavicle_r": "rightShoulder",
    "upperarm_r": "rightUpperArm",
    "lowerarm_r": "rightLowerArm",
    "hand_r": "rightHand",
}
SUSU_SOURCE_NAMES = [*SUSU_BODY_NAMES]
SUSU_SOURCE_EDGES = [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),
    (0, 5),
    (5, 6),
    (6, 7),
    (7, 8),
    (0, 9),
    (9, 10),
    (10, 11),
    (11, 12),
    (12, 13),
    (13, 14),
    (14, 15),
    (15, 16),
    (13, 17),
    (17, 18),
    (18, 19),
    (19, 23),
    (13, 20),
    (20, 21),
    (21, 22),
    (22, 24),
]

# Adapted from SentiAvatar's CC BY-NC 4.0
# `template_susu_retarget_63nodes.bvh` and `process_batch_data` (accessed
# 2026-08-08); attribution, modifications, and restrictions are recorded in
# THIRD_PARTY_NOTICES.md.  These are source-skeleton
# model constants, not machine configuration.  The public converter assigns
# the decoded parent-local quaternions to this template after a fixed swizzle;
# using VIREA's canonical offsets here was the cause of the historical
# feet-above-head source distortion for rotation-only retarget_maya clips.
SUSU_MTA25_PARENTS = np.asarray(
    [
        -1,
        0,
        1,
        2,
        3,
        0,
        5,
        6,
        7,
        0,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        13,
        17,
        18,
        13,
        20,
        21,
        19,
        22,
    ],
    dtype=np.int32,
)
SUSU_MTA25_REST_OFFSETS_M = np.asarray(
    [
        [0.0, 0.0, 0.0],
        [-2.31334, -0.050603, 9.31044],
        [46.6594, 0.000796, 0.000019],
        [44.4247, 0.000030, 0.000094],
        [6.50451, 12.7092, 0.435689],
        [-2.31315, -0.051123, -9.31061],
        [-46.6618, -0.000912, -0.000026],
        [-44.4144, 0.000097, 0.000114],
        [-6.51458, -12.7087, -0.433235],
        [2.59545, 0.208490, 0.0],
        [4.87729, -0.954006, 0.022121],
        [6.29747, 0.000308, -0.000423],
        [6.66341, -0.000045, 0.000068],
        [13.1375, 0.000042, 0.000127],
        [13.8702, -0.000043, 0.000048],
        [4.29525, 0.0, 0.000045],
        [4.49171, 0.000740, 0.001639],
        [8.02955, 0.614939, -0.570049],
        [10.1362, 0.0, 0.000032],
        [28.7315, 0.000017, 0.000177],
        [8.02969, 0.615852, 0.570123],
        [-10.1350, -0.002579, -0.000361],
        [-28.7329, 0.001365, 0.005621],
        [24.7624, 0.0, 0.0],
        [-24.7646, -0.001016, 0.000179],
    ],
    dtype=np.float32,
) * np.float32(0.01)


def _susu_official_bvh_local_quats(
    quaternions_xyzw: np.ndarray,
    *,
    correct_pelvis: bool,
) -> np.ndarray:
    """Reproduce SentiAvatar `process_batch_data`'s local quaternion mapping.

    The upstream converter decodes first-two-column 6D rotations to wxyz,
    changes every local quaternion to `(w, -x, y, -z)`, and applies its
    historical pelvis correction before that swizzle.  This function retains
    xyzw storage while matching those exact executed operations.
    """

    source = np.asarray(quaternions_xyzw, dtype=np.float32)
    mapped = np.stack(
        [-source[..., 0], source[..., 1], -source[..., 2], source[..., 3]], axis=-1
    )
    if not correct_pelvis:
        return mapped.astype(np.float32)
    if source.ndim != 3 or source.shape[1] < 1:
        raise ValueError(
            f"SuSu pelvis correction requires shape (T,J,4), got {source.shape}"
        )

    # Upstream temporarily stores xyzw but the pelvis multiplication names its
    # components wxyz.  Reproduce that branch exactly for byte-level semantic
    # compatibility rather than replacing it with an idealized correction.
    selected = source[:, 0]
    selected_as_xyzw = np.stack(
        [selected[:, 1], selected[:, 2], selected[:, 3], selected[:, 0]],
        axis=-1,
    )
    diff_inverse_xyzw = np.broadcast_to(
        np.asarray([0.0, 0.0, -0.70710678, 0.70710678], dtype=np.float32),
        selected_as_xyzw.shape,
    )
    corrected_as_xyzw = quat_multiply_xyzw(selected_as_xyzw, diff_inverse_xyzw)
    corrected_wxyz = np.stack(
        [
            corrected_as_xyzw[:, 3],
            corrected_as_xyzw[:, 0],
            corrected_as_xyzw[:, 1],
            corrected_as_xyzw[:, 2],
        ],
        axis=-1,
    )
    mapped[:, 0] = np.stack(
        [
            -corrected_wxyz[:, 0],
            corrected_wxyz[:, 1],
            -corrected_wxyz[:, 2],
            corrected_wxyz[:, 3],
        ],
        axis=-1,
    )
    return mapped.astype(np.float32)


def _susu_mta25_fk(
    root_translation: np.ndarray, local_quats_xyzw: np.ndarray
) -> np.ndarray:
    positions, _globals_by_joint = _susu_mta25_fk_state(
        root_translation, local_quats_xyzw
    )
    return positions


def _susu_mta25_fk_state(
    root_translation: np.ndarray,
    local_quats_xyzw: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    local = np.asarray(local_quats_xyzw, dtype=np.float32)
    if local.ndim != 3 or local.shape[1:] != (25, 4):
        raise ValueError(
            f"SuSu MTA25 local rotations must have shape (T,25,4), got {local.shape}"
        )
    frame_count = int(local.shape[0])
    positions = np.zeros((frame_count, 25, 3), dtype=np.float32)
    globals_by_joint = np.zeros_like(local)
    positions[:, 0] = np.asarray(root_translation, dtype=np.float32)
    globals_by_joint[:, 0] = local[:, 0]
    for joint in range(1, 25):
        parent = int(SUSU_MTA25_PARENTS[joint])
        offset = np.broadcast_to(SUSU_MTA25_REST_OFFSETS_M[joint], (frame_count, 3))
        positions[:, joint] = positions[:, parent] + quat_apply_xyzw(
            globals_by_joint[:, parent], offset
        )
        globals_by_joint[:, joint] = quat_multiply_xyzw(
            globals_by_joint[:, parent], local[:, joint]
        )
    return positions.astype(np.float32), normalize_quat_xyzw(globals_by_joint)


SUSU_HAND20_PARENTS = np.asarray(
    [-1, 0, 1, 2, 3, 0, 5, 6, 7, 0, 9, 10, 11, 0, 13, 14, 15, 0, 17, 18],
    dtype=np.int32,
)

SUSU_MTA63_SOURCE_GEOMETRY_ID = "sentiavatar.mta63.template_geometry.v1"
SUSU_MTA63_JOINT_ORDER_ID = "susu63_unique"
SUSU_MTA63_SOURCE_TEMPLATE_SHA256 = (
    "323cc542ed9f2e384d80c5b7b1e796a55f4a6ad6690acc144fd90d91baa64f7e"
)

# Adapted SentiAvatar MTA63 source-skeleton geometry under CC BY-NC 4.0; see
# THIRD_PARTY_NOTICES.md.  Index zero duplicates the body wrist and therefore
# has no offset.  Values are metres; the upstream BVH stores centimetres.
# These offsets are used only for source FK evidence, never as canonical or
# target-avatar rest frames.
SUSU_HAND20_REST_OFFSETS_M = {
    "left": np.asarray(
        [
            [0.0, 0.0, 0.0],
            [0.0300577, 0.00596985, -0.0177292],
            [0.0468879, 0.0, 0.0],
            [0.0438351, 0.0, 0.0],
            [0.0196524, 0.0, 0.0],
            [0.0280460, 0.00096878, -0.00451881],
            [0.0501201, 0.0, 0.0],
            [0.0439551, 0.0, 0.0],
            [0.0284250, 0.0, 0.0],
            [0.0285219, -0.00096878, 0.00451885],
            [0.0453370, 0.0, 0.0],
            [0.0376856, 0.0, 0.0],
            [0.0303625, 0.0, 0.0],
            [0.0281893, -0.00276169, 0.0146394],
            [0.0423814, 0.0, 0.0],
            [0.0250432, 0.0, 0.0],
            [0.0182002, 0.0, 0.0],
            [0.0164575, 0.0166833, -0.0152432],
            [0.0455164, 0.0, 0.0],
            [0.0264427, 0.0, 0.0],
        ],
        dtype=np.float32,
    ),
    "right": np.asarray(
        [
            [0.0, 0.0, 0.0],
            [-0.0326870, -0.00454758, 0.0128381],
            [-0.0468771, 0.0, 0.0],
            [-0.0438177, 0.0, 0.0],
            [-0.0196653, 0.0, 0.0],
            [-0.0284032, 0.0, 0.0],
            [-0.0501112, 0.0, 0.0],
            [-0.0439397, 0.0, 0.0],
            [-0.0284558, 0.0, 0.0],
            [-0.0273552, 0.00168312, -0.00904747],
            [-0.0453291, 0.0, 0.0],
            [-0.0376844, 0.0, 0.0],
            [-0.0303635, 0.0, 0.0],
            [-0.0253580, 0.00313965, -0.0190445],
            [-0.0423278, 0.0, 0.0],
            [-0.0250448, 0.0, 0.0],
            [-0.0182145, 0.0, 0.0],
            [-0.0192332, -0.0157207, 0.0128471],
            [-0.0455009, 0.0, 0.0],
            [-0.0264448, 0.0, 0.0],
        ],
        dtype=np.float32,
    ),
}


def _susu_mta63_geometry_table_bytes() -> bytes:
    """Serialize every source-FK geometry table with a stable binary contract."""

    payload = bytearray(b"virea.susu.mta63.geometry-table.v2\n")
    tables = (
        ("body.parents", SUSU_MTA25_PARENTS, "<i4"),
        ("body.offsets_m", SUSU_MTA25_REST_OFFSETS_M, "<f4"),
        ("hand.parents", SUSU_HAND20_PARENTS, "<i4"),
        ("left_hand.offsets_m", SUSU_HAND20_REST_OFFSETS_M["left"], "<f4"),
        ("right_hand.offsets_m", SUSU_HAND20_REST_OFFSETS_M["right"], "<f4"),
    )
    for name, values, dtype in tables:
        array = np.ascontiguousarray(np.asarray(values, dtype=np.dtype(dtype)))
        shape = ",".join(str(dimension) for dimension in array.shape)
        payload.extend(f"{name}|{array.dtype.str}|{shape}\n".encode("ascii"))
        payload.extend(array.tobytes(order="C"))
    return bytes(payload)


SUSU_MTA63_GEOMETRY_TABLE_SHA256 = hashlib.sha256(
    _susu_mta63_geometry_table_bytes()
).hexdigest()


def _susu_mta63_fk(
    root_translation: np.ndarray,
    body_local_quats_xyzw: np.ndarray,
    hand_local_quats_by_side: dict[str, np.ndarray],
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Reconstruct the official MTA63 source joint centres.

    The returned hand mapping contains the 30 VRM-corresponding phalange
    centres.  Four source metacarpals per side remain in the FK chain but are
    collapsed from the target topology; their rotations and offsets therefore
    still affect every downstream position.
    """

    body_positions, body_globals = _susu_mta25_fk_state(
        root_translation,
        body_local_quats_xyzw,
    )
    frame_count = int(body_positions.shape[0])
    canonical_hand_positions: dict[str, np.ndarray] = {}
    for side, wrist_index in (("left", 23), ("right", 24)):
        if side not in hand_local_quats_by_side:
            continue
        local = normalize_quat_xyzw(
            np.asarray(hand_local_quats_by_side[side], dtype=np.float32)
        )
        if local.shape != (frame_count, 20, 4):
            raise ValueError(
                f"SuSu {side} hand rotations must have shape {(frame_count, 20, 4)}, "
                f"got {local.shape}"
            )
        positions = np.zeros((frame_count, 20, 3), dtype=np.float32)
        globals_by_joint = np.zeros_like(local)
        positions[:, 0] = body_positions[:, wrist_index]
        globals_by_joint[:, 0] = body_globals[:, wrist_index]
        rest_offsets = SUSU_HAND20_REST_OFFSETS_M[side]
        for joint in range(1, 20):
            parent = int(SUSU_HAND20_PARENTS[joint])
            offset = np.broadcast_to(rest_offsets[joint], (frame_count, 3))
            positions[:, joint] = positions[:, parent] + quat_apply_xyzw(
                globals_by_joint[:, parent],
                offset,
            )
            globals_by_joint[:, joint] = quat_multiply_xyzw(
                globals_by_joint[:, parent],
                local[:, joint],
            )
        for source_index, canonical_name in _susu_hand_map(side).items():
            canonical_hand_positions[canonical_name] = positions[:, source_index].copy()
    return body_positions, canonical_hand_positions


def _susu_hand_map(side: str) -> dict[int, str]:
    prefix = "left" if side == "left" else "right"
    return {
        17: f"{prefix}ThumbProximal",
        18: f"{prefix}ThumbIntermediate",
        19: f"{prefix}ThumbDistal",
        2: f"{prefix}IndexProximal",
        3: f"{prefix}IndexIntermediate",
        4: f"{prefix}IndexDistal",
        6: f"{prefix}MiddleProximal",
        7: f"{prefix}MiddleIntermediate",
        8: f"{prefix}MiddleDistal",
        10: f"{prefix}RingProximal",
        11: f"{prefix}RingIntermediate",
        12: f"{prefix}RingDistal",
        14: f"{prefix}LittleProximal",
        15: f"{prefix}LittleIntermediate",
        16: f"{prefix}LittleDistal",
    }


SUSU_POSITION_HAND_INDEX: dict[str, int] = {
    **{
        canonical: 24 + source_index
        for source_index, canonical in _susu_hand_map("left").items()
    },
    **{
        canonical: 43 + source_index
        for source_index, canonical in _susu_hand_map("right").items()
    },
}


def _compose_local_quats(quats: np.ndarray, indices: tuple[int, ...]) -> np.ndarray:
    if not indices:
        return identity_quats(int(quats.shape[0]), 1)[:, 0]
    output = quats[:, indices[0]]
    for source_index in indices[1:]:
        output = quat_multiply_xyzw(output, quats[:, source_index])
    return output


SUSU_BODY_LOCAL_CHAINS: dict[str, tuple[int, ...]] = {
    "leftUpperLeg": (5,),
    "leftLowerLeg": (6,),
    "leftFoot": (7,),
    "leftToes": (8,),
    "rightUpperLeg": (1,),
    "rightLowerLeg": (2,),
    "rightFoot": (3,),
    "rightToes": (4,),
    "spine": (9,),
    # SuSu has five spine and two neck joints.  Canonical VRM has three
    # spine/chest joints and one neck, so skipped local rotations are composed.
    "chest": (10, 11),
    "upperChest": (12, 13),
    "neck": (14,),
    "head": (15, 16),
    "leftShoulder": (17,),
    "leftUpperArm": (18,),
    "leftLowerArm": (19,),
    "leftHand": (23,),
    "rightShoulder": (20,),
    "rightUpperArm": (21,),
    "rightLowerArm": (22,),
    "rightHand": (24,),
}


def _susu_body_parent_local(
    body_quats: np.ndarray,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    if body_quats.ndim != 3 or body_quats.shape[1] < 25 or body_quats.shape[2] != 4:
        raise ValueError(
            f"SuSu body rotations must have shape (T, 25, 4), got {body_quats.shape}"
        )
    return body_quats[:, 0], {
        canonical: _compose_local_quats(body_quats, source_chain)
        for canonical, source_chain in SUSU_BODY_LOCAL_CHAINS.items()
    }


def _susu_hand_parent_local(hand_quats: np.ndarray, side: str) -> dict[str, np.ndarray]:
    """Collapse the official 20-joint hand into the VRM 15-joint hand.

    SuSu index 0 duplicates the body wrist.  Each non-thumb chain then has a
    metacarpal plus three phalanges; VRM has only three nodes, so the metacarpal
    and first phalanx local rotations are composed into the proximal node.
    """

    if hand_quats.ndim != 3 or hand_quats.shape[1] < 20 or hand_quats.shape[2] != 4:
        raise ValueError(
            f"SuSu hand rotations must have shape (T, 20, 4), got {hand_quats.shape}"
        )
    prefix = "left" if side == "left" else "right"
    chains = {
        f"{prefix}IndexProximal": (1, 2),
        f"{prefix}IndexIntermediate": (3,),
        f"{prefix}IndexDistal": (4,),
        f"{prefix}MiddleProximal": (5, 6),
        f"{prefix}MiddleIntermediate": (7,),
        f"{prefix}MiddleDistal": (8,),
        f"{prefix}RingProximal": (9, 10),
        f"{prefix}RingIntermediate": (11,),
        f"{prefix}RingDistal": (12,),
        f"{prefix}LittleProximal": (13, 14),
        f"{prefix}LittleIntermediate": (15,),
        f"{prefix}LittleDistal": (16,),
        f"{prefix}ThumbProximal": (17,),
        f"{prefix}ThumbIntermediate": (18,),
        f"{prefix}ThumbDistal": (19,),
    }
    return {
        name: _compose_local_quats(hand_quats, chain) for name, chain in chains.items()
    }


def _susu_body_global_to_local(
    body_quats: np.ndarray,
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray]]:
    frame_count = int(body_quats.shape[0])
    identity = identity_quats(frame_count, 1)[:, 0]
    global_by_name: dict[str, np.ndarray] = {}
    for source_idx, source_name in enumerate(SUSU_BODY_NAMES):
        canonical = SUSU_BODY_TO_CANONICAL.get(source_name)
        if (
            canonical
            and canonical not in global_by_name
            and source_idx < body_quats.shape[1]
        ):
            global_by_name[canonical] = body_quats[:, source_idx]

    root_rot = global_by_name.get("hips", identity)
    local_by_name: dict[str, np.ndarray] = {}
    for canonical, global_quat in global_by_name.items():
        if canonical == "hips":
            continue
        parent = CANONICAL_PARENT.get(canonical)
        parent_global = global_by_name.get(parent or "")
        if parent_global is None:
            local_by_name[canonical] = global_quat
        else:
            local_by_name[canonical] = quat_multiply_xyzw(
                quat_inverse_xyzw(parent_global), global_quat
            )
    return root_rot, local_by_name, global_by_name


def _susu_hand_global_to_local(
    hand_quats: np.ndarray,
    side: str,
    body_global_by_name: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    global_by_name: dict[str, np.ndarray] = {}
    for source_idx, canonical in _susu_hand_map(side).items():
        if source_idx < hand_quats.shape[1] and canonical in HAND_INDEX:
            global_by_name[canonical] = hand_quats[:, source_idx]

    local_by_name: dict[str, np.ndarray] = {}
    for canonical, global_quat in global_by_name.items():
        parent = CANONICAL_PARENT.get(canonical)
        parent_global = global_by_name.get(parent or "")
        if parent_global is None:
            parent_global = body_global_by_name.get(parent or "")
        if parent_global is None:
            local_by_name[canonical] = global_quat
        else:
            local_by_name[canonical] = quat_multiply_xyzw(
                quat_inverse_xyzw(parent_global), global_quat
            )
    return local_by_name


@dataclass(frozen=True)
class SuSuProfile:
    name: str
    path_token: str
    position_scale: float
    root_translation_scale: float
    position_world_basis: str
    root_axes: tuple[int, int, int] = (0, 2, 1)
    root_translation_mode: str = "absolute_xzy_zeroed"
    rotation_6d_layout: str = "first_two_columns"
    rotation_space: str = "parent_local"
    rotation_world_basis: str = "identity_y_up"
    validation_status: str = "draft"


SUSU_RETARGET_MAYA_PROFILE = SuSuProfile(
    name="susu_retarget_maya_6d_body_hands",
    path_token="fbx_to_json_data_susu_retarget_maya/",
    position_scale=0.01,
    root_translation_scale=1.0,
    position_world_basis="neg_z_up_to_y_up",
    root_translation_mode="absolute_xzy_zeroed_auto_units",
    validation_status="draft",
)
SUSU_CHONGLU_PROFILE = SuSuProfile(
    name="susu_chonglu_6d_body_hands_cm",
    path_token="fbx_to_json_data_susu_chonglu/",
    position_scale=0.01,
    root_translation_scale=0.01,
    position_world_basis="identity_y_up",
    root_translation_mode="absolute_xzy_cm_zeroed",
    validation_status="draft",
)
SUSU_PROFILE_BY_CODEC = {
    SUSU_RETARGET_MAYA_PROFILE.name: SUSU_RETARGET_MAYA_PROFILE,
    SUSU_CHONGLU_PROFILE.name: SUSU_CHONGLU_PROFILE,
}
SUSU_CODEC_KEYS = frozenset({"susu_6d_body_hands", *SUSU_PROFILE_BY_CODEC})


class SuSu6DCodec(MotionCodec):
    key = "susu_6d_body_hands"

    def __init__(self, profile: SuSuProfile | None = None) -> None:
        self.profile = profile

    def _select_profile(self, clip: RawClip, has_positions: bool) -> SuSuProfile:
        if self.profile:
            return self.profile
        sample_id = clip.sample.sample_id
        for profile in SUSU_PROFILE_BY_CODEC.values():
            if sample_id.startswith(profile.path_token):
                return profile
        return SUSU_CHONGLU_PROFILE if has_positions else SUSU_RETARGET_MAYA_PROFILE

    @staticmethod
    def _body_array(clip: RawClip) -> np.ndarray:
        body = np.asarray(clip.motion.get("body"), dtype=np.float32)
        if body.ndim != 2 or body.shape[1] != 153 or body.shape[0] < 1:
            raise ValueError(
                f"SuSu body motion must have exact shape (T,153), got {body.shape}"
            )
        if not np.isfinite(body).all():
            raise ValueError("SuSu body motion must contain only finite values")
        return body

    def _positions_from_available_data(
        self, clip: RawClip, profile: SuSuProfile
    ) -> np.ndarray | None:
        positions = clip.motion.get("positions")
        if positions is None:
            return None
        body = self._body_array(clip)
        values = np.asarray(positions)
        expected_shape = (int(body.shape[0]) if body.ndim >= 1 else 0, 63, 3)
        if values.shape != expected_shape:
            raise ValueError(
                "SuSu native positions must have exact shape "
                f"(body_T,63,3)={expected_shape}, got {values.shape}"
            )
        if not np.isfinite(values).all():
            raise ValueError("SuSu native positions must contain only finite values")
        joint_order = clip.sample.metadata.get("positions_joint_order")
        if joint_order != SUSU_MTA63_JOINT_ORDER_ID:
            raise ValueError(
                "SuSu native positions require explicit positions_joint_order="
                f"{SUSU_MTA63_JOINT_ORDER_ID!r}, got {joint_order!r}"
            )
        expected_dataset_profile = {
            SUSU_RETARGET_MAYA_PROFILE.name: "susu_retarget_maya_positions",
            SUSU_CHONGLU_PROFILE.name: "susu_chonglu",
        }.get(profile.name, "susu_official_columns_local")
        dataset_profile = clip.sample.metadata.get("dataset_profile")
        if dataset_profile != expected_dataset_profile:
            raise ValueError(
                "SuSu native positions dataset profile mismatch: expected "
                f"{expected_dataset_profile!r}, got {dataset_profile!r}"
            )
        return (values.astype(np.float32) * np.float32(profile.position_scale)).astype(
            np.float32
        )

    def _sixd_quats(self, values: np.ndarray, profile: SuSuProfile) -> np.ndarray:
        if profile.rotation_6d_layout == "first_two_columns":
            return sixd_to_quat_xyzw(values)
        if profile.rotation_6d_layout == "first_two_rows":
            return sixd_rows_to_quat_xyzw(values)
        raise ValueError(f"unsupported SuSu 6D layout: {profile.rotation_6d_layout}")

    def _decoded_rotations(
        self,
        clip: RawClip,
        profile: SuSuProfile,
    ) -> tuple[
        np.ndarray,
        dict[str, np.ndarray],
        dict[str, np.ndarray],
        dict[str, np.ndarray],
        dict[str, np.ndarray],
        dict[str, np.ndarray],
    ]:
        body = self._body_array(clip)
        frame_count = int(body.shape[0])
        body_quats = _susu_official_bvh_local_quats(
            self._sixd_quats(body[:, 3:].reshape(frame_count, 25, 6), profile),
            correct_pelvis=True,
        )
        body_globals: dict[str, np.ndarray] = {}
        if profile.rotation_space == "parent_local":
            root_rotation, body_locals = _susu_body_parent_local(body_quats)
        elif profile.rotation_space == "global":
            root_rotation, body_locals, body_globals = _susu_body_global_to_local(
                body_quats
            )
        else:
            raise ValueError(
                f"unsupported SuSu rotation space: {profile.rotation_space}"
            )

        hand_locals: dict[str, np.ndarray] = {}
        native_hand_quats: dict[str, np.ndarray] = {}
        for side in ("left", "right"):
            if side not in clip.motion:
                raise ValueError(f"SuSu {side} hand 6D channel is required")
            source_hand = np.asarray(clip.motion[side], dtype=np.float32)
            if source_hand.shape != (frame_count, 120):
                raise ValueError(
                    f"SuSu {side} hand motion must have exact shape (T,120), got {source_hand.shape}"
                )
            if not np.isfinite(source_hand).all():
                raise ValueError(
                    f"SuSu {side} hand motion must contain only finite values"
                )
            hand_values = source_hand.reshape(frame_count, 20, 6)
            hand_quats = _susu_official_bvh_local_quats(
                self._sixd_quats(hand_values, profile),
                correct_pelvis=False,
            )
            native_hand_quats[side] = hand_quats
            if profile.rotation_space == "parent_local":
                hand_locals.update(_susu_hand_parent_local(hand_quats, side))
            else:
                hand_locals.update(
                    _susu_hand_global_to_local(hand_quats, side, body_globals)
                )
        return (
            root_rotation,
            body_locals,
            hand_locals,
            body_globals,
            body_quats,
            native_hand_quats,
        )

    def _source_body_positions(self, positions: np.ndarray) -> np.ndarray:
        return positions[:, : min(len(SUSU_SOURCE_NAMES), positions.shape[1])].astype(
            np.float32
        )

    def _canonical_body_from_source_positions(
        self, positions: np.ndarray
    ) -> tuple[np.ndarray, list[str], list[tuple[int, int]]]:
        body_positions = self._source_body_positions(positions)
        mapped_names: list[str] = []
        mapped_positions: list[np.ndarray] = []
        seen: set[str] = set()
        for source_index, source_name in enumerate(
            SUSU_BODY_NAMES[: body_positions.shape[1]]
        ):
            canonical = SUSU_BODY_TO_CANONICAL.get(source_name)
            if canonical and canonical in FK_BONES and canonical not in seen:
                mapped_names.append(canonical)
                mapped_positions.append(body_positions[:, source_index])
                seen.add(canonical)
        if mapped_positions:
            canonical_positions = np.stack(mapped_positions, axis=1).astype(np.float32)
        else:
            mapped_names = ["hips"]
            canonical_positions = np.zeros((positions.shape[0], 1, 3), dtype=np.float32)
        canonical_positions = canonical_positions.copy()
        return (
            canonical_positions,
            mapped_names,
            _canonical_edges_for_names(mapped_names),
        )

    def _canonical_hand_from_source_positions(
        self, positions: np.ndarray
    ) -> dict[str, np.ndarray]:
        source = np.asarray(positions, dtype=np.float32)
        return {
            canonical: source[:, source_index].copy()
            for canonical, source_index in SUSU_POSITION_HAND_INDEX.items()
            if source_index < source.shape[1]
        }

    def _root_translation(
        self, body: np.ndarray, profile: SuSuProfile
    ) -> tuple[np.ndarray, float, str]:
        axes = list(profile.root_axes)
        root = body[:, axes].astype(np.float32)
        unit = "profile"
        scale = float(profile.root_translation_scale)
        if profile.name == SUSU_RETARGET_MAYA_PROFILE.name:
            # Retarget-maya files mix meter-like roots and centimeter FBX exports.
            # The values are absolute roots in the shipped data, not deltas.
            median_height = (
                float(np.nanmedian(np.abs(root[:, 1]))) if root.size else 0.0
            )
            max_abs = float(np.nanmax(np.abs(root))) if root.size else 0.0
            if median_height > 5.0 or max_abs > 20.0:
                scale = 0.01
                unit = "cm"
            else:
                scale = 1.0
                unit = "m"
        root = root * np.float32(scale)
        root = root - root[:1]
        return root.astype(np.float32), scale, unit

    def to_canonical(self, clip: RawClip) -> CanonicalResult:
        body = self._body_array(clip)
        profile = self._select_profile(clip, has_positions="positions" in clip.motion)
        available_positions = self._positions_from_available_data(clip, profile)
        if available_positions is None and profile.rotation_space != "parent_local":
            raise ValueError(
                "SuSu rotation-only MTA63 reconstruction requires verified "
                "parent-local 6D rotations"
            )
        root_translation, root_translation_effective_scale, root_translation_unit = (
            self._root_translation(body, profile)
        )
        if available_positions is not None:
            native_positions, native_names, native_edges = (
                self._canonical_body_from_source_positions(available_positions)
            )
            body_positions = body_positions_from_fk_positions(
                native_positions, native_names
            )
            hand_positions = self._canonical_hand_from_source_positions(
                available_positions
            )
            retarget = fit_positions_to_vrm(
                body_positions,
                world_basis=profile.position_world_basis,
                hand_positions_by_name=hand_positions,
            )
        else:
            (
                _root_rot,
                _local_body_quats,
                _local_hand_quats,
                _global_body_quats,
                native_body_quats,
                native_hand_quats,
            ) = self._decoded_rotations(clip, profile)
            source_positions, reconstructed_hands = _susu_mta63_fk(
                root_translation,
                native_body_quats,
                native_hand_quats,
            )
            native_positions, native_names, native_edges = (
                self._canonical_body_from_source_positions(source_positions)
            )
            reconstructed = body_positions_from_fk_positions(
                native_positions, native_names
            )
            retarget = fit_positions_to_vrm(
                reconstructed,
                world_basis=profile.rotation_world_basis,
                hand_positions_by_name=reconstructed_hands,
            )

        # SuSu publishes absolute local BVH rotations, not a calibrated
        # NormalizedLocalRotation stream.  Positions constrain swing and the
        # palm frame without pretending that an anatomical offset determines
        # axial twist.  A future source T-pose contract may add a verified twist
        # prior; until then the minimum-twist/identity leaf gauge is explicit.
        if available_positions is None:
            retarget["mode"] = "sentiavatar_mta63_position_fit"
            finger_retarget = "derived_63_joint_positions_minimum_twist"
        else:
            retarget["mode"] = (
                "position_fit_body_wrist_and_finger_swing_from_63_positions"
            )
            finger_retarget = "native_63_joint_positions_minimum_twist"
        return CanonicalResult(
            sequence=retarget["sequence"],
            positions=retarget["positions"],
            joint_names=FK_BONES,
            edges=FK_EDGES,
            metadata={
                "codec": clip.sample.codec_key,
                "source_profile": profile.name,
                "canonical_skeleton": CANONICAL_SKELETON_ID,
                "rotation_semantics": CANONICAL_ROTATION_SEMANTICS,
                "target_skeleton": "vrm1_humanoid",
                "root_translation": profile.root_translation_mode,
                "root_translation_scale": profile.root_translation_scale,
                "root_translation_effective_scale": root_translation_effective_scale,
                "root_translation_unit": root_translation_unit,
                "position_scale": profile.position_scale,
                "declared_world_basis": profile.position_world_basis
                if available_positions is not None
                else profile.rotation_world_basis,
                "source_positions_available": available_positions is not None,
                "positions_joint_order": (
                    SUSU_MTA63_JOINT_ORDER_ID
                    if available_positions is not None
                    else None
                ),
                "native_mapped_joint_names": native_names,
                "native_mapped_edges": native_edges,
                "retarget_mode": retarget["mode"],
                "retarget_scale": retarget["scale"],
                "world_basis": retarget.get("world_basis", {}),
                "root_rotation_semantics": "position_derived_not_direct_rotation",
                "rotation_6d_layout": profile.rotation_6d_layout,
                "rotation_space": profile.rotation_space,
                "rotation_export_transform": "sentiavatar_process_batch_data.local_bvh.v1",
                "source_geometry_template": SUSU_MTA63_SOURCE_GEOMETRY_ID,
                "source_geometry_template_sha256": SUSU_MTA63_SOURCE_TEMPLATE_SHA256,
                "source_geometry_table_sha256": SUSU_MTA63_GEOMETRY_TABLE_SHA256,
                "rotation_profile_status": profile.validation_status,
                "finger_retarget": finger_retarget,
                "finger_twist_observability": "unobservable_without_calibrated_source_tpose",
                "distal_leaf_orientation": "unobservable_without_fingertip_or_calibrated_source_tpose",
                "source_rotation_usage": (
                    "derived_positions_via_official_mta63_fk"
                    if available_positions is None
                    else "not_applied; native_positions_are_authoritative"
                ),
                "position_fit_twist_limit": True,
                "root_orientation_recovery": retarget.get("root_orientation_recovery"),
                "upper_chest_orientation_recovery": retarget.get(
                    "upper_chest_orientation_recovery"
                ),
                "rotation_observability": retarget.get("rotation_observability", {}),
                "hand_biomechanics": retarget.get("hand_biomechanics"),
            },
            retarget_source_positions=retarget.get(
                "source_positions_full",
                retarget.get("source_positions"),
            ),
            retarget_source_joint_names=(
                list(FK_BONES)
                if retarget.get("source_positions_full") is not None
                else list(BODY_BONES)
            ),
            hand_observation=HandObservationMetadata.position_directions(
                source=f"{profile.name}:susu63_joint_centres",
                fps=float(clip.motion.get("fps", clip.sample.fps or 20.0)),
                unobservable_policy="neutral",
            ),
        )

    def extract_source(self, clip: RawClip) -> SourceSnapshot:
        profile = self._select_profile(clip, has_positions="positions" in clip.motion)
        available_positions = self._positions_from_available_data(clip, profile)
        fps = float(clip.motion.get("fps", clip.sample.fps or 20.0))
        if available_positions is not None:
            native_positions, native_names, native_edges = (
                self._canonical_body_from_source_positions(available_positions)
            )
            body_pos = body_positions_from_fk_positions(native_positions, native_names)
            native_hands = self._canonical_hand_from_source_positions(
                available_positions
            )
            full_positions = np.zeros(
                (body_pos.shape[0], len(FK_BONES), 3),
                dtype=np.float32,
            )
            for body_name in BODY_BONES:
                full_positions[:, FK_BONES.index(body_name)] = body_pos[
                    :, BODY_INDEX[body_name]
                ]
            for hand_name, values in native_hands.items():
                full_positions[:, FK_BONES.index(hand_name)] = values
            normalized = source_positions_normalized(
                full_positions,
                FK_BONES,
                world_basis=profile.position_world_basis,
            )
            return SourceSnapshot(
                positions=normalized,
                joint_names=list(FK_BONES),
                edges=list(FK_EDGES),
                fps=fps,
                coordinate_system="world_normalized",
                metadata={
                    "codec": clip.sample.codec_key,
                    "source_profile": profile.name,
                    "position_scale": profile.position_scale,
                    "declared_world_basis": profile.position_world_basis,
                    "positions_joint_order": SUSU_MTA63_JOINT_ORDER_ID,
                },
            )
        body = self._body_array(clip)
        root_translation, _, unit = self._root_translation(body, profile)
        (
            _root_rotation,
            _body_locals,
            _hand_locals,
            _body_globals,
            native_body_quats,
            native_hand_quats,
        ) = self._decoded_rotations(clip, profile)
        source_positions, source_hand_positions = _susu_mta63_fk(
            root_translation,
            native_body_quats,
            native_hand_quats,
        )
        native_positions, native_names, _native_edges = (
            self._canonical_body_from_source_positions(source_positions)
        )
        body_positions = body_positions_from_fk_positions(
            native_positions, native_names
        )
        full_positions = np.zeros(
            (body_positions.shape[0], len(FK_BONES), 3),
            dtype=np.float32,
        )
        for body_name in BODY_BONES:
            full_positions[:, FK_BONES.index(body_name)] = body_positions[
                :, BODY_INDEX[body_name]
            ]
        for hand_name, values in source_hand_positions.items():
            full_positions[:, FK_BONES.index(hand_name)] = values
        positions = source_positions_normalized(
            full_positions,
            FK_BONES,
            world_basis=profile.rotation_world_basis,
        )
        names = list(FK_BONES)
        edges = list(FK_EDGES)
        return SourceSnapshot(
            positions=positions,
            joint_names=names,
            edges=edges,
            fps=fps,
            coordinate_system="world_normalized",
            metadata={
                "codec": clip.sample.codec_key,
                "source_profile": profile.name,
                "root_translation_unit": unit,
                "declared_world_basis": profile.rotation_world_basis,
                "rotation_6d_layout": profile.rotation_6d_layout,
                "rotation_space": profile.rotation_space,
                "rotation_profile_status": profile.validation_status,
                "rotation_export_transform": "sentiavatar_process_batch_data.local_bvh.v1",
                "source_geometry_template": SUSU_MTA63_SOURCE_GEOMETRY_ID,
                "source_geometry_template_sha256": SUSU_MTA63_SOURCE_TEMPLATE_SHA256,
                "source_geometry_table_sha256": SUSU_MTA63_GEOMETRY_TABLE_SHA256,
                "hand_source_geometry": "derived:SentiAvatar_6D_plus_MTA63_template_FK",
            },
        )


def default_codecs() -> dict[str, MotionCodec]:
    return {
        "axis_angle_body22": AxisAngleBody22Codec(),
        "smplh_body_hands": SMPLHBodyHandsCodec(),
        "beat_axis_angle_body22": AxisAngleBody22Codec(
            source_rest_offsets=DEFAULT_REST_OFFSETS,
            source_profile="beat_bvh_full75_body22_hands30",
            world_basis="identity_y_up",
            root_rotation_semantics="local_to_world",
        ),
        "smplx_fullpose": SMPLXFullposeCodec(),
        "position_sequence": PositionSequenceCodec(),
        "humanml3d_263d": HumanML3D263Codec(),
        "susu_6d_body_hands": SuSu6DCodec(),
        "susu_retarget_maya_6d_body_hands": SuSu6DCodec(SUSU_RETARGET_MAYA_PROFILE),
        "susu_chonglu_6d_body_hands_cm": SuSu6DCodec(SUSU_CHONGLU_PROFILE),
    }
