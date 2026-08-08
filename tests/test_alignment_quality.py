from __future__ import annotations

import numpy as np
import pytest

from virea.data.registry import DatasetRegistry
from virea.motion.canonical import CORE_INDEX, HAND_BONES, HAND_INDEX, pack_sequence, unpack_sequence
from virea.motion.codecs import (
    SMPLH_HAND_INDEX,
    SMPLX_HAND_INDEX,
    SUSU_BODY_NAMES,
    SUSU_POSITION_HAND_INDEX,
    default_codecs,
)
from virea.motion.retarget import resolve_world_basis
from virea.motion.rotation import axis_angle_to_quat_xyzw, quat_to_matrix_xyzw
from virea.motion.skeleton import (
    BODY_BONES,
    DEFAULT_REST_OFFSETS,
    FK_BONES,
    control_rest_alignment_audit,
    forward_kinematics_from_sequence,
    target_rest_offsets_map,
)
from virea.pipelines.processed_preview import ProcessedPreviewPipeline
from virea.pipelines.raw_preview import RawPreviewPipeline


def _full_registry_or_skip() -> DatasetRegistry:
    registry = DatasetRegistry.default(data_source="full")
    if not registry.paths.raw_root.exists():
        pytest.skip("full raw root is not configured; set VIREA_RAW_ROOT to run full-data regressions")
    return registry


def _long_edges(payload) -> list[tuple[int, int, float]]:
    long = []
    for a, b in payload.edges:
        distance = np.linalg.norm(payload.positions[:, a] - payload.positions[:, b], axis=1)
        median = float(np.median(distance))
        if median > 0.95:
            long.append((a, b, median))
    return long


def _assert_finite_payload(payload) -> None:
    assert payload.positions.ndim == 3
    assert payload.positions.shape[0] > 0
    assert payload.positions.shape[2] == 3
    assert np.isfinite(payload.positions).all()
    if "hips" in payload.joint_names:
        hips0 = payload.positions[0, payload.joint_names.index("hips")]
        assert float(np.linalg.norm(hips0)) <= 1e-4
    assert _long_edges(payload) == []


def _assert_processed_is_true_vrm_fk(payload) -> None:
    assert payload.joint_names == FK_BONES
    assert payload.motion is not None
    motion = payload.motion
    sequence = pack_sequence(
        root_translation=np.asarray(motion["root_translation"], dtype=np.float32),
        root_rotation_xyzw=np.asarray(motion["root_rotation"], dtype=np.float32),
        core_quats_xyzw=np.asarray(motion["core_quaternions"], dtype=np.float32),
        hand_quats_xyzw=np.asarray(motion["hand_quaternions"], dtype=np.float32),
    )
    fk_positions = forward_kinematics_from_sequence(sequence)
    error_mm = float(np.max(np.linalg.norm(fk_positions - payload.positions, axis=2)) * 1000.0)
    assert error_mm <= 0.02
    edge_std_mm = [
        float(np.std(np.linalg.norm(payload.positions[:, a] - payload.positions[:, b], axis=1)) * 1000.0)
        for a, b in payload.edges
    ]
    assert max(edge_std_mm, default=0.0) <= 0.02


def _max_foot_above_head(payload) -> float:
    names = payload.joint_names
    head = payload.positions[:, names.index("head"), 1]
    feet = np.maximum(
        payload.positions[:, names.index("leftFoot"), 1],
        payload.positions[:, names.index("rightFoot"), 1],
    )
    return float(np.max(feet - head))


def _mean_delta(payload, parent: str, child: str) -> np.ndarray:
    names = payload.joint_names
    return np.mean(
        payload.positions[:, names.index(child)] - payload.positions[:, names.index(parent)],
        axis=0,
    )


@pytest.mark.parametrize("dataset", ["amass", "babel", "beat", "grab", "humanml3d", "motionx", "susuinteracts"])
def test_processed_preview_is_vrm_fk_not_a_raw_copy(dataset: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if dataset in {"grab", "susuinteracts"}:
        monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    registry = _full_registry_or_skip()
    adapter = registry.adapter(dataset)
    if not adapter.exists():
        pytest.skip(f"raw root not available for {dataset}")
    samples = adapter.discover(limit=500)
    if not samples:
        pytest.skip(f"no samples found for {dataset}")

    selected = samples[0].sample_id
    if dataset == "susuinteracts":
        selected = next((sample.sample_id for sample in samples if "chonglu" in sample.sample_id), selected)

    raw = RawPreviewPipeline(registry).preview(dataset, selected, max_frames=32)
    processed = ProcessedPreviewPipeline(registry).preview(dataset, selected, max_frames=32)

    _assert_finite_payload(raw)
    _assert_finite_payload(processed)
    _assert_processed_is_true_vrm_fk(processed)
    if processed.joint_names == raw.joint_names and processed.positions.shape == raw.positions.shape:
        # A source adapter may now expose the complete canonical-name topology
        # (BEAT full BVH is the important case).  Topology equality is not a raw
        # copy: the processed payload must still be independently reconstructed
        # by canonical target FK and differ numerically from the source rig.
        delta = np.linalg.norm(processed.positions - raw.positions, axis=2)
        assert float(np.max(delta)) > 1e-5
    assert processed.metadata["canonical_skeleton"] == "virea_canonical_skeleton.v1"


def test_susu_retarget_maya_rotation_only_is_explicitly_draft_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    registry = _full_registry_or_skip()
    adapter = registry.adapter("susuinteracts")
    assert adapter._profile_for("fbx_to_json_data_susu_retarget_maya/example", has_positions=True)[1] == "susu_retarget_maya_6d_body_hands"
    assert adapter._profile_for("fbx_to_json_data_susu_chonglu/example", has_positions=False)[1] == "susu_chonglu_6d_body_hands_cm"
    samples = adapter.discover(limit=500)
    selected = next((sample.sample_id for sample in samples if "retarget_maya" in sample.sample_id), None)
    if selected is None:
        pytest.skip("SuSu retarget_maya regression sample is not available")

    raw = RawPreviewPipeline(registry).preview("susuinteracts", selected, max_frames=32)
    processed = ProcessedPreviewPipeline(registry).preview("susuinteracts", selected, max_frames=32)

    assert SUSU_BODY_NAMES[20:25] == ["clavicle_r", "upperarm_r", "lowerarm_r", "hand_l", "hand_r"]
    _assert_finite_payload(raw)
    _assert_finite_payload(processed)
    _assert_processed_is_true_vrm_fk(processed)
    assert processed.metadata["dataset_profile"] == "susu_retarget_maya_rotation_only"
    assert processed.metadata["profile_status"] == "draft"
    assert any("DRAFT PROFILE" in warning for warning in processed.validation_warnings)
    # Rotation-only source FK follows the official SentiAvatar template,
    # quaternion swizzle and pelvis correction. The profile remains draft until
    # broader actor/VRM visual coverage is complete, so persistence still fails
    # closed even though this known inversion is corrected.
    assert processed.metadata["root_translation"] == "absolute_xzy_zeroed_auto_units"
    assert processed.metadata["rotation_space"] == "parent_local"
    assert processed.metadata["rotation_6d_layout"] == "first_two_columns"
    hips = raw.positions[:, raw.joint_names.index("hips")]
    root_steps = np.linalg.norm(np.diff(hips, axis=0), axis=1)
    assert float(np.max(root_steps)) < 0.05
    names = raw.joint_names
    hips = raw.positions[:, names.index("hips")]
    left_hand = raw.positions[:, names.index("leftHand")] - hips
    right_hand = raw.positions[:, names.index("rightHand")] - hips
    left_upper_arm = raw.positions[:, names.index("leftUpperArm")] - hips
    right_upper_arm = raw.positions[:, names.index("rightUpperArm")] - hips
    assert _max_foot_above_head(raw) < 0.05
    assert _max_foot_above_head(processed) < 0.05
    assert float(np.median(left_hand[:, 0] - right_hand[:, 0])) > 0.03
    assert float(np.median(left_upper_arm[:, 0] - right_upper_arm[:, 0])) > 0.10


@pytest.mark.parametrize(
    ("dataset", "sample_id"),
    [
        ("amass", "ACCAD/Female1General_c3d/A10_-_lie_to_crouch_stageii"),
        ("babel", "babel-teach/train/11929"),
        ("grab", "s1/airplane_fly_1"),
        ("motionx", "motion_data/smplx_322/aist/subset_0000/Dance_Break"),
    ],
)
def test_real_direct_profiles_preserve_every_mapped_local_rotation(
    dataset: str,
    sample_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if dataset == "grab":
        monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    registry = _full_registry_or_skip()
    adapter = registry.adapter(dataset)
    try:
        clip = adapter.load(sample_id, max_frames=8)
    except FileNotFoundError:
        pytest.skip(f"direct rotation oracle sample is unavailable: {dataset}/{sample_id}")
    codec = default_codecs()[clip.sample.codec_key]
    result = codec.to_canonical(clip)
    decoded = unpack_sequence(result.sequence)

    if clip.sample.codec_key == "smplh_body_hands":
        source_axis_angles = np.asarray(clip.motion["poses"], dtype=np.float32).reshape(-1, 52, 3)
        hand_mapping = SMPLH_HAND_INDEX
        hand_source_offset = 22
    elif clip.sample.codec_key == "smplx_fullpose":
        source_axis_angles = np.asarray(clip.motion["fullpose"], dtype=np.float32).reshape(-1, 55, 3)
        hand_mapping = SMPLX_HAND_INDEX
        hand_source_offset = 0
    else:
        pytest.skip(f"sample does not use a direct SMPL-family codec: {clip.sample.codec_key}")

    source_quaternions = axis_angle_to_quat_xyzw(source_axis_angles)
    source_hands = source_quaternions[:, hand_source_offset:]
    basis = resolve_world_basis(result.metadata["declared_world_basis"])["rotation_matrix"]
    np.testing.assert_allclose(
        quat_to_matrix_xyzw(decoded["root_rotation_xyzw"]),
        np.einsum("ij,tjk->tik", basis, quat_to_matrix_xyzw(source_quaternions[:, 0])),
        atol=2e-5,
    )
    for body_index, bone_name in enumerate(BODY_BONES):
        if bone_name == "hips" or bone_name not in CORE_INDEX:
            continue
        np.testing.assert_allclose(
            quat_to_matrix_xyzw(decoded["core_quats_xyzw"][:, CORE_INDEX[bone_name]]),
            quat_to_matrix_xyzw(source_quaternions[:, body_index]),
            atol=2e-5,
            err_msg=f"real {dataset} body local rotation mismatch at {bone_name}",
        )
    for bone_name, source_index in hand_mapping.items():
        np.testing.assert_allclose(
            quat_to_matrix_xyzw(decoded["hand_quats_xyzw"][:, HAND_INDEX[bone_name]]),
            quat_to_matrix_xyzw(source_hands[:, source_index]),
            atol=2e-5,
            err_msg=f"real {dataset} hand local rotation mismatch at {bone_name}",
        )


def test_prone_and_inverted_motions_are_not_rotated_upright() -> None:
    registry = _full_registry_or_skip()
    adapter = registry.adapter("motionx")
    if not adapter.exists():
        pytest.skip("raw root not available for motionx")

    plank_id = "motion_data/smplx_322/fitness/subset_0004/Sport_Fitness_Plank"
    handstand_id = "motion_data/smplx_322/game_motion/subset_0010/Gymnastics_Handstand"
    if not (adapter.raw_root / f"{plank_id}.npy").exists() or not (adapter.raw_root / f"{handstand_id}.npy").exists():
        pytest.skip("Motion-X prone/handstand regression samples are not available")

    plank = ProcessedPreviewPipeline(registry).preview("motionx", plank_id, max_frames=64)
    names = plank.joint_names
    head_delta = _mean_delta(plank, "hips", "head")
    assert abs(float(head_delta[1])) < 0.12
    assert abs(float(head_delta[2])) > 0.45
    assert float(np.median(plank.positions[:, names.index("leftHand"), 1])) < float(np.median(plank.positions[:, names.index("hips"), 1]))

    handstand = ProcessedPreviewPipeline(registry).preview("motionx", handstand_id, max_frames=64)
    names = handstand.joint_names
    hands_y = np.maximum(handstand.positions[:, names.index("leftHand"), 1], handstand.positions[:, names.index("rightHand"), 1])
    feet_y = np.maximum(handstand.positions[:, names.index("leftFoot"), 1], handstand.positions[:, names.index("rightFoot"), 1])
    assert float(np.median(hands_y)) < float(np.median(handstand.positions[:, names.index("hips"), 1]))
    assert float(np.median(feet_y)) > float(np.median(handstand.positions[:, names.index("head"), 1]))


def test_amass_stageii_embedded_markers_prove_z_up_and_processed_motion_uses_it() -> None:
    registry = _full_registry_or_skip()
    adapter = registry.adapter("amass")
    stand_id = "ACCAD/Female1General_c3d/A1_-_Stand_stageii"
    stand_path = adapter.raw_root / f"{stand_id}.npz"
    if not stand_path.exists():
        pytest.skip("AMASS Stage-II stand regression sample is not available")

    with np.load(stand_path, allow_pickle=False) as payload:
        markers = np.asarray(payload["markers"], dtype=np.float32)
        translation = np.asarray(payload["trans"], dtype=np.float32)
    marker_span = np.nanpercentile(markers, 99, axis=(0, 1)) - np.nanpercentile(
        markers, 1, axis=(0, 1)
    )
    assert float(marker_span[2]) > 2.0 * float(max(marker_span[0], marker_span[1]))
    assert float(np.median(translation[:, 2])) > 0.8

    stand = ProcessedPreviewPipeline(registry).preview("amass", stand_id, max_frames=64)
    names = stand.joint_names
    head_y = stand.positions[:, names.index("head"), 1]
    feet_y = np.maximum(
        stand.positions[:, names.index("leftFoot"), 1],
        stand.positions[:, names.index("rightFoot"), 1],
    )
    assert float(np.median(head_y - feet_y)) > 1.2
    assert stand.metadata["declared_world_basis"] == "z_up_to_y_up"
    assert stand.metadata["dataset_profile"] == "amass_smplx_stageii165"

    crawl_id = "ACCAD/Female1General_c3d/A11_-_crawl_forward_stageii"
    if not (adapter.raw_root / f"{crawl_id}.npz").exists():
        return
    processed = ProcessedPreviewPipeline(registry).preview("amass", crawl_id, max_frames=64)
    head_delta = _mean_delta(processed, "hips", "head")
    assert abs(float(head_delta[1])) < 0.18
    assert abs(float(head_delta[0])) > 0.45
    assert processed.metadata["declared_world_basis"] == "z_up_to_y_up"
    assert processed.metadata["dataset_profile"] == "amass_smplx_stageii165"


def test_susu_position_samples_use_declared_basis_without_left_right_flip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    registry = _full_registry_or_skip()
    adapter = registry.adapter("susuinteracts")
    sample_id = "fbx_to_json_data_susu_retarget_maya/20251106/Human_0916_183_0_4_01_XG"
    if not (adapter.raw_root / "motion_data" / f"{sample_id}.npy").exists():
        pytest.skip("SuSu retarget_maya regression sample is not available")

    raw = RawPreviewPipeline(registry).preview("susuinteracts", sample_id, max_frames=8)
    names = raw.joint_names
    assert raw.metadata["declared_world_basis"] == "neg_z_up_to_y_up"
    assert float(raw.positions[0, names.index("leftUpperArm"), 0] - raw.positions[0, names.index("rightUpperArm"), 0]) > 0.05


@pytest.mark.parametrize(
    "sample_id",
    [
        "fbx_to_json_data_susu_retarget_maya/20251106/Human_0916_183_0_4_01_XG",
        "fbx_to_json_data_susu_retarget_maya/20251119/Human_0916_308_0_13_01_XC",
    ],
)
def test_real_susu_63_point_finger_segments_reach_target_fk(
    sample_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "1")
    registry = _full_registry_or_skip()
    adapter = registry.adapter("susuinteracts")
    try:
        clip = adapter.load(sample_id, max_frames=124)
    except FileNotFoundError:
        pytest.skip(f"SuSu 63-point regression sample is unavailable: {sample_id}")
    source_positions = np.asarray(clip.motion.get("positions"), dtype=np.float32)
    if source_positions.shape[1:] != (63, 3):
        pytest.skip(f"SuSu sample does not carry authoritative 63-point positions: {sample_id}")

    result = default_codecs()[clip.sample.codec_key].to_canonical(clip)
    assert result.metadata["retarget_mode"] == "position_fit_body_wrist_and_finger_swing_from_63_positions"
    assert result.metadata["finger_retarget"] == "position_fit_swing_from_authoritative_positions"
    basis = resolve_world_basis(result.metadata["declared_world_basis"])["rotation_matrix"]
    target_index = {name: index for index, name in enumerate(result.joint_names)}
    errors: list[np.ndarray] = []
    for side in ("left", "right"):
        for finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
            chain = [
                f"{side}{finger}Proximal",
                f"{side}{finger}Intermediate",
                f"{side}{finger}Distal",
            ]
            for parent, child in zip(chain, chain[1:]):
                source_vector = (
                    source_positions[:, SUSU_POSITION_HAND_INDEX[child]]
                    - source_positions[:, SUSU_POSITION_HAND_INDEX[parent]]
                )
                source_vector = np.einsum("ij,tj->ti", basis, source_vector)
                target_vector = (
                    result.positions[:, target_index[child]]
                    - result.positions[:, target_index[parent]]
                )
                source_norm = np.linalg.norm(source_vector, axis=1)
                target_norm = np.linalg.norm(target_vector, axis=1)
                valid = (source_norm > 1e-7) & (target_norm > 1e-7)
                assert valid.any(), f"degenerate real finger segment {parent}->{child}"
                dot = np.sum(source_vector[valid] * target_vector[valid], axis=1)
                dot /= source_norm[valid] * target_norm[valid]
                errors.append(np.degrees(np.arccos(np.clip(dot, -1.0, 1.0))))

    all_errors = np.concatenate(errors)
    assert len(errors) == 20
    assert float(np.max(all_errors)) < 0.1
    assert set(SUSU_POSITION_HAND_INDEX) == set(HAND_BONES)


def test_real_vrm_control_template_is_audited_without_changing_canonical_payload() -> None:
    audit = control_rest_alignment_audit()
    if audit["source"]["mode"] != "vrm_control_rest_template":
        pytest.skip("real VRM control template is not configured; set VIREA_VRM_MODEL_ROOT")
    assert audit["passed"]
    assert audit["source"]["mode"] == "vrm_control_rest_template"
    assert audit["source"]["inspected_vrm_count"] >= 1
    assert audit["left_right_axis_passed"]
    assert audit["head_above_hips_passed"]

    target_offsets = target_rest_offsets_map()
    assert target_offsets["leftUpperArm"] != DEFAULT_REST_OFFSETS["leftUpperArm"]

    registry = DatasetRegistry.default(data_source="demo")
    adapter = registry.adapter("amass")
    samples = adapter.discover(limit=1)
    assert samples
    processed = ProcessedPreviewPipeline(registry).preview("amass", samples[0].sample_id, max_frames=4)
    # Persisted/preview canonical motion is deterministic and must not change
    # with whichever avatar files happen to be installed on this machine. The
    # real VRM control rest is audited above and aligned only at Viewer runtime.
    assert processed.motion["rest_source"] == "virea_canonical_rest.v1"
    assert processed.motion["rest_offsets"]["leftUpperArm"] == DEFAULT_REST_OFFSETS["leftUpperArm"]
    assert processed.motion["rest_offsets"]["leftUpperArm"] != target_offsets["leftUpperArm"]
