import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from virea_compat.model_adapters import smplx_fullpose_to_motion_ir
from virea_retarget import retarget_motion_ir

from virea.motion.canonical import CORE_INDEX, unpack_sequence
from virea.motion.skeleton import BODY_BONES, DEFAULT_REST_OFFSETS, canonical_geometry
from virea.motion.source_rig import installed_smplx_rig, load_smplx_rig


def test_smplx_codec_uses_source_rest_offsets_for_conversion_and_source_oracle():
    offsets = {n: np.array(v) for n, v in DEFAULT_REST_OFFSETS.items()}
    offsets["leftHand"] = Rotation.from_euler("y", 35, degrees=True).apply(
        offsets["leftHand"]
    )
    pose = np.zeros((12, 165), dtype=np.float32)
    pose[:, 54:57] = Rotation.from_euler(
        "x", (np.arange(12) * 7)[:, None], degrees=True
    ).as_rotvec()
    result = smplx_fullpose_to_motion_ir(pose, fps=30, source_rest_offsets=offsets)
    q = unpack_sequence(retarget_motion_ir(result.motion_ir).actors[0].canonical211)
    frames = Rotation.from_quat(q["core_quats_xyzw"][:, CORE_INDEX["leftLowerArm"]])
    direction = frames.apply(np.array(DEFAULT_REST_OFFSETS["leftHand"]))
    expected = Rotation.from_rotvec(pose[:, 54:57]).apply(offsets["leftHand"])
    np.testing.assert_allclose(direction, expected, atol=1e-7)


def test_installed_geometry_is_detected_and_hand_means_are_explicit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("VIREA_HOME", str(tmp_path))
    assert installed_smplx_rig() is None
    directory = tmp_path / "model-store/assets/skeletons"
    directory.mkdir(parents=True)
    from virea.motion.codecs import SMPLX_HAND_INDEX

    rig = canonical_geometry()
    positions, _ = rig.forward(np.zeros(3), np.tile([0, 0, 0, 1], (52, 1)))
    joints = np.zeros((55, 3))
    indices = {**{n: i for i, n in enumerate(BODY_BONES)}, **SMPLX_HAND_INDEX}
    for n, i in indices.items():
        joints[i] = positions[rig.names.index(n)]
    path = directory / "smplx-neutral.npz"
    np.savez(
        path,
        joints55=joints,
        hands_meanl=np.arange(45) / 100,
        hands_meanr=-np.arange(45) / 100,
    )
    loaded = installed_smplx_rig()
    assert len(loaded.sha256) == 64
    assert not hasattr(loaded, "hand_mean")
    for n, v in DEFAULT_REST_OFFSETS.items():
        np.testing.assert_allclose(loaded.offsets[n], v, atol=1e-8)
    np.savez(path, joints55=joints, hands_meanl=np.zeros(2), hands_meanr=np.zeros(2))
    # Even malformed legacy mean fields cannot change geometric decoding.
    same_geometry = load_smplx_rig(path)
    for n in loaded.offsets:
        np.testing.assert_array_equal(same_geometry.offsets[n], loaded.offsets[n])


def test_incomplete_rest_geometry_cannot_be_silently_padded():
    with pytest.raises(ValueError, match="every body and finger"):
        smplx_fullpose_to_motion_ir(
            np.zeros((1, 165)), fps=30, source_rest_offsets={"leftHand": [0.2, 0, 0]}
        )
