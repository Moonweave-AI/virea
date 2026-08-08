from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from virea.data.annotations import cache_data_sidecar, make_annotation, make_channel
from virea.data.types import RawClip, SampleRef
from virea.motion.canonical import pack_sequence
from virea.motion.codecs import CanonicalResult
from virea.motion.snapshot import SourceSnapshot
from virea.pipelines.artifacts import artifact_paths, motion_uid
from virea.pipelines.batch import BatchPipeline, ProcessingTask
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

    with pytest.raises(ValueError, match="object arrays require explicit trusted legacy migration"):
        PreviewReader(_Registry()).read_processed_preview("beat", "sample")
    preview = PreviewReader(_Registry(), allow_trusted_legacy_pickle=True).read_processed_preview("beat", "sample")

    assert len(preview.annotations) == 1
    annotation = preview.annotations[0]
    assert annotation["schema_version"] == "virea.annotation.v1.0.0"
    assert annotation["type"] == "gesture_or_semantic"
    assert annotation["text"] == "wave"
    assert annotation["start_frame"] == 0
    assert annotation["end_frame"] == 10
    assert annotation["provenance"] == "derived"
    assert annotation["original"]["legacy_record"]["text"] == "wave"
    assert any("Compatibility mode" in warning for warning in preview.validation_warnings)
    assert any("Trusted legacy migration mode" in warning for warning in preview.validation_warnings)
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
                "source": {"dataset": "beat", "source_id": "sample", "source_format": sample.source_format},
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

    cached = PreviewReader(_Registry()).read_processed_preview("beat", "sample", max_frames=5)
    assert cached.annotations == online.annotations
    assert cached.channels == online.channels
    assert cached.validation_warnings[: len(online.validation_warnings)] == online.validation_warnings
    assert any("Compatibility mode" in warning for warning in cached.validation_warnings)
    assert cached.sample.to_dict() == online.sample.to_dict()


def test_preview_reader_deterministically_selects_full_or_sufficient_crop(tmp_path: Path) -> None:
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
                    "source": {"dataset": "beat", "source_id": "sample", "source_format": "legacy"},
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


def test_preview_reader_rejects_known_truncated_artifact_as_full_clip(tmp_path: Path) -> None:
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
                "source": {"dataset": "beat", "source_id": "cropped", "source_format": "legacy"},
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
        metadata={"license_family": "test", "citation_keys": [], "dataset_profile": "amass_smplh156"},
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
    positions = np.zeros((2, 1, 3), dtype=np.float32)
    source = SourceSnapshot(positions=positions, joint_names=["hips"], edges=[], fps=30.0)
    canonical = CanonicalResult(
        sequence=pack_sequence(np.zeros((2, 3), dtype=np.float32)),
        positions=positions,
        joint_names=["hips"],
        edges=[],
        metadata={
            "codec": "smplh_body_hands",
            "source_profile": "smplh_body22_hands30",
            "declared_world_basis": "z_up_to_y_up",
            "root_rotation_semantics": "local_to_world",
            "world_basis": {"determinant": 1.0, "rotation_matrix": [[1, 0, 0], [0, 0, 1], [0, -1, 0]]},
        },
    )
    uid = motion_uid("amass", sample.sample_id, 2)
    output = ProcessingOutput(clip=clip, source=source, canonical=canonical, quality={}, motion_uid=uid, paths={})

    class _Paths:
        processed_root = tmp_path
        processing_version = "v0.2.0"

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

    paths = artifact_paths(tmp_path, "v0.2.0", "amass", uid)
    metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
    with np.load(paths.canonical_motion, allow_pickle=False) as payload:
        assert float(payload["fps"]) == 30.0
    assert metadata["time"]["effective_fps"] == 30.0
    assert metadata["time"]["duration_sec"] == pytest.approx(2 / 30.0)
    assert metadata["sample"]["fps"] == 30.0
    assert metadata["processing"]["profile"]["schema_version"] == "virea.dataset_profile.v1.0.0"
    assert len(metadata["processing"]["profile_sha256"]) == 64
    assert len(metadata["manifest_sha256"]) == 64
    manifest = json.loads(paths.canonical_manifest.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "virea.canonical_artifact.v1.0.0"
    assert manifest["profile"]["key"] == "amass_smplh156"
    assert manifest["canonical"]["frame_dim"] == 211
    assert manifest["rest"]["source"] == "virea_canonical_rest.v1"
    assert manifest["arrays"]
    assert len(manifest["sidecars"]) == 2
    assert all((tmp_path / reference["path"]).is_file() for reference in manifest["sidecars"])
    serialized_artifact = paths.canonical_manifest.read_text(encoding="utf-8") + paths.metadata.read_text(encoding="utf-8")
    assert str(tmp_path).replace("\\", "/") not in serialized_artifact.replace("\\", "/")
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
    assert not any("mismatch" in warning.lower() for warning in restored.validation_warnings)
    assert restored.annotations == clip.annotations
    assert restored.channels == clip.channels
    reader.read_source_preview("amass", sample.sample_id)
    assert load_calls == 1

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
    assert any("array" in error.lower() and "mismatch" in error.lower() for error in validation_errors)

    tampered["positions"][0, 0, 0] = 0.0
    np.savez_compressed(paths.vrm_positions, **tampered)
    with np.load(paths.source_snapshot, allow_pickle=False) as stored_source:
        malicious_source = {key: np.asarray(stored_source[key]) for key in stored_source.files}
    malicious_source["joint_names"] = np.asarray([{"payload": "must-not-unpickle"}], dtype=object)
    np.savez_compressed(paths.source_snapshot, **malicious_source)
    for reader in (
        PreviewReader(_Registry()),
        PreviewReader(_Registry(), allow_trusted_legacy_pickle=True),
    ):
        with pytest.raises(ValueError, match="Object arrays cannot be loaded|unsafe or invalid NPZ"):
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
        motion={"fullpose": np.zeros((1, 165), dtype=np.float32), "translation": np.zeros((1, 3)), "fps": 30.0},
    )
    positions = np.zeros((1, 1, 3), dtype=np.float32)
    output = ProcessingOutput(
        clip=clip,
        source=SourceSnapshot(positions=positions, joint_names=["hips"], edges=[], fps=30.0),
        canonical=CanonicalResult(
            sequence=pack_sequence(np.zeros((1, 3), dtype=np.float32)),
            positions=positions,
            joint_names=["hips"],
            edges=[],
            metadata={"codec": "smplx_fullpose", "declared_world_basis": "identity_y_up"},
        ),
        quality={},
        motion_uid=motion_uid("motionx", sample.sample_id, 1),
        paths={},
    )

    class _Paths:
        processed_root = tmp_path
        processing_version = "v0.2.0"

    class _Registry:
        paths = _Paths()

    pipeline = ProcessingPipeline.__new__(ProcessingPipeline)
    pipeline.registry = _Registry()
    with pytest.raises(ValueError, match="draft dataset profile"):
        pipeline.persist(output)
    paths = artifact_paths(tmp_path, "v0.2.0", "motionx", output.motion_uid)
    assert not any(path.exists() for path in paths.all_outputs())
    assert list(tmp_path.iterdir()) == []
