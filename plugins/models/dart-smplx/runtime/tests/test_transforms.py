from __future__ import annotations

import torch
from pytorch3d import transforms


def test_rotation_conversions_round_trip() -> None:
    axis_angle = torch.tensor(
        [[0.0, 0.0, 0.0], [0.2, -0.4, 0.1], [1.0, 0.5, -0.8]],
        dtype=torch.float64,
    )
    matrices = transforms.axis_angle_to_matrix(axis_angle)
    reconstructed = transforms.matrix_to_axis_angle(matrices)
    assert torch.allclose(reconstructed, axis_angle, atol=1e-7, rtol=1e-7)

    rotations6d = transforms.matrix_to_rotation_6d(matrices)
    reconstructed_matrices = transforms.rotation_6d_to_matrix(rotations6d)
    assert torch.allclose(reconstructed_matrices, matrices, atol=1e-7, rtol=1e-7)
