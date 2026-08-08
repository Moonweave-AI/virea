from __future__ import annotations

import numpy as np

EPS = 1e-8


def normalize_quat_xyzw(quat: np.ndarray) -> np.ndarray:
    arr = np.asarray(quat, dtype=np.float32)
    if arr.shape[-1:] != (4,):
        raise ValueError(f"quaternions must end in 4 xyzw components, got {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError("quaternions must be finite")
    norm = np.linalg.norm(arr, axis=-1, keepdims=True)
    if np.any(norm < EPS):
        raise ValueError("quaternions must have non-zero norm")
    return arr / norm


def axis_angle_to_quat_xyzw(axis_angle: np.ndarray) -> np.ndarray:
    aa = np.asarray(axis_angle, dtype=np.float32)
    if aa.shape[-1:] != (3,):
        raise ValueError(f"axis-angle values must end in 3 components, got {aa.shape}")
    if not np.all(np.isfinite(aa)):
        raise ValueError("axis-angle values must be finite")
    angle = np.linalg.norm(aa, axis=-1, keepdims=True)
    half = 0.5 * angle
    axis = aa / np.clip(angle, EPS, None)
    xyz = axis * np.sin(half)
    w = np.cos(half)
    quat = np.concatenate([xyz, w], axis=-1)
    small = angle[..., 0] < 1e-8
    if np.any(small):
        quat[small] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    return normalize_quat_xyzw(quat)


def quat_to_axis_angle_xyzw(quaternion: np.ndarray) -> np.ndarray:
    """Convert finite unit quaternions to the principal axis-angle vector.

    Antipodal inputs are canonicalized to non-negative ``w`` so the returned
    angle is in ``[0, pi]`` and does not acquire artificial 2-pi jumps.
    """

    quat = normalize_quat_xyzw(np.asarray(quaternion, dtype=np.float32))
    quat = np.where(quat[..., 3:4] < 0.0, -quat, quat)
    vector = quat[..., :3]
    vector_norm = np.linalg.norm(vector, axis=-1, keepdims=True)
    angle = 2.0 * np.arctan2(vector_norm, np.clip(quat[..., 3:4], 0.0, 1.0))
    scale = np.divide(
        angle,
        vector_norm,
        out=np.full_like(angle, 2.0),
        where=vector_norm >= EPS,
    )
    return (vector * scale).astype(np.float32)


def quat_multiply_xyzw(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    q1 = normalize_quat_xyzw(q1)
    q2 = normalize_quat_xyzw(q2)
    x1, y1, z1, w1 = np.moveaxis(q1, -1, 0)
    x2, y2, z2, w2 = np.moveaxis(q2, -1, 0)
    out = np.stack(
        [
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        ],
        axis=-1,
    )
    return normalize_quat_xyzw(out)


def quat_inverse_xyzw(quat: np.ndarray) -> np.ndarray:
    q = normalize_quat_xyzw(quat)
    out = q.copy()
    out[..., :3] *= -1.0
    return out


def quat_from_two_vectors_xyzw(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    src = np.asarray(source, dtype=np.float32)
    dst = np.asarray(target, dtype=np.float32)
    if src.shape[-1:] != (3,) or dst.shape[-1:] != (3,):
        raise ValueError("vector-to-vector rotation inputs must end in 3 components")
    if not np.all(np.isfinite(src)) or not np.all(np.isfinite(dst)):
        raise ValueError("vector-to-vector rotation inputs must be finite")
    src_norm = np.linalg.norm(src, axis=-1, keepdims=True)
    dst_norm = np.linalg.norm(dst, axis=-1, keepdims=True)
    if np.any(src_norm < EPS) or np.any(dst_norm < EPS):
        raise ValueError("vector-to-vector rotation inputs must be non-degenerate")
    src = src / src_norm
    dst = dst / dst_norm
    dot = np.sum(src * dst, axis=-1, keepdims=True)
    cross = np.cross(src, dst, axis=-1)
    quat = np.concatenate([cross, 1.0 + dot], axis=-1)

    opposite = dot[..., 0] < -0.999999
    if np.any(opposite):
        fallback = np.zeros_like(src)
        fallback[..., 0] = 1.0
        nearly_parallel = np.abs(src[..., 0]) > 0.9
        fallback[nearly_parallel] = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        axis = np.cross(src, fallback, axis=-1)
        axis = axis / np.clip(np.linalg.norm(axis, axis=-1, keepdims=True), EPS, None)
        opposite_quat = np.concatenate([axis, np.zeros((*axis.shape[:-1], 1), dtype=np.float32)], axis=-1)
        quat[opposite] = opposite_quat[opposite]
    return normalize_quat_xyzw(quat)


def quat_to_matrix_xyzw(quat: np.ndarray) -> np.ndarray:
    q = normalize_quat_xyzw(quat)
    x, y, z, w = np.moveaxis(q, -1, 0)
    xx = x * x
    yy = y * y
    zz = z * z
    xy = x * y
    xz = x * z
    yz = y * z
    xw = x * w
    yw = y * w
    zw = z * w
    return np.stack(
        [
            1.0 - 2.0 * (yy + zz),
            2.0 * (xy - zw),
            2.0 * (xz + yw),
            2.0 * (xy + zw),
            1.0 - 2.0 * (xx + zz),
            2.0 * (yz - xw),
            2.0 * (xz - yw),
            2.0 * (yz + xw),
            1.0 - 2.0 * (xx + yy),
        ],
        axis=-1,
    ).reshape(*q.shape[:-1], 3, 3)


def quat_apply_xyzw(quat: np.ndarray, vector: np.ndarray) -> np.ndarray:
    matrix = quat_to_matrix_xyzw(quat)
    vec = np.asarray(vector, dtype=np.float32)
    return np.matmul(matrix, np.expand_dims(vec, axis=-1)).squeeze(-1)


def _orthonormal_axes_from_sixd(sixd: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    arr = np.asarray(sixd, dtype=np.float32)
    if arr.shape[-1:] != (6,):
        raise ValueError(f"6D rotations must end in 6 components, got {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError("6D rotations must be finite")
    a1 = arr[..., 0:3]
    a2 = arr[..., 3:6]
    first_norm = np.linalg.norm(a1, axis=-1, keepdims=True)
    if np.any(first_norm < EPS):
        raise ValueError("6D rotation first axis is degenerate")
    b1 = a1 / first_norm
    dot = np.sum(b1 * a2, axis=-1, keepdims=True)
    residual = a2 - dot * b1
    residual_norm = np.linalg.norm(residual, axis=-1, keepdims=True)
    if np.any(residual_norm < EPS):
        raise ValueError("6D rotation axes are collinear")
    b2 = residual / residual_norm
    b3 = np.cross(b1, b2)
    if np.any(np.linalg.norm(b3, axis=-1) < 1.0 - 1e-5):
        raise ValueError("6D rotation Gram-Schmidt basis is invalid")
    return b1, b2, b3


def sixd_to_matrix(sixd: np.ndarray) -> np.ndarray:
    b1, b2, b3 = _orthonormal_axes_from_sixd(sixd)
    return np.stack([b1, b2, b3], axis=-1)


def sixd_rows_to_matrix(sixd: np.ndarray) -> np.ndarray:
    b1, b2, b3 = _orthonormal_axes_from_sixd(sixd)
    return np.stack([b1, b2, b3], axis=-2)


def matrix_to_quat_xyzw(matrix: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix, dtype=np.float32)
    if m.shape[-2:] != (3, 3):
        raise ValueError(f"rotation matrices must end in shape (3, 3), got {m.shape}")
    if not np.all(np.isfinite(m)):
        raise ValueError("rotation matrices must be finite")
    gram = np.matmul(m, np.swapaxes(m, -1, -2))
    if not np.allclose(gram, np.eye(3, dtype=np.float32), atol=1e-4):
        raise ValueError("rotation matrices must be orthonormal")
    determinant = np.linalg.det(m)
    if not np.allclose(determinant, 1.0, atol=1e-4):
        raise ValueError("rotation matrices must have determinant +1")
    q = np.zeros((*m.shape[:-2], 4), dtype=np.float32)
    trace = m[..., 0, 0] + m[..., 1, 1] + m[..., 2, 2]

    positive = trace > 0.0
    if np.any(positive):
        s = np.sqrt(np.clip(trace[positive] + 1.0, EPS, None)) * 2.0
        q[positive, 3] = 0.25 * s
        q[positive, 0] = (m[positive, 2, 1] - m[positive, 1, 2]) / s
        q[positive, 1] = (m[positive, 0, 2] - m[positive, 2, 0]) / s
        q[positive, 2] = (m[positive, 1, 0] - m[positive, 0, 1]) / s

    not_positive = ~positive
    cond_x = not_positive & (m[..., 0, 0] > m[..., 1, 1]) & (m[..., 0, 0] > m[..., 2, 2])
    if np.any(cond_x):
        s = np.sqrt(np.clip(1.0 + m[cond_x, 0, 0] - m[cond_x, 1, 1] - m[cond_x, 2, 2], EPS, None)) * 2.0
        q[cond_x, 3] = (m[cond_x, 2, 1] - m[cond_x, 1, 2]) / s
        q[cond_x, 0] = 0.25 * s
        q[cond_x, 1] = (m[cond_x, 0, 1] + m[cond_x, 1, 0]) / s
        q[cond_x, 2] = (m[cond_x, 0, 2] + m[cond_x, 2, 0]) / s

    cond_y = not_positive & ~cond_x & (m[..., 1, 1] > m[..., 2, 2])
    if np.any(cond_y):
        s = np.sqrt(np.clip(1.0 + m[cond_y, 1, 1] - m[cond_y, 0, 0] - m[cond_y, 2, 2], EPS, None)) * 2.0
        q[cond_y, 3] = (m[cond_y, 0, 2] - m[cond_y, 2, 0]) / s
        q[cond_y, 0] = (m[cond_y, 0, 1] + m[cond_y, 1, 0]) / s
        q[cond_y, 1] = 0.25 * s
        q[cond_y, 2] = (m[cond_y, 1, 2] + m[cond_y, 2, 1]) / s

    cond_z = not_positive & ~cond_x & ~cond_y
    if np.any(cond_z):
        s = np.sqrt(np.clip(1.0 + m[cond_z, 2, 2] - m[cond_z, 0, 0] - m[cond_z, 1, 1], EPS, None)) * 2.0
        q[cond_z, 3] = (m[cond_z, 1, 0] - m[cond_z, 0, 1]) / s
        q[cond_z, 0] = (m[cond_z, 0, 2] + m[cond_z, 2, 0]) / s
        q[cond_z, 1] = (m[cond_z, 1, 2] + m[cond_z, 2, 1]) / s
        q[cond_z, 2] = 0.25 * s

    return normalize_quat_xyzw(q)


def sixd_to_quat_xyzw(sixd: np.ndarray) -> np.ndarray:
    return matrix_to_quat_xyzw(sixd_to_matrix(sixd))


def sixd_rows_to_quat_xyzw(sixd: np.ndarray) -> np.ndarray:
    return matrix_to_quat_xyzw(sixd_rows_to_matrix(sixd))
