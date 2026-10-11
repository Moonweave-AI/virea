"""Centered, coordinate-equivariant conditioning of sampled SO(3) curves."""

import numpy as np
from scipy.ndimage import gaussian_filter1d


def gaussian_rotation_mean(quaternions, sigma):
    """Gaussian-weighted Markley mean, invariant under q -> -q.

    The dominant eigenvector of sum(w q q^T) minimizes chordal rotation error.
    Left/right multiplication by constant unit quaternions commutes with this
    operation, so changing rig frames cannot change the temporal filter.
    At a repeated top eigenvalue, project the center sample into the optimal
    eigenspace: the data do not identify a unique mean in that case.
    """
    q = np.array(quaternions, dtype=np.float64, copy=True)
    if q.ndim < 2 or q.shape[-1] != 4 or not len(q) or not np.isfinite(q).all():
        raise ValueError("rotation curve requires finite (T,...,4) quaternions")
    norms = np.linalg.norm(q, axis=-1, keepdims=True)
    if np.any(norms < 1e-9) or not np.isfinite(sigma) or sigma < 0:
        raise ValueError("nonzero rotations and nonnegative finite sigma required")
    q /= norms
    if sigma == 0:
        return q
    moments = gaussian_filter1d(
        q[..., :, None] * q[..., None, :], sigma, axis=0, mode="nearest"
    )
    eigenvalues, eigenvectors = np.linalg.eigh(moments)
    optimal = eigenvalues >= eigenvalues[..., -1:] - 1e-12
    projection = np.einsum("...ij,...i->...j", eigenvectors, q) * optimal
    result = np.einsum("...ij,...j->...i", eigenvectors, projection)
    # A simple top eigenvalue already identifies one rotation (q and -q).
    # It remains valid even if the center observation is orthogonal to it.
    result = np.where(
        (np.sum(optimal, axis=-1) == 1)[..., None], eigenvectors[..., -1], result
    )
    length = np.linalg.norm(result, axis=-1, keepdims=True)
    # If the center is orthogonal to an ambiguous optimal eigenspace, retain
    # that observation. An arbitrary eigenvector would make the answer depend
    # on the coordinate basis used by the eigensolver.
    result = np.where(length > 1e-12, result / np.maximum(length, 1e-12), q)
    signs = np.ones(result.shape[:-1])
    signs[1:] = np.where(np.sum(result[1:] * result[:-1], axis=-1) < 0, -1, 1)
    return result * np.cumprod(signs, axis=0)[..., None]
