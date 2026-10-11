import numpy as np
from scipy.spatial.transform import Rotation

from virea.vrchat.continuity import ContinuedTimeline
from virea.vrchat.grounding import GroundedTimeline
from virea.vrchat.mapping import world_pose
from virea.vrchat.timeline import MotionTimeline, Pose


def test_floor_constraint_keeps_travel_rotations_and_airborne_frames():
    frames = 31
    source = dict(
        offset=0,
        seconds=1,
        fps=30,
        root=np.array(
            [[i / 30, y, 0.3] for i, y in enumerate(np.linspace(0.7, 1.4, frames))]
        ),
        rotations={
            "hips": np.tile([0.0, 0, 0, 1], (frames, 1)),
            "leftFoot": Rotation.from_euler(
                "x", np.linspace(0, 20, frames)[:, None], degrees=True
            ).as_quat(),
        },
    )
    raw = MotionTimeline([source], 1)
    grounded = GroundedTimeline(raw)
    for second in np.linspace(0, 1, 80):
        before, after = raw.sample(second), grounded.sample(second)
        points, _ = world_pose(after.root, after.rotations)
        assert (
            min(
                points[n][1] for n in ("leftFoot", "rightFoot", "leftToes", "rightToes")
            )
            >= -1e-8
        )
        np.testing.assert_array_equal(before.root[[0, 2]], after.root[[0, 2]])
        for name in before.rotations:
            np.testing.assert_array_equal(before.rotations[name], after.rotations[name])
    np.testing.assert_array_equal(grounded.sample(1).root, raw.sample(1).root)
    assert grounded.max_correction_m >= 0.3 - 1e-6
    assert source["root"][0, 1] == 0.7


def test_floor_constraint_runs_after_cross_performance_pose_blend():
    source = dict(
        offset=0,
        seconds=1,
        fps=30,
        root=np.tile([0, 0.7, 0], (31, 1)),
        rotations={"hips": np.tile([0, 0, 0, 1.0], (31, 1))},
    )
    continued = ContinuedTimeline(
        MotionTimeline([source], 1),
        Pose(np.array([0.5, 1.0, 0.2]), {"hips": np.array([0, 0, 0, 1.0])}),
    )
    grounded = GroundedTimeline(continued)
    for second in np.linspace(0, 1, 70):
        pose = grounded.sample(second)
        positions, _ = world_pose(pose.root, pose.rotations)
        assert positions["leftFoot"][1] >= -1e-8
        np.testing.assert_allclose(pose.root[[0, 2]], [0.5, 0.2])


def test_player_applies_declared_grounding_to_head_hands_and_body_together():
    from test_pose_continuity import setup_sink

    from virea.vrchat.contracts import BridgeConfig
    from virea.vrchat.generated_pose import pose_payload
    from virea.vrchat.mapping import tracker_messages
    from virea.vrchat.osc import bundle, decode
    from virea.vrchat.player import PerformancePlayer

    source = dict(
        offset=0,
        seconds=1,
        fps=30,
        grounding="prevent_penetration",
        root=np.tile([0, 0.7, 0], (31, 1)),
        rotations={"hips": np.tile([0, 0, 0, 1.0], (31, 1))},
    )
    config = BridgeConfig(mode="generated_vr")
    player = PerformancePlayer(config, setup_sink(), [source], {"duration_seconds": 1})
    raw = MotionTimeline([source], 1).sample(0.5)
    pose = player.timeline.sample(0.5)
    native_before, _ = pose_payload(raw, player.anchor)
    native_after, _ = pose_payload(pose, player.anchor)
    np.testing.assert_allclose(native_after[:, 1] - native_before[:, 1], 0.3)
    targets = dict(
        decode(
            bundle(tracker_messages(pose.root, pose.rotations, config, player.anchor))
        )
    )
    assert abs(targets["/tracking/trackers/2/position"][1]) < 1e-8
    assert abs(targets["/tracking/trackers/3/position"][1]) < 1e-8
    assert (
        player.output_status()["grounding"]["max_vertical_correction_m"] >= 0.3 - 1e-6
    )
