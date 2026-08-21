from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from virea.data.annotations import (
    json_value,
    materialize_sidecars,
    normalize_annotations,
    normalize_channels,
    security_manifest,
)
from virea.data.profiles import (
    DatasetProfile,
    profile_for_sample,
    profile_key_for_source,
)
from virea.data.registry import DatasetRegistry
from virea.data.types import RawClip
from virea.motion.canonical import (
    CANONICAL_ROTATION_SEMANTICS,
    CANONICAL_SCHEMA_VERSION,
    CANONICAL_SKELETON_ID,
    CORE_BONES,
    HAND_BONES,
    ROOT_DIM,
    unpack_sequence,
)
from virea.motion.codecs import CanonicalResult, MotionCodec, default_codecs
from virea.motion.continuity import analyze_canonical_continuity, continuity_warning
from virea.motion.hand_solver import (
    HAND_CONSTRAINT_POLICY_ID,
    HandObservationMetadata,
    solve_hand_constraints,
)
from virea.motion.quality import constraint_retarget_quality
from virea.motion.skeleton import (
    CANONICAL_REST_ID,
    DEFAULT_REST_OFFSETS,
    FK_BONES,
    forward_kinematics_from_sequence,
)
from virea.motion.snapshot import SourceSnapshot
from virea.pipelines.artifact_manifest import (
    CANONICAL_ARTIFACT_SCHEMA_VERSION,
    CANONICAL_PROCESSING_VERSION,
    MOTION_SAMPLE_SCHEMA_VERSION,
    build_hand_retarget_record,
    build_manifest,
    canonical_json_bytes,
    hand_evidence_mode_from_observation,
    hand_observation_from_report,
    json_document_descriptor,
    load_npz_arrays,
    serialize_hand_position_evidence,
    verify_hand_retarget_replay,
    verify_json_document_descriptor,
    verify_manifest,
)
from virea.pipelines.artifacts import artifact_paths, legacy_vrm_motion_path, motion_uid


@dataclass
class ProcessingOutput:
    clip: RawClip
    source: SourceSnapshot
    canonical: CanonicalResult
    quality: dict[str, Any]
    motion_uid: str
    paths: dict[str, str]


class ProcessingPipeline:
    """Pure data processing: load, extract source, convert, assess, persist. No preview payloads."""

    def __init__(
        self, registry: DatasetRegistry, codecs: dict[str, MotionCodec] | None = None
    ) -> None:
        self.registry = registry
        self.codecs = codecs or default_codecs()

    @staticmethod
    def _hand_evidence_mode(observation: HandObservationMetadata) -> str:
        if observation.swing_basis == "palm_joint_geometry":
            return "joint_positions"
        states = [
            state
            for bone in HAND_BONES
            for state in observation.per_bone[bone].as_dict().values()
        ]
        if all(state == "unobservable" for state in states):
            if observation.unobservable_policy != "neutral":
                raise ValueError(
                    "identity-neutral hand evidence requires the explicit neutral policy"
                )
            return "identity_neutral"
        return "parent_local_rotations"

    @staticmethod
    def _position_hand_evidence(
        canonical: CanonicalResult,
        *,
        frame_count: int,
    ) -> dict[str, np.ndarray]:
        positions = canonical.retarget_source_positions
        names = canonical.retarget_source_joint_names
        if positions is None or names is None:
            raise ValueError(
                "joint-position hand evidence requires named source joint centres"
            )
        values = np.asarray(positions, dtype=np.float32)
        if values.ndim != 3 or values.shape != (frame_count, len(names), 3):
            raise ValueError(
                "joint-position hand evidence shape/name mismatch: "
                f"positions={values.shape}, names={len(names)}, frames={frame_count}"
            )
        if not np.all(np.isfinite(values)):
            raise ValueError("joint-position hand evidence must be finite")
        if len(set(names)) != len(names):
            raise ValueError(
                "joint-position hand evidence contains duplicate joint names"
            )
        index = {name: idx for idx, name in enumerate(names)}
        required = ["leftHand", "rightHand", *HAND_BONES]
        missing = [name for name in required if name not in index]
        if missing:
            raise ValueError(
                "joint-position hand evidence is incomplete; missing "
                + ", ".join(missing)
            )
        return {
            name: np.asarray(values[:, index[name]], dtype=np.float32).copy()
            for name in required
        }

    _PASSTHROUGH_UNIT_CODECS = frozenset(
        {
            "axis_angle_body22",
            "smplh_body_hands",
            "beat_axis_angle_body22",
            "smplx_fullpose",
            "position_sequence",
            "humanml3d_263d",
        }
    )
    _IDENTITY_ROOT_AXES_CODECS = _PASSTHROUGH_UNIT_CODECS
    _ROTATION_SPACE_BY_CODEC = {
        "axis_angle_body22": "parent_local",
        "smplh_body_hands": "parent_local",
        "beat_axis_angle_body22": "parent_local",
        "smplx_fullpose": "parent_local",
        "position_sequence": "position_fitting",
        "humanml3d_263d": "position_recovery",
    }

    @staticmethod
    def _selected_structured_codec_profile(
        codec: MotionCodec | None, clip: RawClip
    ) -> Any | None:
        """Return the exact runtime profile selected by structured codecs.

        SuSu's generic codec performs selection at runtime.  Observing that
        selected immutable profile here prevents a dataset profile from
        claiming different root axes/layout/space after conversion.
        """
        if codec is None:
            return None
        selected = getattr(codec, "profile", None)
        selector = getattr(codec, "_select_profile", None)
        if (
            selected is None
            and callable(selector)
            and clip.sample.codec_key.startswith("susu")
        ):
            selected = selector(clip, has_positions="positions" in clip.motion)
        required = (
            "name",
            "root_axes",
            "rotation_6d_layout",
            "rotation_space",
            "position_world_basis",
            "rotation_world_basis",
        )
        return (
            selected
            if selected is not None and all(hasattr(selected, key) for key in required)
            else None
        )

    def _observe_codec_runtime(
        self,
        clip: RawClip,
        result: CanonicalResult,
        codec: MotionCodec | None = None,
    ) -> dict[str, Any]:
        """Normalize facts observed from the executed codec, never from the declared dataset profile."""
        metadata = dict(result.metadata or {})
        embedded = metadata.get("codec_runtime")
        observation = (
            dict(embedded) if codec is None and isinstance(embedded, dict) else {}
        )
        source_metadata = clip.motion.get("source_metadata")
        source_metadata = (
            dict(source_metadata) if isinstance(source_metadata, dict) else {}
        )
        selected = self._selected_structured_codec_profile(codec, clip)

        observation.update(
            {
                "schema_version": "virea.codec_runtime_observation.v1.0.0",
                "codec_key": clip.sample.codec_key,
                "source_profile": metadata.get("source_profile"),
                "world_basis": metadata.get("declared_world_basis"),
                "rotation_6d_layout": metadata.get("rotation_6d_layout"),
                "rotation_space": metadata.get("rotation_space"),
                "root_rotation_semantics": metadata.get("root_rotation_semantics"),
            }
        )
        if selected is not None:
            observation.update(
                {
                    "selected_source_profile": str(selected.name),
                    "root_axes": [int(value) for value in selected.root_axes],
                    "rotation_6d_layout": str(selected.rotation_6d_layout),
                    "rotation_space": str(selected.rotation_space),
                }
            )
            has_positions = bool(metadata.get("source_positions_available"))
            if has_positions:
                observation["unit_scale_to_meter"] = float(selected.position_scale)
                observation["unit_observation"] = (
                    "selected_codec_profile.position_scale"
                )
            else:
                effective_scale = metadata.get("root_translation_effective_scale")
                observation["unit_scale_to_meter"] = float(
                    effective_scale
                    if effective_scale is not None
                    else selected.root_translation_scale
                )
                observation["unit_observation"] = (
                    "codec_result.root_translation_effective_scale"
                )
            if observation.get("root_rotation_semantics") is None:
                # The executed SuSu path first decodes a source root rotation
                # and calls direct local-quaternion retarget with this semantic,
                # even though final body rotations are position-fitted.
                observation["root_rotation_semantics"] = "local_to_world"
                observation["root_semantics_observation"] = (
                    "susu_direct_local_quaternion_path"
                )

        if observation.get("unit_scale_to_meter") is None:
            explicit_unit = metadata.get("unit_scale_to_meter")
            if explicit_unit is None:
                explicit_unit = source_metadata.get(
                    "translation_scale", metadata.get("translation_scale")
                )
            if explicit_unit is not None:
                observation["unit_scale_to_meter"] = float(explicit_unit)
                observation["unit_observation"] = "codec_or_source_metadata"
            elif clip.sample.codec_key in self._PASSTHROUGH_UNIT_CODECS:
                observation["unit_scale_to_meter"] = 1.0
                observation["unit_observation"] = "codec_passthrough_contract"

        if observation.get("root_axes") is None:
            explicit_axes = metadata.get("root_axes")
            if explicit_axes is not None:
                observation["root_axes"] = [int(value) for value in explicit_axes]
            elif clip.sample.codec_key in self._IDENTITY_ROOT_AXES_CODECS:
                observation["root_axes"] = [0, 1, 2]

        if observation.get("rotation_space") is None:
            observation["rotation_space"] = self._ROTATION_SPACE_BY_CODEC.get(
                clip.sample.codec_key
            )
        if observation.get(
            "root_rotation_semantics"
        ) is None and clip.sample.codec_key in {
            "position_sequence",
            "humanml3d_263d",
        }:
            observation["root_rotation_semantics"] = "not_applicable"
        return json_value(observation)

    @staticmethod
    def _runtime_profile_errors(
        profile: DatasetProfile, runtime: dict[str, Any]
    ) -> list[str]:
        errors: list[str] = []
        actual_source_profile = runtime.get("source_profile")
        if actual_source_profile not in profile.codec_source_profiles:
            errors.append(
                "source_profile expected one of "
                f"{list(profile.codec_source_profiles)!r}, observed {actual_source_profile!r}"
            )
        selected_source_profile = runtime.get("selected_source_profile")
        if (
            selected_source_profile is not None
            and selected_source_profile != actual_source_profile
        ):
            errors.append(
                f"selected_source_profile={selected_source_profile!r} disagrees with codec metadata "
                f"source_profile={actual_source_profile!r}"
            )
        checks = {
            "world_basis": profile.world_basis,
            "root_axes": list(profile.root_axes),
            "rotation_space": profile.rotation_space,
            "root_rotation_semantics": profile.root_rotation_semantics,
        }
        if profile.rotation_6d_layout is not None:
            checks["rotation_6d_layout"] = profile.rotation_6d_layout
        for field_name, expected in checks.items():
            actual = runtime.get(field_name)
            if actual != expected:
                errors.append(
                    f"{field_name} expected {expected!r}, observed {actual!r}"
                )
        actual_unit = runtime.get("unit_scale_to_meter")
        try:
            unit_matches = actual_unit is not None and np.isclose(
                float(actual_unit),
                float(profile.unit_scale_to_meter),
                atol=1e-8,
                rtol=0.0,
            )
        except (TypeError, ValueError):
            unit_matches = False
        if not unit_matches:
            errors.append(
                f"unit_scale_to_meter expected {profile.unit_scale_to_meter!r}, observed {actual_unit!r}"
            )
        return errors

    def process_clip(self, clip: RawClip) -> tuple[SourceSnapshot, CanonicalResult]:
        codec = self.codecs[clip.sample.codec_key]
        source = codec.extract_source(clip)
        canonical = codec.to_canonical(clip)
        explicit_profile = profile_key_for_source(
            clip.sample.dataset,
            clip.sample.codec_key,
            clip.sample.sample_id,
            clip.sample.metadata,
        )
        profile = profile_for_sample(
            clip.sample.dataset, clip.sample.sample_id, explicit_key=explicit_profile
        )
        clip.sample.metadata["dataset_profile"] = profile.key
        source.metadata = {
            **dict(source.metadata or {}),
            "dataset_profile": profile.key,
        }
        runtime = self._observe_codec_runtime(clip, canonical, codec)
        contract_errors = self._runtime_profile_errors(profile, runtime)
        canonical.metadata = {
            **dict(canonical.metadata),
            "dataset_profile": profile.key,
            "profile_status": profile.validation_status,
            "codec_runtime": runtime,
            "profile_contract": {
                "status": "mismatch" if contract_errors else "matched",
                "errors": contract_errors,
            },
        }
        if contract_errors:
            clip.validation_warnings = list(
                dict.fromkeys(
                    [
                        *clip.validation_warnings,
                        f"Dataset profile {profile.key} does not match executed codec runtime: "
                        + "; ".join(contract_errors),
                    ]
                )
            )
        if profile.validation_status == "draft":
            clip.validation_warnings = list(
                dict.fromkeys(
                    [
                        *clip.validation_warnings,
                        f"Dataset profile {profile.key} is draft; release-grade spatial verification is unavailable.",
                    ]
                )
            )
        fps = float(clip.motion.get("fps", clip.sample.fps or 30.0))
        pre_solver_continuity = analyze_canonical_continuity(
            canonical.sequence,
            fps=fps,
            positions=canonical.positions,
            joint_names=canonical.joint_names[: canonical.positions.shape[1]],
            profile_key=profile.key,
        )
        if canonical.hand_observation is None:
            raise ValueError(
                "canonical codec omitted the required dataset-neutral hand observation contract"
            )
        if profile.hand_solver_applicability != "required":
            raise ValueError(
                "every current canonical output requires the unified hand solver; "
                f"profile {profile.key} declared {profile.hand_solver_applicability!r}"
            )
        if profile.hand_constraint_policy_id != HAND_CONSTRAINT_POLICY_ID:
            raise ValueError(
                f"profile {profile.key} hand policy {profile.hand_constraint_policy_id!r} "
                f"does not match runtime {HAND_CONSTRAINT_POLICY_ID!r}"
            )
        codec_hand_observation = canonical.hand_observation
        codec_hand_mode = self._hand_evidence_mode(codec_hand_observation)
        if profile.hand_evidence_mode == "identity_neutral":
            canonical.hand_observation = HandObservationMetadata.identity_only(
                source=(
                    f"dataset_profile:{profile.key}:verified_hand_channel_absent_or_"
                    "uncalibrated_static_prior"
                ),
                fps=fps,
            )
        elif profile.hand_evidence_mode == "joint_positions":
            canonical.hand_observation = HandObservationMetadata.position_directions(
                source=f"dataset_profile:{profile.key}:named_joint_centres",
                fps=fps,
                unobservable_policy=profile.hand_unobservable_policy,
            )
        elif codec_hand_mode != "parent_local_rotations":
            raise ValueError(
                f"profile {profile.key} requires calibrated parent-local hand rotations, "
                f"codec produced {codec_hand_mode!r}"
            )
        observed_hand_mode = self._hand_evidence_mode(canonical.hand_observation)
        if observed_hand_mode != profile.hand_evidence_mode:
            raise ValueError(
                f"profile {profile.key} expects hand evidence {profile.hand_evidence_mode!r}, "
                f"resolved runtime produced {observed_hand_mode!r}"
            )
        if not np.isclose(canonical.hand_observation.fps, fps, rtol=0.0, atol=1e-6):
            raise ValueError(
                "hand observation FPS does not match the effective motion FPS: "
                f"{canonical.hand_observation.fps!r} != {fps!r}"
            )
        continuity_segments = [
            (int(segment["start_frame"]), int(segment["end_frame"]))
            for segment in pre_solver_continuity.get("segments", [])
        ]
        unpacked = unpack_sequence(canonical.sequence)
        pre_solver_hands = np.asarray(
            unpacked["hand_quats_xyzw"],
            dtype=np.float32,
        ).copy()
        hand_position_evidence = (
            self._position_hand_evidence(
                canonical,
                frame_count=pre_solver_hands.shape[0],
            )
            if observed_hand_mode == "joint_positions"
            else None
        )
        solved_hands = solve_hand_constraints(
            pre_solver_hands,
            continuity_segments=continuity_segments,
            observation=canonical.hand_observation,
            position_evidence=hand_position_evidence,
        )
        hand_start = ROOT_DIM + len(CORE_BONES) * 4
        constrained_sequence = np.asarray(canonical.sequence, dtype=np.float32).copy()
        constrained_sequence[:, hand_start:] = solved_hands.quats_xyzw.reshape(
            constrained_sequence.shape[0],
            -1,
        )
        if not np.array_equal(
            constrained_sequence[:, :hand_start],
            np.asarray(canonical.sequence, dtype=np.float32)[:, :hand_start],
        ):
            raise ValueError("hand solver modified root or core canonical motion")
        canonical.sequence = constrained_sequence
        canonical.positions = forward_kinematics_from_sequence(constrained_sequence)
        canonical.joint_names = list(FK_BONES)
        canonical.hand_position_evidence = hand_position_evidence
        canonical.pre_solver_hand_quaternions = pre_solver_hands
        canonical.metadata = {
            **dict(canonical.metadata),
            "hand_retarget": solved_hands.report,
            "hand_evidence_resolution": {
                "profile_mode": profile.hand_evidence_mode,
                "codec_declared_mode": codec_hand_mode,
                "resolved_mode": observed_hand_mode,
                "profile_solver_validation_status": (
                    profile.hand_solver_validation_status
                ),
                "policy_id": profile.hand_constraint_policy_id,
            },
            "pre_solver_continuity": pre_solver_continuity,
        }
        continuity = analyze_canonical_continuity(
            canonical.sequence,
            fps=fps,
            positions=canonical.positions,
            joint_names=canonical.joint_names[: canonical.positions.shape[1]],
            profile_key=profile.key,
        )
        canonical.metadata = {
            **dict(canonical.metadata),
            "continuity": continuity,
        }
        warning = continuity_warning(continuity)
        if warning is not None:
            clip.validation_warnings = list(
                dict.fromkeys(
                    [
                        *clip.validation_warnings,
                        warning,
                    ]
                )
            )
        return source, canonical

    def process(
        self, dataset: str, sample_id: str, max_frames: int | None = None
    ) -> ProcessingOutput:
        adapter = self.registry.adapter(dataset)
        clip = adapter.load(sample_id, max_frames=max_frames)
        source, canonical = self.process_clip(clip)
        uid = motion_uid(dataset, sample_id, int(canonical.positions.shape[0]))
        fps = float(clip.motion.get("fps", clip.sample.fps or 30.0))
        quality, _quality_source_positions, _quality_source_joint_names = (
            self._quality_contract(source, canonical, fps)
        )
        return ProcessingOutput(
            clip=clip,
            source=source,
            canonical=canonical,
            quality=quality,
            motion_uid=uid,
            paths={},
        )

    @staticmethod
    def _quality_contract(
        source: SourceSnapshot,
        canonical: CanonicalResult,
        fps: float,
    ) -> tuple[dict[str, Any], np.ndarray | None, list[str] | None]:
        retarget_source = canonical.retarget_source_positions
        if (
            retarget_source is not None
            and retarget_source.shape[0] == canonical.positions.shape[0]
        ):
            source_positions = np.asarray(retarget_source, dtype=np.float32)
            source_joint_names = canonical.retarget_source_joint_names
            if (
                source_joint_names is None
                or len(source_joint_names) != source_positions.shape[1]
            ):
                raise ValueError(
                    "canonical retarget source positions require an exact joint-name contract"
                )
            source_joint_names = list(source_joint_names)
        elif source.positions.shape[0] == canonical.positions.shape[0]:
            source_positions = np.asarray(source.positions, dtype=np.float32)
            source_joint_names = list(source.joint_names)
        else:
            source_positions = None
            source_joint_names = None

        pre_solver_hands = canonical.pre_solver_hand_quaternions
        if pre_solver_hands is None:
            raise ValueError(
                "canonical result is missing pre-solver hand quaternions required "
                "by the constrained-hand quality contract"
            )
        retarget_mode = str(
            canonical.metadata.get("retarget_mode")
            or canonical.metadata.get("position_to_rotation")
            or ""
        )
        solver_report = canonical.metadata.get("hand_retarget")
        if not isinstance(solver_report, dict):
            raise ValueError("canonical result is missing the hand solver report")
        quality = constraint_retarget_quality(
            np.asarray(canonical.sequence, dtype=np.float32),
            canonical.positions,
            np.asarray(pre_solver_hands),
            solver_report,
            joint_names=canonical.joint_names[: canonical.positions.shape[1]],
            source_positions=source_positions,
            source_joint_names=source_joint_names,
            fps=fps,
            retarget_mode=retarget_mode,
            continuity=(
                canonical.metadata.get("continuity")
                if isinstance(canonical.metadata.get("continuity"), dict)
                else None
            ),
        )
        return json_value(quality), source_positions, source_joint_names

    @staticmethod
    def _file_sha256(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _portable_locator(
        self, path: Path, *, dataset: str, sample_id: str, role: str
    ) -> str:
        value = Path(path)
        if not value.is_absolute():
            return value.as_posix()
        raw_root = getattr(self.registry.paths, "raw_root", None)
        if raw_root is not None:
            try:
                return f"raw/{value.resolve().relative_to(Path(raw_root).resolve()).as_posix()}"
            except ValueError:
                pass
        suffix = value.suffix
        return f"sample/{dataset}/{sample_id}/{role}{suffix}"

    def _source_fingerprint(self, clip: RawClip) -> dict[str, Any]:
        path = Path(clip.sample.source_path)
        fingerprint: dict[str, Any] = {
            "locator": self._portable_locator(
                path,
                dataset=clip.sample.dataset,
                sample_id=clip.sample.sample_id,
                role="source",
            ),
            "sha256": None,
            "byte_length": None,
        }
        if path.is_file():
            fingerprint["sha256"] = self._file_sha256(path)
            fingerprint["byte_length"] = path.stat().st_size
        return fingerprint

    @staticmethod
    def _source_time_contract_errors(clip: RawClip) -> list[str]:
        contract = clip.sample.metadata.get("carrier_time_contract")
        if not isinstance(contract, dict):
            return []
        if contract.get("status") == "matched":
            return []
        return [
            "source carrier time contract failed: "
            f"frames/fps={contract.get('decoded_duration_sec')!r}s, "
            f"declared={contract.get('declared_duration_sec')!r}s, "
            f"delta={contract.get('delta_sec')!r}s exceeds tolerance={contract.get('tolerance_sec')!r}s"
        ]

    def validate_existing(self, clip: RawClip, paths) -> tuple[bool, list[str]]:
        """Validate a skip candidate against current profile/source/semantics and all artifacts."""
        errors: list[str] = []
        if self.registry.paths.processing_version != CANONICAL_PROCESSING_VERSION:
            raise ValueError(
                "canonical v3 validation requires processing version "
                f"{CANONICAL_PROCESSING_VERSION}"
            )
        profile_key = profile_key_for_source(
            clip.sample.dataset,
            clip.sample.codec_key,
            clip.sample.sample_id,
            clip.sample.metadata,
        )
        profile = profile_for_sample(
            clip.sample.dataset,
            clip.sample.sample_id,
            explicit_key=profile_key,
        )
        if profile.validation_status == "draft":
            raise ValueError(
                f"refusing formal canonical artifact for draft dataset profile {profile.key}; "
                "existing files cannot bypass the release gate"
            )
        if profile.hand_solver_validation_status == "draft":
            raise ValueError(
                "refusing formal canonical artifact because the hand solver profile gate "
                f"is draft for {profile.key}; existing files cannot bypass hand validation"
            )
        time_contract_errors = self._source_time_contract_errors(clip)
        if time_contract_errors:
            return False, time_contract_errors
        if not paths.exists():
            return False, ["one or more required artifact files are missing"]
        try:
            manifest = json.loads(paths.canonical_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return False, [f"canonical manifest is unreadable: {exc}"]
        if manifest.get("schema_version") != CANONICAL_ARTIFACT_SCHEMA_VERSION:
            errors.append("canonical manifest schema version changed")
        if manifest.get("processing_version") != self.registry.paths.processing_version:
            errors.append("processing version changed")
        canonical_contract = (
            manifest.get("canonical")
            if isinstance(manifest.get("canonical"), dict)
            else {}
        )
        rest_contract = (
            manifest.get("rest") if isinstance(manifest.get("rest"), dict) else {}
        )
        if canonical_contract.get("schema_version") != CANONICAL_SCHEMA_VERSION:
            errors.append("canonical motion schema changed")
        if canonical_contract.get("skeleton_id") != CANONICAL_SKELETON_ID:
            errors.append("canonical skeleton changed")
        if canonical_contract.get("rotation_semantics") != CANONICAL_ROTATION_SEMANTICS:
            errors.append("canonical rotation semantics changed")
        if rest_contract.get("source") != CANONICAL_REST_ID:
            errors.append("canonical rest contract changed")
        expected_profile = profile.to_dict()
        expected_profile_hash = hashlib.sha256(
            canonical_json_bytes(expected_profile)
        ).hexdigest()
        if (
            manifest.get("profile") != expected_profile
            or manifest.get("profile_sha256") != expected_profile_hash
        ):
            errors.append("resolved dataset profile snapshot/hash changed")
        if manifest.get("source_fingerprint") != self._source_fingerprint(clip):
            errors.append("source fingerprint changed")
        effective_fps = float(clip.motion.get("fps", clip.sample.fps or 30.0))
        annotations, _ = normalize_annotations(
            clip.annotations,
            dataset=clip.sample.dataset,
            sample_id=clip.sample.sample_id,
            fps=effective_fps,
        )
        channels, _ = normalize_channels(
            clip.channels,
            dataset=clip.sample.dataset,
            sample_id=clip.sample.sample_id,
        )
        if (
            manifest.get("annotations") != annotations
            or manifest.get("channels") != channels
        ):
            errors.append("annotation/channel semantics changed")
        try:
            arrays = load_npz_arrays(
                {
                    "source_snapshot": paths.source_snapshot,
                    "canonical_motion": paths.canonical_motion,
                    "vrm_positions": paths.vrm_positions,
                }
            )
            errors.extend(verify_manifest(manifest, arrays))
            sequence = arrays.get("canonical_motion.sequence")
            pre_solver_hands = arrays.get(
                "canonical_motion.pre_solver_hand_quaternions"
            )
            hand_position_evidence = arrays.get(
                "canonical_motion.hand_position_evidence"
            )
            hand_retarget = manifest.get("hand_retarget")
            if (
                sequence is None
                or pre_solver_hands is None
                or hand_position_evidence is None
                or not isinstance(hand_retarget, dict)
            ):
                errors.append("canonical v3 hand retarget replay inputs are missing")
            else:
                output_hands = unpack_sequence(sequence)["hand_quats_xyzw"]
                errors.extend(
                    verify_hand_retarget_replay(
                        hand_retarget,
                        pre_solver_hands,
                        output_hands,
                        hand_position_evidence,
                    )
                )
                try:
                    persisted_observation = hand_observation_from_report(
                        hand_retarget["report"]
                    )
                    persisted_mode = hand_evidence_mode_from_observation(
                        persisted_observation
                    )
                    if persisted_mode != profile.hand_evidence_mode:
                        errors.append(
                            "hand evidence mode/profile mismatch: "
                            f"{persisted_mode!r} != {profile.hand_evidence_mode!r}"
                        )
                    if (
                        persisted_observation.unobservable_policy
                        != profile.hand_unobservable_policy
                    ):
                        errors.append("hand unobservable policy/profile mismatch")
                    if (
                        hand_retarget.get("policy_id")
                        != profile.hand_constraint_policy_id
                    ):
                        errors.append("hand constraint policy/profile mismatch")
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(f"hand evidence profile contract is invalid: {exc}")
        except (OSError, ValueError) as exc:
            errors.append(f"artifact arrays are unreadable: {exc}")
        try:
            quality_content = paths.quality_report.read_bytes()
            quality_value = json.loads(quality_content)
            quality_reference = manifest.get("quality_report")
            if not isinstance(quality_reference, dict):
                errors.append("quality report commitment is missing")
            else:
                expected_quality_path = paths.quality_report.relative_to(
                    self.registry.paths.processed_root
                ).as_posix()
                if quality_reference.get("path") != expected_quality_path:
                    errors.append("quality report path changed")
                descriptor = {
                    key: quality_reference.get(key)
                    for key in (
                        "byte_length",
                        "sha256",
                        "canonical_json_sha256",
                    )
                }
                errors.extend(
                    verify_json_document_descriptor(
                        descriptor,
                        quality_value,
                        quality_content,
                    )
                )
                if quality_value != manifest.get("quality"):
                    errors.append("quality report/manifest mismatch")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"quality report is unreadable: {exc}")
        try:
            metadata_value = json.loads(paths.metadata.read_text(encoding="utf-8"))
            for key in (
                "quality",
                "preview",
                "processing",
                "continuity",
                "hand_retarget",
            ):
                if metadata_value.get(key) != manifest.get(key):
                    errors.append(f"metadata/manifest {key} mismatch")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"motion metadata is unreadable: {exc}")
        processed_root = Path(self.registry.paths.processed_root).resolve()
        for reference in manifest.get("sidecars", []):
            relative = Path(str(reference.get("path") or ""))
            if relative.is_absolute() or ".." in relative.parts:
                errors.append("sidecar path is not processed-root relative")
                continue
            sidecar = (processed_root / relative).resolve()
            if processed_root != sidecar and processed_root not in sidecar.parents:
                errors.append("sidecar path escaped processed root")
                continue
            if not sidecar.is_file():
                errors.append(f"sidecar is missing: {relative.as_posix()}")
                continue
            content = sidecar.read_bytes()
            if len(content) != int(reference.get("byte_length", -1)) or hashlib.sha256(
                content
            ).hexdigest() != reference.get("sha256"):
                errors.append(f"sidecar integrity mismatch: {relative.as_posix()}")
        return not errors, errors

    def persist(self, output: ProcessingOutput) -> dict[str, str]:
        version = self.registry.paths.processing_version
        if version != CANONICAL_PROCESSING_VERSION:
            raise ValueError(
                "canonical v3 writer requires processing version "
                f"{CANONICAL_PROCESSING_VERSION}, got {version!r}"
            )
        root = self.registry.paths.processed_root
        paths = artifact_paths(
            root, version, output.clip.sample.dataset, output.motion_uid
        )

        source = output.source
        result = output.canonical
        clip = output.clip

        effective_fps = float(clip.motion.get("fps", clip.sample.fps or 30.0))
        if not np.isfinite(effective_fps) or effective_fps <= 0:
            raise ValueError(
                f"effective motion FPS must be positive and finite, got {effective_fps}"
            )
        profile_key = profile_key_for_source(
            clip.sample.dataset,
            clip.sample.codec_key,
            clip.sample.sample_id,
            clip.sample.metadata,
        )
        profile = profile_for_sample(
            clip.sample.dataset,
            clip.sample.sample_id,
            explicit_key=profile_key,
        )
        if profile.validation_status == "draft":
            raise ValueError(
                f"refusing formal canonical artifact for draft dataset profile {profile_key}; "
                "run source/target/VRM regression before persistence"
            )
        if profile.hand_solver_validation_status == "draft":
            raise ValueError(
                "refusing formal canonical artifact because the hand solver profile gate "
                f"is draft for {profile_key}; run source/solver/VRM hand regression before persistence"
            )
        time_contract_errors = self._source_time_contract_errors(clip)
        if time_contract_errors:
            raise ValueError("; ".join(time_contract_errors))
        codecs = getattr(self, "codecs", {})
        codec = codecs.get(clip.sample.codec_key) if isinstance(codecs, dict) else None
        runtime = self._observe_codec_runtime(clip, result, codec)
        contract_errors = self._runtime_profile_errors(profile, runtime)
        if contract_errors:
            raise ValueError(
                f"runtime profile contract mismatch for {profile_key}: "
                + "; ".join(contract_errors)
            )
        resolved_profile = profile.to_dict()
        applied_basis = str(runtime["world_basis"])
        actual_root_semantics = str(runtime["root_rotation_semantics"])
        basis_record = result.metadata.get("world_basis")
        if (
            not isinstance(basis_record, dict)
            or basis_record.get("determinant") is None
        ):
            raise ValueError(
                "codec result.metadata.world_basis.determinant is required for canonical artifacts"
            )
        basis_determinant = float(basis_record["determinant"])
        if not np.isfinite(basis_determinant) or not np.isclose(
            abs(basis_determinant), 1.0, atol=1e-5
        ):
            raise ValueError(f"invalid world basis determinant: {basis_determinant}")
        quality_record, quality_source_positions, quality_source_joint_names = (
            self._quality_contract(source, result, effective_fps)
        )
        if canonical_json_bytes(json_value(output.quality)) != canonical_json_bytes(
            quality_record
        ):
            raise ValueError(
                "processing quality report does not match deterministic persisted inputs"
            )
        if quality_source_positions is None:
            persisted_quality_source_positions = np.empty((0, 0, 3), dtype="<f4")
            persisted_quality_source_joint_names = np.asarray([], dtype=np.str_)
        else:
            persisted_quality_source_positions = np.asarray(
                quality_source_positions,
                dtype="<f4",
            )
            persisted_quality_source_joint_names = np.asarray(
                quality_source_joint_names,
                dtype=np.str_,
            )
        pre_solver_hands = result.pre_solver_hand_quaternions
        if pre_solver_hands is None:
            raise ValueError(
                "canonical v3 persistence requires pre-solver hand quaternions"
            )
        pre_solver_hands = np.asarray(pre_solver_hands, dtype="<f4")
        hand_position_evidence = serialize_hand_position_evidence(
            result.hand_position_evidence,
            frame_count=int(result.sequence.shape[0]),
        )
        hand_report = result.metadata.get("hand_retarget")
        if not isinstance(hand_report, dict):
            raise ValueError("canonical v3 persistence requires a verified hand report")
        output_hands = np.asarray(
            unpack_sequence(np.asarray(result.sequence, dtype="<f4"))[
                "hand_quats_xyzw"
            ],
            dtype="<f4",
        )
        hand_retarget_record = build_hand_retarget_record(
            hand_report,
            pre_solver_hands,
            output_hands,
            hand_position_evidence,
        )
        persisted_observation = hand_observation_from_report(
            hand_retarget_record["report"]
        )
        persisted_hand_mode = hand_evidence_mode_from_observation(persisted_observation)
        if persisted_hand_mode != profile.hand_evidence_mode:
            raise ValueError(
                "canonical v3 hand evidence mode/profile mismatch: "
                f"{persisted_hand_mode!r} != {profile.hand_evidence_mode!r}"
            )
        if (
            persisted_observation.unobservable_policy
            != profile.hand_unobservable_policy
        ):
            raise ValueError(
                "canonical v3 hand unobservable policy/profile mismatch: "
                f"{persisted_observation.unobservable_policy!r} != "
                f"{profile.hand_unobservable_policy!r}"
            )
        if hand_retarget_record["policy_id"] != profile.hand_constraint_policy_id:
            raise ValueError("canonical v3 hand constraint policy/profile mismatch")
        if not np.isclose(
            persisted_observation.fps,
            effective_fps,
            rtol=0.0,
            atol=1e-6,
        ):
            raise ValueError(
                "canonical v3 hand observation FPS differs from persisted motion FPS"
            )
        source_payload = {
            "positions": np.asarray(source.positions, dtype="<f4"),
            "joint_names": np.asarray(source.joint_names, dtype=np.str_),
            "edges": np.asarray(source.edges, dtype="<i4"),
            "fps": np.asarray(float(source.fps), dtype="<f4"),
            "coordinate_system": np.asarray([source.coordinate_system], dtype=np.str_),
        }
        canonical_payload = {
            "sequence": np.asarray(result.sequence, dtype="<f4"),
            "positions": np.asarray(result.positions, dtype="<f4"),
            "joint_names": np.asarray(result.joint_names, dtype=np.str_),
            "edges": np.asarray(result.edges, dtype="<i4"),
            "fps": np.asarray(effective_fps, dtype="<f4"),
            "quality_source_positions": persisted_quality_source_positions,
            "quality_source_joint_names": persisted_quality_source_joint_names,
            "pre_solver_hand_quaternions": pre_solver_hands,
            "hand_position_evidence": hand_position_evidence,
        }
        vrm_payload = {
            "positions": np.asarray(result.positions, dtype="<f4"),
            "joint_names": np.asarray(result.joint_names, dtype=np.str_),
            "edges": np.asarray(result.edges, dtype="<i4"),
            "fps": np.asarray(effective_fps, dtype="<f4"),
            "coordinate_system": np.asarray(["gltf_y_up_z_forward"], dtype=np.str_),
        }
        # Resolve every fail-closed profile/time/runtime gate before touching the
        # artifact tree. Rejected draft or time-inconsistent samples must leave
        # neither files nor misleading empty dataset directories behind.
        for path in paths.all_outputs():
            path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(paths.source_snapshot, **source_payload)
        np.savez_compressed(paths.canonical_motion, **canonical_payload)
        np.savez_compressed(paths.vrm_positions, **vrm_payload)
        legacy = legacy_vrm_motion_path(paths)
        legacy.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(legacy, **vrm_payload)

        quality_report_bytes = json.dumps(
            quality_record,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        paths.quality_report.write_bytes(quality_report_bytes)

        profile_sha256 = hashlib.sha256(
            canonical_json_bytes(resolved_profile)
        ).hexdigest()
        annotations, annotation_warnings = normalize_annotations(
            clip.annotations,
            dataset=clip.sample.dataset,
            sample_id=clip.sample.sample_id,
            fps=effective_fps,
        )
        channels, channel_warnings = normalize_channels(
            clip.channels,
            dataset=clip.sample.dataset,
            sample_id=clip.sample.sample_id,
        )
        validation_warnings = list(
            dict.fromkeys(
                [
                    *clip.validation_warnings,
                    *annotation_warnings,
                    *channel_warnings,
                ]
            )
        )
        source_time = clip.sample.metadata.get("original_time", {})
        source_fps = float(source_time.get("fps") or source.fps or effective_fps)
        source_frames = int(
            source_time.get("frame_count")
            or clip.sample.frame_count
            or result.positions.shape[0]
        )
        sample_snapshot = clip.sample.to_dict()
        sample_snapshot["source_path"] = self._portable_locator(
            clip.sample.source_path,
            dataset=clip.sample.dataset,
            sample_id=clip.sample.sample_id,
            role="source",
        )
        sample_snapshot["related_paths"] = {
            key: self._portable_locator(
                value,
                dataset=clip.sample.dataset,
                sample_id=clip.sample.sample_id,
                role=key,
            )
            for key, value in clip.sample.related_paths.items()
        }
        sample_snapshot["metadata"] = json_value(clip.sample.metadata)
        sample_snapshot["fps"] = effective_fps
        sample_snapshot["frame_count"] = int(result.positions.shape[0])
        sample_snapshot["duration_sec"] = float(
            result.positions.shape[0] / effective_fps
        )
        time_record = {
            "fps": effective_fps,
            "source_fps": source_fps,
            "effective_fps": effective_fps,
            "num_frames": int(result.positions.shape[0]),
            "source_frames": source_frames,
            "effective_frames": int(result.positions.shape[0]),
            "duration_sec": float(result.positions.shape[0] / effective_fps),
            "start_frame": 0,
            "end_frame": int(result.positions.shape[0]),
            "interval": "half_open",
        }
        rest_offsets = {
            "hips": [0.0, 0.0, 0.0],
            **{
                key: [float(v) for v in value]
                for key, value in DEFAULT_REST_OFFSETS.items()
            },
        }
        rest_sha256 = hashlib.sha256(canonical_json_bytes(rest_offsets)).hexdigest()
        preview_record = {
            "source_metadata": json_value(
                {
                    "source_format": clip.sample.source_format,
                    "coordinate_system": source.coordinate_system,
                    **dict(source.metadata or {}),
                }
            ),
            "processed_metadata": json_value(result.metadata),
        }
        processing_record = {
            "version": version,
            "codec": result.metadata.get("codec"),
            "profile": resolved_profile,
            "profile_sha256": profile_sha256,
            "profile_status": resolved_profile["validation_status"],
            "annotation_schema_version": "virea.annotation.v1.0.0",
            "channel_schema_version": "virea.channel.v1.0.0",
            "artifact_schema_version": CANONICAL_ARTIFACT_SCHEMA_VERSION,
        }
        quality_report_record = {
            "path": paths.quality_report.relative_to(root).as_posix(),
            **json_document_descriptor(quality_record, quality_report_bytes),
        }
        protected_values = {
            "annotations": annotations,
            "channels": channels,
            "sample_metadata": sample_snapshot.get("metadata", {}),
            "preview": preview_record,
        }
        materialize_sidecars(protected_values, root)
        security = security_manifest(protected_values)
        transform_record = {
            "basis_name": applied_basis,
            "basis": json_value(
                result.metadata.get("world_basis") or {"name": applied_basis}
            ),
            "basis_determinant": basis_determinant,
            "root_rotation_semantics": actual_root_semantics,
            "unit_scale_to_meter": runtime["unit_scale_to_meter"],
            "root_axes": runtime["root_axes"],
            "rotation_6d_layout": runtime.get("rotation_6d_layout"),
            "rotation_space": runtime["rotation_space"],
            "codec_runtime": runtime,
            "translation_zeroed": resolved_profile["translation_zeroed"],
            "crop_resample_map": {
                "source_fps": source_fps,
                "effective_fps": effective_fps,
                "source_frame_count": source_frames,
                "effective_frame_count": int(result.positions.shape[0]),
                "source_start_frame": 0,
                "source_end_frame_exclusive": source_frames,
                "time_origin_sec": 0.0,
                "resampled": source_fps != effective_fps,
            },
        }
        artifact_arrays = {
            **{
                f"source_snapshot.{key}": value for key, value in source_payload.items()
            },
            **{
                f"canonical_motion.{key}": value
                for key, value in canonical_payload.items()
            },
            **{f"vrm_positions.{key}": value for key, value in vrm_payload.items()},
        }
        canonical_manifest = build_manifest(
            {
                "schema_version": CANONICAL_ARTIFACT_SCHEMA_VERSION,
                "processing_version": version,
                "motion_uid": output.motion_uid,
                "source_fingerprint": self._source_fingerprint(clip),
                "sample": sample_snapshot,
                "time": time_record,
                "profile": resolved_profile,
                "profile_sha256": profile_sha256,
                "canonical": {
                    "schema_version": CANONICAL_SCHEMA_VERSION,
                    "skeleton_id": CANONICAL_SKELETON_ID,
                    "rotation_semantics": CANONICAL_ROTATION_SEMANTICS,
                    "frame_dim": 211,
                    "dtype": "<f4",
                    "quaternion_order": "xyzw",
                    "core_bones": list(CORE_BONES),
                    "hand_bones": list(HAND_BONES),
                    "joint_order": list(result.joint_names),
                    "edges": [[int(a), int(b)] for a, b in result.edges],
                },
                "rest": {
                    "source": CANONICAL_REST_ID,
                    "offsets": rest_offsets,
                    "sha256": rest_sha256,
                },
                "transform": transform_record,
                "continuity": json_value(result.metadata.get("continuity", {})),
                "hand_retarget": hand_retarget_record,
                "quality": quality_record,
                "quality_report": quality_report_record,
                "preview": preview_record,
                "processing": processing_record,
                "annotations": annotations,
                "channels": channels,
                "sidecars": security["sidecars"],
                "redactions": security["redactions"],
                "validation_warnings": validation_warnings,
            },
            artifact_arrays,
        )
        manifest_sha256 = str(canonical_manifest["manifest_sha256"])
        array_hashes = {
            key: value["sha256"] for key, value in canonical_manifest["arrays"].items()
        }
        paths.canonical_manifest.write_bytes(canonical_json_bytes(canonical_manifest))

        sample_record = {
            "schema_version": MOTION_SAMPLE_SCHEMA_VERSION,
            "artifact_schema_version": CANONICAL_ARTIFACT_SCHEMA_VERSION,
            "motion_uid": output.motion_uid,
            "manifest_sha256": manifest_sha256,
            "array_sha256": array_hashes,
            "source_fingerprint": canonical_manifest["source_fingerprint"],
            "sample": sample_snapshot,
            "source": {
                "dataset": clip.sample.dataset,
                "source_id": clip.sample.sample_id,
                "source_path": sample_snapshot["source_path"],
                "source_format": clip.sample.source_format,
                "license_family": clip.sample.metadata.get("license_family"),
                "citation_keys": clip.sample.metadata.get("citation_keys", []),
            },
            "time": time_record,
            "skeleton": {
                "source_skeleton": result.metadata.get("source_profile"),
                "canonical_skeleton": CANONICAL_SKELETON_ID,
                "target_skeleton": "vrm1_humanoid",
                "coordinate_system": "gltf_y_up_z_forward",
                "rotation_format": "quat_xyzw",
                "unit": "meter",
                "rotation_semantics": CANONICAL_ROTATION_SEMANTICS,
                "rest_source": CANONICAL_REST_ID,
                "rest_offsets": rest_offsets,
            },
            "annotations": annotations,
            "channels": channels,
            "validation_warnings": validation_warnings,
            "sidecars": security["sidecars"],
            "redactions": security["redactions"],
            "canonical_artifact": {
                "schema_version": CANONICAL_ARTIFACT_SCHEMA_VERSION,
                "manifest": paths.canonical_manifest.relative_to(root).as_posix(),
                "manifest_sha256": manifest_sha256,
            },
            "files": {
                "source_snapshot": paths.source_snapshot.relative_to(root).as_posix(),
                "canonical_motion": paths.canonical_motion.relative_to(root).as_posix(),
                "canonical_manifest": paths.canonical_manifest.relative_to(
                    root
                ).as_posix(),
                "vrm_positions": paths.vrm_positions.relative_to(root).as_posix(),
                "quality_report": paths.quality_report.relative_to(root).as_posix(),
                "metadata": paths.metadata.relative_to(root).as_posix(),
            },
            "quality": quality_record,
            "continuity": json_value(result.metadata.get("continuity", {})),
            "hand_retarget": hand_retarget_record,
            "processing": processing_record,
            "preview": preview_record,
        }
        paths.metadata.write_text(
            json.dumps(sample_record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        file_map = {
            "motion_uid": output.motion_uid,
            "processed_root": ".",
            "source_snapshot": paths.source_snapshot.relative_to(root).as_posix(),
            "canonical_motion": paths.canonical_motion.relative_to(root).as_posix(),
            "canonical_manifest": paths.canonical_manifest.relative_to(root).as_posix(),
            "vrm_positions": paths.vrm_positions.relative_to(root).as_posix(),
            "vrm_motion": legacy.relative_to(root).as_posix(),
            "quality_report": paths.quality_report.relative_to(root).as_posix(),
            "metadata": paths.metadata.relative_to(root).as_posix(),
        }
        output.paths = file_map
        return file_map

    def run(
        self,
        dataset: str,
        sample_id: str,
        max_frames: int | None = None,
        persist: bool = True,
        skip_existing: bool = False,
    ) -> ProcessingOutput:
        output = self.process(dataset, sample_id, max_frames=max_frames)
        if persist:
            if skip_existing:
                paths = artifact_paths(
                    self.registry.paths.processed_root,
                    self.registry.paths.processing_version,
                    dataset,
                    output.motion_uid,
                )
                if paths.exists():
                    valid, _errors = self.validate_existing(output.clip, paths)
                    if valid:
                        root = self.registry.paths.processed_root
                        output.paths = {
                            "motion_uid": output.motion_uid,
                            "skipped": "true",
                            "processed_root": ".",
                            "source_snapshot": paths.source_snapshot.relative_to(
                                root
                            ).as_posix(),
                            "canonical_motion": paths.canonical_motion.relative_to(
                                root
                            ).as_posix(),
                            "canonical_manifest": paths.canonical_manifest.relative_to(
                                root
                            ).as_posix(),
                            "vrm_positions": paths.vrm_positions.relative_to(
                                root
                            ).as_posix(),
                            "quality_report": paths.quality_report.relative_to(
                                root
                            ).as_posix(),
                            "metadata": paths.metadata.relative_to(root).as_posix(),
                        }
                        return output
            self.persist(output)
        return output
