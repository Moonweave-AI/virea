from __future__ import annotations

import json
import os
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from virea.data.adapters.amass import AMASSAdapter
from virea.data.adapters.babel import BABELAdapter
from virea.data.adapters.beat import BEATAdapter
from virea.data.adapters.grab import GRABAdapter
from virea.data.adapters.humanml3d import HumanML3DAdapter
from virea.data.adapters.motionx import MotionXAdapter
from virea.data.adapters.susuinteracts import SuSuInterActsAdapter
from virea.data.annotations import (
    AnnotationV1,
    cache_data_sidecar,
    cache_numpy_sidecar,
    clip_annotations,
    make_annotation,
    make_channel,
    materialize_sidecars,
    resolve_cached_sidecar,
    security_manifest,
    sidecar_cache_health,
)
from virea.data.bvh import (
    BEAT_BODY_SOURCE_JOINT,
    BEAT_HAND_SOURCE_JOINT,
    BVHMotion,
    beat_bvh_to_body22,
    parse_bvh,
)
from virea.data.types import DatasetRecord, PreviewPayload, RawClip, SampleRef
from virea.motion.canonical import (
    CANONICAL_TO_VRM_BONE_NAME,
    CORE_INDEX,
    HAND_INDEX,
    unpack_sequence,
)
from virea.motion.codecs import default_codecs
from virea.motion.rotation import axis_angle_to_quat_xyzw, quat_to_matrix_xyzw
from virea.motion.skeleton import CANONICAL_PARENT, FK_BONES


def _record(key: str) -> DatasetRecord:
    return DatasetRecord(
        key=key,
        name=key,
        full_name=key,
        type="test",
        raw_dir=key,
        adapter="test.Adapter",
        license_family="test",
        citation_keys=(),
        modalities={},
    )


class _MarkerOnUnpickle:
    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self):  # noqa: ANN204
        expression = (
            "__import__('pathlib').Path("
            + repr(str(self.marker))
            + ").write_text('executed', encoding='utf-8')"
        )
        return eval, (expression,)


def test_annotation_v1_has_stable_identity_and_requires_reasoning() -> None:
    base = dict(
        dataset="amass",
        sample_id="subject/walk",
        source="amass.source_path.filename",
        record_key="filename",
        ordinal=0,
        level="sequence",
        type="inferred_action_name",
        provenance="derived",
        reasoning="Derived from filename.",
    )
    first = make_annotation(**base, text="walk")
    translated = make_annotation(**base, text="walking")
    assert first["id"] == translated["id"]
    assert set(first) == {
        "schema_version",
        "id",
        "level",
        "type",
        "text",
        "bodypart",
        "start_sec",
        "end_sec",
        "start_frame",
        "end_frame",
        "confidence",
        "source",
        "provenance",
        "reasoning",
        "original",
        "clipped",
        "extras",
    }
    invalid = dict(first)
    invalid["reasoning"] = None
    with pytest.raises(ValidationError):
        AnnotationV1.model_validate(invalid)


def test_raw_clip_limited_uses_half_open_time_and_preserves_original() -> None:
    sample = SampleRef(
        dataset="beat",
        sample_id="clip",
        source_path=Path("clip.npz"),
        source_format="test",
        codec_key="axis_angle_body22",
        fps=10.0,
        frame_count=100,
        duration_sec=10.0,
    )
    annotation = make_annotation(
        dataset="beat",
        sample_id="clip",
        source="beat.tsv",
        record_key="0",
        ordinal=0,
        level="action",
        type="gesture",
        text="wave",
        provenance="native",
        start_sec=1.0,
        end_sec=5.0,
        fps=10.0,
        original={"line": "wave"},
    )
    channel = make_channel(
        dataset="beat",
        sample_id="clip",
        source="test.curve",
        record_key="curve",
        ordinal=0,
        kind="face",
        availability="inline",
        representation="weights",
        timebase={"start_frame": 0, "end_frame": 100, "interval": "half_open"},
        fps=10.0,
        frame_count=100,
        shape=[100, 1],
        preview={"weights": [[float(index)] for index in range(100)]},
    )
    clip = RawClip(
        sample=sample,
        motion={"positions": np.zeros((100, 1, 3), dtype=np.float32), "fps": 10.0},
        annotations=[annotation],
        channels=[channel],
    ).limited(20)
    assert clip.sample.frame_count == 20
    assert clip.sample.duration_sec == 2.0
    assert clip.annotations[0]["start_frame"] == 10
    assert clip.annotations[0]["end_frame"] == 20
    assert clip.annotations[0]["end_sec"] == 2.0
    assert clip.annotations[0]["clipped"] is True
    assert clip.annotations[0]["original"]["time"]["end_sec"] == 5.0
    assert clip.channels[0]["frame_count"] == 20
    assert clip.channels[0]["shape"] == [20, 1]
    assert len(clip.channels[0]["preview"]["weights"]) == 20


def test_annotation_clip_retains_outside_records_for_detail_audit() -> None:
    values = [
        make_annotation(
            dataset="beat",
            sample_id="clip",
            source="beat.tsv",
            record_key=key,
            ordinal=index,
            level="action",
            type="gesture",
            text=key,
            provenance="native",
            start_frame=start,
            end_frame=end,
            fps=10.0,
        )
        for index, (key, start, end) in enumerate(
            (("partial", 10, 30), ("outside", 30, 40), ("boundary", 0, 20))
        )
    ]
    clipped, warnings = clip_annotations(
        values,
        dataset="beat",
        sample_id="clip",
        fps=10.0,
        frame_count=20,
    )
    assert len(clipped) == 3
    partial, outside, boundary = clipped
    assert (partial["start_frame"], partial["end_frame"], partial["clipped"]) == (
        10,
        20,
        True,
    )
    assert (outside["start_frame"], outside["end_frame"], outside["clipped"]) == (
        20,
        20,
        True,
    )
    assert outside["extras"]["clipped_out"] is True
    assert outside["original"]["time"]["start_frame"] == 30
    assert (boundary["start_frame"], boundary["end_frame"], boundary["clipped"]) == (
        0,
        20,
        False,
    )
    assert any("retained as clipped-out" in warning for warning in warnings)


def test_unknown_json_is_bounded_redacted_and_materialized_as_sidecar(
    tmp_path: Path,
) -> None:
    annotation = make_annotation(
        dataset="beat",
        sample_id="sample",
        source="beat.test",
        record_key="record",
        ordinal=0,
        level="metadata",
        type="unknown_fields",
        text="audit",
        provenance="native",
        extras={
            "password": "do-not-expose",
            "auth_token": "auth-secret",
            "client_secret": "client-secret",
            "machine_path": r"C:\Users\person\private.json",
            "file_url": "file:///C:/Users/person/private.txt",
            "large_values": list(range(513)),
        },
    )
    serialized = json.dumps(annotation, ensure_ascii=False)
    assert "do-not-expose" not in serialized
    assert "auth-secret" not in serialized
    assert "client-secret" not in serialized
    assert r"C:\Users\person\private.json" not in serialized
    assert "file:///C:/Users/person/private.txt" not in serialized
    assert annotation["extras"]["password"]["redaction"]["reason"] == "sensitive_key"
    assert "sidecar" in annotation["extras"]["large_values"]
    manifest = security_manifest(annotation)
    assert manifest["sidecars"]
    assert len(manifest["redactions"]) >= 2
    references = materialize_sidecars(annotation, tmp_path)
    assert references
    for reference in references:
        assert (tmp_path / reference["path"]).is_file()


def test_default_sidecar_cache_stays_outside_the_repository() -> None:
    import virea.data.annotations as annotation_module

    project_root = Path(__file__).resolve().parents[1]
    cache_parent = annotation_module._SIDECAR_CACHE_ROOT.parent
    assert cache_parent == annotation_module._SIDECAR_CACHE_PARENT
    assert not cache_parent.is_relative_to(project_root)
    assert annotation_module._SIDECAR_CACHE_ROOT.name.startswith("sidecar-cache-v1-")
    assert cache_parent.name == "annotations"


def test_process_sidecar_cleanup_preserves_other_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import virea.data.annotations as annotation_module

    parent = tmp_path / ".virea-runtime"
    own_cache = parent / "sidecar-cache-v1-100"
    sibling_cache = parent / "sidecar-cache-v1-200"
    own_cache.mkdir(parents=True)
    sibling_cache.mkdir()
    (own_cache / "blob").write_bytes(b"owned")
    (sibling_cache / "blob").write_bytes(b"other")
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_PARENT", parent)
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_ROOT", own_cache)

    annotation_module._cleanup_process_sidecar_cache()

    assert not own_cache.exists()
    assert (sibling_cache / "blob").read_bytes() == b"other"


def test_sidecar_cache_is_atomic_bounded_and_lru(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import virea.data.annotations as annotation_module

    cache_root = tmp_path / "cache"
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_ROOT", cache_root)
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_MAX_FILE_BYTES", 64)
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_MAX_TOTAL_BYTES", 130)

    first = cache_data_sidecar(
        b"a" * 60, media_type="application/octet-stream", encoding="binary"
    )
    second = cache_data_sidecar(
        b"b" * 60, media_type="application/octet-stream", encoding="binary"
    )
    second_path = cache_root / second["sha256"]
    os.utime(second_path, ns=(1, 1))
    assert resolve_cached_sidecar(first["sha256"]) is not None
    third = cache_data_sidecar(
        b"c" * 60, media_type="application/octet-stream", encoding="binary"
    )
    assert resolve_cached_sidecar(second["sha256"]) is None
    assert resolve_cached_sidecar(first["sha256"]) is not None
    assert resolve_cached_sidecar(third["sha256"]) is not None

    with ThreadPoolExecutor(max_workers=8) as executor:
        references = list(
            executor.map(
                lambda _index: cache_data_sidecar(
                    b"d" * 50,
                    media_type="application/octet-stream",
                    encoding="binary",
                ),
                range(16),
            )
        )
    assert len({item["sha256"] for item in references}) == 1
    cached = resolve_cached_sidecar(references[0]["sha256"])
    assert cached is not None and cached.read_bytes() == b"d" * 50
    health = sidecar_cache_health()
    assert health["status"] == "healthy"
    assert health["byte_length"] <= health["max_total_bytes"]
    processed_root = tmp_path / "processed"
    materialize_sidecars({"sidecar": references[0]}, processed_root)
    cached.unlink()
    (processed_root / references[0]["path"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="materialized sidecar.*mismatch"):
        materialize_sidecars({"sidecar": references[0]}, processed_root)
    with pytest.raises(ValueError, match="per file"):
        cache_data_sidecar(
            b"x" * 65, media_type="application/octet-stream", encoding="binary"
        )


def test_numpy_sidecar_uses_lossless_compression_before_capacity_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import virea.data.annotations as annotation_module

    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_MAX_FILE_BYTES", 512)
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_MAX_TOTAL_BYTES", 4096)
    values = np.zeros((4096,), dtype=np.int8)
    reference = cache_numpy_sidecar(values)
    assert reference["media_type"] == "application/x-npz"
    cached = resolve_cached_sidecar(reference["sha256"])
    assert cached is not None
    with np.load(cached, allow_pickle=False) as payload:
        np.testing.assert_array_equal(payload["values"], values)


def test_oversized_contact_and_audio_degrade_explicitly_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import virea.data.annotations as annotation_module

    monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_MAX_FILE_BYTES", 32)
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_MAX_TOTAL_BYTES", 256)

    grab_root = tmp_path / "grab"
    grab_path = grab_root / "s1" / "large_contact.npz"
    grab_path.parent.mkdir(parents=True)
    body = {"params": {"fullpose": np.zeros((2, 165)), "transl": np.zeros((2, 3))}}
    contact = {
        "body": np.zeros((2, 256), dtype=np.int8),
        "object": np.zeros((2, 256), dtype=np.int8),
    }
    np.savez(
        grab_path,
        body=np.asarray(body, dtype=object),
        contact=np.asarray(contact, dtype=object),
        framerate=30.0,
    )
    grab_clip = GRABAdapter(_record("grab"), grab_root).load("s1/large_contact")
    contact_channels = [
        item
        for item in grab_clip.channels
        if item["representation"] == "categorical_per_element"
    ]
    assert len(contact_channels) == 2
    assert all(item["availability"] == "metadata_only" for item in contact_channels)
    assert all(
        "capacity" in str(item["reason_unavailable"]).lower()
        for item in contact_channels
    )
    assert all(
        len(item["extras"]["native_array_sha256"]) == 64 for item in contact_channels
    )

    audio_path = tmp_path / "large.wav"
    with wave.open(str(audio_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 100)
    beat_channel = BEATAdapter(_record("beat"), tmp_path)._audio_channel(
        "sample", audio_path, 30.0, 1
    )
    assert beat_channel["availability"] == "metadata_only"
    assert len(beat_channel["extras"]["native_sha256"]) == 64

    susu_root = tmp_path / "susu"
    susu_motion = susu_root / "motion_data" / "sample.npy"
    susu_motion.parent.mkdir(parents=True)
    body_motion = np.zeros((2, 12), dtype=np.float32)
    body_motion[1, 0] = 1.0
    np.save(susu_motion, {"body": body_motion})
    susu_audio = susu_root / "wav_data" / "sample.wav"
    susu_audio.parent.mkdir(parents=True)
    susu_audio.write_bytes(audio_path.read_bytes())
    susu_clip = SuSuInterActsAdapter(_record("susuinteracts"), susu_root).load("sample")
    susu_channel = next(item for item in susu_clip.channels if item["kind"] == "audio")
    assert susu_channel["availability"] == "metadata_only"
    assert len(susu_channel["extras"]["native_sha256"]) == 64


def test_large_face_curves_remain_lossless_external_channels(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import virea.data.annotations as annotation_module

    monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    monkeypatch.setattr(annotation_module, "_SIDECAR_CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(
        annotation_module, "_SIDECAR_CACHE_MAX_FILE_BYTES", 64 * 1024 * 1024
    )
    monkeypatch.setattr(
        annotation_module, "_SIDECAR_CACHE_MAX_TOTAL_BYTES", 128 * 1024 * 1024
    )

    motionx_id = "motion_data/smplx_322/source/sample"
    motionx_path = tmp_path / "motionx" / f"{motionx_id}.npy"
    motionx_path.parent.mkdir(parents=True)
    motionx_values = np.zeros((10_500, 322), dtype=np.float32)
    motionx_values[:, 159:209] = 0.25
    np.save(motionx_path, motionx_values)
    motionx_clip = MotionXAdapter(_record("motionx"), tmp_path / "motionx").load(
        motionx_id, max_frames=1
    )
    motionx_face = next(
        item
        for item in motionx_clip.channels
        if item["source"] == "motionx.smplx_322.face_expression_slice"
    )
    assert motionx_face["availability"] == "external"
    assert motionx_face["shape"] == [10_500, 50]
    assert resolve_cached_sidecar(motionx_face["data_ref"]["sha256"]) is not None

    susu_root = tmp_path / "susu_large_face"
    susu_motion_path = susu_root / "motion_data" / "sample.npy"
    susu_motion_path.parent.mkdir(parents=True)
    susu_body = np.zeros((11_000, 12), dtype=np.float32)
    susu_body[:, 0] = np.linspace(0.0, 1.0, 11_000)
    np.save(susu_motion_path, {"body": susu_body})
    susu_face_path = susu_root / "arkit_data" / "sample.npy"
    susu_face_path.parent.mkdir(parents=True)
    np.save(susu_face_path, np.full((11_000, 51), 0.5, dtype=np.float32))
    susu_clip = SuSuInterActsAdapter(_record("susuinteracts"), susu_root).load(
        "sample", max_frames=1
    )
    susu_face = next(item for item in susu_clip.channels if item["kind"] == "face")
    assert susu_face["availability"] == "external"
    assert susu_face["shape"] == [11_000, 51]
    assert resolve_cached_sidecar(susu_face["data_ref"]["sha256"]) is not None

    beat_face_path = tmp_path / "beat_face.json"
    beat_face_path.write_text(
        json.dumps(
            {
                "names": [f"c{index}" for index in range(51)],
                "frames": [
                    {"time": index / 60.0, "weights": [0.0] * 51}
                    for index in range(11_000)
                ],
            }
        ),
        encoding="utf-8",
    )
    beat_face = BEATAdapter(_record("beat"), tmp_path)._face_channel(
        "sample", beat_face_path
    )
    assert beat_face["availability"] == "external"
    assert beat_face["shape"] == [11_000, 51]
    assert resolve_cached_sidecar(beat_face["data_ref"]["sha256"]) is not None


def test_preview_sample_snapshot_never_exposes_raw_absolute_paths_or_secrets(
    tmp_path: Path,
) -> None:
    source_path = (tmp_path / "raw" / "clip.npz").resolve()
    sample = SampleRef(
        dataset="amass",
        sample_id="clip",
        source_path=source_path,
        source_format="npz",
        codec_key="axis_angle_body22",
        fps=30.0,
        frame_count=1,
        duration_sec=1 / 30.0,
        related_paths={"text": (tmp_path / "raw" / "clip.txt").resolve()},
        metadata={"api_key": "private-value"},
    )
    payload = PreviewPayload(
        stage="raw",
        sample=sample,
        fps=30.0,
        positions=np.zeros((1, 1, 3), dtype=np.float32),
        joint_names=["hips"],
        edges=[],
    ).to_dict()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(source_path) not in serialized
    assert "private-value" not in serialized
    assert (
        payload["sample"]["source_path"]["redaction"]["reason"]
        == "absolute_path_not_exposed"
    )


def test_adapter_sample_id_cannot_escape_dataset_root(tmp_path: Path) -> None:
    sibling = tmp_path / "beat" / "pose" / "escape.npz"
    sibling.parent.mkdir(parents=True)
    np.savez(sibling, poses=np.zeros((1, 66), dtype=np.float32))
    amass_root = tmp_path / "amass"
    amass_root.mkdir()
    with pytest.raises(ValueError, match="escaped raw root"):
        AMASSAdapter(_record("amass"), amass_root).load(
            "../beat/pose/escape", max_frames=1
        )


def test_raw_numpy_pickle_is_disabled_by_default_and_never_executes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", raising=False)
    marker = tmp_path / "pickle-executed.txt"
    amass_path = tmp_path / "amass" / "malicious.npz"
    amass_path.parent.mkdir(parents=True)
    np.savez(amass_path, poses=np.asarray([_MarkerOnUnpickle(marker)], dtype=object))
    with pytest.raises(ValueError, match="Object arrays cannot be loaded"):
        AMASSAdapter(_record("amass"), amass_path.parent).load("malicious")
    assert not marker.exists()

    grab_root = tmp_path / "grab"
    grab_path = grab_root / "s1" / "safe.npz"
    grab_path.parent.mkdir(parents=True)
    body = {"params": {"fullpose": np.zeros((1, 165)), "transl": np.zeros((1, 3))}}
    np.savez(grab_path, body=np.asarray(body, dtype=object), framerate=30.0)
    with pytest.raises(
        PermissionError, match="VIREA_ALLOW_TRUSTED_RAW_PICKLE=1"
    ) as blocked:
        GRABAdapter(_record("grab"), grab_root).load("s1/safe")
    assert str(grab_path) not in str(blocked.value)
    monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    trusted = GRABAdapter(_record("grab"), grab_root).load("s1/safe")
    assert trusted.sample.frame_count == 1


def test_amass_156_keeps_hands_and_marks_filename_as_derived(tmp_path: Path) -> None:
    path = tmp_path / "subject" / "wave_poses.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        poses=np.zeros((2, 156), dtype=np.float32),
        trans=np.zeros((2, 3)),
        mocap_framerate=20.0,
    )
    clip = AMASSAdapter(_record("amass"), tmp_path).load("subject/wave_poses")
    assert clip.sample.codec_key == "smplh_body_hands"
    assert clip.sample.metadata["dataset_profile"] == "amass_smplh156"
    assert clip.annotations[0]["provenance"] == "derived"
    assert "filename" in clip.annotations[0]["reasoning"].lower()


def test_babel_resolves_amass_alias_and_keeps_seq_and_frame_annotations(
    tmp_path: Path,
) -> None:
    babel_root = tmp_path / "babel"
    amass_path = tmp_path / "amass" / "BMLrub" / "rub001" / "clip.npz"
    amass_path.parent.mkdir(parents=True)
    np.savez(
        amass_path,
        poses=np.zeros((2, 156), dtype=np.float32),
        trans=np.zeros((2, 3)),
        mocap_framerate=20.0,
    )
    annotation_dir = babel_root / "babel-teach"
    annotation_dir.mkdir(parents=True)
    record = {
        "1": {
            "feat_p": "BMLrub/BioMotionLab_NTroje/rub001/clip.npz",
            "dur": 0.1,
            "seq_ann": {
                "labels": [{"raw_label": "walk", "proc_label": "walk", "extra": 1}]
            },
            "frame_ann": {
                "labels": [{"raw_label": "turn", "start_t": 0.0, "end_t": 0.1}]
            },
        }
    }
    (annotation_dir / "train.json").write_text(json.dumps(record), encoding="utf-8")
    (annotation_dir / "val.json").write_text("{}", encoding="utf-8")
    adapter = BABELAdapter(_record("babel"), babel_root)
    clip = adapter.load("babel-teach/train/1")
    assert clip.sample.codec_key == "smplh_body_hands"
    assert (
        clip.sample.metadata["carrier_path_rule"]
        == "mapped_dataset_drop_archive_wrapper"
    )
    assert [item["level"] for item in clip.annotations] == ["sequence", "action"]
    assert all(item["provenance"] == "native" for item in clip.annotations)


@pytest.mark.parametrize(
    ("seq_value", "frame_value"),
    [(None, None), ([], []), (None, {"labels": []})],
)
def test_babel_accepts_nullable_or_empty_annotation_blocks(
    tmp_path: Path,
    seq_value: object,
    frame_value: object,
) -> None:
    babel_root = tmp_path / "babel"
    carrier = tmp_path / "amass" / "BMLrub" / "rub001" / "clip.npz"
    carrier.parent.mkdir(parents=True)
    np.savez(
        carrier,
        poses=np.zeros((2, 156), dtype=np.float32),
        trans=np.zeros((2, 3)),
        mocap_framerate=20.0,
    )
    annotation_dir = babel_root / "babel-teach"
    annotation_dir.mkdir(parents=True)
    record = {
        "1": {
            "feat_p": "BMLrub/BioMotionLab_NTroje/rub001/clip.npz",
            "dur": 0.1,
            "seq_ann": seq_value,
            "frame_ann": frame_value,
        }
    }
    (annotation_dir / "train.json").write_text(json.dumps(record), encoding="utf-8")
    (annotation_dir / "val.json").write_text("{}", encoding="utf-8")
    clip = BABELAdapter(_record("babel"), babel_root).load(
        "babel-teach/train/1", max_frames=2
    )
    assert clip.annotations == []


def test_babel_annotation_carrier_path_cannot_escape_amass_root(tmp_path: Path) -> None:
    adapter = BABELAdapter(_record("babel"), tmp_path / "babel")
    with pytest.raises(ValueError, match="escaped the sibling AMASS root"):
        adapter._annotation_motion_path({"feat_p": "../../private/outside.npz"})


def test_beat_preserves_full_tsv_and_semantic_score_scale(tmp_path: Path) -> None:
    path = tmp_path / "labels.txt"
    path.write_text("07_iconic_h\t1.0\t2.0\t1.0\t0.7\thuge\textra\n", encoding="utf-8")
    adapter = BEATAdapter(_record("beat"), tmp_path)
    _text, annotations = adapter._read_text(path, "pose/clip", 30.0)
    item = annotations[0]
    assert item["confidence"] is None
    assert item["extras"]["semantic_relevancy_score"] == 0.7
    assert item["extras"]["semantic_relevancy_scale"] == {
        "min": 0.0,
        "max": 10.0,
        "unit": "ordinal",
    }
    assert item["original"]["line"].endswith("extra")


def _write_beat_body_fixture(
    path: Path,
    *,
    declared_frame_count: int = 2,
    payload_frame_count: int = 2,
) -> None:
    if payload_frame_count not in {1, 2} or declared_frame_count < payload_frame_count:
        raise ValueError("fixture supports one or two payload frames")
    children = {
        "Hips": ["Spine", "RightUpLeg", "LeftUpLeg"],
        "Spine": ["Spine1"],
        "Spine1": ["Spine2"],
        "Spine2": ["Spine3"],
        "Spine3": ["Neck", "RightShoulder", "LeftShoulder"],
        "Neck": ["Neck1"],
        "Neck1": ["Head"],
        "RightShoulder": ["RightArm"],
        "RightArm": ["RightForeArm"],
        "RightForeArm": ["RightHand"],
        "LeftShoulder": ["LeftArm"],
        "LeftArm": ["LeftForeArm"],
        "LeftForeArm": ["LeftHand"],
        "RightUpLeg": ["RightLeg"],
        "RightLeg": ["RightFoot"],
        "RightFoot": ["RightForeFoot"],
        "RightForeFoot": ["RightToeBase"],
        "LeftUpLeg": ["LeftLeg"],
        "LeftLeg": ["LeftFoot"],
        "LeftFoot": ["LeftForeFoot"],
        "LeftForeFoot": ["LeftToeBase"],
    }
    for side in ("Right", "Left"):
        hand = f"{side}Hand"
        children[hand] = [f"{hand}Middle1", f"{hand}Ring", f"{hand}Index"]
        for finger in ("Middle",):
            for index in range(1, 4):
                children[f"{hand}{finger}{index}"] = [f"{hand}{finger}{index + 1}"]
        children[f"{hand}Ring"] = [f"{hand}Ring1", f"{hand}Pinky"]
        for finger in ("Ring", "Pinky", "Index", "Thumb"):
            for index in range(1, 4):
                children[f"{hand}{finger}{index}"] = [f"{hand}{finger}{index + 1}"]
        children[f"{hand}Pinky"] = [f"{hand}Pinky1"]
        children[f"{hand}Index"] = [f"{hand}Index1", f"{hand}Thumb1"]
    channel_starts: dict[str, int] = {}
    lines = ["HIERARCHY"]
    channel_cursor = 0

    def emit(name: str, depth: int) -> None:
        nonlocal channel_cursor
        indent = "\t" * depth
        lines.append(f"{indent}{'ROOT' if name == 'Hips' else 'JOINT'} {name}")
        lines.append(f"{indent}{{")
        offset = "0 0 0" if name == "Hips" else "0 1 0"
        lines.append(f"{indent}\tOFFSET {offset}")
        if name == "Hips":
            lines.append(
                f"{indent}\tCHANNELS 6 Xposition Yposition Zposition Xrotation Yrotation Zrotation"
            )
            channel_starts[name] = channel_cursor + 3
            channel_cursor += 6
        else:
            lines.append(f"{indent}\tCHANNELS 3 Xrotation Yrotation Zrotation")
            channel_starts[name] = channel_cursor
            channel_cursor += 3
        for child in children.get(name, []):
            emit(child, depth + 1)
        lines.append(f"{indent}}}")

    emit("Hips", 0)
    first = np.zeros(channel_cursor, dtype=np.float32)
    second = first.copy()
    second[channel_starts["Spine2"]] = 10.0
    second[channel_starts["Spine3"] + 1] = 20.0
    second[channel_starts["Neck1"] + 2] = 30.0
    second[channel_starts["Head"]] = 5.0
    second[channel_starts["LeftForeFoot"] + 1] = 15.0
    second[channel_starts["LeftToeBase"] + 2] = 7.0
    second[channel_starts["LeftHandIndex"]] = 11.0
    second[channel_starts["LeftHandIndex1"] + 1] = 13.0
    second[channel_starts["LeftHandThumb1"] + 2] = 17.0
    second[channel_starts["LeftHandThumb2"]] = 19.0
    second[channel_starts["LeftHandThumb3"] + 1] = 23.0
    payload_rows = [first, second][:payload_frame_count]
    lines.extend(
        [
            "MOTION",
            f"Frames: {declared_frame_count}",
            "Frame Time: 0.008333333333333333",
            *(" ".join(str(float(value)) for value in row) for row in payload_rows),
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def test_beat_loads_full_bvh_and_composes_skipped_joint_rotations(
    tmp_path: Path,
) -> None:
    _write_beat_body_fixture(tmp_path / "hf" / "speaker" / "clip.bvh")
    adapter = BEATAdapter(_record("beat"), tmp_path)
    discovered = adapter.discover()
    assert [item.sample_id for item in discovered] == ["pose/speaker/clip"]
    assert discovered[0].source_format == "beat_bvh_full_hierarchy"
    clip = adapter.load("pose/speaker/clip")
    assert clip.sample.fps == 120.0
    assert clip.motion["fps"] == 120.0
    assert clip.sample.duration_sec == pytest.approx(2.0 / 120.0)
    assert clip.sample.metadata["fps_source"] == "bvh_frame_time"
    assert clip.sample.metadata["dataset_profile"] == "beat_bvh_full75_runtime"
    assert clip.sample.metadata["legacy_pose_pack_status"] == "absent"
    assert clip.sample.metadata["collapsed_rotation_paths"]["upperChest"] == [
        "Spine2",
        "Spine3",
    ]
    assert clip.sample.metadata["collapsed_rotation_paths"]["head"] == ["Neck1", "Head"]
    matrices = quat_to_matrix_xyzw(
        axis_angle_to_quat_xyzw(clip.motion["poses"].reshape(2, 22, 3))
    )

    def rotation(axis: str, degrees: float) -> np.ndarray:
        vector = np.zeros(3, dtype=np.float32)
        vector["XYZ".index(axis)] = np.deg2rad(degrees)
        return quat_to_matrix_xyzw(axis_angle_to_quat_xyzw(vector))

    np.testing.assert_allclose(
        matrices[1, 9],
        rotation("X", 10.0) @ rotation("Y", 20.0),
        atol=1e-5,
    )
    np.testing.assert_allclose(
        matrices[1, 15],
        rotation("Z", 30.0) @ rotation("X", 5.0),
        atol=1e-5,
    )
    np.testing.assert_allclose(
        matrices[1, 10],
        rotation("Y", 15.0) @ rotation("Z", 7.0),
        atol=1e-5,
    )
    hand_matrices = quat_to_matrix_xyzw(clip.motion["hand_quaternions_xyzw"])
    np.testing.assert_allclose(
        hand_matrices[1, 3],
        rotation("X", 11.0) @ rotation("Y", 13.0),
        atol=1e-5,
    )
    assert CANONICAL_TO_VRM_BONE_NAME["leftThumbProximal"] == "leftThumbMetacarpal"
    np.testing.assert_allclose(
        hand_matrices[1, HAND_INDEX["leftThumbProximal"]],
        rotation("X", 11.0) @ rotation("Z", 17.0),
        atol=1e-5,
    )
    np.testing.assert_allclose(
        hand_matrices[1, HAND_INDEX["leftThumbIntermediate"]],
        rotation("X", 19.0),
        atol=1e-5,
    )
    np.testing.assert_allclose(
        hand_matrices[1, HAND_INDEX["leftThumbDistal"]],
        rotation("Y", 23.0),
        atol=1e-5,
    )

    canonical = default_codecs()[clip.sample.codec_key].to_canonical(clip)
    decoded = unpack_sequence(canonical.sequence)
    canonical_hands = quat_to_matrix_xyzw(decoded["hand_quats_xyzw"])
    thumb_proximal = canonical_hands[1, HAND_INDEX["leftThumbProximal"]]
    thumb_intermediate = canonical_hands[1, HAND_INDEX["leftThumbIntermediate"]]
    thumb_distal = canonical_hands[1, HAND_INDEX["leftThumbDistal"]]
    np.testing.assert_allclose(
        thumb_proximal,
        rotation("X", 11.0) @ rotation("Z", 17.0),
        atol=1e-5,
    )
    np.testing.assert_allclose(
        thumb_proximal @ thumb_intermediate,
        rotation("X", 11.0) @ rotation("Z", 17.0) @ rotation("X", 19.0),
        atol=1e-5,
    )
    np.testing.assert_allclose(
        thumb_proximal @ thumb_intermediate @ thumb_distal,
        rotation("X", 11.0)
        @ rotation("Z", 17.0)
        @ rotation("X", 19.0)
        @ rotation("Y", 23.0),
        atol=1e-5,
    )
    assert canonical.metadata["hand_channels"] == "adapter_native_parent_path_collapsed"
    assert canonical.metadata["rest_frame_correction_policy"] == (
        "identity_world_aligned_bvh_axes"
    )

    # Independent endpoint-orientation oracle across all 52 target bones.  It
    # catches body/hand packing, non-standard palm hierarchy and root ordering
    # mistakes that local-path assertions alone cannot see.
    raw_motion = parse_bvh(tmp_path / "hf" / "speaker" / "clip.bvh")
    raw_world: dict[str, np.ndarray] = {}
    for joint in raw_motion.joints:
        local = np.eye(3, dtype=np.float32)
        for channel, channel_index in zip(joint.channels, joint.channel_indices):
            if channel.endswith("rotation"):
                local = local @ rotation(
                    channel[0].upper(),
                    float(raw_motion.frames[1, channel_index]),
                )
        raw_world[joint.name] = (
            local if joint.parent is None else raw_world[joint.parent] @ local
        )

    root_matrix = quat_to_matrix_xyzw(decoded["root_rotation_xyzw"])[1]
    core_matrices = quat_to_matrix_xyzw(decoded["core_quats_xyzw"])[1]
    final_hand_matrices = quat_to_matrix_xyzw(decoded["hand_quats_xyzw"])[1]
    target_world: dict[str, np.ndarray] = {}
    for bone_name in FK_BONES:
        if bone_name == "hips":
            target_world[bone_name] = root_matrix
            continue
        local = (
            core_matrices[CORE_INDEX[bone_name]]
            if bone_name in CORE_INDEX
            else final_hand_matrices[HAND_INDEX[bone_name]]
        )
        target_world[bone_name] = target_world[CANONICAL_PARENT[bone_name]] @ local
    source_mapping = {**BEAT_BODY_SOURCE_JOINT, **BEAT_HAND_SOURCE_JOINT}
    for bone_name in FK_BONES:
        np.testing.assert_allclose(
            target_world[bone_name],
            raw_world[source_mapping[bone_name]],
            atol=1e-5,
            err_msg=f"BEAT endpoint world orientation mismatch at {bone_name}",
        )


def test_beat_chunked_decoder_matches_single_chunk_across_boundaries(
    tmp_path: Path,
) -> None:
    bvh_path = tmp_path / "chunked.bvh"
    _write_beat_body_fixture(bvh_path)
    parsed = parse_bvh(bvh_path)
    frames = np.repeat(parsed.frames[1:2], 7, axis=0)
    frame_scale = np.arange(1, 8, dtype=np.float32).reshape(-1, 1)
    frames *= frame_scale
    frames[0] = parsed.frames[0]
    frames[:, 0] = np.arange(7, dtype=np.float32) * 2.5
    frames[:, 1] = np.arange(7, dtype=np.float32) * -1.25
    frames[:, 2] = np.arange(7, dtype=np.float32) * 0.5
    motion = BVHMotion(
        joints=parsed.joints,
        frames=frames,
        frame_time=parsed.frame_time,
        declared_frame_count=frames.shape[0],
    )

    chunked = beat_bvh_to_body22(motion, chunk_size=2)
    single_chunk = beat_bvh_to_body22(motion, chunk_size=frames.shape[0])
    expected_shapes = {
        "poses": (7, 66),
        "translation": (7, 3),
        "source_positions": (7, 22, 3),
        "source_full_positions": (7, 52, 3),
        "hand_quaternions_xyzw": (7, 30, 4),
    }
    for key, expected_shape in expected_shapes.items():
        actual = np.asarray(chunked[key])
        assert actual.shape == expected_shape
        assert np.all(np.isfinite(actual))
        np.testing.assert_allclose(actual, single_chunk[key], atol=1e-6, rtol=1e-6)
    assert (
        chunked["source_rest_offsets"].keys()
        == single_chunk["source_rest_offsets"].keys()
    )
    for bone_name, offset in chunked["source_rest_offsets"].items():
        np.testing.assert_array_equal(
            offset, single_chunk["source_rest_offsets"][bone_name]
        )
    assert chunked["collapsed_paths"] == single_chunk["collapsed_paths"]
    with pytest.raises(ValueError, match="chunk_size must be a positive integer"):
        beat_bvh_to_body22(motion, chunk_size=0)


def test_beat_reports_declared_actual_and_intentionally_decoded_frames(
    tmp_path: Path,
) -> None:
    bvh_path = tmp_path / "hf" / "speaker" / "short.bvh"
    _write_beat_body_fixture(
        bvh_path,
        declared_frame_count=3,
        payload_frame_count=2,
    )
    adapter = BEATAdapter(_record("beat"), tmp_path)
    short = adapter.load("pose/speaker/short")
    assert short.sample.frame_count == 2
    assert short.sample.duration_sec == pytest.approx(2 / 120.0)
    assert short.sample.metadata["bvh_declared_frame_count"] == 3
    assert short.sample.metadata["bvh_decoded_frame_count"] == 2
    assert short.sample.metadata["bvh_actual_payload_frame_count"] == 2
    assert short.sample.metadata["bvh_payload_ended_early"] is True
    assert any(
        "actual readable frame count" in item for item in short.validation_warnings
    )

    complete_path = tmp_path / "hf" / "speaker" / "complete.bvh"
    _write_beat_body_fixture(complete_path)
    limited = adapter.load("pose/speaker/complete", max_frames=1)
    assert limited.sample.frame_count == 1
    assert limited.sample.metadata["bvh_decoded_frame_count"] == 1
    assert limited.sample.metadata["bvh_actual_payload_frame_count"] is None
    assert limited.sample.metadata["bvh_decode_truncated_by_max_frames"] is True
    assert limited.sample.metadata["original_time"] == {
        "frame_count": 2,
        "duration_sec": pytest.approx(2 / 120.0),
        "fps": pytest.approx(120.0),
    }
    with pytest.raises(ValueError, match="max_frames must be positive"):
        adapter.load("pose/speaker/complete", max_frames=0)


def test_grab_exposes_object_pose_and_honest_categorical_contact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    path = tmp_path / "s1" / "cup_lift.npz"
    path.parent.mkdir(parents=True)
    body = {
        "params": {
            "fullpose": np.zeros((2, 165)),
            "transl": np.asarray([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]),
        },
        "vtemp": "body",
    }
    obj = {
        "params": {
            "transl": np.asarray([[2.0, 4.0, 6.0], [2.0, 4.0, 6.0]]),
            "global_orient": np.zeros((2, 3)),
        },
        "object_mesh": "cup.ply",
    }
    contact = {
        "body": np.zeros((2, 4), dtype=np.int8),
        "object": np.asarray([[0, 1, 2], [3, 0, 0]], dtype=np.int8),
        "threshold": 0.01,
    }
    np.savez(
        path,
        body=np.asarray(body, dtype=object),
        object=np.asarray(obj, dtype=object),
        contact=np.asarray(contact, dtype=object),
        framerate=30.0,
        sbj_id="s1",
        gender="test",
        obj_name="cup",
        motion_intent="use",
    )
    clip = GRABAdapter(_record("grab"), tmp_path).load("s1/cup_lift", max_frames=1)
    object_pose = next(item for item in clip.channels if item["kind"] == "object_pose")
    canonical_object_pose = next(
        item
        for item in clip.channels
        if item["source"] == "virea.transform(grab.object.params)"
    )
    contact_channel = next(
        item
        for item in clip.channels
        if item["representation"] == "categorical_per_element"
    )
    assert object_pose["availability"] == "inline"
    assert object_pose["extras"]["source_to_canonical"][
        "body_root_first_translation_m"
    ] == [1.0, 2.0, 3.0]
    np.testing.assert_allclose(
        canonical_object_pose["preview"]["translation_m"][0], [1.0, 3.0, -2.0]
    )
    assert contact_channel["availability"] == "external"
    assert contact_channel["data_ref"]["path"].startswith("sidecars/")
    assert contact_channel["data_ref"]["media_type"] == "application/x-npy"
    assert contact_channel["frame_count"] == 2
    assert contact_channel["shape"] == [2, 3]
    assert contact_channel["extras"]["effective_frame_count"] == 1
    cached_contact = resolve_cached_sidecar(contact_channel["data_ref"]["sha256"])
    assert cached_contact is not None
    assert (
        list(np.load(cached_contact, allow_pickle=False).shape)
        == contact_channel["shape"]
    )
    assert contact_channel["extras"]["heatmap_supported"] is False
    body_contact = next(
        item for item in clip.channels if item["source"] == "grab.contact.body"
    )
    assert body_contact["availability"] == "external"
    assert body_contact["shape"] == [2, 4]


def test_humanml_only_uses_valid_native_ranges(tmp_path: Path) -> None:
    adapter = HumanML3DAdapter(_record("humanml3d"), tmp_path)
    caption = (
        "whole clip#tokens#0.0#0.0\nvalid action#tokens#0.0#1.0\noutside#tokens#0.0#9.0"
    )
    annotations = adapter._caption_annotations(
        "train/x/0", caption, fps=20.0, duration_sec=2.0
    )
    assert [item["level"] for item in annotations] == ["sequence", "action", "sequence"]
    assert annotations[1]["end_frame"] == 20
    assert annotations[2]["extras"]["native_interval_valid"] is False


def test_motionx_reorders_fullpose_and_uses_aist_unit_profile(tmp_path: Path) -> None:
    sample_id = "motion_data/smplx_322/aist/subset_0000/clip"
    path = tmp_path / f"{sample_id}.npy"
    path.parent.mkdir(parents=True)
    data = np.zeros((2, 324), dtype=np.float32)
    data[:, 0:66] = 1.0
    data[:, 66:156] = 2.0
    data[:, 156:159] = 3.0
    data[:, 159:209] = 4.0
    data[:, 309:312] = 100.0
    data[:, 312:322] = 5.0
    data[:, 322:324] = 9.0
    np.save(path, data)
    clip = MotionXAdapter(_record("motionx"), tmp_path).load(sample_id, max_frames=1)
    fullpose = clip.motion["fullpose"]
    assert fullpose.shape == (1, 165)
    np.testing.assert_allclose(fullpose[:, 0:66], 1.0)
    np.testing.assert_allclose(fullpose[:, 66:69], 3.0)
    np.testing.assert_allclose(fullpose[:, 69:75], 0.0)
    np.testing.assert_allclose(fullpose[:, 75:165], 2.0)
    np.testing.assert_allclose(
        clip.motion["translation"],
        np.asarray([[100.0 / 94.0, 100.0 / 94.0, -100.0 / 94.0]], dtype=np.float32),
    )
    assert clip.sample.metadata["dataset_profile"] == "motionx_aist_smplx322"
    assert clip.sample.metadata["translation_scale"] == pytest.approx(1.0 / 94.0)
    assert (
        clip.sample.metadata["translation_transform"]
        == "motionx_official_aist_div94_flip_z"
    )
    source_parameters = next(
        item for item in clip.channels if item["kind"] == "source_parameters"
    )
    assert source_parameters["availability"] == "external"
    assert source_parameters["shape"] == [2, 324]
    assert source_parameters["frame_count"] == 2
    assert source_parameters["extras"]["effective_frame_count"] == 1
    assert source_parameters["extras"]["unknown_tail_slice"] == [322, 324]
    source_cache = resolve_cached_sidecar(source_parameters["data_ref"]["sha256"])
    assert source_cache is not None
    stored_source = np.load(source_cache, allow_pickle=False)
    assert stored_source.shape == (2, 324)
    np.testing.assert_allclose(stored_source[:, 322:324], 9.0)
    betas = next(item for item in clip.channels if item["kind"] == "body_shape")
    assert betas["shape"] == [1, 10]


def test_motionx_exact_discovery_is_direct_and_reports_frame_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_id = "motion_data/smplx_322/aist/subset_0000/direct_clip"
    path = tmp_path / f"{sample_id}.npy"
    path.parent.mkdir(parents=True)
    np.save(path, np.zeros((7, 322), dtype=np.float32))
    adapter = MotionXAdapter(_record("motionx"), tmp_path)

    def reject_tree_scan(_self, _pattern):  # noqa: ANN001
        raise AssertionError(
            "exact Motion-X discovery must not traverse the dataset tree"
        )

    monkeypatch.setattr(Path, "rglob", reject_tree_scan)
    samples = adapter.discover(limit=500, query=sample_id)
    assert len(samples) == 1
    assert samples[0].sample_id == sample_id
    assert samples[0].frame_count == 7
    assert samples[0].fps == 30.0
    assert samples[0].duration_sec == pytest.approx(7 / 30.0)


def test_susu_exact_discovery_is_direct_under_explicit_local_trust(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    sample_id = "fbx_to_json_data_susu_chonglu/20260115/direct_clip"
    path = tmp_path / "motion_data" / f"{sample_id}.npy"
    path.parent.mkdir(parents=True)
    np.save(
        path,
        {
            "body": np.zeros((9, 153), dtype=np.float32),
            "positions": np.zeros((9, 63, 3), dtype=np.float32),
        },
    )
    adapter = SuSuInterActsAdapter(_record("susuinteracts"), tmp_path)

    def reject_tree_scan(_self, _pattern):  # noqa: ANN001
        raise AssertionError(
            "exact SuSu discovery must not traverse split lists or the motion tree"
        )

    monkeypatch.setattr(Path, "rglob", reject_tree_scan)
    monkeypatch.setattr(
        adapter,
        "_split_items",
        lambda _split: (_ for _ in ()).throw(AssertionError("split scan")),
    )
    samples = adapter.discover(limit=500, query=sample_id)
    assert len(samples) == 1
    assert samples[0].sample_id == sample_id
    assert samples[0].frame_count == 9
    assert samples[0].fps == 20.0
    assert samples[0].duration_sec == pytest.approx(9 / 20.0)
    assert samples[0].metadata["dataset_profile"] == "susu_chonglu"


def test_susu_separates_dialogue_face_and_audio_availability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    sample_id = "fbx_to_json_data_susu_retarget_maya/20250101/clip"
    motion_path = tmp_path / "motion_data" / f"{sample_id}.npy"
    motion_path.parent.mkdir(parents=True)
    body = np.zeros((2, 12), dtype=np.float32)
    body[1, 0] = 1.0
    np.save(motion_path, {"body": body})
    face_path = tmp_path / "arkit_data" / f"{sample_id}.npy"
    face_path.parent.mkdir(parents=True)
    np.save(face_path, np.zeros((2, 51), dtype=np.float32))
    text_path = tmp_path / "text_data" / "motion2text.json"
    text_path.parent.mkdir(parents=True)
    text_path.write_text(
        json.dumps({sample_id: "你好"}, ensure_ascii=False), encoding="utf-8"
    )
    clip = SuSuInterActsAdapter(_record("susuinteracts"), tmp_path).load(sample_id)
    assert clip.sample.metadata["dataset_profile"] == "susu_retarget_maya_rotation_only"
    assert any("DRAFT PROFILE" in warning for warning in clip.validation_warnings)
    assert clip.annotations[0]["type"] == "dialogue"
    assert clip.annotations[0]["provenance"] == "native"
    assert (
        next(item for item in clip.channels if item["kind"] == "face")["availability"]
        == "inline"
    )
    assert (
        next(item for item in clip.channels if item["kind"] == "audio")["availability"]
        == "missing"
    )
