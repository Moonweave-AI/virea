"""Rigid skeletal geometry and frame changes, independent of model and renderer.

Offsets live in the parent's frame; local rotations map child to parent.
All internal arithmetic is float64. A rig has one root and topological order.
"""

from dataclasses import dataclass

import numpy as np
from scipy.spatial.transform import Rotation


@dataclass(frozen=True)
class RigGeometry:
    names: tuple[str, ...]
    parents: tuple[int, ...]
    offsets: np.ndarray

    def __post_init__(self):
        offsets = np.array(self.offsets, dtype=np.float64, copy=True)
        if (
            not self.names
            or len(set(self.names)) != len(self.names)
            or len(self.parents) != len(self.names)
            or offsets.shape != (len(self.names), 3)
            or not np.isfinite(offsets).all()
            or self.parents[0] != -1
            or any(not 0 <= p < i for i, p in enumerate(self.parents[1:], 1))
        ):
            raise ValueError(
                "rig requires finite offsets and one topologically ordered tree"
            )
        if np.any(np.linalg.norm(offsets[1:], axis=1) < 1e-9):
            raise ValueError("rig bone lengths must be positive")
        offsets.setflags(write=False)
        object.__setattr__(self, "offsets", offsets)

    @classmethod
    def from_named(cls, names, parents, offsets):
        names = tuple(names)
        return cls(
            names,
            tuple(
                -1 if i == 0 else names.index(parents[n]) for i, n in enumerate(names)
            ),
            np.array([[0, 0, 0], *[offsets[n] for n in names[1:]]]),
        )

    def forward(self, root, local_xyzw):
        """Return positions and orientations for (..., joints, 4) local poses."""
        root = np.asarray(root, dtype=np.float64)
        local = np.asarray(local_xyzw, dtype=np.float64)
        if (
            local.shape[-2:] != (len(self.names), 4)
            or root.shape != (*local.shape[:-2], 3)
            or not np.isfinite(root).all()
            or not np.isfinite(local).all()
            or np.any(np.linalg.norm(local, axis=-1) < 1e-9)
        ):
            raise ValueError(
                "pose shape or finite nonzero quaternion contract violated"
            )
        matrices = (
            Rotation.from_quat(local.reshape(-1, 4))
            .as_matrix()
            .reshape(*local.shape[:-1], 3, 3)
        )
        world = np.empty_like(matrices)
        # Preserve the input quaternion representative through composition.
        # Matrix extraction can switch q to -q at arbitrary branch boundaries.
        quats = local / np.linalg.norm(local, axis=-1, keepdims=True)
        positions = np.empty((*local.shape[:-1], 3))
        world[..., 0, :, :] = matrices[..., 0, :, :]
        positions[..., 0, :] = root
        for i, parent in enumerate(self.parents[1:], 1):
            world[..., i, :, :] = world[..., parent, :, :] @ matrices[..., i, :, :]
            positions[..., i, :] = (
                positions[..., parent, :] + world[..., parent, :, :] @ self.offsets[i]
            )
            quats[..., i, :] = (
                (
                    Rotation.from_quat(quats[..., parent, :].reshape(-1, 4))
                    * Rotation.from_quat(quats[..., i, :].reshape(-1, 4))
                )
                .as_quat()
                .reshape(*local.shape[:-2], 4)
            )
        return positions, quats


def rest_frame_binding(source: RigGeometry, target: RigGeometry):
    """Constant C_j mapping target rest axes into source rest axes.

    Fit the normalized outgoing bone directions (Wahba/Kabsch). A single
    direction observes swing only: choose its minimum-angle rotation. Leaves
    inherit their parent's frame rather than inventing a time-varying twist.
    Branches with different rest angles have a measurable fit residual.
    """
    if source.names != target.names or source.parents != target.parents:
        raise ValueError("rest binding requires an explicit matching topology")
    matrices = np.repeat(np.eye(3)[None], len(source.names), axis=0)
    residuals = np.zeros(len(source.names))
    for i in range(len(source.names)):
        children = [j for j, p in enumerate(source.parents) if p == i]
        if not children:
            if source.parents[i] >= 0:
                matrices[i] = matrices[source.parents[i]]
            continue
        a, b = source.offsets[children], target.offsets[children]
        a = a / np.linalg.norm(a, axis=1, keepdims=True)
        b = b / np.linalg.norm(b, axis=1, keepdims=True)
        # Collinear branches constrain only one direction, just like a chain.
        if (
            len(children) == 1
            or min(np.linalg.matrix_rank(a), np.linalg.matrix_rank(b)) < 2
        ):
            rotation, _ = Rotation.align_vectors(a[:1], b[:1])
        else:
            rotation, _ = Rotation.align_vectors(a, b)
        matrices[i] = rotation.as_matrix()
        residuals[i] = np.max(np.linalg.norm(rotation.apply(b) - a, axis=1))
    return Rotation.from_matrix(matrices).as_quat(), residuals


def change_local_frames(local_xyzw, parents, target_to_source_xyzw):
    """R'_root = R_root C_root; R'_j = C_parent^-1 R_j C_j.

    This is a coordinate change, not pose inference or a per-frame IK repair.
    It preserves rotation-space distances and observed axial twist.
    """
    local = np.asarray(local_xyzw, dtype=np.float64)
    frames = Rotation.from_quat(target_to_source_xyzw).as_matrix()
    if local.shape[-2:] != (len(parents), 4) or frames.shape != (len(parents), 3, 3):
        raise ValueError("local pose and frame binding must share a topology")
    matrices = (
        Rotation.from_quat(local.reshape(-1, 4))
        .as_matrix()
        .reshape(*local.shape[:-1], 3, 3)
    )
    parent_frames = np.stack([np.eye(3) if p == -1 else frames[p].T for p in parents])
    result = parent_frames @ matrices @ frames
    return Rotation.from_matrix(result.reshape(-1, 3, 3)).as_quat().reshape(local.shape)
