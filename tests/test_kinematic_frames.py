"""Frame covariance and length invariants, with independent matrix oracles."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from virea.motion.kinematics import RigGeometry, change_local_frames, rest_frame_binding
from virea.motion.rotation_filter import gaussian_rotation_mean
from virea.motion.skeleton import FK_BONES, canonical_geometry, forward_kinematics
from virea.vrchat.mapping import world_pose


def test_arbitrary_joint_frame_change_preserves_world_geometry_and_bone_lengths():
    rng = np.random.default_rng(8401)
    rig = canonical_geometry()
    local = (
        Rotation.random(20 * len(rig.names), random_state=rng)
        .as_quat()
        .reshape(20, -1, 4)
    )
    root = rng.normal(size=(20, 3))
    frames = Rotation.random(len(rig.names), random_state=rng)
    offsets = rig.offsets.copy()
    for i, p in enumerate(rig.parents[1:], 1):
        offsets[i] = frames[p].inv().apply(offsets[i])
    changed = RigGeometry(rig.names, rig.parents, offsets)
    converted = change_local_frames(local, rig.parents, frames.as_quat())
    a, qa = rig.forward(root, local)
    b, qb = changed.forward(root, converted)
    np.testing.assert_allclose(b, a, atol=5e-14)
    ga = Rotation.from_quat(qa.reshape(-1, 4)).as_matrix().reshape(20, -1, 3, 3)
    gb = Rotation.from_quat(qb.reshape(-1, 4)).as_matrix().reshape(20, -1, 3, 3)
    np.testing.assert_allclose(gb, ga @ frames.as_matrix(), atol=5e-14)
    lengths = np.linalg.norm(b[:, 1:] - b[:, np.array(rig.parents[1:])], axis=-1)
    np.testing.assert_allclose(
        lengths,
        np.broadcast_to(np.linalg.norm(offsets[1:], axis=1), lengths.shape),
        atol=5e-14,
    )


def test_geometric_binding_preserves_observed_chain_directions_under_all_poses():
    rng = np.random.default_rng(1802)
    target = RigGeometry(
        ("root", "arm", "wrist", "finger"),
        (-1, 0, 1, 2),
        np.array([[0, 0, 0], [0.1, 0.3, 0], [0.4, 0, 0], [0.1, 0, 0]]),
    )
    source = RigGeometry(
        target.names,
        target.parents,
        np.array([[0, 0, 0], [0.08, 0.2, 0.1], [0.3, -0.1, 0.04], [0.04, -0.02, 0.03]]),
    )
    binding, residual = rest_frame_binding(source, target)
    q = Rotation.random(400, random_state=rng).as_quat().reshape(100, 4, 4)
    mapped = change_local_frames(q, source.parents, binding)
    p, _ = source.forward(np.zeros((100, 3)), q)
    t, _ = target.forward(np.zeros((100, 3)), mapped)
    for i, parent in enumerate(source.parents[1:], 1):
        a, b = p[:, i] - p[:, parent], t[:, i] - t[:, parent]
        np.testing.assert_allclose(
            a / np.linalg.norm(a, axis=1)[:, None],
            b / np.linalg.norm(b, axis=1)[:, None],
            atol=1e-12,
        )
    assert residual.max() < 1e-12
    # Constant frame changes cannot erase wrist twist or amplify temporal jumps.
    before = (
        Rotation.from_quat(q[:-1].reshape(-1, 4)).inv()
        * Rotation.from_quat(q[1:].reshape(-1, 4))
    ).magnitude()
    after = (
        Rotation.from_quat(mapped[:-1].reshape(-1, 4)).inv()
        * Rotation.from_quat(mapped[1:].reshape(-1, 4))
    ).magnitude()
    np.testing.assert_allclose(before, after, atol=1e-12)


def test_offline_and_device_fk_share_geometry_and_orientations():
    q = Rotation.random(len(FK_BONES), random_state=14).as_quat()
    root = [0.1, 1.2, -0.4]
    positions, _ = world_pose(root, dict(zip(FK_BONES, q)))
    offline = forward_kinematics(
        np.array([root]), q[:1], {n: q[i : i + 1] for i, n in enumerate(FK_BONES)}
    )
    np.testing.assert_allclose(
        offline[0], np.stack([positions[n] for n in FK_BONES]), atol=8e-8
    )


def test_world_quaternions_stay_continuous_through_a_full_turn():
    rig = RigGeometry(
        ("root", "arm", "wrist"),
        (-1, 0, 1),
        np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0]]),
    )
    angles = np.linspace(0, 2 * np.pi, 361)
    root = Rotation.from_rotvec(angles[:, None] * [0, 0, 1])
    arm = Rotation.from_rotvec(angles[:, None] * [0, 1, 0])
    local = np.zeros((len(angles), 3, 4))
    local[..., 3] = 1
    local[:, 0] = root.as_quat()
    local[:, 1] = arm.as_quat()
    positions, world = rig.forward(np.zeros((len(angles), 3)), local)
    assert np.sum(world[1:] * world[:-1], axis=-1).min() > 0.999
    np.testing.assert_allclose(world[:, 0], root.as_quat(), atol=1e-14)
    np.testing.assert_allclose(world[:, 2], (root * arm).as_quat(), atol=1e-14)
    np.testing.assert_allclose(
        positions[:, 2],
        root.apply([0, 1, 0]) + (root * arm).apply([1, 0, 0]),
        atol=1e-14,
    )


def test_so3_filter_sign_frame_invariance_and_pi_branch_cut():
    t = np.arange(151)
    angles = 179 + 0.5 * np.sin(t * 0.1) + 5 * (-1.0) ** t
    q = Rotation.from_euler("x", angles[:, None], degrees=True).as_quat()
    q[::3] *= -1
    original = q.copy()
    smooth = gaussian_rotation_mean(q, 3.5)
    a, b = Rotation.random(2, random_state=99)
    transformed = (a * Rotation.from_quat(q) * b).as_quat()
    expected = (a * Rotation.from_quat(smooth) * b).as_matrix()
    actual = Rotation.from_quat(gaussian_rotation_mean(transformed, 3.5)).as_matrix()
    np.testing.assert_allclose(actual, expected, atol=1e-12)
    np.testing.assert_array_equal(original, q)
    # Must stay near pi, not collapse toward identity at the rotvec branch cut.
    assert np.min(Rotation.from_quat(smooth).magnitude()) > 3
    target = Rotation.from_euler(
        "x", (179 + 0.5 * np.sin(t * 0.1))[:, None], degrees=True
    )
    error = (target.inv() * Rotation.from_quat(smooth)).magnitude()
    assert np.rad2deg(error[15:-15]).max() < 0.04


def test_temporal_filter_preserves_constant_angular_velocity_away_from_edges():
    q = Rotation.from_rotvec(
        np.arange(200)[:, None] * np.array([[0.01, -0.02, 0.03]])
    ).as_quat()
    result = gaussian_rotation_mean(q, 3.5)
    error = (Rotation.from_quat(q).inv() * Rotation.from_quat(result)).magnitude()
    assert error[15:-15].max() < 1e-12


def test_ambiguous_orthogonal_rotations_do_not_invent_a_coordinate_dependent_axis():
    q = np.array(
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [1, 0, 0, 0], [0, 1, 0, 0]],
        dtype=float,
    )
    result = gaussian_rotation_mean(q, 3.5)
    a, b = Rotation.random(2, random_state=33)
    other = gaussian_rotation_mean((a * Rotation.from_quat(q) * b).as_quat(), 3.5)
    np.testing.assert_allclose(
        Rotation.from_quat(other).as_matrix(),
        (a * Rotation.from_quat(result) * b).as_matrix(),
        atol=1e-12,
    )
    np.testing.assert_allclose(abs(result[2]), q[2], atol=1e-12)


def test_unique_rotation_mean_can_be_orthogonal_to_the_center_sample():
    q = np.tile([1.0, 0, 0, 0], (31, 1))
    q[15] = [0, 0, 0, 1]
    result = gaussian_rotation_mean(q, 3.5)
    np.testing.assert_allclose(abs(result[15]), [1, 0, 0, 0], atol=1e-12)
    a, b = Rotation.random(2, random_state=71)
    transformed = (a * Rotation.from_quat(q) * b).as_quat()
    np.testing.assert_allclose(
        Rotation.from_quat(gaussian_rotation_mean(transformed, 3.5)).as_matrix(),
        (a * Rotation.from_quat(result) * b).as_matrix(),
        atol=1e-12,
    )


@pytest.mark.parametrize("parents", [(-1, 2, 0), (-1, -1, 0), (-1, 0, 2)])
def test_invalid_topology_is_rejected(parents):
    with pytest.raises(ValueError, match="topologically"):
        RigGeometry(("a", "b", "c"), parents, np.ones((3, 3)))
