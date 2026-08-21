from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from virea.motion import skeleton
from virea.motion.vrm_inspector import VRMInspectionError, inspect_vrm_avatar
from virea.verification import write_verification_report


def _write_glb(path: Path, payload: dict[str, object]) -> None:
    json_chunk = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    total_length = 12 + 8 + len(json_chunk)
    path.write_bytes(
        struct.pack("<III", 0x46546C67, 2, total_length)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
    )


def _vrm0_payload() -> dict[str, object]:
    root_matrix = [
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        1.0,
        2.0,
        3.0,
        1.0,
    ]
    return {
        "asset": {"version": "2.0"},
        "nodes": [
            {"name": "Root", "matrix": root_matrix, "children": [1]},
            {"name": "Hips", "translation": [0.0, 0.9, 0.0], "children": [2, 3, 4]},
            {"name": "Spine", "translation": [0.0, 0.2, 0.0], "children": [5]},
            {"name": "LeftArm", "translation": [0.4, 0.35, 0.0]},
            {"name": "RightArm", "translation": [-0.4, 0.35, 0.0]},
            {"name": "Head", "translation": [0.0, 0.5, 0.0]},
        ],
        "extensions": {
            "VRM": {
                "meta": {"title": "Synthetic VRM0"},
                "humanoid": {
                    "humanBones": [
                        {"bone": "hips", "node": 1},
                        {"bone": "spine", "node": 2},
                        {"bone": "leftUpperArm", "node": 3},
                        {"bone": "rightUpperArm", "node": 4},
                        {"bone": "head", "node": 5},
                    ]
                },
            }
        },
    }


def _clear_control_rest_caches() -> None:
    skeleton._inspect_vrm_descriptors.cache_clear()
    skeleton.vrm_control_rest_source.cache_clear()
    skeleton.baseline_rest_world_positions.cache_clear()
    skeleton.control_rest_world_positions.cache_clear()
    skeleton.control_rest_offsets.cache_clear()


def test_inspect_vrm0_applies_column_major_matrix_and_ancestor_trs(
    tmp_path: Path,
) -> None:
    vrm_path = tmp_path / "avatar.vrm"
    _write_glb(vrm_path, _vrm0_payload())

    descriptor = inspect_vrm_avatar(vrm_path)

    assert descriptor["vrm_version"] == "0.x"
    assert descriptor["avatar_file"] == "avatar.vrm"
    assert len(descriptor["avatar_sha256"]) == 64
    assert "avatar_path" not in descriptor
    graph = descriptor["humanoid_bone_nodes"]
    np.testing.assert_allclose(graph["hips"]["world_position"], [1.0, 2.9, 3.0])
    np.testing.assert_allclose(graph["head"]["world_position"], [1.0, 3.6, 3.0])
    assert graph["head"]["nearest_humanoid_parent_canonical"] == "spine"


def test_inspect_vrm1_uses_trs_rotation_and_version_native_thumb_names(
    tmp_path: Path,
) -> None:
    vrm_path = tmp_path / "avatar-v1.vrm"
    payload = {
        "asset": {"version": "2.0"},
        "nodes": [
            {
                "name": "Root",
                "translation": [2.0, 0.0, 0.0],
                "rotation": [0.0, 0.0, 2**-0.5, 2**-0.5],
                "children": [1],
            },
            {"name": "Hips", "translation": [1.0, 0.0, 0.0], "children": [2]},
            {"name": "ThumbMeta", "translation": [0.1, 0.0, 0.0], "children": [3]},
            {"name": "ThumbProximal", "translation": [0.1, 0.0, 0.0], "children": [4]},
            {"name": "ThumbDistal", "translation": [0.1, 0.0, 0.0]},
        ],
        "extensions": {
            "VRMC_vrm": {
                "specVersion": "1.0",
                "meta": {"name": "Synthetic VRM1"},
                "humanoid": {
                    "humanBones": {
                        "hips": {"node": 1},
                        "leftThumbMetacarpal": {"node": 2},
                        "leftThumbProximal": {"node": 3},
                        "leftThumbDistal": {"node": 4},
                    }
                },
            }
        },
    }
    _write_glb(vrm_path, payload)

    descriptor = inspect_vrm_avatar(vrm_path)
    graph = descriptor["humanoid_bone_nodes"]

    assert descriptor["vrm_version"] == "1.0"
    np.testing.assert_allclose(
        graph["hips"]["world_position"], [2.0, 1.0, 0.0], atol=1e-6
    )
    assert graph["leftThumbProximal"]["node_index"] == 2
    assert graph["leftThumbIntermediate"]["node_index"] == 3
    assert graph["leftThumbDistal"]["node_index"] == 4


def test_non_vrm_glb_fails_closed(tmp_path: Path) -> None:
    glb_path = tmp_path / "ordinary.glb"
    _write_glb(glb_path, {"asset": {"version": "2.0"}, "nodes": [{}]})

    with pytest.raises(VRMInspectionError, match="VRM extension"):
        inspect_vrm_avatar(glb_path)


def test_control_rest_safely_ignores_an_invalid_vrm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "broken.vrm").write_bytes(b"not a glb")
    monkeypatch.setenv("VIREA_VRM_MODEL_ROOT", str(tmp_path))
    _clear_control_rest_caches()
    try:
        audit = skeleton.control_rest_alignment_audit()
        assert audit["source"]["mode"] == "default_rest_template"
        assert audit["source"]["inspected_vrm_count"] == 0
        assert audit["descriptors"] == []
        assert not audit["passed"]
    finally:
        _clear_control_rest_caches()


def test_control_rest_audit_does_not_serialize_local_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private-user-model-root"
    private_root.mkdir()
    vrm_path = private_root / "private-avatar.vrm"
    _write_glb(vrm_path, _vrm0_payload())
    monkeypatch.setenv("VIREA_VRM_MODEL_ROOT", str(private_root.resolve()))
    _clear_control_rest_caches()
    try:
        audit = skeleton.control_rest_alignment_audit()
        serialized = json.dumps(audit, ensure_ascii=False)
        assert audit["source"]["mode"] == "vrm_control_rest_template"
        assert audit["source"]["inspected_vrm_count"] == 1
        assert audit["source"]["models"][0]["basename"] == "private-avatar.vrm"
        assert str(private_root.resolve()) not in serialized
        assert str(vrm_path.resolve()) not in serialized
        assert "avatar_path" not in serialized
        assert "vrm_model_root" not in serialized

        report_path = tmp_path / "verification.json"
        write_verification_report({"vrm_control_rest_audit": audit}, report_path)
        written = report_path.read_text(encoding="utf-8")
        assert str(private_root.resolve()) not in written
        assert str(vrm_path.resolve()) not in written
        assert "avatar_path" not in written
        assert "vrm_model_root" not in written
    finally:
        _clear_control_rest_caches()
