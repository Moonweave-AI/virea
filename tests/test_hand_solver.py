from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from virea.motion.canonical import HAND_BONES, HAND_INDEX, identity_quats
from virea.motion.hand_solver import (
    ANATOMICAL_FRAMES,
    HAND_CONSTRAINT_POLICY_ID,
    HAND_CONSTRAINT_POLICY_SHA256,
    HAND_JOINT_CONSTRAINTS,
    HAND_SOLVER_SCHEMA_VERSION,
    NEUTRAL_HAND_PRIOR_ID,
    PIP_BEND_OBSERVABILITY_THRESHOLD_DEG,
    HandConstraintError,
    HandObservationMetadata,
    JointObservation,
    anatomical_angles_deg,
    solve_hand_constraints,
    verify_hand_constraint_certificate,
)
from virea.motion.rotation import (
    axis_angle_to_quat_xyzw,
    quat_from_two_vectors_xyzw,
    quat_multiply_xyzw,
)
from virea.motion.skeleton import CANONICAL_PARENT, DEFAULT_REST_OFFSETS


def _identity(frame_count: int) -> np.ndarray:
    return identity_quats(frame_count, len(HAND_BONES))


def _axis_quat(axis: tuple[float, float, float], angle_deg: float) -> np.ndarray:
    return axis_angle_to_quat_xyzw(
        np.asarray(axis, dtype=np.float32) * np.radians(np.float32(angle_deg))
    )


def _flex_quat(bone: str, angle_deg: float) -> np.ndarray:
    return _axis_quat(ANATOMICAL_FRAMES[bone].flexion_axis, angle_deg)


def _twist_quat(bone: str, angle_deg: float) -> np.ndarray:
    return _axis_quat(ANATOMICAL_FRAMES[bone].longitudinal_axis, angle_deg)


def _observed(frame_count: int) -> HandObservationMetadata:
    return HandObservationMetadata.all_observed(
        source="unit_test_native_local_rotations",
        fps=30.0,
    )


def _identity_joint_positions(frame_count: int) -> dict[str, np.ndarray]:
    positions = {
        "leftHand": np.zeros((frame_count, 3), dtype=np.float32),
        "rightHand": np.zeros((frame_count, 3), dtype=np.float32),
    }
    for bone in HAND_BONES:
        positions[bone] = (
            positions[CANONICAL_PARENT[bone]]
            + np.asarray(DEFAULT_REST_OFFSETS[bone], dtype=np.float32)[None, :]
        )
    return positions


def test_anatomical_frames_and_constraints_cover_exact_full_mirrored_topology() -> None:
    assert list(ANATOMICAL_FRAMES) == HAND_BONES
    assert list(HAND_JOINT_CONSTRAINTS) == HAND_BONES
    assert len(ANATOMICAL_FRAMES) == 30

    for finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
        for level in ("Proximal", "Intermediate", "Distal"):
            left = ANATOMICAL_FRAMES[f"left{finger}{level}"]
            right = ANATOMICAL_FRAMES[f"right{finger}{level}"]
            np.testing.assert_allclose(
                np.asarray(right.longitudinal_axis) * np.asarray([-1.0, 1.0, 1.0]),
                left.longitudinal_axis,
                atol=1e-7,
            )
            np.testing.assert_allclose(
                left.flexion_direction,
                [0.0, -1.0, 0.0],
                atol=1e-7,
            )
            np.testing.assert_allclose(
                right.flexion_direction,
                [0.0, -1.0, 0.0],
                atol=1e-7,
            )
            assert (
                HAND_JOINT_CONSTRAINTS[f"left{finger}{level}"]
                == (HAND_JOINT_CONSTRAINTS[f"right{finger}{level}"])
            )


def test_safe_observed_motion_is_exact_noop_and_input_is_immutable() -> None:
    hands = _identity(3)
    for side in ("left", "right"):
        pip = f"{side}IndexIntermediate"
        mcp = f"{side}MiddleProximal"
        dip = f"{side}RingDistal"
        hands[1, HAND_INDEX[pip]] = _flex_quat(pip, 60.0)
        hands[2, HAND_INDEX[mcp]] = _axis_quat(
            ANATOMICAL_FRAMES[mcp].abduction_axis, 10.0
        )
        hands[2, HAND_INDEX[dip]] = _twist_quat(dip, 5.0)
    native = hands.copy()

    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 3)],
        observation=_observed(3),
    )

    np.testing.assert_array_equal(hands, native)
    np.testing.assert_array_equal(result.quats_xyzw, native)
    assert not np.shares_memory(result.quats_xyzw, hands)
    assert result.report["status"] == "passed_noop"
    assert result.report["source_input_unchanged"] is True
    assert result.report["input_sha256"] == result.report["output_sha256"]
    assert result.report["changed_frame_joint_count"] == 0


def test_pathological_flexion_is_constrained_on_every_one_of_30_bones() -> None:
    hands = _identity(1)
    for bone in HAND_BONES:
        hands[0, HAND_INDEX[bone]] = _flex_quat(bone, 160.0)
    native = hands.copy()

    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 1)],
        observation=_observed(1),
    )
    after = anatomical_angles_deg(result.quats_xyzw)

    np.testing.assert_array_equal(hands, native)
    assert result.report["status"] == "passed_constrained"
    assert result.report["changed_frame_joint_count"] == 30
    assert result.report["changed_bones"] == HAND_BONES
    for bone_index, bone in enumerate(HAND_BONES):
        constraint = HAND_JOINT_CONSTRAINTS[bone]
        assert after["flexion"][0, bone_index] == pytest.approx(
            constraint.flexion_max_deg,
            abs=2e-3,
        )
        assert abs(float(after["abduction"][0, bone_index])) < 2e-3
        assert abs(float(after["twist"][0, bone_index])) < 2e-3


def test_mirrored_hands_share_positive_palmward_flexion_semantics() -> None:
    hands = _identity(1)
    left = "leftIndexIntermediate"
    right = "rightIndexIntermediate"
    hands[0, HAND_INDEX[left]] = _flex_quat(left, 145.0)
    hands[0, HAND_INDEX[right]] = _flex_quat(right, 145.0)

    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 1)],
        observation=_observed(1),
    )
    after = anatomical_angles_deg(result.quats_xyzw)

    assert after["flexion"][0, HAND_INDEX[left]] == pytest.approx(131.0, abs=2e-3)
    assert after["flexion"][0, HAND_INDEX[right]] == pytest.approx(131.0, abs=2e-3)


def test_swing_twist_projection_constrains_outward_and_axial_pathologies() -> None:
    hands = _identity(1)
    abduction_bone = "rightRingProximal"
    extension_bone = "leftLittleIntermediate"
    twist_bone = "rightIndexDistal"
    hands[0, HAND_INDEX[abduction_bone]] = _axis_quat(
        ANATOMICAL_FRAMES[abduction_bone].abduction_axis, 80.0
    )
    hands[0, HAND_INDEX[extension_bone]] = _flex_quat(extension_bone, -100.0)
    hands[0, HAND_INDEX[twist_bone]] = _twist_quat(twist_bone, 100.0)

    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 1)],
        observation=_observed(1),
    )
    after = anatomical_angles_deg(result.quats_xyzw)

    assert after["abduction"][0, HAND_INDEX[abduction_bone]] == pytest.approx(
        20.0, abs=2e-3
    )
    assert after["flexion"][0, HAND_INDEX[extension_bone]] == pytest.approx(
        -30.0, abs=2e-3
    )
    assert after["twist"][0, HAND_INDEX[twist_bone]] == pytest.approx(8.0, abs=2e-3)
    assert result.report["clipped_frame_dof_count"] == 3


def test_position_evidence_neutralizes_unobservable_twist_and_leaf_dofs() -> None:
    hands = _identity(1)
    proximal = "leftIndexProximal"
    intermediate = "leftIndexIntermediate"
    distal = "leftIndexDistal"
    hands[0, HAND_INDEX[proximal]] = quat_multiply_xyzw(
        _flex_quat(proximal, 40.0), _twist_quat(proximal, 50.0)
    )
    hands[0, HAND_INDEX[intermediate]] = _twist_quat(intermediate, -50.0)
    hands[0, HAND_INDEX[distal]] = _flex_quat(distal, 45.0)

    observation = HandObservationMetadata.position_directions(
        source="joint_positions_without_fingertips",
        fps=30.0,
    )
    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 1)],
        observation=observation,
    )
    after = anatomical_angles_deg(result.quats_xyzw)

    assert after["flexion"][0, HAND_INDEX[proximal]] == pytest.approx(40.0, abs=2e-3)
    assert after["twist"][0, HAND_INDEX[proximal]] == pytest.approx(0.0, abs=2e-3)
    assert after["twist"][0, HAND_INDEX[intermediate]] == pytest.approx(0.0, abs=2e-3)
    for dof in ("flexion", "abduction", "twist"):
        assert after[dof][0, HAND_INDEX[distal]] == pytest.approx(0.0, abs=2e-3)
    unresolved = result.report["observation"]["unobservable_dofs"]
    assert {entry["resolution"] for entry in unresolved} == {"neutral_identity_policy"}
    assert {entry["dof"] for entry in unresolved if entry["bone"] == distal} == {
        "flexion",
        "abduction",
        "twist",
    }


def test_position_evidence_neutralizes_thumb_without_using_thumb_geometry() -> None:
    hands = _identity(1)
    positions = _identity_joint_positions(1)
    thumb_bones = [bone for bone in HAND_BONES if "Thumb" in bone]
    for index, bone in enumerate(thumb_bones, start=1):
        hands[0, HAND_INDEX[bone]] = quat_multiply_xyzw(
            _flex_quat(bone, 8.0 * index),
            _twist_quat(bone, 3.0 * index),
        )

    # Thumb centres alone do not define the independent CMC/opposition frame
    # required to label clinical flexion/abduction.  Deliberately collapse the
    # thumb chains: the position path must not inspect or invent those DOFs.
    for side in ("left", "right"):
        wrist = positions[f"{side}Hand"].copy()
        for level in ("Proximal", "Intermediate", "Distal"):
            positions[f"{side}Thumb{level}"] = wrist.copy()

    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 1)],
        observation=HandObservationMetadata.position_directions(
            source="joint_centres_without_calibrated_thumb_frame",
            fps=30.0,
        ),
        position_evidence=positions,
    )

    identity = np.asarray([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    for bone in thumb_bones:
        np.testing.assert_allclose(
            result.quats_xyzw[0, HAND_INDEX[bone]],
            identity,
            atol=1e-6,
        )
        assert result.report["observation"]["per_bone"][bone] == {
            "flexion": "unobservable",
            "abduction": "unobservable",
            "twist": "unobservable",
        }


def test_calibrated_rotation_evidence_preserves_safe_thumb_rotation() -> None:
    hands = _identity(1)
    bone = "rightThumbIntermediate"
    hands[0, HAND_INDEX[bone]] = quat_multiply_xyzw(
        _flex_quat(bone, 30.0),
        _twist_quat(bone, 5.0),
    )
    native = hands.copy()

    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 1)],
        observation=_observed(1),
    )

    np.testing.assert_array_equal(result.quats_xyzw, native)
    assert result.report["observation"]["per_bone"][bone] == {
        "flexion": "observed",
        "abduction": "observed",
        "twist": "observed",
    }


def test_position_geometry_overrides_wrong_local_sign_and_projects_bend_plane() -> None:
    hands = _identity(1)
    positions = _identity_joint_positions(1)

    extension_bone = "rightLittleIntermediate"
    extension_parent = "rightLittleProximal"
    extension_child = "rightLittleDistal"
    first = positions[extension_bone] - positions[extension_parent]
    first /= np.linalg.norm(first, axis=-1, keepdims=True)
    palmward = np.asarray([[0.0, -1.0, 0.0]], dtype=np.float32)
    extension_angle = np.radians(np.float32(-105.133))
    extension_direction = (
        np.cos(extension_angle) * first + np.sin(extension_angle) * palmward
    )
    segment_length = np.linalg.norm(
        positions[extension_child] - positions[extension_bone], axis=-1, keepdims=True
    )
    positions[extension_child] = (
        positions[extension_bone] + segment_length * extension_direction
    )
    # This deliberately recreates the failure mode: a fixed local-axis audit
    # calls the same motion +105 degrees of flexion, while joint geometry proves
    # it is -105.133 degrees of extension.
    hands[0, HAND_INDEX[extension_bone]] = _flex_quat(extension_bone, 105.133)
    assert anatomical_angles_deg(hands)["flexion"][
        0, HAND_INDEX[extension_bone]
    ] == pytest.approx(105.133, abs=2e-3)

    plane_bone = "rightRingIntermediate"
    plane_parent = "rightRingProximal"
    plane_child = "rightRingDistal"
    plane_first = positions[plane_bone] - positions[plane_parent]
    plane_first /= np.linalg.norm(plane_first, axis=-1, keepdims=True)
    flexion_axis = np.cross(plane_first, palmward)
    flexion_axis /= np.linalg.norm(flexion_axis, axis=-1, keepdims=True)
    tangent_axis = np.cross(plane_first, flexion_axis)
    bend_plane = np.radians(np.float32(60.0))
    bend_normal = np.cos(bend_plane) * flexion_axis + np.sin(bend_plane) * tangent_axis
    transverse = np.cross(bend_normal, plane_first)
    flexion = np.radians(np.float32(80.0))
    plane_direction = np.cos(flexion) * plane_first + np.sin(flexion) * transverse
    plane_length = np.linalg.norm(
        positions[plane_child] - positions[plane_bone], axis=-1, keepdims=True
    )
    positions[plane_child] = positions[plane_bone] + plane_length * plane_direction
    hands[0, HAND_INDEX[plane_bone]] = _flex_quat(plane_bone, 80.0)
    positions_guard = {name: values.copy() for name, values in positions.items()}

    observation = HandObservationMetadata.position_directions(
        source="synthetic_joint_centres",
        fps=30.0,
    )
    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 1)],
        observation=observation,
        position_evidence=positions,
    )

    extension_report = result.report["per_bone"][extension_bone]
    plane_report = result.report["per_bone"][plane_bone]
    assert extension_report["before_deg"]["flexion"]["min"] == pytest.approx(
        -105.133, abs=2e-3
    )
    assert extension_report["after_deg"]["flexion"]["min"] == pytest.approx(
        -30.0, abs=2e-3
    )
    assert plane_report["before_deg"]["abduction"]["max"] == pytest.approx(
        60.0, abs=2e-3
    )
    assert abs(plane_report["after_deg"]["abduction"]["max"]) <= 8.002
    assert result.report["position_evidence"]["mode"] == "provided_joint_positions"
    assert result.report["position_evidence"]["claim"] == "source_joint_centres"
    assert len(result.report["position_evidence"]["sha256"]) == 64
    for name, values in positions.items():
        np.testing.assert_array_equal(values, positions_guard[name])


def test_position_geometry_mcp_spherical_abduction_is_mirror_invariant() -> None:
    hands = _identity(1)
    positions = _identity_joint_positions(1)
    angle = np.radians(np.float32(20.0))
    palmward = np.asarray([[0.0, -1.0, 0.0]], dtype=np.float32)

    for side in ("left", "right"):
        bone = f"{side}IndexProximal"
        child = f"{side}IndexIntermediate"
        distal = f"{side}IndexDistal"
        reference = positions[child] - positions[bone]
        segment_length = np.linalg.norm(reference, axis=-1, keepdims=True)
        reference /= segment_length
        abduction_direction = np.cross(reference, palmward)
        abduction_direction /= np.linalg.norm(
            abduction_direction, axis=-1, keepdims=True
        )
        outgoing = np.cos(angle) * reference + np.sin(angle) * abduction_direction
        positions[child] = positions[bone] + segment_length * outgoing
        distal_length = np.linalg.norm(
            positions[distal] - _identity_joint_positions(1)[child],
            axis=-1,
            keepdims=True,
        )
        positions[distal] = positions[child] + distal_length * outgoing
        hands[0, HAND_INDEX[bone]] = quat_from_two_vectors_xyzw(
            np.asarray(DEFAULT_REST_OFFSETS[child], dtype=np.float32),
            outgoing[0],
        )

    native = hands.copy()
    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 1)],
        observation=HandObservationMetadata.position_directions(
            source="synthetic_mirrored_pure_MCP_abduction",
            fps=30.0,
        ),
        position_evidence=positions,
    )

    np.testing.assert_array_equal(result.quats_xyzw, native)
    assert result.report["status"] == "passed_noop"
    for side in ("left", "right"):
        before = result.report["per_bone"][f"{side}IndexProximal"]["before_deg"]
        assert before["flexion"]["min"] == pytest.approx(0.0, abs=2e-3)
        assert before["abduction"]["min"] == pytest.approx(20.0, abs=2e-3)


def test_near_straight_pip_bend_plane_is_frame_unobservable_and_neutralized() -> None:
    frame_count = 31
    hands = _identity(frame_count)
    positions = _identity_joint_positions(frame_count)
    bend_deg = np.linspace(
        0.001,
        PIP_BEND_OBSERVABILITY_THRESHOLD_DEG - 0.001,
        frame_count,
        dtype=np.float32,
    )
    plane_deg = np.linspace(-179.0, 179.0, frame_count, dtype=np.float32)
    palmward = np.broadcast_to(
        np.asarray([0.0, -1.0, 0.0], dtype=np.float32),
        (frame_count, 3),
    )
    intermediate_bones: list[str] = []

    for side in ("left", "right"):
        for finger in ("Index", "Middle", "Ring", "Little"):
            bone = f"{side}{finger}Intermediate"
            parent = f"{side}{finger}Proximal"
            child = f"{side}{finger}Distal"
            intermediate_bones.append(bone)
            reference = positions[bone] - positions[parent]
            reference /= np.linalg.norm(reference, axis=-1, keepdims=True)
            flexion_axis = np.cross(reference, palmward)
            flexion_axis /= np.linalg.norm(flexion_axis, axis=-1, keepdims=True)
            tangent_axis = np.cross(reference, flexion_axis)
            tangent_axis /= np.linalg.norm(tangent_axis, axis=-1, keepdims=True)
            plane = np.radians(plane_deg)[:, None]
            bend_normal = np.cos(plane) * flexion_axis + np.sin(plane) * tangent_axis
            transverse = np.cross(bend_normal, reference)
            bend = np.radians(bend_deg)[:, None]
            outgoing = np.cos(bend) * reference + np.sin(bend) * transverse
            segment_length = np.linalg.norm(
                positions[child] - positions[bone],
                axis=-1,
                keepdims=True,
            )
            positions[child] = positions[bone] + segment_length * outgoing
            rest_outgoing = np.broadcast_to(
                np.asarray(DEFAULT_REST_OFFSETS[child], dtype=np.float32),
                outgoing.shape,
            )
            hands[:, HAND_INDEX[bone]] = quat_from_two_vectors_xyzw(
                rest_outgoing,
                outgoing,
            )

    native_hands = hands.copy()
    native_positions = {name: values.copy() for name, values in positions.items()}
    segments = [(0, 10), (10, 20), (20, frame_count)]
    result = solve_hand_constraints(
        hands,
        continuity_segments=segments,
        observation=HandObservationMetadata.position_directions(
            source="synthetic_near_straight_PIP_conditioning_grid",
            fps=30.0,
        ),
        position_evidence=positions,
    )

    np.testing.assert_array_equal(hands, native_hands)
    for name, values in positions.items():
        np.testing.assert_array_equal(values, native_positions[name])
    identity = np.asarray([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    for bone in intermediate_bones:
        np.testing.assert_allclose(
            result.quats_xyzw[:, HAND_INDEX[bone]],
            np.broadcast_to(identity, (frame_count, 4)),
            atol=1e-6,
        )

    conditioned = result.report["frame_conditioned_unobservable"]
    assert conditioned["active"] is True
    assert conditioned["pip_bend_observability_threshold_deg"] == 0.5
    assert conditioned["resolution"] == "neutral_zero_swing"
    assert conditioned["frame_joint_count"] == frame_count * 8
    assert conditioned["frame_dof_count"] == frame_count * 8 * 2
    assert conditioned["ranges_respect_continuity_segments"] is True
    for bone in intermediate_bones:
        item = conditioned["per_bone"][bone]
        assert item["near_straight_frame_count"] == frame_count
        assert item["near_straight_frames_half_open"] == [
            [0, 10],
            [10, 20],
            [20, frame_count],
        ]
        assert item["source_bend_magnitude_deg"]["max"] < 0.5
        assert item["unobservable_dofs"] == ["flexion", "abduction"]
        assert item["resolution"] == "neutral_zero_swing"
    assert verify_hand_constraint_certificate(result.report, result.quats_xyzw)


def test_unobservable_reject_policy_fails_closed() -> None:
    observation = HandObservationMetadata.position_directions(
        source="positions",
        fps=30.0,
        unobservable_policy="reject",
    )
    with pytest.raises(HandConstraintError, match="unobservable_dof_rejected") as exc:
        solve_hand_constraints(
            _identity(1),
            continuity_segments=[(0, 1)],
            observation=observation,
        )
    assert exc.value.code == "unobservable_dof_rejected"


def test_inferred_dof_requires_named_approved_prior_and_is_reported() -> None:
    per_bone = {
        bone: JointObservation("observed", "observed", "observed")
        for bone in HAND_BONES
    }
    bone = "rightLittleDistal"
    per_bone[bone] = JointObservation("observed", "observed", "inferred")
    hands = _identity(1)
    hands[0, HAND_INDEX[bone]] = _twist_quat(bone, 6.0)

    rejected = HandObservationMetadata(
        source="model_output",
        fps=30.0,
        per_bone=per_bone,
        inference_prior_id="unapproved.model.v9",
    )
    with pytest.raises(HandConstraintError, match="unapproved_inference_prior"):
        solve_hand_constraints(
            hands,
            continuity_segments=[(0, 1)],
            observation=rejected,
        )

    approved = HandObservationMetadata(
        source="model_output",
        fps=30.0,
        per_bone=per_bone,
        inference_prior_id=NEUTRAL_HAND_PRIOR_ID,
    )
    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 1)],
        observation=approved,
    )
    assert anatomical_angles_deg(result.quats_xyzw)["twist"][
        0, HAND_INDEX[bone]
    ] == pytest.approx(0.0, abs=2e-3)
    assert result.report["observation"]["inferred_dofs"] == [
        {
            "bone": bone,
            "dof": "twist",
            "resolution": "neutral_identity_prior",
            "prior_id": NEUTRAL_HAND_PRIOR_ID,
        }
    ]


def test_absolute_180_degree_rotation_fails_closed() -> None:
    hands = _identity(1)
    bone = "leftMiddleIntermediate"
    hands[0, HAND_INDEX[bone]] = _flex_quat(bone, 180.0)

    with pytest.raises(HandConstraintError, match="rotation_180_degenerate") as exc:
        solve_hand_constraints(
            hands,
            continuity_segments=[(0, 1)],
            observation=_observed(1),
        )
    assert exc.value.code == "rotation_180_degenerate"


def test_temporal_180_degree_ambiguity_respects_declared_segments() -> None:
    hands = _identity(2)
    bone = "leftIndexIntermediate"
    hands[0, HAND_INDEX[bone]] = _flex_quat(bone, 90.0)
    hands[1, HAND_INDEX[bone]] = _flex_quat(bone, -90.0)

    with pytest.raises(HandConstraintError, match="temporal_180_degenerate"):
        solve_hand_constraints(
            hands,
            continuity_segments=[(0, 2)],
            observation=_observed(2),
        )

    result = solve_hand_constraints(
        hands,
        continuity_segments=[(0, 1), (1, 2)],
        observation=_observed(2),
    )
    assert result.report["continuity_segments_frames_half_open"] == [[0, 1], [1, 2]]
    assert result.report["status"] == "passed_constrained"


@pytest.mark.parametrize(
    "segments",
    [[], [(1, 2)], [(0, 1)], [(0, 2), (1, 3)], [(0, 0), (0, 3)]],
)
def test_continuity_segments_must_exactly_partition_the_sequence(
    segments: list[tuple[int, int]],
) -> None:
    with pytest.raises(HandConstraintError, match="invalid_continuity_segments"):
        solve_hand_constraints(
            _identity(3),
            continuity_segments=segments,
            observation=_observed(3),
        )


def test_observation_metadata_must_cover_exactly_all_bones() -> None:
    observation = HandObservationMetadata(
        source="partial",
        fps=30.0,
        per_bone={HAND_BONES[0]: JointObservation("observed", "observed", "observed")},
    )
    with pytest.raises(HandConstraintError, match="incomplete_observation_metadata"):
        solve_hand_constraints(
            _identity(1),
            continuity_segments=[(0, 1)],
            observation=observation,
        )


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (lambda value: value.astype(np.float64), "invalid_hand_dtype"),
        (
            lambda value: np.concatenate([value, value[:, :1]], axis=1),
            "invalid_hand_shape",
        ),
    ],
)
def test_invalid_canonical_inputs_fail_closed(mutator, error_code: str) -> None:
    with pytest.raises(HandConstraintError, match=error_code):
        solve_hand_constraints(
            mutator(_identity(1)),
            continuity_segments=[(0, 1)],
            observation=_observed(1),
        )


def test_nonfinite_and_nonunit_inputs_fail_closed() -> None:
    nonfinite = _identity(1)
    nonfinite[0, 0, 0] = np.nan
    with pytest.raises(HandConstraintError, match="nonfinite_hand_quaternion"):
        solve_hand_constraints(
            nonfinite,
            continuity_segments=[(0, 1)],
            observation=_observed(1),
        )

    nonunit = _identity(1)
    nonunit[0, 0] *= 2.0
    with pytest.raises(HandConstraintError, match="nonunit_hand_quaternion"):
        solve_hand_constraints(
            nonunit,
            continuity_segments=[(0, 1)],
            observation=_observed(1),
        )


def test_report_and_certificate_are_deterministic_json_safe() -> None:
    hands = _identity(2)
    bone = "rightThumbDistal"
    hands[1, HAND_INDEX[bone]] = _flex_quat(bone, 120.0)
    kwargs = {
        "continuity_segments": [(0, 2)],
        "observation": _observed(2),
    }

    first = solve_hand_constraints(hands, **kwargs)
    second = solve_hand_constraints(hands, **kwargs)

    np.testing.assert_array_equal(first.quats_xyzw, second.quats_xyzw)
    assert first.report == second.report
    assert json.dumps(first.report, sort_keys=True, allow_nan=False)
    assert first.report["schema_version"] == HAND_SOLVER_SCHEMA_VERSION
    assert first.report["policy_id"] == HAND_CONSTRAINT_POLICY_ID
    assert first.report["policy_sha256"] == HAND_CONSTRAINT_POLICY_SHA256
    assert len(first.report["certificate"]["sha256"]) == 64
    assert first.report["certificate"]["verified"] is True
    assert verify_hand_constraint_certificate(first.report, first.quats_xyzw)
    assert first.report == copy.deepcopy(first.report)

    tampered_report = copy.deepcopy(first.report)
    tampered_report["changed_frame_joint_count"] += 1
    assert not verify_hand_constraint_certificate(tampered_report, first.quats_xyzw)
    tampered_output = first.quats_xyzw.copy()
    tampered_output[0, 0] = _flex_quat(HAND_BONES[0], 1.0)
    assert not verify_hand_constraint_certificate(first.report, tampered_output)
