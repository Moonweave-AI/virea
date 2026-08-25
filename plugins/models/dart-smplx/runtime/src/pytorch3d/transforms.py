"""Portable rotation conversions matching PyTorch3D conventions.

This is a deliberately small, independently packaged subset of the algorithms
used by DART. PyTorch3D is BSD licensed; see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import torch
import torch.nn.functional as functional


def rotation_6d_to_matrix(values: torch.Tensor) -> torch.Tensor:
    if values.shape[-1] != 6:
        raise ValueError("6D rotations must have a final dimension of 6")
    first = values[..., :3]
    second = values[..., 3:]
    basis1 = functional.normalize(first, dim=-1)
    basis2 = functional.normalize(
        second - (basis1 * second).sum(dim=-1, keepdim=True) * basis1,
        dim=-1,
    )
    basis3 = torch.cross(basis1, basis2, dim=-1)
    return torch.stack((basis1, basis2, basis3), dim=-2)


def matrix_to_rotation_6d(matrix: torch.Tensor) -> torch.Tensor:
    if matrix.shape[-2:] != (3, 3):
        raise ValueError("rotation matrices must have shape (...,3,3)")
    batch_shape = matrix.shape[:-2]
    return matrix[..., :2, :].clone().reshape(*batch_shape, 6)


def axis_angle_to_matrix(axis_angle: torch.Tensor) -> torch.Tensor:
    if axis_angle.shape[-1] != 3:
        raise ValueError("axis-angle rotations must have shape (...,3)")
    angles = torch.linalg.vector_norm(axis_angle, dim=-1, keepdim=True)
    sin_half_over_angle = 0.5 * torch.sinc(angles * 0.5 / torch.pi)
    quaternion = torch.cat(
        (torch.cos(angles * 0.5), axis_angle * sin_half_over_angle), dim=-1
    )
    return _quaternion_to_matrix(quaternion)


def matrix_to_axis_angle(matrix: torch.Tensor) -> torch.Tensor:
    quaternion = _matrix_to_quaternion(matrix)
    vector = quaternion[..., 1:]
    vector_norm = torch.linalg.vector_norm(vector, dim=-1, keepdim=True)
    half_angle = torch.atan2(vector_norm, quaternion[..., :1])
    angle = 2.0 * half_angle
    small = angle.abs() < 1e-6
    sin_half_over_angle = torch.where(
        small,
        0.5 - (angle * angle) / 48.0,
        torch.sin(half_angle) / angle,
    )
    return vector / sin_half_over_angle


def _quaternion_to_matrix(quaternion: torch.Tensor) -> torch.Tensor:
    if quaternion.shape[-1] != 4:
        raise ValueError("quaternions must have shape (...,4)")
    real, i, j, k = torch.unbind(quaternion, -1)
    scale = 2.0 / (quaternion * quaternion).sum(-1)
    values = (
        1 - scale * (j * j + k * k),
        scale * (i * j - k * real),
        scale * (i * k + j * real),
        scale * (i * j + k * real),
        1 - scale * (i * i + k * k),
        scale * (j * k - i * real),
        scale * (i * k - j * real),
        scale * (j * k + i * real),
        1 - scale * (i * i + j * j),
    )
    return torch.stack(values, dim=-1).reshape(quaternion.shape[:-1] + (3, 3))


def _sqrt_positive_part(values: torch.Tensor) -> torch.Tensor:
    result = torch.zeros_like(values)
    positive = values > 0
    result[positive] = torch.sqrt(values[positive])
    return result


def _matrix_to_quaternion(matrix: torch.Tensor) -> torch.Tensor:
    if matrix.shape[-2:] != (3, 3):
        raise ValueError("rotation matrices must have shape (...,3,3)")
    m00 = matrix[..., 0, 0]
    m01 = matrix[..., 0, 1]
    m02 = matrix[..., 0, 2]
    m10 = matrix[..., 1, 0]
    m11 = matrix[..., 1, 1]
    m12 = matrix[..., 1, 2]
    m20 = matrix[..., 2, 0]
    m21 = matrix[..., 2, 1]
    m22 = matrix[..., 2, 2]
    magnitudes = _sqrt_positive_part(
        torch.stack(
            (
                1.0 + m00 + m11 + m22,
                1.0 + m00 - m11 - m22,
                1.0 - m00 + m11 - m22,
                1.0 - m00 - m11 + m22,
            ),
            dim=-1,
        )
    )
    candidates = torch.stack(
        (
            torch.stack(
                (magnitudes[..., 0] ** 2, m21 - m12, m02 - m20, m10 - m01), dim=-1
            ),
            torch.stack(
                (m21 - m12, magnitudes[..., 1] ** 2, m10 + m01, m02 + m20), dim=-1
            ),
            torch.stack(
                (m02 - m20, m10 + m01, magnitudes[..., 2] ** 2, m12 + m21), dim=-1
            ),
            torch.stack(
                (m10 - m01, m20 + m02, m21 + m12, magnitudes[..., 3] ** 2), dim=-1
            ),
        ),
        dim=-2,
    )
    floor = torch.tensor(0.1, dtype=magnitudes.dtype, device=magnitudes.device)
    candidates = candidates / (2.0 * magnitudes[..., None].max(floor))
    index = magnitudes.argmax(dim=-1)
    gather_index = index[..., None, None].expand(index.shape + (1, 4))
    result = torch.gather(candidates, -2, gather_index).squeeze(-2)
    return torch.where(result[..., :1] < 0, -result, result)
