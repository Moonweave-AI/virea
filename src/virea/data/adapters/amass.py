from __future__ import annotations

from pathlib import Path

import numpy as np

from virea.data.adapters.base import BaseDatasetAdapter
from virea.data.annotations import make_annotation
from virea.data.types import RawClip, SampleRef
from virea.motion.codecs import SMPL24_NAMES
from virea.motion.skeleton import BODY_EDGES


def amass_pose_codec(payload: np.lib.npyio.NpzFile, width: int) -> tuple[str, str]:
    """Select the source codec without conflating SMPL-H hands with body22."""
    if width == 156:
        return "smplh_body_hands", "smplh_axis_angle_npz"
    model_tokens: list[str] = []
    for key in ("model_type", "surface_model_type", "body_model"):
        if key in payload.files:
            model_tokens.extend(str(value).casefold() for value in np.asarray(payload[key]).reshape(-1).tolist())
    if width >= 165 and any("smplx" in token or "smpl-x" in token for token in model_tokens):
        return "smplx_fullpose", "smplx_fullpose_npz"
    return "axis_angle_body22", "smplh_axis_angle_npz"


def inspect_amass_pose_codec(path: Path) -> tuple[str, str]:
    try:
        with np.load(path, allow_pickle=False) as payload:
            width = int(np.asarray(payload["poses"]).shape[1])
            return amass_pose_codec(payload, width)
    except (OSError, KeyError, ValueError, IndexError):
        return "axis_angle_body22", "smplh_axis_angle_npz"


def amass_profile_key(codec_key: str) -> str:
    return {
        "smplh_body_hands": "amass_smplh156",
        "smplx_fullpose": "amass_smplx_stageii165",
        "position_sequence": "amass_humanact12_positions",
    }.get(codec_key, "amass_smpl_body22")


class AMASSAdapter(BaseDatasetAdapter):
    _SKIP_STEMS = {"female_stagei", "male_stagei", "shape", "marker"}

    def _derived_path_annotation(self, sample_id: str) -> dict:
        stem = Path(sample_id).stem
        text = " ".join(stem.replace("-", " ").replace("_", " ").split()) or sample_id
        return make_annotation(
            dataset=self.record.key,
            sample_id=sample_id,
            source="amass.source_path.filename",
            record_key="filename",
            ordinal=0,
            level="sequence",
            type="inferred_action_name",
            text=text,
            provenance="derived",
            reasoning="AMASS does not provide an action label here; this display name is derived from the source filename.",
            original={"sample_id": sample_id, "filename_stem": stem},
        )

    def discover(self, limit: int = 50, query: str = "") -> list[SampleRef]:
        if not self.raw_root.exists():
            return []
        samples: list[SampleRef] = []
        for path in sorted(self.raw_root.rglob("*.npz")):
            if "LICENSE" in path.name.upper():
                continue
            if path.stem.lower() in self._SKIP_STEMS:
                continue
            sample_id = self._rel_id(path)
            if not self._matches(sample_id, query):
                continue
            codec_key, source_format = inspect_amass_pose_codec(path)
            samples.append(
                self._sample(
                    sample_id,
                    path,
                    source_format,
                    codec_key,
                    metadata={"dataset_profile": amass_profile_key(codec_key)},
                )
            )
            if len(samples) >= limit:
                return samples
        for path in sorted((self.raw_root / "humanact12").rglob("*.npy")) if (self.raw_root / "humanact12").exists() else []:
            sample_id = self._rel_id(path)
            if not self._matches(sample_id, query):
                continue
            samples.append(
                self._sample(
                    sample_id,
                    path,
                    "humanact12_positions_npy",
                    "position_sequence",
                    fps=20.0,
                    metadata={"dataset_profile": "amass_humanact12_positions"},
                )
            )
            if len(samples) >= limit:
                break
        return samples

    def load(self, sample_id: str, max_frames: int | None = None) -> RawClip:
        npz_path = self._path_from_id(sample_id, ".npz")
        npy_path = self._path_from_id(sample_id, ".npy")
        if npz_path.exists():
            payload = np.load(npz_path, allow_pickle=False)
            poses = np.asarray(payload["poses"], dtype=np.float32)
            trans = np.asarray(payload.get("trans", np.zeros((poses.shape[0], 3))), dtype=np.float32)
            fps = float(np.asarray(payload.get("mocap_framerate", payload.get("mocap_frame_rate", 60.0))).reshape(-1)[0])
            codec_key, source_format = amass_pose_codec(payload, poses.shape[1])
            profile_key = amass_profile_key(codec_key)
            sample = self._sample(
                sample_id,
                npz_path,
                source_format,
                codec_key,
                fps=fps,
                frame_count=poses.shape[0],
                metadata={"dataset_profile": profile_key},
            )
            motion = {
                "poses": poses,
                "translation": trans,
                "fps": fps,
                "source_metadata": {
                    "dataset_profile": profile_key,
                    "declared_world_basis": "identity_y_up" if codec_key == "smplx_fullpose" else "z_up_to_y_up",
                },
            }
            if codec_key == "smplx_fullpose":
                motion["fullpose"] = poses[:, :165]
            clip = RawClip(
                sample=sample,
                motion=motion,
                annotations=[self._derived_path_annotation(sample_id)],
            )
            return clip.limited(max_frames)
        if npy_path.exists():
            positions = np.asarray(np.load(npy_path, allow_pickle=False), dtype=np.float32)
            sample = self._sample(
                sample_id,
                npy_path,
                "humanact12_positions_npy",
                "position_sequence",
                fps=20.0,
                frame_count=positions.shape[0],
                metadata={"dataset_profile": "amass_humanact12_positions"},
            )
            edges = [edge for edge in BODY_EDGES if edge[0] < positions.shape[1] and edge[1] < positions.shape[1]]
            clip = RawClip(
                sample=sample,
                motion={"positions": positions, "fps": 20.0},
                annotations=[self._derived_path_annotation(sample_id)],
                source_joint_names=SMPL24_NAMES[: positions.shape[1]],
                source_edges=edges,
            )
            return clip.limited(max_frames)
        raise FileNotFoundError(f"AMASS sample not found: {sample_id}")
