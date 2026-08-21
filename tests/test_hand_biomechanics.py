from __future__ import annotations

import numpy as np
import pytest

from virea.motion.hand_biomechanics import (
    ANGLE_COMPARISON_TOLERANCE_DEG,
    HAND_BIOMECHANICS_SCHEMA_VERSION,
    PIP_BEND_PLANE_REVIEW_DEG,
    PIP_ENVELOPE_PROJECTION_SCHEMA_VERSION,
    PIP_HARD_REVIEW_DEG,
    PIP_HEALTHY_EXTENSION_MEAN_PLUS_2SD_DEG,
    PIP_HEALTHY_MEAN_PLUS_2SD_DEG,
    PROJECTION_INTERIOR_MARGIN_DEG,
    analyze_hand_joint_positions,
    derive_observable_non_thumb_pip_envelope_positions,
)
from virea.motion.skeleton import BODY_BONES, BODY_INDEX


def _observable_index_fixture(
    angles_deg: list[float],
    *,
    sides: tuple[str, ...] = ("left",),
    bend_mode: str = "flexion",
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    frame_count = len(angles_deg)
    body = np.zeros((frame_count, len(BODY_BONES), 3), dtype=np.float32)
    hand_positions: dict[str, np.ndarray] = {}
    angles = np.radians(np.asarray(angles_deg, dtype=np.float32))

    for side in sides:
        mirror = 1.0 if side == "left" else -1.0
        body[:, BODY_INDEX[f"{side}Hand"]] = 0.0
        index_root = np.broadcast_to(
            np.asarray([mirror, 0.0, 1.0], dtype=np.float32),
            (frame_count, 3),
        ).copy()
        middle_root = np.broadcast_to(
            np.asarray([mirror, 0.0, 0.0], dtype=np.float32),
            (frame_count, 3),
        ).copy()
        little_root = np.broadcast_to(
            np.asarray([mirror, 0.0, -1.0], dtype=np.float32),
            (frame_count, 3),
        ).copy()
        first_segment = np.broadcast_to(
            np.asarray([mirror, 0.0, 0.0], dtype=np.float32),
            (frame_count, 3),
        ).copy()
        if bend_mode == "flexion":
            # The side-oriented anatomical convention defines -Y as positive
            # flexion for both mirrored hands in this fixture.
            second_segment = np.stack(
                [
                    mirror * np.cos(angles),
                    -np.sin(angles),
                    np.zeros(frame_count),
                ],
                axis=1,
            ).astype(np.float32)
        elif bend_mode == "extension":
            second_segment = np.stack(
                [
                    mirror * np.cos(angles),
                    np.sin(angles),
                    np.zeros(frame_count),
                ],
                axis=1,
            ).astype(np.float32)
        elif bend_mode == "palm_plane":
            # A sideways bend stays in the XZ palm plane and should be 90
            # degrees away from the per-finger flexion axis.
            second_segment = np.stack(
                [
                    mirror * np.cos(angles),
                    np.zeros(frame_count),
                    np.sin(angles),
                ],
                axis=1,
            ).astype(np.float32)
        elif bend_mode == "diagonal":
            flexion_direction = np.broadcast_to(
                np.asarray([0.0, -1.0, 0.0], dtype=np.float32),
                (frame_count, 3),
            ).copy()
            flexion_axis = np.cross(first_segment, flexion_direction)
            tangent_axis = np.cross(first_segment, flexion_axis)
            bend_normal = (flexion_axis + tangent_axis) / np.sqrt(2.0)
            transverse = np.cross(bend_normal, first_segment)
            second_segment = (
                np.cos(angles)[:, None] * first_segment
                + np.sin(angles)[:, None] * transverse
            ).astype(np.float32)
        else:
            raise ValueError(f"unsupported bend mode: {bend_mode}")

        hand_positions[f"{side}IndexProximal"] = index_root
        hand_positions[f"{side}MiddleProximal"] = middle_root
        hand_positions[f"{side}LittleProximal"] = little_root
        hand_positions[f"{side}IndexIntermediate"] = index_root + first_segment
        hand_positions[f"{side}IndexDistal"] = (
            index_root + first_segment + second_segment
        )

    return body, hand_positions


def _uniform_all_finger_fixture(
    angle_deg: float,
    *,
    bend_mode: str,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    body = np.zeros((1, len(BODY_BONES), 3), dtype=np.float32)
    hands: dict[str, np.ndarray] = {}
    root_z = {"Index": 1.0, "Middle": 0.25, "Ring": -0.3, "Little": -1.0}
    angle = np.radians(np.float32(angle_deg))
    for side in ("left", "right"):
        mirror = 1.0 if side == "left" else -1.0
        body[:, BODY_INDEX[f"{side}Hand"]] = 0.0
        first = np.asarray([[mirror, 0.0, 0.0]], dtype=np.float32)
        if bend_mode == "flexion":
            second = np.asarray(
                [[mirror * np.cos(angle), -np.sin(angle), 0.0]],
                dtype=np.float32,
            )
        elif bend_mode == "extension":
            second = np.asarray(
                [[mirror * np.cos(angle), np.sin(angle), 0.0]],
                dtype=np.float32,
            )
        elif bend_mode == "antiparallel":
            second = -first
        else:
            raise ValueError(f"unsupported bend mode: {bend_mode}")
        for finger, z_offset in root_z.items():
            root = np.asarray([[mirror, 0.0, z_offset]], dtype=np.float32)
            intermediate = root + first
            hands[f"{side}{finger}Proximal"] = root
            hands[f"{side}{finger}Intermediate"] = intermediate
            hands[f"{side}{finger}Distal"] = intermediate + second
    return body, hands


def test_hand_biomechanics_is_mirror_invariant_in_palm_relative_coordinates() -> None:
    body, hands = _observable_index_fixture([72.0], sides=("left", "right"))
    report = analyze_hand_joint_positions(body, hands)

    left = report["per_joint"]["leftIndexPIP"]
    right = report["per_joint"]["rightIndexPIP"]
    assert report["schema_version"] == HAND_BIOMECHANICS_SCHEMA_VERSION
    assert report["status"] == "within_hard_review_envelope"
    assert left["mean_deg"] == pytest.approx(72.0, abs=1e-4)
    assert right["mean_deg"] == pytest.approx(left["mean_deg"], abs=1e-4)
    assert left["signed_min_deg"] == pytest.approx(72.0, abs=1e-4)
    assert right["signed_min_deg"] == pytest.approx(left["signed_min_deg"], abs=1e-4)
    assert left["bend_plane_max_deviation_deg"] == pytest.approx(0.0, abs=1e-4)
    assert right["bend_plane_max_deviation_deg"] == pytest.approx(0.0, abs=1e-4)


@pytest.mark.parametrize("extension_deg", [90.0, 179.9])
def test_mirrored_extension_is_not_misclassified_as_flexion(
    extension_deg: float,
) -> None:
    body, hands = _uniform_all_finger_fixture(
        extension_deg,
        bend_mode="extension",
    )
    native = {name: values.copy() for name, values in hands.items()}

    report = analyze_hand_joint_positions(body, hands)
    projection = derive_observable_non_thumb_pip_envelope_positions(body, hands)

    assert report["status"] == "review_required"
    assert report["signed_angle_convention"] == (
        "positive_anatomical_flexion_negative_extension_side_oriented"
    )
    assert report["flexion_limit_violation_count"] == 0
    assert report["extension_limit_violation_count"] == 8
    assert report["bend_plane_violation_count"] == 0
    assert report["review_candidate_count"] == 8
    assert report["extension_limit_provenance"]["pmid"] == "39345665"
    assert report["motion_mutated"] is False
    for side in ("left", "right"):
        for finger in ("Index", "Middle", "Ring", "Little"):
            joint = report["per_joint"][f"{side}{finger}PIP"]
            assert joint["signed_min_deg"] == pytest.approx(
                -extension_deg,
                abs=0.01,
            )
            assert joint["flexion_max_deg"] == pytest.approx(0.0, abs=1e-4)
            assert joint["extension_max_deg"] == pytest.approx(
                extension_deg,
                abs=0.01,
            )
            assert joint["extension_limit_violation_frames_half_open"] == [[0, 1]]

    derived_report = projection["derived_diagnostics"]
    assert derived_report["flexion_limit_violation_count"] == 0
    assert derived_report["extension_limit_violation_count"] == 0
    assert derived_report["bend_plane_violation_count"] == 0
    assert projection["change_metadata"]["changed_frame_joint_count"] == 8
    for name, values in hands.items():
        np.testing.assert_array_equal(values, native[name])


def test_antiparallel_pip_is_reviewed_but_not_projected_without_a_bend_plane() -> None:
    body, hands = _uniform_all_finger_fixture(180.0, bend_mode="antiparallel")
    native = {name: values.copy() for name, values in hands.items()}

    report = analyze_hand_joint_positions(body, hands)
    projection = derive_observable_non_thumb_pip_envelope_positions(body, hands)

    assert report["status"] == "review_required"
    assert report["direction_unobservable_violation_count"] == 8
    assert report["review_candidate_count"] == 8
    assert report["max_pip_deg"] == pytest.approx(180.0, abs=1e-4)
    assert projection["change_metadata"]["changed_frame_joint_count"] == 0
    assert (
        projection["change_metadata"]["unresolved_unobservable_frame_joint_count"] == 8
    )
    assert (
        projection["derived_diagnostics"]["direction_unobservable_violation_count"] == 8
    )
    for name, values in hands.items():
        np.testing.assert_array_equal(values, native[name])
        np.testing.assert_array_equal(
            projection["derived_hand_positions_by_name"][name],
            native[name],
        )


def test_hand_biomechanics_distinguishes_flexion_from_in_palm_sideways_bend() -> None:
    flexion_body, flexion_hands = _observable_index_fixture(
        [72.0],
        sides=("left", "right"),
        bend_mode="flexion",
    )
    sideways_body, sideways_hands = _observable_index_fixture(
        [72.0],
        sides=("left", "right"),
        bend_mode="palm_plane",
    )

    flexion = analyze_hand_joint_positions(flexion_body, flexion_hands)
    sideways = analyze_hand_joint_positions(sideways_body, sideways_hands)

    for side in ("left", "right"):
        joint = f"{side}IndexPIP"
        assert flexion["per_joint"][joint][
            "bend_plane_max_deviation_deg"
        ] == pytest.approx(0.0, abs=1e-4)
        assert sideways["per_joint"][joint][
            "bend_plane_max_deviation_deg"
        ] == pytest.approx(90.0, abs=1e-4)
        assert sideways["per_joint"][joint][
            "bend_plane_violation_frames_half_open"
        ] == [[0, 1]]

    assert PIP_BEND_PLANE_REVIEW_DEG == 45.0
    assert flexion["status"] == "within_hard_review_envelope"
    assert sideways["status"] == "review_required"
    assert sideways["violation_count"] == 0
    assert sideways["bend_plane_violation_count"] == 2
    assert sideways["review_candidate_count"] == 2
    assert sideways["motion_mutated"] is False
    assert sideways["regularization_applied"] is False
    assert sideways["source_motion_preserved"] is True
    assert sideways["threshold_semantics"]["bend_plane_review_deg"] == (
        "project_geometric_qc_midpoint_not_physiological_rom"
    )


def test_hand_biomechanics_reports_strict_limit_as_half_open_frame_ranges() -> None:
    body, hands = _observable_index_fixture([10.0, 130.0, 130.01, 140.0, 20.0, 150.0])
    report = analyze_hand_joint_positions(body, hands)
    index = report["per_joint"]["leftIndexPIP"]

    assert PIP_HARD_REVIEW_DEG == 130.0
    assert report["hard_limit_policy"] == "diagnostic_only_no_motion_mutation"
    assert report["status"] == "review_required"
    assert report["violation_count"] == 3
    assert report["pip_limit_violation_count"] == 3
    assert report["bend_plane_violation_count"] == 0
    assert report["review_candidate_count"] == 3
    assert index["violation_frames_half_open"] == [[2, 4], [5, 6]]
    assert index["max_deg"] == pytest.approx(150.0, abs=1e-4)
    assert report["dip_observability"] == (
        "unobservable_without_fingertip_or_calibrated_rotation_frame"
    )


def _pip_angles_deg(
    hand_positions: dict[str, np.ndarray],
    *,
    side: str = "left",
    finger: str = "Index",
) -> np.ndarray:
    proximal = hand_positions[f"{side}{finger}Proximal"]
    intermediate = hand_positions[f"{side}{finger}Intermediate"]
    distal = hand_positions[f"{side}{finger}Distal"]
    first = intermediate - proximal
    second = distal - intermediate
    first /= np.linalg.norm(first, axis=-1, keepdims=True)
    second /= np.linalg.norm(second, axis=-1, keepdims=True)
    cosine = np.clip(np.sum(first * second, axis=-1), -1.0, 1.0)
    return np.degrees(np.arccos(cosine))


def test_opt_in_pip_projection_preserves_native_data_and_bone_lengths() -> None:
    body, hands = _observable_index_fixture([60.0, 150.0, 60.0])
    native_copy = {name: values.copy() for name, values in hands.items()}
    native_length = np.linalg.norm(
        hands["leftIndexDistal"] - hands["leftIndexIntermediate"],
        axis=-1,
    )

    result = derive_observable_non_thumb_pip_envelope_positions(body, hands)
    derived = result["derived_hand_positions_by_name"]
    derived_length = np.linalg.norm(
        derived["leftIndexDistal"] - derived["leftIndexIntermediate"],
        axis=-1,
    )
    derived_angles = _pip_angles_deg(derived)
    framewise_clamped = np.asarray([60.0, 131.0, 60.0], dtype=np.float32)

    assert result["schema_version"] == PIP_ENVELOPE_PROJECTION_SCHEMA_VERSION
    for name, values in hands.items():
        np.testing.assert_array_equal(values, native_copy[name])
    np.testing.assert_allclose(derived_length, native_length, atol=1e-6)
    assert float(np.max(derived_angles)) <= (
        PIP_HEALTHY_MEAN_PLUS_2SD_DEG["Index"] + 1e-4
    )
    # The bounded first-difference solve has lower temporal variation than an
    # isolated framewise clamp while retaining the same hard upper bound.
    assert float(np.sum(np.abs(np.diff(derived_angles)))) < float(
        np.sum(np.abs(np.diff(framewise_clamped)))
    )

    changes = result["change_metadata"]
    assert changes["provenance"] == (
        "derived_observable_non_thumb_PIP_envelope_projection"
    )
    assert changes["requires_explicit_opt_in"] is True
    assert changes["pipeline_integration"] == "none"
    assert changes["native_input_mutated"] is False
    assert changes["source_faithful_default_unchanged"] is True
    assert changes["bone_length_policy"] == "preserved"
    assert changes["scope"] == "observable_non_thumb_PIP_distal_joint_centers_only"
    assert changes["no_go_scope"] == (
        "thumb_MCP_DIP_twist_and_unobservable_leaf_orientation"
    )
    assert changes["changed_frame_joint_count"] == 3
    assert changes["max_bone_length_error"] < 1e-6
    assert changes["pip_limit_provenance"]["pmid"] == "39345665"
    assert changes["pip_limit_provenance"]["limits_deg"] == (
        PIP_HEALTHY_MEAN_PLUS_2SD_DEG
    )
    assert changes["pip_limit_provenance"]["extension_limits_deg"] == (
        PIP_HEALTHY_EXTENSION_MEAN_PLUS_2SD_DEG
    )


def test_opt_in_pip_projection_limits_sideways_bend_for_both_hands() -> None:
    body, hands = _observable_index_fixture(
        [72.0, 72.0, 72.0],
        sides=("left", "right"),
        bend_mode="palm_plane",
    )
    native_lengths = {
        side: np.linalg.norm(
            hands[f"{side}IndexDistal"] - hands[f"{side}IndexIntermediate"],
            axis=-1,
        )
        for side in ("left", "right")
    }

    result = derive_observable_non_thumb_pip_envelope_positions(body, hands)
    derived = result["derived_hand_positions_by_name"]

    for side in ("left", "right"):
        joint = result["change_metadata"]["per_joint"][f"{side}IndexPIP"]
        assert joint["native_max_bend_plane_deviation_deg"] == pytest.approx(
            90.0,
            abs=1e-4,
        )
        assert joint["derived_max_bend_plane_deviation_deg"] <= 45.0001
        derived_length = np.linalg.norm(
            derived[f"{side}IndexDistal"] - derived[f"{side}IndexIntermediate"],
            axis=-1,
        )
        np.testing.assert_allclose(derived_length, native_lengths[side], atol=1e-6)
        assert (
            result["derived_diagnostics"]["per_joint"][f"{side}IndexPIP"][
                "bend_plane_max_deviation_deg"
            ]
            <= 45.0001
        )

    assert result["change_metadata"]["bend_plane_limit_provenance"] == {
        "kind": "project_geometric_qc_threshold",
        "limit_deg": 45.0,
        "interpretation": "not_a_published_physiological_rom_limit",
    }


def test_per_finger_limits_and_numeric_boundaries_are_self_consistent() -> None:
    body, at_index_limit = _observable_index_fixture([131.0])
    report = analyze_hand_joint_positions(
        body,
        at_index_limit,
        pip_upper_limits_deg=PIP_HEALTHY_MEAN_PLUS_2SD_DEG,
    )
    projected = derive_observable_non_thumb_pip_envelope_positions(
        body,
        at_index_limit,
    )

    assert report["pip_limit_mode"] == "per_finger"
    assert report["hard_pip_limit_deg"] is None
    assert report["per_joint"]["leftIndexPIP"]["hard_limit_deg"] == 131.0
    assert report["pip_limit_violation_count"] == 0
    assert projected["change_metadata"]["changed_frame_joint_count"] == 0
    assert projected["derived_diagnostics"]["pip_limit_violation_count"] == 0

    body, at_plane_limit = _observable_index_fixture(
        [72.0],
        bend_mode="diagonal",
    )
    report = analyze_hand_joint_positions(
        body,
        at_plane_limit,
        pip_upper_limits_deg=PIP_HEALTHY_MEAN_PLUS_2SD_DEG,
    )
    projected = derive_observable_non_thumb_pip_envelope_positions(
        body,
        at_plane_limit,
    )
    assert report["bend_plane_violation_count"] == 0
    assert projected["change_metadata"]["changed_frame_joint_count"] == 0
    assert projected["derived_diagnostics"]["bend_plane_violation_count"] == 0
    assert projected["change_metadata"]["comparison_tolerance_deg"] == (
        ANGLE_COMPARISON_TOLERANCE_DEG
    )
    assert projected["change_metadata"]["projection_interior_margin_deg"] == (
        PROJECTION_INTERIOR_MARGIN_DEG
    )


def _random_observable_hand_fixture(
    *,
    seed: int,
    frame_count: int,
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    body = np.zeros((frame_count, len(BODY_BONES), 3), dtype=np.float32)
    hands: dict[str, np.ndarray] = {}
    signed_angle_oracle: dict[str, np.ndarray] = {}
    root_z = {"Index": 1.0, "Middle": 0.25, "Ring": -0.3, "Little": -1.0}

    for side in ("left", "right"):
        mirror = 1.0 if side == "left" else -1.0
        body[:, BODY_INDEX[f"{side}Hand"]] = 0.0
        first = np.broadcast_to(
            np.asarray([mirror, 0.0, 0.0], dtype=np.float32),
            (frame_count, 3),
        ).copy()
        flexion_direction = np.broadcast_to(
            np.asarray([0.0, -1.0, 0.0], dtype=np.float32),
            (frame_count, 3),
        ).copy()
        flexion_axis = np.cross(first, flexion_direction)
        tangent_axis = np.cross(first, flexion_axis)

        for finger in ("Index", "Middle", "Ring", "Little"):
            root = np.broadcast_to(
                np.asarray([mirror, 0.0, root_z[finger]], dtype=np.float32),
                (frame_count, 3),
            ).copy()
            first_length = rng.uniform(0.2, 1.0, frame_count).astype(np.float32)
            second_length = rng.uniform(0.2, 1.0, frame_count).astype(np.float32)
            pip_angle_deg = rng.uniform(0.5, 179.0, frame_count).astype(np.float32)
            pip_angle = np.radians(pip_angle_deg)
            bend_plane_angle = rng.uniform(-np.pi, np.pi, frame_count).astype(
                np.float32
            )
            bend_normal = (
                np.cos(bend_plane_angle)[:, None] * flexion_axis
                + np.sin(bend_plane_angle)[:, None] * tangent_axis
            )
            transverse = np.cross(bend_normal, first)
            second = (
                np.cos(pip_angle)[:, None] * first
                + np.sin(pip_angle)[:, None] * transverse
            )
            intermediate = root + first_length[:, None] * first
            distal = intermediate + second_length[:, None] * second
            hands[f"{side}{finger}Proximal"] = root
            hands[f"{side}{finger}Intermediate"] = intermediate
            hands[f"{side}{finger}Distal"] = distal
            signed_angle_oracle[f"{side}{finger}PIP"] = pip_angle_deg * np.where(
                np.cos(bend_plane_angle) < 0.0,
                -1.0,
                1.0,
            )

    return body, hands, signed_angle_oracle


@pytest.mark.parametrize("seed", [7, 19, 73, 211])
def test_pip_projection_random_observable_geometry_properties(seed: int) -> None:
    body, hands, signed_oracle = _random_observable_hand_fixture(
        seed=seed,
        frame_count=384,
    )
    native = {name: values.copy() for name, values in hands.items()}

    first_result = derive_observable_non_thumb_pip_envelope_positions(body, hands)
    second_result = derive_observable_non_thumb_pip_envelope_positions(body, hands)
    derived = first_result["derived_hand_positions_by_name"]
    diagnostics = first_result["derived_diagnostics"]
    native_diagnostics = first_result["native_diagnostics"]

    expected_flexion_violations = 0
    expected_extension_violations = 0
    for joint_name, signed_angles in signed_oracle.items():
        finger = next(
            finger
            for finger in ("Index", "Middle", "Ring", "Little")
            if finger in joint_name
        )
        expected_flexion_violations += int(
            np.count_nonzero(
                signed_angles
                > PIP_HEALTHY_MEAN_PLUS_2SD_DEG[finger] + ANGLE_COMPARISON_TOLERANCE_DEG
            )
        )
        expected_extension_violations += int(
            np.count_nonzero(
                -signed_angles
                > PIP_HEALTHY_EXTENSION_MEAN_PLUS_2SD_DEG[finger]
                + ANGLE_COMPARISON_TOLERANCE_DEG
            )
        )
        joint_report = native_diagnostics["per_joint"][joint_name]
        assert joint_report["signed_min_deg"] == pytest.approx(
            float(np.min(signed_angles)),
            abs=1e-3,
        )
        assert joint_report["signed_max_deg"] == pytest.approx(
            float(np.max(signed_angles)),
            abs=1e-3,
        )

    assert native_diagnostics["flexion_limit_violation_count"] == (
        expected_flexion_violations
    )
    assert native_diagnostics["extension_limit_violation_count"] == (
        expected_extension_violations
    )

    assert diagnostics["pip_limit_mode"] == "per_finger"
    assert diagnostics["pip_limit_violation_count"] == 0
    assert diagnostics["flexion_limit_violation_count"] == 0
    assert diagnostics["extension_limit_violation_count"] == 0
    assert diagnostics["direction_unobservable_violation_count"] == 0
    assert diagnostics["bend_plane_violation_count"] == 0
    assert diagnostics["review_candidate_count"] == 0
    assert first_result["change_metadata"]["max_bone_length_error"] < 1e-5
    assert first_result["change_metadata"]["changed_frame_joint_count"] > 0

    for side in ("left", "right"):
        for finger in ("Index", "Middle", "Ring", "Little"):
            joint = first_result["change_metadata"]["per_joint"][f"{side}{finger}PIP"]
            assert joint["derived_max_flexion_deg"] <= (
                PIP_HEALTHY_MEAN_PLUS_2SD_DEG[finger] + ANGLE_COMPARISON_TOLERANCE_DEG
            )
            assert joint["derived_max_extension_deg"] <= (
                PIP_HEALTHY_EXTENSION_MEAN_PLUS_2SD_DEG[finger]
                + ANGLE_COMPARISON_TOLERANCE_DEG
            )
            intermediate_name = f"{side}{finger}Intermediate"
            distal_name = f"{side}{finger}Distal"
            native_length = np.linalg.norm(
                native[distal_name] - native[intermediate_name],
                axis=-1,
            )
            derived_length = np.linalg.norm(
                derived[distal_name] - derived[intermediate_name],
                axis=-1,
            )
            np.testing.assert_allclose(derived_length, native_length, atol=1e-5)

    for name, values in hands.items():
        np.testing.assert_array_equal(values, native[name])
        np.testing.assert_array_equal(
            first_result["derived_hand_positions_by_name"][name],
            second_result["derived_hand_positions_by_name"][name],
        )
