from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest
from _schema_validation import validate_schema_instance

from virea.data.annotations import cache_data_sidecar, make_annotation, make_channel
from virea.data.types import RawClip, SampleRef
from virea.motion.canonical import (
    CORE_BONES,
    FRAME_DIM,
    HAND_BONES,
    pack_sequence,
    unpack_sequence,
)
from virea.motion.codecs import CanonicalResult
from virea.motion.hand_biomechanics import analyze_hand_joint_positions
from virea.motion.hand_solver import HandObservationMetadata, solve_hand_constraints
from virea.motion.skeleton import (
    BODY_BONES,
    DEFAULT_REST_OFFSETS,
    FK_BONES,
    FK_EDGES,
    forward_kinematics_from_sequence,
)
from virea.motion.snapshot import SourceSnapshot
from virea.pipelines.artifact_manifest import (
    build_hand_retarget_record,
    build_manifest,
    canonical_json_bytes,
    float32_array_sha256,
    json_document_descriptor,
    serialize_hand_position_evidence,
)
from virea.pipelines.artifacts import artifact_paths, motion_uid
from virea.pipelines.batch import BatchPipeline, ProcessingTask
from virea.pipelines.preview_builder import PreviewBuilder
from virea.pipelines.preview_reader import PreviewReader
from virea.pipelines.processing import ProcessingOutput, ProcessingPipeline
from virea.server.binary_codec import pack_positions_binary, unpack_positions_binary


def test_binary_codec_roundtrip() -> None:
    positions = np.arange(24, dtype=np.float32).reshape(2, 4, 3)
    packed = pack_positions_binary(positions, 2, 4)
    decoded = unpack_positions_binary(packed)
    assert decoded["frame_count"] == 2
    assert decoded["joint_count"] == 4
    np.testing.assert_allclose(decoded["positions"], positions)


def test_float32_payload_hash_matches_cross_language_vector() -> None:
    value = np.asarray(
        [[[0.0, -0.0, np.float32(0.1), 1.0]]],
        dtype="<f4",
    )
    assert float32_array_sha256(value) == (
        "4d930b2e5f967c50c22307f91e04a4a301d6e789068ee989eb8f5c614b393fdc"
    )


def test_preview_builder_binds_exact_f32_hand_payload_and_truncated_slice() -> None:
    frame_count = 3
    pre_solver_hands = np.zeros((frame_count, len(HAND_BONES), 4), dtype=np.float32)
    angle = np.float32(0.1234567)
    pre_solver_hands[..., 0] = np.sin(angle / np.float32(2.0))
    pre_solver_hands[..., 3] = np.cos(angle / np.float32(2.0))
    observation = HandObservationMetadata.all_observed(
        source="preview-builder-f32-contract",
        fps=30.0,
    )
    solution = solve_hand_constraints(
        pre_solver_hands,
        continuity_segments=[(0, frame_count)],
        observation=observation,
    )
    sequence = pack_sequence(
        np.zeros((frame_count, 3), dtype=np.float32),
        hand_quats_xyzw=solution.quats_xyzw,
    )
    hand_retarget = build_hand_retarget_record(
        solution.report,
        np.asarray(pre_solver_hands, dtype="<f4"),
        np.asarray(solution.quats_xyzw, dtype="<f4"),
        serialize_hand_position_evidence(None, frame_count=frame_count),
    )

    full = PreviewBuilder.motion_dict_from_sequence(
        sequence,
        hand_retarget=hand_retarget,
    )
    emitted_full = np.asarray(full["hand_quaternions"], dtype="<f4")
    np.testing.assert_array_equal(emitted_full, solution.quats_xyzw)
    assert full["hand_constraint_certificate"]["output_hand_sha256"] == (
        float32_array_sha256(emitted_full)
    )
    assert any(
        float(component) != round(float(component), 6)
        for component in solution.quats_xyzw.reshape(-1)
    )

    cropped = PreviewBuilder.motion_dict_from_sequence(
        sequence[:2],
        hand_retarget=hand_retarget,
        verified_output_hand_quaternions=solution.quats_xyzw,
        artifact_frame_interval=(0, 2),
    )
    emitted_crop = np.asarray(cropped["hand_quaternions"], dtype="<f4")
    np.testing.assert_array_equal(emitted_crop, solution.quats_xyzw[:2])
    crop_proof = cropped["hand_constraint_certificate"]
    assert crop_proof["frame_count"] == frame_count
    assert crop_proof["payload_frame_interval_frames_half_open"] == [0, 2]
    assert crop_proof["output_hand_sha256"] == float32_array_sha256(emitted_crop)
    assert crop_proof["output_hand_sha256"] != solution.report["output_sha256"]


def test_artifact_paths_exists(tmp_path: Path) -> None:
    uid = motion_uid("beat", "sample", 10)
    paths = artifact_paths(tmp_path, "v0.1.0", "beat", uid)
    assert not paths.exists()
    for path in paths.all_outputs():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".npz":
            np.savez_compressed(
                path,
                positions=np.zeros((10, 22, 3), dtype=np.float32),
                joint_names=np.asarray(["hips"], dtype=object),
                edges=np.zeros((0, 2), dtype=np.int32),
            )
        else:
            path.write_text("{}", encoding="utf-8")
    assert paths.exists()


def test_batch_collect_tasks_structure() -> None:
    pipeline = BatchPipeline.__new__(BatchPipeline)
    pipeline.registry = None  # type: ignore[assignment]
    task = ProcessingTask(dataset="amass", sample_id="x")
    assert task.dataset == "amass"


def test_preview_reader_restores_persisted_annotations(tmp_path: Path) -> None:
    uid = motion_uid("beat", "sample", 10)
    paths = artifact_paths(tmp_path, "v0.1.0", "beat", uid)
    for path in paths.all_outputs():
        path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "positions": np.zeros((10, 3, 3), dtype=np.float32),
        "joint_names": np.asarray(["hips", "spine", "head"], dtype=object),
        "edges": np.asarray([[0, 1], [1, 2]], dtype=np.int32),
        "fps": np.float32(20.0),
        "coordinate_system": np.asarray(["gltf_y_up_z_forward"], dtype=object),
    }
    np.savez_compressed(paths.source_snapshot, **payload)
    np.savez_compressed(paths.vrm_positions, **payload)
    np.savez_compressed(
        paths.canonical_motion,
        sequence=pack_sequence(np.zeros((10, 3), dtype=np.float32)),
    )
    paths.quality_report.write_text("{}", encoding="utf-8")
    paths.metadata.write_text(
        """{
          "motion_uid": "virea:beat:sample:000000:000010:test",
          "source": {"dataset": "beat", "source_id": "sample", "source_format": "beat_bvh_axis_angle_npz"},
          "time": {"fps": 20.0, "source_fps": 20.0, "source_frames": 10, "num_frames": 10, "duration_sec": 0.5},
          "annotations": [{"type": "gesture_or_semantic", "bodypart": "action", "text": "wave", "start_sec": 0.0, "end_sec": 0.5}]
        }""",
        encoding="utf-8",
    )

    class _Paths:
        processed_root = tmp_path
        processing_version = "v0.1.0"

    class _Registry:
        paths = _Paths()

    with pytest.raises(
        ValueError, match="object arrays require explicit trusted legacy migration"
    ):
        PreviewReader(_Registry()).read_processed_preview("beat", "sample")
    preview = PreviewReader(
        _Registry(), allow_trusted_legacy_pickle=True
    ).read_processed_preview("beat", "sample")

    assert len(preview.annotations) == 1
    annotation = preview.annotations[0]
    assert annotation["schema_version"] == "virea.annotation.v1.0.0"
    assert annotation["type"] == "gesture_or_semantic"
    assert annotation["text"] == "wave"
    assert annotation["start_frame"] == 0
    assert annotation["end_frame"] == 10
    assert annotation["provenance"] == "derived"
    assert annotation["original"]["legacy_record"]["text"] == "wave"
    assert any(
        "Compatibility mode" in warning for warning in preview.validation_warnings
    )
    assert any(
        "Trusted legacy migration mode" in warning
        for warning in preview.validation_warnings
    )
    assert any(
        "Legacy canonical sequence withheld" in warning
        for warning in preview.validation_warnings
    )
    assert preview.motion is None
    with pytest.raises(FileNotFoundError, match="no motion payload"):
        PreviewReader(
            _Registry(), allow_trusted_legacy_pickle=True
        ).read_motion_payload("beat", "sample")
    assert preview.sample.sample_id == "sample"


def test_preview_reader_v1_matches_online_semantics_after_limit(tmp_path: Path) -> None:
    annotation = make_annotation(
        dataset="beat",
        sample_id="sample",
        source="beat.converted_tsv",
        record_key="line[0]",
        ordinal=0,
        level="action",
        type="gesture_semantic",
        text="wave",
        provenance="native",
        start_sec=0.0,
        end_sec=0.5,
        fps=20.0,
    )
    channel = make_channel(
        dataset="beat",
        sample_id="sample",
        source="beat.face.json",
        record_key="face",
        ordinal=0,
        kind="face",
        availability="inline",
        representation="weights",
        timebase={"start_frame": 0, "end_frame": 10, "interval": "half_open"},
        fps=20.0,
        frame_count=10,
        shape=[10, 1],
        preview={"weights": [[float(index)] for index in range(10)]},
    )
    sample = SampleRef(
        dataset="beat",
        sample_id="sample",
        source_path=Path("raw/beat/sample.npz"),
        source_format="beat_bvh_axis_angle_npz",
        codec_key="beat_axis_angle_body22",
        fps=20.0,
        frame_count=10,
        duration_sec=0.5,
        text="wave",
        split="train",
        related_paths={"text": Path("raw/beat/sample.txt")},
        metadata={"license_family": "test"},
    )
    online = RawClip(
        sample=sample,
        motion={"positions": np.zeros((10, 3, 3), dtype=np.float32), "fps": 20.0},
        annotations=[annotation],
        channels=[channel],
        validation_warnings=["source warning"],
    ).limited(5)

    uid = motion_uid("beat", "sample", 10)
    paths = artifact_paths(tmp_path, "v0.2.0", "beat", uid)
    for path in paths.all_outputs():
        path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "positions": np.zeros((10, 3, 3), dtype=np.float32),
        "joint_names": np.asarray(["hips", "spine", "head"], dtype=np.str_),
        "edges": np.asarray([[0, 1], [1, 2]], dtype=np.int32),
        "fps": np.float32(20.0),
        "coordinate_system": np.asarray(["gltf_y_up_z_forward"], dtype=np.str_),
    }
    np.savez_compressed(paths.source_snapshot, **payload)
    np.savez_compressed(paths.vrm_positions, **payload)
    paths.quality_report.write_text("{}", encoding="utf-8")
    paths.metadata.write_text(
        json.dumps(
            {
                "schema_version": "virea.motion_sample.semantic_cache.v1.0.0",
                "motion_uid": uid,
                "sample": sample.to_dict(),
                "source": {
                    "dataset": "beat",
                    "source_id": "sample",
                    "source_format": sample.source_format,
                },
                "time": {"fps": 20.0, "num_frames": 10, "duration_sec": 0.5},
                "annotations": [annotation],
                "channels": [channel],
                "validation_warnings": ["source warning"],
                "preview": {"processed_metadata": {"codec": "test"}},
            }
        ),
        encoding="utf-8",
    )

    class _Paths:
        processed_root = tmp_path
        processing_version = "v0.2.0"

    class _Registry:
        paths = _Paths()

    cached = PreviewReader(_Registry()).read_processed_preview(
        "beat", "sample", max_frames=5
    )
    assert cached.annotations == online.annotations
    assert cached.channels == online.channels
    assert (
        cached.validation_warnings[: len(online.validation_warnings)]
        == online.validation_warnings
    )
    assert any(
        "Compatibility mode" in warning for warning in cached.validation_warnings
    )
    assert cached.sample.to_dict() == online.sample.to_dict()


def test_preview_reader_deterministically_selects_full_or_sufficient_crop(
    tmp_path: Path,
) -> None:
    for frame_count, marker in ((5, 5.0), (10, 10.0)):
        uid = motion_uid("beat", "sample", frame_count)
        paths = artifact_paths(tmp_path, "v0.2.0", "beat", uid)
        for path in (paths.vrm_positions, paths.quality_report, paths.metadata):
            path.parent.mkdir(parents=True, exist_ok=True)
        positions = np.full((frame_count, 1, 3), marker, dtype=np.float32)
        np.savez_compressed(
            paths.vrm_positions,
            positions=positions,
            joint_names=np.asarray(["hips"], dtype=np.str_),
            edges=np.zeros((0, 2), dtype=np.int32),
            fps=np.float32(20.0),
            coordinate_system=np.asarray(["gltf_y_up_z_forward"], dtype=np.str_),
        )
        paths.quality_report.write_text("{}", encoding="utf-8")
        paths.metadata.write_text(
            json.dumps(
                {
                    "motion_uid": uid,
                    "source": {
                        "dataset": "beat",
                        "source_id": "sample",
                        "source_format": "legacy",
                    },
                    "time": {
                        "fps": 20.0,
                        "source_fps": 20.0,
                        "source_frames": 10,
                        "num_frames": frame_count,
                        "effective_frames": frame_count,
                    },
                }
            ),
            encoding="utf-8",
        )

    class _Paths:
        processed_root = tmp_path
        processing_version = "v0.2.0"

    class _Registry:
        paths = _Paths()

    reader = PreviewReader(_Registry())
    full = reader.read_processed_preview("beat", "sample")
    exact_crop = reader.read_processed_preview("beat", "sample", max_frames=5)
    larger_request = reader.read_processed_preview("beat", "sample", max_frames=8)
    assert full.positions.shape[0] == 10
    assert np.all(full.positions == 10.0)
    assert exact_crop.positions.shape[0] == 5
    assert np.all(exact_crop.positions == 5.0)
    assert larger_request.positions.shape[0] == 8
    assert np.all(larger_request.positions == 10.0)


def test_preview_reader_rejects_known_truncated_artifact_as_full_clip(
    tmp_path: Path,
) -> None:
    frame_count = 5
    uid = motion_uid("beat", "cropped", frame_count)
    paths = artifact_paths(tmp_path, "v0.2.0", "beat", uid)
    for path in (paths.vrm_positions, paths.quality_report, paths.metadata):
        path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        paths.vrm_positions,
        positions=np.zeros((frame_count, 1, 3), dtype=np.float32),
        joint_names=np.asarray(["hips"], dtype=np.str_),
        edges=np.zeros((0, 2), dtype=np.int32),
        fps=np.float32(20.0),
        coordinate_system=np.asarray(["gltf_y_up_z_forward"], dtype=np.str_),
    )
    paths.quality_report.write_text('{"status":"cropped"}', encoding="utf-8")
    paths.metadata.write_text(
        json.dumps(
            {
                "motion_uid": uid,
                "source": {
                    "dataset": "beat",
                    "source_id": "cropped",
                    "source_format": "legacy",
                },
                "time": {
                    "fps": 20.0,
                    "source_fps": 20.0,
                    "source_frames": 10,
                    "num_frames": frame_count,
                    "effective_frames": frame_count,
                },
            }
        ),
        encoding="utf-8",
    )

    class _Paths:
        processed_root = tmp_path
        processing_version = "v0.2.0"

    class _Registry:
        paths = _Paths()

    reader = PreviewReader(_Registry())
    assert reader._select_persisted_paths("beat", "cropped", 5) is not None
    with pytest.raises(FileNotFoundError, match="cropped or has unknown completeness"):
        reader._select_persisted_paths("beat", "cropped", None)
    with pytest.raises(FileNotFoundError, match="fewer than 8 frames"):
        reader._select_persisted_paths("beat", "cropped", 8)
    assert reader.read_quality_report("beat", "cropped") == {"status": "cropped"}


def test_persist_uses_effective_motion_fps_and_verifiable_profile_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = SampleRef(
        dataset="amass",
        sample_id="subject/clip",
        source_path=Path("raw/amass/subject/clip.npz"),
        source_format="smplh_axis_angle_npz",
        codec_key="smplh_body_hands",
        fps=60.0,
        frame_count=2,
        duration_sec=2 / 60.0,
        metadata={
            "license_family": "test",
            "citation_keys": [],
            "dataset_profile": "amass_smplh156",
        },
    )
    annotation = make_annotation(
        dataset="amass",
        sample_id=sample.sample_id,
        source="amass.source_path.filename",
        record_key="filename",
        ordinal=0,
        level="sequence",
        type="inferred_action_name",
        text="clip",
        provenance="derived",
        reasoning="Derived from filename.",
        extras={"raw_unknown_values": list(range(513))},
    )
    data_ref = cache_data_sidecar(
        b"native-channel-bytes",
        media_type="application/octet-stream",
        encoding="binary",
        suffix=".bin",
    )
    channel = make_channel(
        dataset="amass",
        sample_id=sample.sample_id,
        source="test.native_channel",
        record_key="native",
        ordinal=0,
        kind="test",
        availability="external",
        representation="opaque_test_bytes",
        data_ref=data_ref,
    )
    clip = RawClip(
        sample=sample,
        motion={"poses": np.zeros((2, 156), dtype=np.float32), "fps": 30.0},
        annotations=[annotation],
        channels=[channel],
    )
    source_positions = np.zeros((2, 1, 3), dtype=np.float32)
    source = SourceSnapshot(
        positions=source_positions,
        joint_names=["hips"],
        edges=[],
        fps=30.0,
        metadata={
            "source_geometry_template": "test_source_geometry.v1",
            "source_geometry_template_sha256": "1" * 64,
            "source_geometry_table_sha256": "2" * 64,
        },
    )
    sequence = pack_sequence(np.zeros((2, 3), dtype=np.float32))
    pre_solver_hands = np.asarray(
        unpack_sequence(sequence)["hand_quats_xyzw"], dtype=np.float32
    ).copy()
    hand_observation = HandObservationMetadata.identity_only(
        source="test.static_export_prior_identity_neutral",
        fps=30.0,
    )
    hand_solution = solve_hand_constraints(
        pre_solver_hands,
        continuity_segments=[(0, 2)],
        observation=hand_observation,
    )
    positions = forward_kinematics_from_sequence(sequence)
    position_index = {name: index for index, name in enumerate(FK_BONES)}
    hand_biomechanics = analyze_hand_joint_positions(
        np.stack(
            [positions[:, position_index[name]] for name in BODY_BONES],
            axis=1,
        ),
        {name: positions[:, position_index[name]] for name in HAND_BONES},
    )
    canonical = CanonicalResult(
        sequence=sequence,
        positions=positions,
        joint_names=list(FK_BONES),
        edges=list(FK_EDGES),
        metadata={
            "codec": "smplh_body_hands",
            "source_profile": "smplh_body22_hands30",
            "declared_world_basis": "z_up_to_y_up",
            "root_rotation_semantics": "local_to_world",
            "world_basis": {
                "determinant": 1.0,
                "rotation_matrix": [[1, 0, 0], [0, 0, 1], [0, -1, 0]],
            },
            "retarget_mode": "position_fit_to_vrm",
            "hand_biomechanics": hand_biomechanics,
            "source_geometry_template": "test_source_geometry.v1",
            "source_geometry_template_sha256": "1" * 64,
            "source_geometry_table_sha256": "2" * 64,
            "hand_retarget": hand_solution.report,
        },
        retarget_source_positions=positions.copy(),
        retarget_source_joint_names=list(FK_BONES),
        hand_observation=hand_observation,
        pre_solver_hand_quaternions=pre_solver_hands,
        hand_position_evidence=None,
    )
    uid = motion_uid("amass", sample.sample_id, 2)
    quality, _quality_positions, _quality_names = ProcessingPipeline._quality_contract(
        source,
        canonical,
        30.0,
    )
    output = ProcessingOutput(
        clip=clip,
        source=source,
        canonical=canonical,
        quality=quality,
        motion_uid=uid,
        paths={},
    )

    class _Paths:
        processed_root = tmp_path
        processing_version = "v0.4.0"

    class _Registry:
        paths = _Paths()

    pipeline = ProcessingPipeline.__new__(ProcessingPipeline)
    pipeline.registry = _Registry()
    file_map = pipeline.persist(output)
    assert file_map["processed_root"] == "."
    assert all(
        not Path(value).is_absolute()
        for key, value in file_map.items()
        if key not in {"motion_uid", "skipped"}
    )

    paths = artifact_paths(tmp_path, "v0.4.0", "amass", uid)
    metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
    with np.load(paths.canonical_motion, allow_pickle=False) as payload:
        assert float(payload["fps"]) == 30.0
        assert payload["pre_solver_hand_quaternions"].shape == (2, 30, 4)
        assert payload["pre_solver_hand_quaternions"].dtype == np.dtype("<f4")
        assert payload["hand_position_evidence"].shape == (0, 32, 3)
    assert metadata["time"]["effective_fps"] == 30.0
    assert metadata["time"]["duration_sec"] == pytest.approx(2 / 30.0)
    assert metadata["sample"]["fps"] == 30.0
    assert (
        metadata["processing"]["profile"]["schema_version"]
        == "virea.dataset_profile.v2.0.0"
    )
    assert len(metadata["processing"]["profile_sha256"]) == 64
    assert len(metadata["manifest_sha256"]) == 64
    manifest = json.loads(paths.canonical_manifest.read_text(encoding="utf-8"))
    validate_schema_instance(manifest, "canonical_artifact.schema.json")
    validate_schema_instance(metadata, "motion_sample.schema.json")
    assert manifest["schema_version"] == "virea.canonical_artifact.v3.0.0"
    assert manifest["profile"]["key"] == "amass_smplh156"
    assert manifest["canonical"]["frame_dim"] == 211
    assert manifest["rest"]["source"] == "virea_canonical_rest.v3"
    assert manifest["hand_retarget"] == metadata["hand_retarget"]
    assert manifest["hand_retarget"]["report"]["status"] == "passed_noop"
    assert manifest["quality"] == metadata["quality"]
    assert manifest["preview"] == metadata["preview"]
    assert manifest["processing"] == metadata["processing"]
    assert manifest["quality_report"]["path"] == metadata["files"]["quality_report"]
    assert len(manifest["quality_report"]["canonical_json_sha256"]) == 64
    assert manifest["arrays"]
    assert len(manifest["sidecars"]) == 2
    assert all(
        (tmp_path / reference["path"]).is_file() for reference in manifest["sidecars"]
    )
    serialized_artifact = paths.canonical_manifest.read_text(
        encoding="utf-8"
    ) + paths.metadata.read_text(encoding="utf-8")
    assert str(tmp_path).replace("\\", "/") not in serialized_artifact.replace(
        "\\", "/"
    )
    valid, validation_errors = pipeline.validate_existing(clip, paths)
    assert valid
    assert validation_errors == []

    import virea.pipelines.preview_reader as reader_module

    load_calls = 0
    original_loader = reader_module.load_npz_arrays

    def counting_loader(files):  # noqa: ANN001
        nonlocal load_calls
        load_calls += 1
        return original_loader(files)

    monkeypatch.setattr(reader_module, "load_npz_arrays", counting_loader)
    reader = PreviewReader(_Registry())
    restored = reader.read_processed_preview("amass", sample.sample_id)
    assert not any(
        "mismatch" in warning.lower() for warning in restored.validation_warnings
    )
    assert restored.annotations == clip.annotations
    assert restored.channels == clip.channels
    assert restored.motion is not None
    assert restored.motion["schema_version"] == "virea.vrm_motion_payload.v3.0.0"
    assert (
        restored.motion["hand_constraint_certificate"]["viewer_pose_mutation_count"]
        == 0
    )
    reader.read_source_preview("amass", sample.sample_id)
    assert reader.read_quality_report("amass", sample.sample_id) == quality
    assert load_calls == 3

    signed_files = (
        paths.metadata,
        paths.canonical_manifest,
        paths.source_snapshot,
        paths.canonical_motion,
        paths.vrm_positions,
        paths.quality_report,
    )
    signed_baseline = {path: path.read_bytes() for path in signed_files}

    def restore_signed_artifact() -> None:
        for path, content in signed_baseline.items():
            path.write_bytes(content)

    def resign_artifact(mutator) -> None:  # noqa: ANN001
        artifact_manifest = json.loads(
            paths.canonical_manifest.read_text(encoding="utf-8")
        )
        artifact_metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
        payloads: dict[str, dict[str, np.ndarray]] = {}
        for prefix, path in (
            ("source_snapshot", paths.source_snapshot),
            ("canonical_motion", paths.canonical_motion),
            ("vrm_positions", paths.vrm_positions),
        ):
            with np.load(path, allow_pickle=False) as stored:
                payloads[prefix] = {
                    key: np.asarray(stored[key]) for key in stored.files
                }
        mutator(artifact_manifest, artifact_metadata, payloads)
        arrays = {
            f"{prefix}.{key}": value
            for prefix, payload in payloads.items()
            for key, value in payload.items()
        }
        quality_record = artifact_manifest["quality"]
        quality_content = json.dumps(
            quality_record,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        artifact_manifest["quality_report"] = {
            "path": paths.quality_report.relative_to(tmp_path).as_posix(),
            **json_document_descriptor(quality_record, quality_content),
        }
        resigned = build_manifest(artifact_manifest, arrays)
        for prefix, path in (
            ("source_snapshot", paths.source_snapshot),
            ("canonical_motion", paths.canonical_motion),
            ("vrm_positions", paths.vrm_positions),
        ):
            np.savez_compressed(path, **payloads[prefix])
        paths.quality_report.write_bytes(quality_content)
        artifact_metadata["manifest_sha256"] = resigned["manifest_sha256"]
        artifact_metadata["array_sha256"] = {
            key: descriptor["sha256"] for key, descriptor in resigned["arrays"].items()
        }
        artifact_metadata["canonical_artifact"]["manifest_sha256"] = resigned[
            "manifest_sha256"
        ]
        paths.canonical_manifest.write_bytes(canonical_json_bytes(resigned))
        paths.metadata.write_text(
            json.dumps(artifact_metadata, ensure_ascii=False),
            encoding="utf-8",
        )
        validate_schema_instance(resigned, "canonical_artifact.schema.json")
        validate_schema_instance(artifact_metadata, "motion_sample.schema.json")

    restore_signed_artifact()

    def rewrite_pre_solver_hand(_manifest, _metadata, payloads) -> None:  # noqa: ANN001
        pre_solver = payloads["canonical_motion"]["pre_solver_hand_quaternions"].copy()
        angle = np.float32(np.deg2rad(10.0) / 2.0)
        pre_solver[0, 0] = np.asarray(
            [np.sin(angle), 0.0, 0.0, np.cos(angle)], dtype=np.float32
        )
        payloads["canonical_motion"]["pre_solver_hand_quaternions"] = pre_solver

    resign_artifact(rewrite_pre_solver_hand)
    with pytest.raises(ValueError, match="pre-solver hand quaternion SHA-256"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)

    restore_signed_artifact()

    def rewrite_hand_policy_hash(
        artifact_manifest, artifact_metadata, _payloads
    ) -> None:  # noqa: ANN001
        for record in (
            artifact_manifest["hand_retarget"],
            artifact_metadata["hand_retarget"],
        ):
            record["policy_sha256"] = "f" * 64

    resign_artifact(rewrite_hand_policy_hash)
    with pytest.raises(ValueError, match="policy SHA-256 mismatch"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)

    restore_signed_artifact()
    cache_probe = PreviewReader(_Registry())
    cache_probe.read_processed_preview("amass", sample.sample_id)
    quality_stat = paths.quality_report.stat()
    signed_quality = paths.quality_report.read_bytes()
    if b'"status": "passed"' in signed_quality:
        tampered_quality = signed_quality.replace(
            b'"status": "passed"', b'"status": "failed"', 1
        )
    else:
        tampered_quality = signed_quality.replace(
            b'"status": "failed"', b'"status": "passed"', 1
        )
    assert tampered_quality != signed_quality
    assert len(tampered_quality) == len(signed_quality)
    paths.quality_report.write_bytes(tampered_quality)
    os.utime(
        paths.quality_report,
        ns=(quality_stat.st_atime_ns, quality_stat.st_mtime_ns),
    )
    tampered_stat = paths.quality_report.stat()
    assert tampered_stat.st_size == quality_stat.st_size
    assert tampered_stat.st_mtime_ns == quality_stat.st_mtime_ns
    with pytest.raises(ValueError, match="quality report integrity"):
        cache_probe.read_quality_report("amass", sample.sample_id)

    restore_signed_artifact()
    cache_probe.read_processed_preview("amass", sample.sample_id)
    manifest_stat = paths.canonical_manifest.stat()
    signed_manifest = paths.canonical_manifest.read_bytes()
    tampered_manifest = signed_manifest.replace(
        b"virea_canonical_skeleton.v3",
        b"virea_canonical_skeleton.x3",
        1,
    )
    assert tampered_manifest != signed_manifest
    assert len(tampered_manifest) == len(signed_manifest)
    paths.canonical_manifest.write_bytes(tampered_manifest)
    os.utime(
        paths.canonical_manifest,
        ns=(manifest_stat.st_atime_ns, manifest_stat.st_mtime_ns),
    )
    tampered_manifest_stat = paths.canonical_manifest.stat()
    assert tampered_manifest_stat.st_size == manifest_stat.st_size
    assert tampered_manifest_stat.st_mtime_ns == manifest_stat.st_mtime_ns
    with pytest.raises(ValueError, match="canonical skeleton"):
        cache_probe.read_processed_preview("amass", sample.sample_id)

    restore_signed_artifact()

    def rewrite_quality_status(artifact_manifest, artifact_metadata, _payloads) -> None:  # noqa: ANN001
        replacement = (
            "failed" if artifact_manifest["quality"]["status"] == "passed" else "passed"
        )
        artifact_manifest["quality"]["status"] = replacement
        artifact_metadata["quality"]["status"] = replacement

    resign_artifact(rewrite_quality_status)
    with pytest.raises(ValueError, match="deterministic persisted inputs"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)

    restore_signed_artifact()

    def rewrite_hand_biomechanics(
        artifact_manifest, artifact_metadata, _payloads
    ) -> None:  # noqa: ANN001
        for record in (artifact_manifest, artifact_metadata):
            biomechanics = record["preview"]["processed_metadata"]["hand_biomechanics"]
            biomechanics["status"] = (
                "review_required"
                if biomechanics["status"] == "within_hard_review_envelope"
                else "within_hard_review_envelope"
            )

    resign_artifact(rewrite_hand_biomechanics)
    with pytest.raises(ValueError, match="hand biomechanics"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)

    restore_signed_artifact()

    def swap_core_order(artifact_manifest, _metadata, _payloads) -> None:  # noqa: ANN001
        bones = artifact_manifest["canonical"]["core_bones"]
        bones[CORE_BONES.index("leftHand")], bones[CORE_BONES.index("rightHand")] = (
            bones[CORE_BONES.index("rightHand")],
            bones[CORE_BONES.index("leftHand")],
        )

    def swap_hand_order(artifact_manifest, _metadata, _payloads) -> None:  # noqa: ANN001
        bones = artifact_manifest["canonical"]["hand_bones"]
        bones[0], bones[len(HAND_BONES) // 2] = bones[len(HAND_BONES) // 2], bones[0]

    def swap_joint_order(artifact_manifest, _metadata, payloads) -> None:  # noqa: ANN001
        left = FK_BONES.index("leftHand")
        right = FK_BONES.index("rightHand")
        order = artifact_manifest["canonical"]["joint_order"]
        order[left], order[right] = order[right], order[left]
        for prefix in ("canonical_motion", "vrm_positions"):
            names = payloads[prefix]["joint_names"].copy()
            names[left], names[right] = names[right], names[left]
            payloads[prefix]["joint_names"] = names
            positions = payloads[prefix]["positions"].copy()
            positions[:, [left, right]] = positions[:, [right, left]]
            payloads[prefix]["positions"] = positions

    def reorder_edges(artifact_manifest, _metadata, payloads) -> None:  # noqa: ANN001
        artifact_manifest["canonical"]["edges"] = list(
            reversed(artifact_manifest["canonical"]["edges"])
        )
        for prefix in ("canonical_motion", "vrm_positions"):
            payloads[prefix]["edges"] = payloads[prefix]["edges"][::-1].copy()

    structure_mutations = (
        (swap_core_order, "core bone order"),
        (swap_hand_order, "hand bone order"),
        (swap_joint_order, "joint order"),
        (reorder_edges, "edges"),
    )
    for mutate, error in structure_mutations:
        restore_signed_artifact()
        resign_artifact(mutate)
        with pytest.raises(ValueError, match=error):
            PreviewReader(_Registry()).read_processed_preview(
                "amass",
                sample.sample_id,
            )

    restore_signed_artifact()

    def replace_rest(artifact_manifest, artifact_metadata, _payloads) -> None:  # noqa: ANN001
        rest_offsets = {
            "hips": [0.0, 0.0, 0.0],
            **{
                bone: [float(component) for component in offset]
                for bone, offset in DEFAULT_REST_OFFSETS.items()
            },
        }
        rest_offsets["leftIndexIntermediate"] = [-0.0447213595, 0.0, 0.0]
        artifact_manifest["rest"]["offsets"] = rest_offsets
        artifact_manifest["rest"]["sha256"] = hashlib.sha256(
            canonical_json_bytes(rest_offsets)
        ).hexdigest()
        artifact_metadata["skeleton"]["rest_offsets"] = rest_offsets

    resign_artifact(replace_rest)
    with pytest.raises(ValueError, match="rest offsets"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)

    restore_signed_artifact()

    def truncate_frame_width(_manifest, _metadata, payloads) -> None:  # noqa: ANN001
        payloads["canonical_motion"]["sequence"] = payloads["canonical_motion"][
            "sequence"
        ][:, : FRAME_DIM - 1]

    resign_artifact(truncate_frame_width)
    with pytest.raises(ValueError, match="sequence shape"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)

    restore_signed_artifact()

    def misdeclare_frame_count(artifact_manifest, artifact_metadata, _payloads) -> None:  # noqa: ANN001
        for record in (artifact_manifest["time"], artifact_metadata["time"]):
            record["num_frames"] = 3
            record["effective_frames"] = 3
            record["end_frame"] = 3
        artifact_manifest["sample"]["frame_count"] = 3
        artifact_metadata["sample"]["frame_count"] = 3

    resign_artifact(misdeclare_frame_count)
    with pytest.raises(ValueError, match="sequence shape"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)

    restore_signed_artifact()

    def substitute_avatar_skeleton(_manifest, _metadata, payloads) -> None:  # noqa: ANN001
        joint_index = FK_BONES.index("rightIndexIntermediate")
        for prefix in ("canonical_motion", "vrm_positions"):
            substituted = payloads[prefix]["positions"].copy()
            substituted[:, joint_index, 2] += np.float32(0.01)
            payloads[prefix]["positions"] = substituted

    resign_artifact(substitute_avatar_skeleton)
    with pytest.raises(ValueError, match="FK reconstruction"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)

    restore_signed_artifact()

    def diverge_vrm_positions(_manifest, _metadata, payloads) -> None:  # noqa: ANN001
        diverged = payloads["vrm_positions"]["positions"].copy()
        diverged[:, FK_BONES.index("leftLittleDistal"), 0] += np.float32(0.001)
        payloads["vrm_positions"]["positions"] = diverged

    resign_artifact(diverge_vrm_positions)
    with pytest.raises(ValueError, match="positions differ"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)

    restore_signed_artifact()

    clip.sample.metadata["carrier_time_contract"] = {
        "status": "mismatch",
        "declared_duration_sec": 1.0,
        "decoded_duration_sec": 2.0,
        "delta_sec": 1.0,
        "tolerance_sec": 0.01,
    }
    with pytest.raises(ValueError, match="source carrier time contract failed"):
        pipeline.persist(output)
    clip.sample.metadata.pop("carrier_time_contract")

    downgraded_metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
    downgraded_metadata.pop("artifact_schema_version")
    paths.metadata.write_text(json.dumps(downgraded_metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact schema declaration"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)
    paths.metadata.write_text(json.dumps(metadata), encoding="utf-8")

    with np.load(paths.vrm_positions, allow_pickle=False) as stored:
        tampered = {key: np.asarray(stored[key]) for key in stored.files}
    tampered["positions"] = np.asarray(tampered["positions"], dtype=np.float32)
    tampered["positions"][0, 0, 0] = 1.0
    np.savez_compressed(paths.vrm_positions, **tampered)
    with pytest.raises(ValueError, match="array.*mismatch"):
        PreviewReader(_Registry()).read_processed_preview("amass", sample.sample_id)
    valid, validation_errors = pipeline.validate_existing(clip, paths)
    assert not valid
    assert any(
        "array" in error.lower() and "mismatch" in error.lower()
        for error in validation_errors
    )

    tampered["positions"][0, 0, 0] = 0.0
    np.savez_compressed(paths.vrm_positions, **tampered)
    with np.load(paths.source_snapshot, allow_pickle=False) as stored_source:
        malicious_source = {
            key: np.asarray(stored_source[key]) for key in stored_source.files
        }
    malicious_source["joint_names"] = np.asarray(
        [{"payload": "must-not-unpickle"}], dtype=object
    )
    np.savez_compressed(paths.source_snapshot, **malicious_source)
    for reader in (
        PreviewReader(_Registry()),
        PreviewReader(_Registry(), allow_trusted_legacy_pickle=True),
    ):
        with pytest.raises(
            ValueError, match="Object arrays cannot be loaded|unsafe or invalid NPZ"
        ):
            reader.read_processed_preview("amass", sample.sample_id)


def test_persist_refuses_draft_profile_before_writing_artifacts(tmp_path: Path) -> None:
    sample = SampleRef(
        dataset="motionx",
        sample_id="motion_data/smplx_322/aist/sample",
        source_path=Path("raw/motionx/sample.npy"),
        source_format="smplx_322_npy",
        codec_key="smplx_fullpose",
        fps=30.0,
        frame_count=1,
        duration_sec=1 / 30.0,
        metadata={"dataset_profile": "motionx_aist_smplx322", "sub_source": "aist"},
    )
    clip = RawClip(
        sample=sample,
        motion={
            "fullpose": np.zeros((1, 165), dtype=np.float32),
            "translation": np.zeros((1, 3)),
            "fps": 30.0,
        },
    )
    positions = np.zeros((1, 1, 3), dtype=np.float32)
    output = ProcessingOutput(
        clip=clip,
        source=SourceSnapshot(
            positions=positions, joint_names=["hips"], edges=[], fps=30.0
        ),
        canonical=CanonicalResult(
            sequence=pack_sequence(np.zeros((1, 3), dtype=np.float32)),
            positions=positions,
            joint_names=["hips"],
            edges=[],
            metadata={
                "codec": "smplx_fullpose",
                "declared_world_basis": "identity_y_up",
            },
        ),
        quality={},
        motion_uid=motion_uid("motionx", sample.sample_id, 1),
        paths={},
    )

    class _Paths:
        processed_root = tmp_path
        processing_version = "v0.4.0"

    class _Registry:
        paths = _Paths()

    pipeline = ProcessingPipeline.__new__(ProcessingPipeline)
    pipeline.registry = _Registry()
    with pytest.raises(ValueError, match="draft dataset profile"):
        pipeline.persist(output)
    paths = artifact_paths(tmp_path, "v0.4.0", "motionx", output.motion_uid)
    assert not any(path.exists() for path in paths.all_outputs())
    assert list(tmp_path.iterdir()) == []


def test_persist_refuses_draft_hand_solver_profile_before_writing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = SampleRef(
        dataset="grab",
        sample_id="s1/airplane_lift",
        source_path=Path("raw/grab/airplane_lift.npz"),
        source_format="smplx_grab_npz",
        codec_key="smplx_fullpose",
        fps=30.0,
        frame_count=1,
        duration_sec=1 / 30.0,
        metadata={"dataset_profile": "grab_smplx55"},
    )
    clip = RawClip(
        sample=sample,
        motion={
            "fullpose": np.zeros((1, 165), dtype=np.float32),
            "translation": np.zeros((1, 3), dtype=np.float32),
            "fps": 30.0,
        },
    )
    positions = np.zeros((1, 1, 3), dtype=np.float32)
    output = ProcessingOutput(
        clip=clip,
        source=SourceSnapshot(
            positions=positions,
            joint_names=["hips"],
            edges=[],
            fps=30.0,
        ),
        canonical=CanonicalResult(
            sequence=pack_sequence(np.zeros((1, 3), dtype=np.float32)),
            positions=positions,
            joint_names=["hips"],
            edges=[],
            metadata={
                "codec": "smplx_fullpose",
                "declared_world_basis": "z_up_to_y_up",
            },
        ),
        quality={},
        motion_uid=motion_uid("grab", sample.sample_id, 1),
        paths={},
    )

    class _Paths:
        processed_root = tmp_path
        processing_version = "v0.4.0"

    class _Registry:
        paths = _Paths()

    import virea.pipelines.processing as processing_module

    profile = processing_module.profile_for_sample(
        "grab", sample.sample_id, explicit_key="grab_smplx55"
    )
    from dataclasses import replace

    draft_hand_profile = replace(
        profile,
        hand_solver_validation_status="draft",
    )
    monkeypatch.setattr(
        processing_module,
        "profile_for_sample",
        lambda *_args, **_kwargs: draft_hand_profile,
    )

    pipeline = ProcessingPipeline.__new__(ProcessingPipeline)
    pipeline.registry = _Registry()
    paths = artifact_paths(tmp_path, "v0.4.0", "grab", output.motion_uid)
    with pytest.raises(ValueError, match="hand solver profile gate is draft"):
        pipeline.validate_existing(clip, paths)
    with pytest.raises(ValueError, match="hand solver profile gate is draft"):
        pipeline.persist(output)
    assert not any(path.exists() for path in paths.all_outputs())
    assert list(tmp_path.iterdir()) == []
