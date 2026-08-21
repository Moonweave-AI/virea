"""Binary-structure tests for the VRM Animation GLB exporter."""

from __future__ import annotations

import json
import struct

import numpy as np
import pytest
from virea_cli.real_e2e_validator import AcceptanceFailure, _validate_vrma
from virea_motion_ir.compatibility.canonical211_v3 import CANONICAL211_JOINT_NAMES
from virea_retarget import ActorRetargetResult
from virea_vrm import export_vrma

from virea.motion.canonical import CORE_BONES, HAND_BONES, identity_quats, pack_sequence
from virea.motion.skeleton import DEFAULT_REST_OFFSETS

GLB_MAGIC = 0x46546C67
GLB_VERSION = 2
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def _actor_fixture(frame_count: int = 3) -> ActorRetargetResult:
    translation = np.array(
        [[0.25 * index, 0.0, -0.125 * index] for index in range(frame_count)],
        dtype=np.float32,
    )
    root = identity_quats(frame_count, 1)[:, 0]
    core = identity_quats(frame_count, len(CORE_BONES))
    hands = identity_quats(frame_count, len(HAND_BONES))
    root[-1] = [0.0, 1.0, 0.0, 0.0]
    core[-1, 0] = [1.0, 0.0, 0.0, 0.0]
    hands[-1, -1] = [0.0, 0.0, 1.0, 0.0]
    canonical = pack_sequence(translation, root, core, hands)
    return ActorRetargetResult(
        actor_id="actor-vrma",
        canonical211=canonical,
        positions_m=np.zeros((frame_count, 52, 3), dtype=np.float32),
        joint_names=CANONICAL211_JOINT_NAMES,
        edges=(),
        policy_id="virea.retarget.test.v1",
        provenance={"fixture": "synthetic"},
    )


def _parse_glb(payload: bytes) -> tuple[dict, bytes]:
    magic, version, total_length = struct.unpack_from("<III", payload, 0)
    assert magic == GLB_MAGIC
    assert version == GLB_VERSION
    assert total_length == len(payload)

    json_length, json_type = struct.unpack_from("<II", payload, 12)
    assert json_type == JSON_CHUNK
    json_start = 20
    json_end = json_start + json_length
    document = json.loads(payload[json_start:json_end].decode("utf-8").rstrip(" \x00"))

    binary_length, binary_type = struct.unpack_from("<II", payload, json_end)
    assert binary_type == BIN_CHUNK
    binary_start = json_end + 8
    binary_end = binary_start + binary_length
    assert binary_end == len(payload)
    return document, payload[binary_start:binary_end]


def _build_glb(document: dict, binary: bytes) -> bytes:
    document["buffers"][0]["byteLength"] = len(binary)
    json_payload = json.dumps(
        document,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    json_payload += b" " * ((-len(json_payload)) % 4)
    binary_payload = binary + b"\x00" * ((-len(binary)) % 4)
    total_length = 12 + 8 + len(json_payload) + 8 + len(binary_payload)
    return b"".join(
        (
            struct.pack("<III", GLB_MAGIC, GLB_VERSION, total_length),
            struct.pack("<II", len(json_payload), JSON_CHUNK),
            json_payload,
            struct.pack("<II", len(binary_payload), BIN_CHUNK),
            binary_payload,
        )
    )


def _float_accessor(document: dict, binary: bytes, index: int) -> np.ndarray:
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    widths = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}
    width = widths[accessor["type"]]
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    values = np.frombuffer(
        binary,
        dtype="<f4",
        count=int(accessor["count"]) * width,
        offset=offset,
    )
    return values.reshape(int(accessor["count"]), width)


def _node_world_translations(document: dict) -> np.ndarray:
    nodes = document["nodes"]
    parents = [-1] * len(nodes)
    for parent_index, node in enumerate(nodes):
        for child_index in node.get("children", []):
            parents[child_index] = parent_index
    world = np.zeros((len(nodes), 3), dtype=np.float32)
    for node_index, (node, parent_index) in enumerate(zip(nodes, parents, strict=True)):
        local = np.asarray(node.get("translation", [0.0, 0.0, 0.0]), dtype=np.float32)
        world[node_index] = local if parent_index < 0 else world[parent_index] + local
    return world


def test_vrma_glb_header_extension_animation_and_accessors_are_consistent(
    tmp_path,
) -> None:
    actor = _actor_fixture()
    output = export_vrma(actor, tmp_path / "synthetic.vrma", fps=20.0)
    payload = output.read_bytes()
    document, binary = _parse_glb(payload)

    assert output.suffix == ".vrma"
    assert document["asset"] == {"version": "2.0", "generator": "VIREA 0.4.0"}
    assert document["extensionsUsed"] == ["VRMC_vrm_animation"]
    assert document["extensionsRequired"] == ["VRMC_vrm_animation"]
    extension = document["extensions"]["VRMC_vrm_animation"]
    assert extension["specVersion"] == "1.0"
    human_bones = extension["humanoid"]["humanBones"]
    assert len(human_bones) == 52
    assert {entry["node"] for entry in human_bones.values()} == set(range(52))

    assert document["scene"] == 0
    assert document["scenes"] == [{"nodes": [0]}]
    assert len(document["nodes"]) == 52
    assert document["nodes"][0]["name"] == "hips"
    assert document["nodes"][0]["translation"] == [0.0, 1.0, 0.0]
    for joint_index, joint_name in enumerate(CANONICAL211_JOINT_NAMES[1:], start=1):
        np.testing.assert_allclose(
            document["nodes"][joint_index]["translation"],
            DEFAULT_REST_OFFSETS[joint_name],
            rtol=0.0,
            atol=1e-7,
        )
    rest_world = _node_world_translations(document)
    assert rest_world[0, 1] == pytest.approx(1.0)
    assert float(np.min(rest_world[:, 1])) == pytest.approx(0.0, abs=1e-7)
    # three-vrm-animation uses this value as the denominator when it scales
    # root translation to the target avatar, so it must be finite and non-zero.
    source_hips_height_m = float(rest_world[0, 1])
    assert source_hips_height_m > 1.0e-3
    assert np.isfinite(source_hips_height_m)
    assert document["buffers"] == [{"byteLength": len(binary)}]
    for view in document["bufferViews"]:
        assert view["buffer"] == 0
        assert view.get("byteOffset", 0) % 4 == 0
        assert view.get("byteOffset", 0) + view["byteLength"] <= len(binary)

    assert len(document["animations"]) == 1
    animation = document["animations"][0]
    assert animation["name"] == actor.actor_id
    assert len(animation["samplers"]) == 53
    assert len(animation["channels"]) == 53
    assert len(document["accessors"]) == 54

    frame_count = actor.canonical211.shape[0]
    time_accessor = document["accessors"][0]
    assert time_accessor == {
        "bufferView": 0,
        "componentType": 5126,
        "count": frame_count,
        "type": "SCALAR",
        "min": [0.0],
        "max": [pytest.approx((frame_count - 1) / 20.0)],
    }
    timestamps = _float_accessor(document, binary, 0)[:, 0]
    np.testing.assert_allclose(timestamps, [0.0, 0.05, 0.1], rtol=0.0, atol=1e-7)

    translation_channel = animation["channels"][0]
    assert translation_channel == {
        "sampler": 0,
        "target": {"node": 0, "path": "translation"},
    }
    translation_sampler = animation["samplers"][0]
    assert translation_sampler["input"] == 0
    assert translation_sampler["interpolation"] == "LINEAR"
    expected_vrma_translation = actor.canonical211[:, :3].copy()
    expected_vrma_translation[:, 1] += 1.0
    np.testing.assert_array_equal(
        _float_accessor(document, binary, translation_sampler["output"]),
        expected_vrma_translation,
    )

    rotation_channels = animation["channels"][1:]
    assert [channel["target"]["node"] for channel in rotation_channels] == list(
        range(52)
    )
    assert {channel["target"]["path"] for channel in rotation_channels} == {"rotation"}
    for channel in animation["channels"]:
        sampler = animation["samplers"][channel["sampler"]]
        assert sampler["input"] == 0
        assert sampler["interpolation"] == "LINEAR"
        output_accessor = document["accessors"][sampler["output"]]
        assert output_accessor["componentType"] == 5126
        assert output_accessor["count"] == frame_count
    first_rotation = _float_accessor(
        document,
        binary,
        animation["samplers"][1]["output"],
    )
    np.testing.assert_array_equal(first_rotation, actor.canonical211[:, 3:7])


def test_vrma_export_requires_positive_fps_and_vrma_suffix(tmp_path) -> None:
    actor = _actor_fixture(2)
    with pytest.raises(ValueError, match="fps must be positive"):
        export_vrma(actor, tmp_path / "bad.vrma", fps=0.0)
    with pytest.raises(ValueError, match=r"\.vrma extension"):
        export_vrma(actor, tmp_path / "bad.glb", fps=20.0)


def test_release_validator_accepts_absolute_hips_translation_with_rest_baseline(
    tmp_path,
) -> None:
    actor = _actor_fixture()
    output = export_vrma(actor, tmp_path / "valid.vrma", fps=20.0)

    metrics = _validate_vrma(
        output,
        actor_id=actor.actor_id,
        frame_count=actor.canonical211.shape[0],
        fps=20.0,
        expected_root_displacement=actor.canonical211[:, :3],
    )

    assert metrics["rest_hips_height"] == pytest.approx(1.0)
    assert metrics["translation_range"] == {
        "min_xyz": pytest.approx([0.0, 1.0, -0.25]),
        "max_xyz": pytest.approx([0.5, 1.0, 0.0]),
    }


def test_release_validator_rejects_legacy_vrma_without_translation_channel(
    tmp_path,
) -> None:
    actor = _actor_fixture()
    valid = export_vrma(actor, tmp_path / "source.vrma", fps=20.0)
    document, binary = _parse_glb(valid.read_bytes())
    animation = document["animations"][0]
    animation["channels"] = animation["channels"][1:]
    animation["samplers"] = animation["samplers"][1:]
    for channel in animation["channels"]:
        channel["sampler"] -= 1
    legacy = tmp_path / "legacy-no-translation.vrma"
    legacy.write_bytes(_build_glb(document, binary))

    with pytest.raises(
        AcceptanceFailure,
        match="exactly one root translation channel",
    ):
        _validate_vrma(
            legacy,
            actor_id=actor.actor_id,
            frame_count=actor.canonical211.shape[0],
            fps=20.0,
            expected_root_displacement=actor.canonical211[:, :3],
        )


def test_release_validator_rejects_translation_without_rest_baseline(tmp_path) -> None:
    actor = _actor_fixture()
    valid = export_vrma(actor, tmp_path / "source.vrma", fps=20.0)
    document, binary = _parse_glb(valid.read_bytes())
    animation = document["animations"][0]
    translation_channel = next(
        channel
        for channel in animation["channels"]
        if channel["target"]["path"] == "translation"
    )
    translation_sampler = animation["samplers"][translation_channel["sampler"]]
    output_index = translation_sampler["output"]
    accessor = document["accessors"][output_index]
    view = document["bufferViews"][accessor["bufferView"]]
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    corrupted_binary = bytearray(binary)
    translations = np.frombuffer(
        corrupted_binary,
        dtype="<f4",
        count=int(accessor["count"]) * 3,
        offset=offset,
    ).reshape(int(accessor["count"]), 3)
    translations[:, 1] = actor.canonical211[:, 1]
    missing_baseline = tmp_path / "missing-rest-baseline.vrma"
    missing_baseline.write_bytes(_build_glb(document, bytes(corrupted_binary)))

    with pytest.raises(
        AcceptanceFailure,
        match="absolute hips translation differs",
    ):
        _validate_vrma(
            missing_baseline,
            actor_id=actor.actor_id,
            frame_count=actor.canonical211.shape[0],
            fps=20.0,
            expected_root_displacement=actor.canonical211[:, :3],
        )
