import struct

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from virea.vrchat.contracts import PARAMETER_BUDGET_BITS, BridgeConfig
from virea.vrchat.mapping import (
    chat_chunks,
    tracker_messages,
    unity_euler,
    unity_quaternion,
    world_pose,
)
from virea.vrchat.osc import bundle, decode, message
from virea.vrchat.timeline import MotionTimeline, movement
from virea.vrchat.transport import FeedbackProtocol, reset_packet


def window(seconds=1.0, offset=0.0, root_end=(0, 1, 0)):
    frames = round(seconds * 30) + 1
    return {
        "offset": offset,
        "seconds": seconds,
        "fps": 30,
        "root": np.linspace([0, 1, 0], root_end, frames).tolist(),
        "rotations": {"hips": [[0, 0, 0, 1]] * frames},
    }


def test_wire_types_match_vrchat_not_python_truthiness():
    assert message("/input/Vertical", 0.5) == b"/input/Vertical\0,f\0\0" + struct.pack(
        ">f", 0.5
    )
    assert message("/input/Voice", 1).endswith(b",i\0\0\0\0\0\x01")
    assert decode(
        bundle(
            [message("/chatbox/input", "你好", True, False), message("/input/Voice", 0)]
        )
    ) == [("/chatbox/input", ["你好", True, False]), ("/input/Voice", [0])]


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"/x\0\0,f\0\0",
        b"/x\0\1,f\0\0" + struct.pack(">f", 1),
        b"/x\0\0,f\0\0" + struct.pack(">f", float("nan")),
        b"#bundle\0" + b"\0" * 8 + b"\0\0\0\x40",
        b"/x\0\0,z\0\0",
        b"/x\0\0,i\0\0\0\0\0\0extra",
    ],
)
def test_malformed_packets_are_rejected(packet):
    with pytest.raises(ValueError):
        decode(packet)


def test_release_types_and_custom_budget():
    pairs = dict(
        decode(
            reset_packet(
                BridgeConfig(audio_enabled=True, audio_device="test", microphone="hold")
            )
        )
    )
    assert type(pairs["/input/Vertical"][0]) is float
    assert pairs["/input/Voice"][0] is False
    assert pairs["/input/Run"][0] is False
    assert pairs["/input/Jump"][0] is False
    assert pairs["/avatar/parameters/AI_Active"] == [False]
    assert PARAMETER_BUDGET_BITS == 65
    assert not any(
        k.endswith(("/Viseme", "/GestureLeft", "/GestureRight")) for k in pairs
    )


@pytest.mark.parametrize(
    "angles", [(13, 21, -37), (90, 20, 40), (-90, 20, 40), (179, -37, 91), (0, 0, 0)]
)
def test_unity_euler_reconstructs_rotation_including_gimbal_lock(angles):
    q = Rotation.from_euler("zxy", angles, degrees=True).as_quat()
    x, y, z = unity_euler(q)
    np.testing.assert_allclose(
        Rotation.from_euler("zxy", [z, x, y], degrees=True).as_matrix(),
        Rotation.from_quat(q).as_matrix(),
        atol=1e-7,
    )


def test_basis_reflection_is_applied_to_quaternions_and_positions():
    q = Rotation.from_euler("xyz", [0.3, 0.8, -0.2]).as_quat()
    basis = np.diag([-1, 1, 1])
    np.testing.assert_allclose(
        Rotation.from_quat(unity_quaternion(q)).as_matrix(),
        basis @ Rotation.from_quat(q).as_matrix() @ basis,
    )
    root = np.array([0.0, 1.0, 0.0])
    positions, _ = world_pose(root, {"hips": np.array([0, 0, 0, 1])})
    packets = dict(
        decode(
            bundle(
                tracker_messages(
                    root, {"hips": np.array([0, 0, 0, 1])}, BridgeConfig(), root
                )
            )
        )
    )
    np.testing.assert_allclose(
        packets["/tracking/trackers/2/position"],
        positions["leftFoot"] * [-1, 1, 1],
        atol=1e-6,
    )
    assert (
        packets["/tracking/trackers/2/position"][0]
        < 0
        < packets["/tracking/trackers/3/position"][0]
    )


def test_locomotion_does_not_double_tracker_travel_or_yaw():
    root = np.array([3.0, 1.0, 4.0])
    q = Rotation.from_euler("y", 90, degrees=True).as_quat()
    config = BridgeConfig(locomotion=True)
    pairs = dict(decode(bundle(tracker_messages(root, {"hips": q}, config, root))))
    np.testing.assert_allclose(
        pairs["/tracking/trackers/1/position"], [0, 1, 0], atol=1e-6
    )
    np.testing.assert_allclose(
        pairs["/tracking/trackers/1/rotation"], [0, 0, 0], atol=2e-5
    )


def test_multi_segment_timeline_and_shortest_arc():
    a, b = window(), window(offset=1, root_end=(0, 1, 2))
    b["rotations"]["hips"] = [[0, 0, 0, -1]] * 31
    timeline = MotionTimeline([a, b], 2)
    np.testing.assert_allclose(timeline.sample(0.5).root, [0, 1, 0])
    np.testing.assert_allclose(timeline.sample(1.5).root, [0, 1, 1])
    assert abs(timeline.sample(1.5).rotations["hips"][3]) == 1
    assert movement(timeline, 1.5, BridgeConfig(), {}) == pytest.approx((0, 0.65, 0))
    b["offset"] = 1.1
    with pytest.raises(ValueError, match="contiguous"):
        MotionTimeline([a, b], 2)


def test_vrm_thumb_names_are_normalized_without_losing_middle_joint():
    w = window()
    w["rotations"]["leftThumbMetacarpal"] = [[0, 0, 0, 1]] * 31
    w["rotations"]["leftThumbProximal"] = [
        Rotation.from_euler("x", 0.3).as_quat().tolist()
    ] * 31
    pose = MotionTimeline([w], 1).sample(0.2)
    assert "leftThumbMetacarpal" not in pose.rotations
    assert pose.rotations["leftThumbIntermediate"][0] > 0.1


def test_chat_chunks_are_bounded_for_unicode_and_lines():
    text = "你好😀" * 100 + "\n" * 20 + "end"
    chunks = chat_chunks(text)
    assert all(
        len(c.encode("utf-16-le")) // 2 <= 144 and c.count("\n") <= 8 for c in chunks
    )
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_feedback_is_bounded_and_does_not_invent_world_position():
    protocol = FeedbackProtocol()
    protocol.datagram_received(
        bundle(
            [
                message("/avatar/change", "avtr_test"),
                message("/avatar/parameters/VelocityX", 0.2),
                message("/avatar/parameters/WorldX", 50.0),
            ]
        ),
        ("127.0.0.1", 9000),
    )
    assert protocol.fresh()["VelocityX"] == pytest.approx(0.2)
    assert "WorldX" not in protocol.values
    protocol.datagram_received(b"bad", ("127.0.0.1", 9000))
    assert protocol.invalid_packets == 1


@pytest.mark.parametrize(
    "options",
    [
        {"audio_enabled": True},
        {"microphone": "hold"},
        {"send_port": 9001},
        {"host": "8.8.8.8"},
        {"tracker_bones": ["head"]},
        {"scale": float("nan")},
    ],
)
def test_invalid_configuration_fails_before_output(options):
    with pytest.raises(ValueError):
        BridgeConfig(**options)


def test_canonical_motion_ir_uses_explicit_rest_hip_height():
    from virea_motion_ir.model import ActorMotion, MotionIR

    actor = ActorMotion(
        actor_id="actor",
        skeleton_profile_id="vrm1.humanoid52.v1",
        joint_names=("hips", "spine"),
        parent_indices=(-1, 0),
        root_translation_m=np.zeros((2, 3)),
        root_rotation_xyzw=np.array([[0, 0, 0, 1]] * 2),
        local_rotations_xyzw=np.array([[[0, 0, 0, 1]]] * 2),
    )
    ir = MotionIR(motion_id="test", fps=30, actors=(actor,))
    timeline = MotionTimeline.from_motion_ir(ir, hip_height=0.85)
    assert timeline.duration == pytest.approx(2 / 30)
    np.testing.assert_allclose(timeline.sample(0).root, [0, 0.85, 0])
