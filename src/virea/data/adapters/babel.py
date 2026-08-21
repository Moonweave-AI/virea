from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from virea.data.adapters.amass import amass_pose_codec, inspect_amass_pose_codec
from virea.data.adapters.base import BaseDatasetAdapter
from virea.data.annotations import make_annotation
from virea.data.types import RawClip, SampleRef


class BABELAdapter(BaseDatasetAdapter):
    _BABEL_TO_AMASS = {
        "ACCAD": "ACCAD",
        "BMLmovi": "BMLmovi",
        "BMLrub": "BMLrub",
        "CMU": "CMU",
        "DFaust67": "DFaust",
        "EKUT": "EKUT",
        "EyesJapanDataset": "EyesJapanDataset",
        "HumanEva": "HumanEva",
        "KIT": "KIT",
        "MPIHDM05": "HDM05",
        "MPILimits": "PosePrior",
        "MPImosh": "MoSh",
        "SFU": "SFU",
        "SSMsynced": "SSM",
        "TCDhandMocap": "TCDHands",
        "TotalCapture": "TotalCapture",
        "Transitionsmocap": "Transitions",
    }

    @staticmethod
    def _carrier_profile_key(codec_key: str) -> str:
        return {
            "smplh_body_hands": "babel_amass_smplh156",
            "smplx_fullpose": "babel_amass_smplx_stageii165",
        }.get(codec_key, "babel_amass_smpl_body22")

    @lru_cache(maxsize=2)
    def _annotations(self, split: str) -> dict[str, Any]:
        path = self.raw_root / "babel-teach" / f"{split}.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _annotation_motion_path(self, record: dict[str, Any]) -> Path:
        feat = str(record.get("feat_p", "")).strip()
        for _rule, candidate in self._annotation_motion_candidates(feat):
            if candidate.exists():
                return candidate
        try:
            return self._safe_path(self.raw_root.parent / "amass", feat)
        except ValueError as exc:
            raise ValueError(
                f"BABEL feat_p escaped the sibling AMASS root: {feat!r}"
            ) from exc

    def _annotation_motion_candidates(self, feat: str) -> list[tuple[str, Path]]:
        parts = list(Path(feat).parts)
        amass_root = self.raw_root.parent / "amass"
        candidates: list[tuple[str, Path]] = []
        if len(parts) >= 3 and parts[0] in self._BABEL_TO_AMASS:
            mapped_dataset = self._BABEL_TO_AMASS[parts[0]]
            try:
                candidates.append(
                    (
                        "mapped_dataset_drop_archive_wrapper",
                        self._safe_path(
                            amass_root, Path(mapped_dataset).joinpath(*parts[2:])
                        ),
                    )
                )
            except ValueError:
                pass
            fallback = self._canonical_carrier_fallback(
                mapped_dataset, tuple(parts[2:-1]), parts[-1]
            )
            if fallback is not None:
                candidates.append(("mapped_dataset_canonical_filename", fallback))
        try:
            candidates.append(
                ("sibling_amass_exact", self._safe_path(amass_root, feat))
            )
            candidates.append(
                ("legacy_babel_local", self._safe_path(self.raw_root, feat))
            )
        except ValueError:
            pass
        unique: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for rule, path in candidates:
            key = path.as_posix().casefold()
            if key not in seen:
                unique.append((rule, path))
                seen.add(key)
        return unique

    @staticmethod
    def _canonical_motion_stem(name: str) -> str:
        stem = Path(name).stem
        stem = re.sub(r"_(?:poses|stageii)$", "", stem, flags=re.IGNORECASE)
        return re.sub(r"[^a-z0-9]+", "", stem.casefold())

    @lru_cache(maxsize=16384)
    def _canonical_carrier_fallback(
        self,
        mapped_dataset: str,
        relative_parent: tuple[str, ...],
        source_name: str,
    ) -> Path | None:
        dataset_root = self._safe_path(self.raw_root.parent / "amass", mapped_dataset)
        preferred_parent = (
            self._safe_path(dataset_root, Path(*relative_parent))
            if relative_parent
            else dataset_root
        )
        search_root = preferred_parent if preferred_parent.is_dir() else dataset_root
        if not search_root.is_dir():
            return None
        wanted = self._canonical_motion_stem(source_name)
        matches = [
            path
            for path in search_root.glob("*.npz")
            if self._canonical_motion_stem(path.name) == wanted
        ]
        return sorted(matches)[0] if len(matches) == 1 else None

    def _annotation_motion_rule(self, record: dict[str, Any], resolved: Path) -> str:
        feat = str(record.get("feat_p", "")).strip()
        for rule, candidate in self._annotation_motion_candidates(feat):
            if candidate == resolved:
                return rule
        return "unresolved"

    def _annotation_text(self, record: dict[str, Any]) -> str:
        labels: list[str] = []
        for block in ("seq_ann", "frame_ann"):
            ann = record.get(block, {})
            for item in ann.get("labels", []) if isinstance(ann, dict) else []:
                if not isinstance(item, dict):
                    continue
                value = item.get("proc_label") or item.get("raw_label")
                if value:
                    labels.append(str(value))
        return ", ".join(dict.fromkeys(labels))

    def discover(self, limit: int = 50, query: str = "") -> list[SampleRef]:
        if not self.raw_root.exists():
            return []
        samples: list[SampleRef] = []
        for split in ("train", "val"):
            for key, record in self._annotations(split).items():
                sample_id = f"babel-teach/{split}/{key}"
                text = self._annotation_text(record)
                if not (self._matches(sample_id, query) or self._matches(text, query)):
                    continue
                motion_path = self._annotation_motion_path(record)
                if not motion_path.exists():
                    continue
                codec_key = inspect_amass_pose_codec(motion_path)[0]
                samples.append(
                    self._sample(
                        sample_id,
                        motion_path,
                        "babel_annotation_json",
                        codec_key,
                        duration_sec=float(record.get("dur", 0.0) or 0.0),
                        text=text,
                        split=split,
                        related_paths={
                            "annotation": self.raw_root
                            / "babel-teach"
                            / f"{split}.json"
                        },
                        metadata={
                            "babel_sid": record.get("babel_sid"),
                            "feat_p": record.get("feat_p"),
                            "carrier_path_rule": self._annotation_motion_rule(
                                record, motion_path
                            ),
                            "dataset_profile": self._carrier_profile_key(codec_key),
                        },
                    )
                )
                if len(samples) >= limit:
                    return samples
        _skip_stems = {"female_stagei", "male_stagei", "shape", "marker"}
        for path in sorted(self.raw_root.rglob("*.npz")):
            if path.stem.lower() in _skip_stems:
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
                    metadata={"dataset_profile": self._carrier_profile_key(codec_key)},
                )
            )
            if len(samples) >= limit:
                break
        return samples

    def _record_for_sample(
        self, sample_id: str
    ) -> tuple[str | None, dict[str, Any] | None]:
        parts = sample_id.split("/")
        if len(parts) == 3 and parts[0] == "babel-teach":
            split, key = parts[1], parts[2]
            return split, self._annotations(split).get(key)
        return None, None

    def load(self, sample_id: str, max_frames: int | None = None) -> RawClip:
        split, record = self._record_for_sample(sample_id)
        annotations: list[dict[str, Any]] = []
        text = ""
        if record is not None:
            path = self._annotation_motion_path(record)
            text = self._annotation_text(record)
        else:
            path = self._path_from_id(sample_id, ".npz")
        if not path.exists():
            raise FileNotFoundError(
                f"BABEL carrier motion not found for {sample_id}: {path}"
            )
        payload = np.load(path, allow_pickle=False)
        poses = np.asarray(payload["poses"], dtype=np.float32)
        trans = np.asarray(
            payload.get("trans", np.zeros((poses.shape[0], 3))), dtype=np.float32
        )
        fps = float(
            np.asarray(
                payload.get(
                    "mocap_framerate",
                    payload.get(
                        "mocap_frame_rate", payload.get("mocap_frame_rate", 60.0)
                    ),
                )
            ).reshape(-1)[0]
        )
        codec_key, carrier_source_format = amass_pose_codec(payload, poses.shape[1])
        profile_key = self._carrier_profile_key(codec_key)
        carrier_time_contract: dict[str, Any] | None = None
        if record is not None and record.get("dur") is not None:
            declared_duration = float(record["dur"])
            decoded_duration = poses.shape[0] / fps
            tolerance = 0.5 / fps + 1e-9
            delta = decoded_duration - declared_duration
            carrier_time_contract = {
                "status": "matched" if abs(delta) <= tolerance else "mismatch",
                "declared_duration_sec": declared_duration,
                "decoded_duration_sec": decoded_duration,
                "delta_sec": delta,
                "tolerance_sec": tolerance,
                "frame_count": int(poses.shape[0]),
                "fps": fps,
                "rule": "abs(frames/fps-declared_duration)<=half_source_frame",
            }
        if record is not None:
            seq_block = record.get("seq_ann")
            seq_block = seq_block if isinstance(seq_block, dict) else {}
            seq_labels = seq_block.get("labels", [])
            for ordinal, item in enumerate(
                seq_labels if isinstance(seq_labels, list) else []
            ):
                if not isinstance(item, dict):
                    continue
                label = item.get("proc_label") or item.get("raw_label")
                if not label:
                    continue
                annotations.append(
                    make_annotation(
                        dataset=self.record.key,
                        sample_id=sample_id,
                        source="babel.seq_ann.labels",
                        record_key=f"seq_ann.labels[{ordinal}]",
                        ordinal=ordinal,
                        level="sequence",
                        type="action",
                        text=str(label),
                        provenance="native",
                        original={"record": item},
                        extras={
                            key: value
                            for key, value in item.items()
                            if key not in {"proc_label", "raw_label"}
                        },
                    )
                )
            frame_block = record.get("frame_ann")
            frame_block = frame_block if isinstance(frame_block, dict) else {}
            frame_labels = frame_block.get("labels", [])
            offset = len(annotations)
            for ordinal, item in enumerate(
                frame_labels if isinstance(frame_labels, list) else []
            ):
                if not isinstance(item, dict):
                    continue
                label = item.get("proc_label") or item.get("raw_label")
                if not label:
                    continue
                annotations.append(
                    make_annotation(
                        dataset=self.record.key,
                        sample_id=sample_id,
                        source="babel.frame_ann.labels",
                        record_key=f"frame_ann.labels[{ordinal}]",
                        ordinal=offset + ordinal,
                        level="action",
                        type="action",
                        text=str(label),
                        provenance="native",
                        start_sec=item.get("start_t"),
                        end_sec=item.get("end_t"),
                        fps=fps,
                        original={"record": item},
                        extras={
                            key: value
                            for key, value in item.items()
                            if key
                            not in {"proc_label", "raw_label", "start_t", "end_t"}
                        },
                    )
                )
        else:
            stem = Path(sample_id).stem
            annotations.append(
                make_annotation(
                    dataset=self.record.key,
                    sample_id=sample_id,
                    source="babel.carrier_path.filename",
                    record_key="filename",
                    ordinal=0,
                    level="sequence",
                    type="inferred_action_name",
                    text=" ".join(stem.replace("-", " ").replace("_", " ").split()),
                    provenance="derived",
                    reasoning="No BABEL annotation record was available; the display name is derived from the carrier filename.",
                    original={"sample_id": sample_id, "filename_stem": stem},
                )
            )
        sample = self._sample(
            sample_id,
            path,
            "babel_annotation_json" if record is not None else carrier_source_format,
            codec_key,
            fps=fps,
            frame_count=poses.shape[0],
            text=text,
            split=split,
            related_paths={
                "annotation": self.raw_root / "babel-teach" / f"{split}.json"
            }
            if record is not None and split
            else None,
            metadata={
                "dataset_profile": profile_key,
                "carrier_source_format": carrier_source_format,
                **(
                    {
                        "annotation_record": record,
                        "declared_duration_sec": record.get("dur"),
                        "carrier_time_contract": carrier_time_contract,
                        "carrier_path_rule": self._annotation_motion_rule(record, path),
                    }
                    if record is not None
                    else {}
                ),
            },
        )
        validation_warnings: list[str] = []
        if (
            carrier_time_contract is not None
            and carrier_time_contract["status"] != "matched"
        ):
            declared_duration = float(carrier_time_contract["declared_duration_sec"])
            decoded_duration = float(carrier_time_contract["decoded_duration_sec"])
            if abs(decoded_duration - declared_duration) > float(
                carrier_time_contract["tolerance_sec"]
            ):
                validation_warnings.append(
                    f"BABEL declared duration {declared_duration:.6f}s differs from carrier frames/fps {decoded_duration:.6f}s."
                )
        motion = {
            "poses": poses,
            "translation": trans,
            "fps": fps,
            "source_metadata": {
                "dataset_profile": profile_key,
                "declared_world_basis": "z_up_to_y_up",
            },
        }
        if codec_key == "smplx_fullpose":
            motion["fullpose"] = poses[:, :165]
        clip = RawClip(
            sample=sample,
            motion=motion,
            annotations=annotations,
            validation_warnings=validation_warnings,
        )
        return clip.limited(max_frames)
