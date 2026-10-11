"""Read locally installed source geometry; never bundle licensed body-model data."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from virea_core.paths import VireaPaths

from .skeleton import BODY_BONES, CANONICAL_PARENT, FK_BONES


@dataclass(frozen=True)
class SMPLXSourceRig:
    offsets: dict
    sha256: str


def load_smplx_rig(path):
    """Accept a numeric neutral joint table or a safe numeric SMPL-X NPZ.

    NPZ may contain joints55, or J_regressor/v_template from a licensed model.
    Hand pose comes from per-frame inputs; model mean fields are not applied.
    No pickle loading and no network or arbitrary filesystem search.
    """
    from .codecs import SMPLX_HAND_INDEX

    path = Path(path)
    raw = path.read_bytes()
    import io

    data = np.load(io.BytesIO(raw), allow_pickle=False)
    if isinstance(data, np.lib.npyio.NpzFile):
        with data:
            if "joints55" in data:
                joints = data["joints55"]
            else:
                joints = data["J_regressor"] @ data["v_template"]
    else:
        joints = data
    joints = np.asarray(joints, dtype=float)
    if joints.shape != (55, 3) or not np.isfinite(joints).all():
        raise ValueError(
            "SMPL-X source rest geometry requires 55 finite joints in metres"
        )
    indices = {**{n: i for i, n in enumerate(BODY_BONES)}, **SMPLX_HAND_INDEX}
    offsets = {
        n: joints[indices[n]] - joints[indices[CANONICAL_PARENT[n]]]
        for n in FK_BONES[1:]
    }
    from .skeleton import canonical_geometry

    canonical_geometry(offsets)  # Validate topology and nonzero bone lengths.
    return SMPLXSourceRig(offsets, hashlib.sha256(raw).hexdigest())


def installed_smplx_rig():
    """Resolve a model asset in the same portable home as all other models."""
    directory = VireaPaths.discover().model_assets / "skeletons"
    for name in ("SMPLX_NEUTRAL.npz", "smplx-neutral.npz", "smplx-neutral.npy"):
        path = directory / name
        if path.is_file():
            return load_smplx_rig(path)
    return None
