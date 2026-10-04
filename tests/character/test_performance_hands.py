import numpy as np

from virea.character.performance_retarget import canonical_motion
from virea.motion.canonical import HAND_BONES, pack_sequence, unpack_sequence
from virea.motion.skeleton import BODY_BONES, FK_INDEX, forward_kinematics_from_sequence


def test_rigid_palm_reconciles_body_hand_translation_without_changing_finger_directions():
    from virea.character.performance_hands import reconcile_palms

    positions = forward_kinematics_from_sequence(pack_sequence(np.zeros((12, 3))))
    body = positions[:, [FK_INDEX[n] for n in BODY_BONES]]
    expected = {name: positions[:, FK_INDEX[name]] for name in HAND_BONES}
    observed = {
        name: values + np.array([0.2, -0.3, 0.4]) for name, values in expected.items()
    }
    before = {name: values.copy() for name, values in observed.items()}
    result = reconcile_palms(body, observed)
    for name in HAND_BONES:
        np.testing.assert_allclose(result[name], expected[name], atol=1e-6)
        np.testing.assert_array_equal(observed[name], before[name])


def test_position_only_hands_do_not_invent_terminal_rotations():
    # Anatomically consistent articulated evidence, in the official H3D joint order.
    hand = np.tile([0, 0, 0, 1.0], (24, 30, 1))
    angle = np.linspace(0, 0.4, 24)
    for index, name in enumerate(HAND_BONES):
        if name.endswith("Intermediate"):
            hand[:, index, 2] = np.sin(angle / 2)
            hand[:, index, 3] = np.cos(angle / 2)
    source = forward_kinematics_from_sequence(
        pack_sequence(np.zeros((24, 3)), hand_quats_xyzw=hand)
    )
    names = list(BODY_BONES) + [
        f"{side}{finger}{joint}"
        for side in ("left", "right")
        for finger in ("Index", "Middle", "Little", "Ring", "Thumb")
        for joint in ("Proximal", "Intermediate", "Distal")
    ]
    features = np.zeros((24, 623), dtype=np.float32)
    features[:, 4:157] = source[:, [FK_INDEX[n] for n in names[1:]]].reshape(24, 153)
    original = features.copy()
    result = unpack_sequence(canonical_motion("syntalker", features))
    np.testing.assert_array_equal(features, original)
    for index, name in enumerate(HAND_BONES):
        if "Thumb" in name or name.endswith("Distal"):
            np.testing.assert_allclose(
                result["hand_quats_xyzw"][:, index],
                np.tile([0, 0, 0, 1], (24, 1)),
                atol=1e-6,
            )
