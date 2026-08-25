from __future__ import annotations

import sys
import types
from typing import Any


def install_portable_pytorch3d_transforms(torch: Any) -> None:
    """Expose the small PyTorch3D rotation surface imported by MotionCraft."""

    if "pytorch3d.transforms" in sys.modules:
        return
    functional = torch.nn.functional

    def axis_angle_to_quaternion(axis_angle: Any) -> Any:
        angles = torch.linalg.vector_norm(axis_angle, dim=-1, keepdim=True)
        half_angles = angles * 0.5
        small = angles.abs() < 1e-6
        scale = torch.where(
            small,
            0.5 - (angles * angles) / 48.0,
            torch.sin(half_angles) / angles.clamp_min(1e-12),
        )
        return torch.cat((torch.cos(half_angles), axis_angle * scale), dim=-1)

    def quaternion_to_matrix(quaternions: Any) -> Any:
        values = quaternions / torch.linalg.vector_norm(
            quaternions, dim=-1, keepdim=True
        ).clamp_min(1e-12)
        real, i, j, k = values.unbind(-1)
        two = 2.0
        return torch.stack(
            (
                1 - two * (j * j + k * k),
                two * (i * j - k * real),
                two * (i * k + j * real),
                two * (i * j + k * real),
                1 - two * (i * i + k * k),
                two * (j * k - i * real),
                two * (i * k - j * real),
                two * (j * k + i * real),
                1 - two * (i * i + j * j),
            ),
            dim=-1,
        ).reshape(values.shape[:-1] + (3, 3))

    def axis_angle_to_matrix(axis_angle: Any) -> Any:
        return quaternion_to_matrix(axis_angle_to_quaternion(axis_angle))

    def matrix_to_quaternion(matrix: Any) -> Any:
        if matrix.shape[-2:] != (3, 3):
            raise ValueError("rotation matrix must end in shape (3,3)")
        m00 = matrix[..., 0, 0]
        m01 = matrix[..., 0, 1]
        m02 = matrix[..., 0, 2]
        m10 = matrix[..., 1, 0]
        m11 = matrix[..., 1, 1]
        m12 = matrix[..., 1, 2]
        m20 = matrix[..., 2, 0]
        m21 = matrix[..., 2, 1]
        m22 = matrix[..., 2, 2]
        q_abs = torch.sqrt(
            torch.clamp(
                torch.stack(
                    (
                        1 + m00 + m11 + m22,
                        1 + m00 - m11 - m22,
                        1 - m00 + m11 - m22,
                        1 - m00 - m11 + m22,
                    ),
                    dim=-1,
                ),
                min=0.0,
            )
        )
        candidates = torch.stack(
            (
                torch.stack(
                    (q_abs[..., 0] ** 2, m21 - m12, m02 - m20, m10 - m01), dim=-1
                ),
                torch.stack(
                    (m21 - m12, q_abs[..., 1] ** 2, m10 + m01, m02 + m20), dim=-1
                ),
                torch.stack(
                    (m02 - m20, m10 + m01, q_abs[..., 2] ** 2, m12 + m21), dim=-1
                ),
                torch.stack(
                    (m10 - m01, m20 + m02, m21 + m12, q_abs[..., 3] ** 2), dim=-1
                ),
            ),
            dim=-2,
        )
        candidates = candidates / (2.0 * q_abs[..., :, None].clamp_min(0.1))
        choice = q_abs.argmax(dim=-1)
        gather_index = choice[..., None, None].expand(choice.shape + (1, 4))
        result = candidates.gather(-2, gather_index).squeeze(-2)
        return functional.normalize(result, dim=-1)

    def quaternion_to_axis_angle(quaternion: Any) -> Any:
        values = quaternion / torch.linalg.vector_norm(
            quaternion, dim=-1, keepdim=True
        ).clamp_min(1e-12)
        values = torch.where(values[..., :1] < 0, -values, values)
        vector = values[..., 1:]
        sin_half = torch.linalg.vector_norm(vector, dim=-1, keepdim=True)
        half = torch.atan2(sin_half, values[..., :1])
        scale = torch.where(
            sin_half < 1e-6,
            2.0 + (sin_half * sin_half) / 3.0,
            2.0 * half / sin_half.clamp_min(1e-12),
        )
        return vector * scale

    def matrix_to_axis_angle(matrix: Any) -> Any:
        return quaternion_to_axis_angle(matrix_to_quaternion(matrix))

    def rotation_6d_to_matrix(values: Any) -> Any:
        first = functional.normalize(values[..., 0:3], dim=-1)
        second_raw = values[..., 3:6]
        second = functional.normalize(
            second_raw - (first * second_raw).sum(-1, keepdim=True) * first,
            dim=-1,
        )
        third = torch.cross(first, second, dim=-1)
        return torch.stack((first, second, third), dim=-2)

    def matrix_to_rotation_6d(matrix: Any) -> Any:
        return matrix[..., :2, :].clone().reshape(matrix.shape[:-2] + (6,))

    transforms = types.ModuleType("pytorch3d.transforms")
    transforms.axis_angle_to_matrix = axis_angle_to_matrix
    transforms.matrix_to_axis_angle = matrix_to_axis_angle
    transforms.matrix_to_quaternion = matrix_to_quaternion
    transforms.matrix_to_rotation_6d = matrix_to_rotation_6d
    transforms.quaternion_to_matrix = quaternion_to_matrix
    transforms.rotation_6d_to_matrix = rotation_6d_to_matrix
    transforms.axis_angle_to_quaternion = axis_angle_to_quaternion
    transforms.quaternion_to_axis_angle = quaternion_to_axis_angle
    root = types.ModuleType("pytorch3d")
    root.transforms = transforms
    sys.modules["pytorch3d"] = root
    sys.modules["pytorch3d.transforms"] = transforms
