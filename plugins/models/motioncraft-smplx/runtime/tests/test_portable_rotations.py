from __future__ import annotations

import sys

import torch
from virea_motioncraft.portable_rotations import install_portable_pytorch3d_transforms


def test_portable_rotation_surface_round_trips_axis_angle_and_6d() -> None:
    install_portable_pytorch3d_transforms(torch)
    transforms = sys.modules["pytorch3d.transforms"]
    axis_angle = torch.tensor(
        [[0.0, 0.0, 0.0], [0.2, -0.4, 0.7], [-1.0, 0.3, 0.5]],
        dtype=torch.float32,
    )

    matrices = transforms.axis_angle_to_matrix(axis_angle)
    restored = transforms.matrix_to_axis_angle(matrices)
    rotation6d = transforms.matrix_to_rotation_6d(matrices)
    restored_matrices = transforms.rotation_6d_to_matrix(rotation6d)

    assert torch.allclose(restored, axis_angle, atol=1e-5, rtol=1e-5)
    assert torch.allclose(restored_matrices, matrices, atol=1e-5, rtol=1e-5)
