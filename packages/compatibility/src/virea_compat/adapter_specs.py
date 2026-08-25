from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping

import numpy as np
from virea_motion_ir import canonical211_to_motion_ir

from virea.motion.skeleton import FK_BONES, FK_EDGES, forward_kinematics_from_sequence
from virea.motion.snapshot import SourceSnapshot

from .model_adapters import (
    AdapterOutput,
    body22_positions_to_motion_ir,
    dart_smplx_primitives_to_motion_ir,
    humanml3d_263_denormalized_to_motion_ir,
    hy_motion_body22_to_motion_ir,
    interhuman_262_to_motion_ir,
    mardm_ric67_to_motion_ir,
    motionx_322_to_motion_ir,
    prism_smplh_body22_axis_angle69_to_motion_ir,
    susu_body_hands_to_motion_ir,
)

ShapeAxis = int | Literal["frames", "variable"]
ArtifactLoader = Callable[[Any], Path]
AdapterConverter = Callable[[Any, "AdapterConversionContext"], AdapterOutput]


@dataclass(frozen=True, slots=True)
class AdapterConversionContext:
    model_id: str
    upstream_revision: str
    fps: float
    motion_id: str


@dataclass(frozen=True, slots=True)
class NativeArtifactSpec:
    """One exact Worker artifact contract within an adapter family."""

    key: str
    names: tuple[str, ...]
    media_type: str
    storage: Literal["npy", "json"]
    dtype: str | None = None
    shape: tuple[ShapeAxis, ...] | None = None
    required: bool = True
    primary: bool = False
    json_required_keys: tuple[str, ...] = ()
    json_array_key: str | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.names or any(not name for name in self.names):
            raise ValueError("native artifact key and names must be non-empty")
        if len(set(self.names)) != len(self.names):
            raise ValueError(f"native artifact {self.key!r} repeats an accepted name")
        if self.storage == "npy" and (self.dtype is None or self.shape is None):
            raise ValueError(f"NPY artifact {self.key!r} needs dtype and shape")
        if self.storage == "json" and self.json_array_key is None:
            if self.dtype is not None or self.shape is not None:
                raise ValueError(
                    f"JSON sidecar {self.key!r} cannot declare array dtype/shape"
                )

    def _shape_matches(self, shape: tuple[int, ...], frame_count: int) -> bool:
        if self.shape is None or len(shape) != len(self.shape):
            return self.shape is None
        for expected, observed in zip(self.shape, shape, strict=True):
            if expected == "frames" and observed != frame_count:
                return False
            if expected == "variable" and observed < 1:
                return False
            if isinstance(expected, int) and observed != expected:
                return False
        return True

    def expected_shape(self, frame_count: int) -> tuple[int | str, ...] | None:
        if self.shape is None:
            return None
        return tuple(
            frame_count
            if axis == "frames"
            else "positive"
            if axis == "variable"
            else axis
            for axis in self.shape
        )

    def artifact_shape_matches(self, artifact: Any, frame_count: int) -> bool:
        if artifact.media_type != self.media_type or artifact.dtype != self.dtype:
            return False
        if self.shape is None:
            return artifact.shape is None
        return artifact.shape is not None and self._shape_matches(
            tuple(int(value) for value in artifact.shape), frame_count
        )

    def load(self, artifact: Any, path: Path, *, frame_count: int) -> Any:
        if artifact.name not in self.names:
            raise ValueError(
                f"{self.key} artifact name must be one of {self.names}, got {artifact.name!r}"
            )
        if artifact.media_type != self.media_type:
            raise ValueError(
                f"{self.key} artifact media_type must be {self.media_type}"
            )
        if self.storage == "npy":
            return self._load_npy(artifact, path, frame_count=frame_count)
        return self._load_json(artifact, path, frame_count=frame_count)

    def _load_npy(self, artifact: Any, path: Path, *, frame_count: int) -> np.ndarray:
        if path.suffix.lower() != ".npy":
            raise ValueError(f"{self.key} artifact must be a .npy file")
        values = np.load(path, allow_pickle=False)
        if not isinstance(values, np.ndarray):
            raise ValueError(f"{self.key} artifact must contain one ndarray")
        expected_dtype = np.dtype(self.dtype)
        if values.dtype != expected_dtype or artifact.dtype != expected_dtype.name:
            raise ValueError(f"{self.key} artifact dtype must be {expected_dtype.name}")
        if not self._shape_matches(values.shape, frame_count):
            raise ValueError(
                f"{self.key} artifact shape must be {self.expected_shape(frame_count)}"
            )
        if artifact.shape != values.shape:
            raise ValueError(f"{self.key} ArtifactRef shape does not match the file")
        if not np.isfinite(values).all():
            raise ValueError(f"{self.key} artifact contains NaN or infinity")
        return values

    def _load_json(self, artifact: Any, path: Path, *, frame_count: int) -> Any:
        if path.suffix.lower() != ".json":
            raise ValueError(f"{self.key} artifact must be a .json file")

        def reject_constant(value: str) -> None:
            raise ValueError(f"{self.key} JSON contains non-finite constant {value}")

        payload = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=reject_constant
        )
        if not isinstance(payload, dict):
            raise ValueError(f"{self.key} JSON sidecar must be an object")
        missing = [key for key in self.json_required_keys if key not in payload]
        if missing:
            raise ValueError(f"{self.key} JSON sidecar is missing keys: {missing}")
        if self.json_array_key is None:
            if artifact.dtype is not None or artifact.shape is not None:
                raise ValueError(
                    f"{self.key} JSON sidecar ArtifactRef must not declare dtype/shape"
                )
            return payload
        if self.json_array_key not in payload:
            raise ValueError(
                f"{self.key} JSON artifact is missing {self.json_array_key!r}"
            )
        try:
            values = np.asarray(
                payload[self.json_array_key], dtype=np.dtype(self.dtype)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{self.key} JSON array has invalid values") from exc
        if not self._shape_matches(values.shape, frame_count):
            raise ValueError(
                f"{self.key} JSON array shape must be {self.expected_shape(frame_count)}"
            )
        if artifact.dtype != self.dtype:
            raise ValueError(f"{self.key} artifact dtype must be {self.dtype}")
        if artifact.shape != values.shape:
            raise ValueError(f"{self.key} ArtifactRef shape does not match JSON")
        if not np.isfinite(values).all():
            raise ValueError(f"{self.key} artifact contains NaN or infinity")
        return payload


@dataclass(frozen=True, slots=True)
class LoadedNativeArtifacts:
    primary_path: Path
    values: Mapping[str, Any]
    payload: Any


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    family: str
    representation_id: str
    skeleton_id: str
    artifacts: tuple[NativeArtifactSpec, ...]
    converter: AdapterConverter
    payload_style: Literal["primary", "mapping"] = "mapping"
    exclusive_primary_shape: bool = False
    compatibility_only: bool = False

    def __post_init__(self) -> None:
        primaries = [artifact for artifact in self.artifacts if artifact.primary]
        if len(primaries) != 1:
            raise ValueError(
                f"adapter {self.family!r} must declare one primary artifact"
            )
        keys = [artifact.key for artifact in self.artifacts]
        if len(set(keys)) != len(keys):
            raise ValueError(f"adapter {self.family!r} repeats an artifact key")

    @property
    def primary_artifact(self) -> NativeArtifactSpec:
        return next(artifact for artifact in self.artifacts if artifact.primary)

    def validate_identity(self, native: Any) -> None:
        if (
            native.representation_id != self.representation_id
            or native.skeleton_id != self.skeleton_id
        ):
            raise ValueError(
                f"native identity does not match adapter {self.family!r}: "
                f"expected {self.representation_id}/{self.skeleton_id}"
            )

    def load_native(
        self,
        artifacts: tuple[Any, ...],
        *,
        frame_count: int,
        resolve_path: ArtifactLoader,
    ) -> LoadedNativeArtifacts:
        primary = self.primary_artifact
        if self.exclusive_primary_shape:
            candidates = [
                artifact
                for artifact in artifacts
                if primary.artifact_shape_matches(artifact, frame_count)
            ]
            if len(candidates) != 1:
                expected = primary.expected_shape(frame_count)
                raise ValueError(
                    "ModelResult must contain exactly one "
                    f"{primary.dtype} NPY artifact with shape {expected}, "
                    f"found {len(candidates)}"
                )

        loaded: dict[str, Any] = {}
        primary_path: Path | None = None
        for contract in self.artifacts:
            matches = [
                artifact for artifact in artifacts if artifact.name in contract.names
            ]
            if not matches and not contract.required:
                continue
            if len(matches) != 1:
                qualifier = "exactly one" if contract.required else "at most one"
                raise ValueError(
                    f"ModelResult must contain {qualifier} {contract.key!r} artifact"
                )
            artifact = matches[0]
            path = resolve_path(artifact)
            loaded[contract.key] = contract.load(
                artifact, path, frame_count=frame_count
            )
            if contract.primary:
                primary_path = path
        if primary_path is None:
            raise ValueError(
                f"adapter {self.family!r} did not load its primary artifact"
            )
        payload: Any = (
            loaded[primary.key] if self.payload_style == "primary" else loaded
        )
        return LoadedNativeArtifacts(
            primary_path=primary_path,
            values=MappingProxyType(loaded),
            payload=payload,
        )

    def convert(self, native: Any, context: AdapterConversionContext) -> AdapterOutput:
        return self.converter(native, context)


def _mapping(native: Any, *, primary_key: str) -> Mapping[str, Any]:
    if isinstance(native, Mapping):
        return native
    return {primary_key: native}


def _metadata(native: Mapping[str, Any]) -> Mapping[str, Any]:
    value = native.get("generation_metadata")
    if not isinstance(value, Mapping):
        raise ValueError("generation_metadata must be a JSON object")
    return value


def _required_text(metadata: Mapping[str, Any], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"generation_metadata.{key} must be non-empty text")
    return value


def _humanml_converter(native: Any, context: AdapterConversionContext) -> AdapterOutput:
    values = _mapping(native, primary_key="motion263")["motion263"]
    return humanml3d_263_denormalized_to_motion_ir(
        values,
        source_model_id=context.model_id,
        upstream_revision=context.upstream_revision,
        fps=context.fps,
        motion_id=context.motion_id,
    )


def _positions_converter(
    native: Any, context: AdapterConversionContext
) -> AdapterOutput:
    values = _mapping(native, primary_key="positions22")["positions22"]
    return body22_positions_to_motion_ir(
        values,
        source_model_id=context.model_id,
        upstream_revision=context.upstream_revision,
        fps=context.fps,
        motion_id=context.motion_id,
    )


def _mardm_converter(native: Any, context: AdapterConversionContext) -> AdapterOutput:
    values = _mapping(native, primary_key="source_mardm_ric67_normalized")
    return mardm_ric67_to_motion_ir(
        values["source_mardm_ric67_normalized"],
        mean=values["mardm_t2m_eval_mean"],
        std=values["mardm_t2m_eval_std"],
        checkpoint_id=(f"mardm-source-{context.upstream_revision[:8]}:t2m-eval-stats"),
        source_model_id=context.model_id,
        upstream_revision=context.upstream_revision,
        fps=context.fps,
        motion_id=context.motion_id,
    )


def _prism_converter(native: Any, context: AdapterConversionContext) -> AdapterOutput:
    values = _mapping(native, primary_key="prism_axis_angle69")
    return prism_smplh_body22_axis_angle69_to_motion_ir(
        values["prism_axis_angle69"],
        fps=context.fps,
        motion_id=context.motion_id,
        source_model_id=context.model_id,
        upstream_revision=context.upstream_revision,
    )


def _dart_converter(native: Any, context: AdapterConversionContext) -> AdapterOutput:
    values = _mapping(native, primary_key="dart_transl")
    metadata = _metadata(values)
    return dart_smplx_primitives_to_motion_ir(
        values["dart_transl"],
        values["dart_global_orient"],
        values["dart_body_pose"],
        values["dart_primitive_boundaries"],
        rollout_reconstructed=metadata.get("rollout_reconstructed") is True,
        overlap_continuity_verified=(
            metadata.get("overlap_continuity_verified") is True
        ),
        rollout_provenance=dict(metadata.get("rollout_provenance") or {}),
        text_segments=tuple(metadata.get("text_segments") or ()),
        fps=context.fps,
        motion_id=context.motion_id,
        betas=values.get("dart_betas"),
        gender=(
            str(metadata["gender"]) if metadata.get("gender") is not None else None
        ),
    )


def _hy_converter(native: Any, context: AdapterConversionContext) -> AdapterOutput:
    values = _mapping(native, primary_key="hy_translation_m")
    metadata = _metadata(values)
    return hy_motion_body22_to_motion_ir(
        values["hy_translation_m"],
        values["hy_rotations_6d"],
        values["hy_latent_denorm"],
        smoothing_applied=metadata.get("smoothing_applied") is True,
        ground_alignment_applied=metadata.get("ground_alignment_applied") is True,
        keypoints3d=values["hy_keypoints3d"],
        fps=context.fps,
        motion_id=context.motion_id,
    )


def _intermask_converter(
    native: Any, context: AdapterConversionContext
) -> AdapterOutput:
    values = _mapping(native, primary_key="intermask_motion262")
    metadata = _metadata(values)
    return interhuman_262_to_motion_ir(
        values["intermask_motion262"],
        shared_frame_transform=values["intermask_shared_frame_transform"],
        source_artifact_id=_required_text(metadata, "source_artifact_id"),
        fps=context.fps,
        motion_id=context.motion_id,
    )


def _motioncraft_converter(
    native: Any, context: AdapterConversionContext
) -> AdapterOutput:
    values = _mapping(native, primary_key="motioncraft_motion322")
    metadata = _metadata(values)
    return motionx_322_to_motion_ir(
        values["motioncraft_motion322"],
        mean=values["motioncraft_mean322"],
        std=values["motioncraft_std322"],
        checkpoint_id=_required_text(metadata, "checkpoint_id"),
        source_profile=_required_text(metadata, "source_profile"),
        fps=context.fps,
        motion_id=context.motion_id,
    )


def _sentiavatar_converter(
    native: Any, context: AdapterConversionContext
) -> AdapterOutput:
    values = _mapping(native, primary_key="sentiavatar_body153")
    metadata = _metadata(values)
    return susu_body_hands_to_motion_ir(
        values["sentiavatar_body153"],
        values["sentiavatar_left_hand120"],
        values["sentiavatar_right_hand120"],
        body_mean=values["sentiavatar_body_mean153"],
        body_std=values["sentiavatar_body_std153"],
        checkpoint_id=_required_text(metadata, "checkpoint_id"),
        hands_are_denormalized=(metadata.get("hands_are_denormalized") is True),
        fps=context.fps,
        face_arkit51=values.get("sentiavatar_face_arkit51"),
        motion_id=context.motion_id,
    )


def _fake_converter(native: Any, context: AdapterConversionContext) -> AdapterOutput:
    payload = native
    if isinstance(native, Mapping) and "fake_motion" in native:
        payload = native["fake_motion"]
    if not isinstance(payload, Mapping):
        raise ValueError("fake motion artifact must be a JSON object")
    root_translation = np.asarray(payload["root_translation_m"], dtype=np.float32)
    frame_count = int(root_translation.shape[0])
    rotations = np.zeros((frame_count, 52, 4), dtype=np.float32)
    rotations[..., 3] = 1.0
    canonical = np.concatenate(
        (root_translation, rotations.reshape(frame_count, -1)), axis=1
    ).astype(np.float32)
    motion = canonical211_to_motion_ir(
        canonical,
        fps=context.fps,
        motion_id=context.motion_id,
        provenance={
            "model_result_schema": "virea.model_result.v1.0.0",
            "model_id": context.model_id,
            "upstream_revision": context.upstream_revision,
            "compatibility_only": True,
        },
    )
    return AdapterOutput(
        motion_ir=motion,
        canonical211=canonical,
        metadata=motion.provenance,
        native_artifacts={"root_translation_m": root_translation.copy()},
        source_snapshot=SourceSnapshot(
            positions=forward_kinematics_from_sequence(canonical),
            joint_names=list(FK_BONES),
            edges=list(FK_EDGES),
            fps=context.fps,
            coordinate_system="world_normalized",
            metadata={"compatibility_only": True},
        ),
    )


def _npy(
    key: str,
    name: str | tuple[str, ...],
    shape: tuple[ShapeAxis, ...],
    *,
    dtype: str = "float32",
    required: bool = True,
    primary: bool = False,
) -> NativeArtifactSpec:
    names = (name,) if isinstance(name, str) else name
    return NativeArtifactSpec(
        key=key,
        names=names,
        media_type="application/x-npy",
        storage="npy",
        dtype=dtype,
        shape=shape,
        required=required,
        primary=primary,
    )


def _json_sidecar(
    *,
    required: bool,
    required_keys: tuple[str, ...] = (),
) -> NativeArtifactSpec:
    return NativeArtifactSpec(
        key="generation_metadata",
        names=("generation_metadata",),
        media_type="application/json",
        storage="json",
        required=required,
        json_required_keys=required_keys,
    )


_SPECS = {
    "humanml3d-motion263-body22": AdapterSpec(
        family="humanml3d-motion263-body22",
        representation_id="humanml3d.vector263.v1",
        skeleton_id="humanml3d.body22.v1",
        artifacts=(
            _npy(
                "motion263",
                (
                    "source_humanml3d_263d",
                    "source_humanml3d_vector263",
                    "source_cmdm_vector263_denormalized",
                    "native_momadiff_humanml3d_vector263",
                    "source_discord_humanml3d_vector263",
                    "source_momask_humanml3d_vector263",
                    "source_remomask_humanml3d_vector263",
                ),
                ("frames", 263),
                primary=True,
            ),
            _json_sidecar(required=False),
        ),
        converter=_humanml_converter,
        payload_style="primary",
        exclusive_primary_shape=True,
    ),
    "joint-positions-body22": AdapterSpec(
        family="joint-positions-body22",
        representation_id="humanml3d.body22.positions.v1",
        skeleton_id="humanml3d.body22.v1",
        artifacts=(
            _npy(
                "positions22",
                "source_acmdm_absolute_positions22",
                ("frames", 22, 3),
                primary=True,
            ),
            _json_sidecar(required=False),
        ),
        converter=_positions_converter,
        payload_style="primary",
        exclusive_primary_shape=True,
    ),
    "mardm-ric67-body22": AdapterSpec(
        family="mardm-ric67-body22",
        representation_id="mardm.humanml3d.ric67.v1",
        skeleton_id="humanml3d.body22.v1",
        artifacts=(
            _npy(
                "source_mardm_ric67_normalized",
                "source_mardm_ric67_normalized",
                ("frames", 67),
                primary=True,
            ),
            _npy("mardm_t2m_eval_mean", "mardm_t2m_eval_mean", (67,)),
            _npy("mardm_t2m_eval_std", "mardm_t2m_eval_std", (67,)),
            _json_sidecar(required=False),
        ),
        converter=_mardm_converter,
    ),
    "prism-smplh-body22-axis-angle69": AdapterSpec(
        family="prism-smplh-body22-axis-angle69",
        representation_id="prism.smplh_body22.axis_angle69.v1",
        skeleton_id="smplh.body22.v1",
        artifacts=(
            _npy(
                "prism_axis_angle69",
                "source_prism_smplh_body22_axis_angle69",
                ("frames", 69),
                primary=True,
            ),
            _json_sidecar(required=False),
        ),
        converter=_prism_converter,
        payload_style="primary",
    ),
    "dart-smplx-primitives": AdapterSpec(
        family="dart-smplx-primitives",
        representation_id="dart.smplx.body22.axis_angle_primitives.v1",
        skeleton_id="smplx.body22.v1",
        artifacts=(
            _npy("dart_transl", "source_dart_transl", ("frames", 3), primary=True),
            _npy(
                "dart_global_orient",
                "source_dart_global_orient",
                ("frames", 3),
            ),
            _npy("dart_body_pose", "source_dart_body_pose", ("frames", 63)),
            _npy(
                "dart_primitive_boundaries",
                "source_dart_primitive_boundaries",
                ("variable", 2),
                dtype="int64",
            ),
            _npy(
                "dart_betas",
                "source_dart_betas",
                (10,),
                required=False,
            ),
            _json_sidecar(
                required=True,
                required_keys=(
                    "rollout_reconstructed",
                    "overlap_continuity_verified",
                    "rollout_provenance",
                    "text_segments",
                ),
            ),
        ),
        converter=_dart_converter,
    ),
    "hy-motion-body22": AdapterSpec(
        family="hy-motion-body22",
        representation_id="hy_motion.body22.rot6d_translation.v1",
        skeleton_id="hy_motion.wooden_body22.v1",
        artifacts=(
            _npy(
                "hy_translation_m",
                "source_hy_translation_m",
                ("frames", 3),
                primary=True,
            ),
            _npy(
                "hy_rotations_6d",
                "source_hy_rotations_6d",
                ("frames", 22, 6),
            ),
            _npy(
                "hy_latent_denorm",
                "source_hy_latent_denorm",
                ("frames", 201),
            ),
            _npy(
                "hy_keypoints3d",
                "source_hy_keypoints3d",
                ("frames", 22, 3),
            ),
            _json_sidecar(
                required=True,
                required_keys=("smoothing_applied", "ground_alignment_applied"),
            ),
        ),
        converter=_hy_converter,
    ),
    "intermask-interhuman-two-actor": AdapterSpec(
        family="intermask-interhuman-two-actor",
        representation_id="interhuman.motion262.v1",
        skeleton_id="interhuman.two_actor_smpl22.v1",
        artifacts=(
            _npy(
                "intermask_motion262",
                "source_intermask_motion262",
                (2, "frames", 262),
                primary=True,
            ),
            _npy(
                "intermask_shared_frame_transform",
                "source_intermask_shared_frame_transform",
                (4, 4),
            ),
            _json_sidecar(
                required=True,
                required_keys=("source_artifact_id",),
            ),
        ),
        converter=_intermask_converter,
    ),
    "motioncraft-smplx322": AdapterSpec(
        family="motioncraft-smplx322",
        representation_id="motionx.smplx322.v1",
        skeleton_id="motionx.smplx53.v1",
        artifacts=(
            _npy(
                "motioncraft_motion322",
                "source_motioncraft_motionx322_normalized",
                ("frames", 322),
                primary=True,
            ),
            _npy(
                "motioncraft_mean322",
                "source_motioncraft_motionx_mean322",
                (322,),
            ),
            _npy(
                "motioncraft_std322",
                "source_motioncraft_motionx_std322",
                (322,),
            ),
            _json_sidecar(
                required=True,
                required_keys=("checkpoint_id", "source_profile"),
            ),
        ),
        converter=_motioncraft_converter,
    ),
    "sentiavatar-susu-mta63": AdapterSpec(
        family="sentiavatar-susu-mta63",
        representation_id="susu.body25_hands40.cont6d_root_delta.v1",
        skeleton_id="susu.body25_hands40.v1",
        artifacts=(
            _npy(
                "sentiavatar_body153",
                "source_sentiavatar_body153_normalized",
                ("frames", 153),
                primary=True,
            ),
            _npy(
                "sentiavatar_left_hand120",
                "source_sentiavatar_left_hand120_denormalized",
                ("frames", 120),
            ),
            _npy(
                "sentiavatar_right_hand120",
                "source_sentiavatar_right_hand120_denormalized",
                ("frames", 120),
            ),
            _npy(
                "sentiavatar_body_mean153",
                "source_sentiavatar_body_mean153",
                (153,),
            ),
            _npy(
                "sentiavatar_body_std153",
                "source_sentiavatar_body_std153",
                (153,),
            ),
            _npy(
                "sentiavatar_face_arkit51",
                "source_sentiavatar_face_arkit51",
                ("frames", 51),
                required=False,
            ),
            _json_sidecar(
                required=True,
                required_keys=("checkpoint_id", "hands_are_denormalized"),
            ),
        ),
        converter=_sentiavatar_converter,
    ),
    "fake-root-translation": AdapterSpec(
        family="fake-root-translation",
        representation_id="virea.fake.root_translation.v1",
        skeleton_id="vrm1.humanoid52.v1",
        artifacts=(
            NativeArtifactSpec(
                key="fake_motion",
                names=("motion",),
                media_type="application/json",
                storage="json",
                dtype="float32",
                shape=("frames", 3),
                primary=True,
                json_required_keys=("root_translation_m",),
                json_array_key="root_translation_m",
            ),
        ),
        converter=_fake_converter,
        payload_style="primary",
        compatibility_only=True,
    ),
}

_SPEC_VIEW: Mapping[str, AdapterSpec] = MappingProxyType(_SPECS)


def adapter_specs() -> Mapping[str, AdapterSpec]:
    return _SPEC_VIEW


def adapter_spec_for_family(family: str) -> AdapterSpec:
    try:
        return _SPECS[family]
    except KeyError as exc:
        raise KeyError(f"no native artifact contract for {family!r}") from exc


def real_adapter_families() -> frozenset[str]:
    return frozenset(
        family for family, spec in _SPECS.items() if not spec.compatibility_only
    )
