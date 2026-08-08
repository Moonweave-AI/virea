from __future__ import annotations

import hashlib

import numpy as np

from virea.data.adapters.base import BaseDatasetAdapter
from virea.data.annotations import SidecarCapacityError, cache_numpy_sidecar, make_annotation, make_channel
from virea.data.types import RawClip, SampleRef
from virea.motion.retarget import map_root_rotations_by_basis
from virea.motion.rotation import axis_angle_to_quat_xyzw


class GRABAdapter(BaseDatasetAdapter):
    def discover(self, limit: int = 50, query: str = "") -> list[SampleRef]:
        if not self.raw_root.exists():
            return []
        samples: list[SampleRef] = []
        for path in sorted(self.raw_root.glob("s*/*.npz")):
            sample_id = self._rel_id(path)
            if not self._matches(sample_id, query):
                continue
            samples.append(self._sample(sample_id, path, "smplx_fullpose_npz", "smplx_fullpose", metadata={"dataset_profile": "grab_smplx55"}))
            if len(samples) >= limit:
                break
        return samples

    def load(self, sample_id: str, max_frames: int | None = None) -> RawClip:
        path = self._path_from_id(sample_id, ".npz")
        if not path.exists():
            raise FileNotFoundError(f"GRAB sample not found: {sample_id}")
        payload = self._load_trusted_pickle_numpy(path)
        body = payload["body"].item()
        params = body["params"]
        fullpose = np.asarray(params["fullpose"], dtype=np.float32)
        translation = np.asarray(params.get("transl", np.zeros((fullpose.shape[0], 3))), dtype=np.float32)
        fps = float(np.asarray(payload.get("framerate", 120.0)).reshape(-1)[0])
        metadata = {
            "subject_id": str(np.asarray(payload.get("sbj_id", path.parent.name)).reshape(-1)[0]),
            "gender": str(np.asarray(payload.get("gender", "")).reshape(-1)[0]),
            "object_name": str(np.asarray(payload.get("obj_name", "")).reshape(-1)[0]),
            "has_contact": "contact" in payload.files,
            "motion_intent": str(np.asarray(payload.get("motion_intent", "")).reshape(-1)[0]),
            "declared_world_basis": "z_up_to_y_up",
            "dataset_profile": "grab_smplx55",
        }
        sample = self._sample(sample_id, path, "smplx_fullpose_npz", "smplx_fullpose", fps=fps, frame_count=fullpose.shape[0], metadata=metadata)
        motion = {"fullpose": fullpose, "translation": translation, "fps": fps, "source_metadata": metadata}
        annotations: list[dict] = []
        ordinal = 0
        if metadata.get("object_name"):
            annotations.append(
                make_annotation(
                    dataset=self.record.key,
                    sample_id=sample_id,
                    source="grab.obj_name",
                    record_key="obj_name",
                    ordinal=ordinal,
                    level="context",
                    type="object",
                    text=metadata["object_name"],
                    bodypart="object",
                    provenance="native",
                    original={"value": metadata["object_name"]},
                )
            )
            ordinal += 1
        if metadata.get("motion_intent"):
            annotations.append(
                make_annotation(
                    dataset=self.record.key,
                    sample_id=sample_id,
                    source="grab.motion_intent",
                    record_key="motion_intent",
                    ordinal=ordinal,
                    level="context",
                    type="motion_intent",
                    text=metadata["motion_intent"],
                    provenance="native",
                    original={"value": metadata["motion_intent"]},
                )
            )
            ordinal += 1
        stem = path.stem
        annotations.append(
            make_annotation(
                dataset=self.record.key,
                sample_id=sample_id,
                source="grab.source_path.filename",
                record_key="filename",
                ordinal=ordinal,
                level="sequence",
                type="inferred_action_context",
                text=" ".join(stem.replace("-", " ").replace("_", " ").split()),
                provenance="derived",
                reasoning="GRAB does not expose a separate action label field in this archive; this context is derived from the sequence filename.",
                original={"filename_stem": stem},
            )
        )
        ordinal += 1

        channels: list[dict] = []

        def contact_storage(value: np.ndarray) -> tuple[str, dict | None, str | None, dict]:
            contiguous = np.ascontiguousarray(value)
            audit = {
                "native_array_sha256": hashlib.sha256(contiguous.tobytes(order="C")).hexdigest(),
                "native_array_byte_length": int(contiguous.nbytes),
                "native_shape": list(contiguous.shape),
                "native_dtype": str(contiguous.dtype),
            }
            try:
                reference = cache_numpy_sidecar(contiguous)
            except SidecarCapacityError as exc:
                audit["lossless_sidecar_status"] = "unavailable_cache_capacity"
                return (
                    "metadata_only",
                    None,
                    f"The lossless contact array exceeds the bounded on-demand sidecar capacity: {exc}",
                    audit,
                )
            audit["lossless_sidecar_status"] = "external"
            audit["lossless_sidecar_media_type"] = reference["media_type"]
            return "external", reference, None, audit

        if "object" in payload.files:
            object_record = payload["object"].item()
            object_params = object_record.get("params", {}) if isinstance(object_record, dict) else {}
            object_trans = np.asarray(object_params.get("transl", []), dtype=np.float32)
            object_orient = np.asarray(object_params.get("global_orient", []), dtype=np.float32)
            if object_trans.ndim == 2 and object_trans.shape[-1] == 3 and object_orient.shape == object_trans.shape:
                object_quat = axis_angle_to_quat_xyzw(object_orient)
                basis = np.asarray(
                    [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]],
                    dtype=np.float32,
                )
                body_root_origin = (
                    np.asarray(translation[0], dtype=np.float32)
                    if translation.ndim == 2 and translation.shape[0]
                    else np.zeros(3, dtype=np.float32)
                )
                canonical_trans = ((object_trans - body_root_origin) @ basis.T).astype(np.float32)
                # GRAB object global_orient is an active object-local -> source-world
                # orientation.  The mesh local basis is unchanged, so only the world
                # side is mapped: R_C = B R_S (not the world-operator B R_S B^-1).
                canonical_quat = map_root_rotations_by_basis(
                    object_quat,
                    basis,
                    semantics="local_to_world",
                ).astype(np.float32)
                channels.append(
                    make_channel(
                        dataset=self.record.key,
                        sample_id=sample_id,
                        source="grab.object.params",
                        record_key="object_pose",
                        ordinal=0,
                        kind="object_pose",
                        availability="inline",
                        representation="translation_m_rotation_xyzw",
                        timebase={"start_frame": 0, "end_frame": int(object_trans.shape[0]), "interval": "half_open"},
                        fps=fps,
                        frame_count=int(object_trans.shape[0]),
                        shape=[int(object_trans.shape[0]), 7],
                        coordinate_system="grab_source_world_z_up",
                        unit="meter",
                        preview={
                            "translation_m": object_trans.tolist(),
                            "rotation_xyzw": object_quat.tolist(),
                        },
                        extras={
                            "object_name": metadata.get("object_name"),
                            "model_ref_available": bool(object_record.get("object_mesh")) if isinstance(object_record, dict) else False,
                            "source_to_canonical": {
                                "formula": "pC = B * (pObjectS - pBodyRoot0)",
                                "basis_matrix": basis.tolist(),
                                "body_root_first_translation_m": body_root_origin.tolist(),
                                "target_coordinate_system": "gltf_y_up_z_forward",
                                "rotation_semantics": "local_to_world",
                                "rotation_formula": "R_C = B * R_S",
                            },
                        },
                    )
                )
                channels.append(
                    make_channel(
                        dataset=self.record.key,
                        sample_id=sample_id,
                        source="virea.transform(grab.object.params)",
                        record_key="object_pose_canonical",
                        ordinal=3,
                        kind="object_pose",
                        availability="inline",
                        representation="translation_m_rotation_xyzw",
                        timebase={"start_frame": 0, "end_frame": int(object_trans.shape[0]), "interval": "half_open"},
                        fps=fps,
                        frame_count=int(object_trans.shape[0]),
                        shape=[int(object_trans.shape[0]), 7],
                        coordinate_system="gltf_y_up_z_forward",
                        unit="meter",
                        provenance="derived",
                        preview={
                            "translation_m": canonical_trans.tolist(),
                            "rotation_xyzw": canonical_quat.tolist(),
                        },
                        extras={
                            "object_name": metadata.get("object_name"),
                            "derived_from_channel_record_key": "object_pose",
                            "reasoning": "Applied the GRAB z-up to canonical y-up basis after subtracting the first body-root translation; object-local-to-world orientation was left-multiplied by that basis while preserving the mesh local basis.",
                            "rotation_semantics": "local_to_world",
                            "rotation_formula": "R_C = B * R_S",
                            "basis_matrix": basis.tolist(),
                            "body_root_first_translation_m": body_root_origin.tolist(),
                        },
                    )
                )
        if "contact" in payload.files:
            contact_record = payload["contact"].item()
            object_contact = np.asarray(contact_record.get("object", []))
            if object_contact.ndim == 2:
                annotations.append(
                    make_annotation(
                        dataset=self.record.key,
                        sample_id=sample_id,
                        source="grab.contact.object",
                        record_key="contact_availability",
                        ordinal=ordinal,
                        level="metadata",
                        type="contact_availability",
                        text="Per-frame object contact labels are available",
                        bodypart="interaction",
                        provenance="native",
                        original={"shape": list(object_contact.shape), "threshold": contact_record.get("threshold")},
                    )
                )
                active_counts = np.count_nonzero(object_contact, axis=1).astype(np.int32)
                contact_availability, contact_ref, contact_reason, contact_audit = contact_storage(object_contact)
                channels.append(
                    make_channel(
                        dataset=self.record.key,
                        sample_id=sample_id,
                        source="grab.contact.object",
                        record_key="native_contact_map",
                        ordinal=1,
                        kind="contact",
                        availability=contact_availability,
                        representation="categorical_per_element",
                        timebase={"start_frame": 0, "end_frame": int(object_contact.shape[0]), "interval": "half_open"},
                        fps=fps,
                        frame_count=int(object_contact.shape[0]),
                        shape=list(object_contact.shape),
                        coordinate_system="grab_object_mesh_vertices",
                        unit="body_part_category",
                        data_ref=contact_ref,
                        reason_unavailable=contact_reason,
                        preview={
                            "active_element_count": active_counts.tolist(),
                            "max_label": int(object_contact.max(initial=0)),
                            "min_label": int(object_contact.min(initial=0)),
                        },
                        extras={
                            "element_ids": "implicit_zero_based_object_vertex_index",
                            "dtype": str(object_contact.dtype),
                            "no_contact_value": 0,
                            "label_range": [
                                int(object_contact.min(initial=0)),
                                int(object_contact.max(initial=0)),
                            ],
                            "label_map": None,
                            "threshold": contact_record.get("threshold"),
                            "preview_is_derived_aggregate": True,
                            "heatmap_supported": False,
                            "heatmap_unsupported_reason": "The archive contact element count is not proven to match the preview object mesh topology.",
                            **contact_audit,
                        },
                    )
                )
                channels.append(
                    make_channel(
                        dataset=self.record.key,
                        sample_id=sample_id,
                        source="virea.aggregate(grab.contact.object)",
                        record_key="contact_activity",
                        ordinal=2,
                        kind="contact_activity",
                        availability="inline",
                        representation="active_element_count_per_frame",
                        timebase={"start_frame": 0, "end_frame": int(object_contact.shape[0]), "interval": "half_open"},
                        fps=fps,
                        frame_count=int(object_contact.shape[0]),
                        shape=[int(object_contact.shape[0])],
                        unit="element_count",
                        provenance="derived",
                        preview={"values": active_counts.tolist()},
                        extras={"reasoning": "Counted non-zero native object-contact categories for each frame; the native map remains separately described."},
                    )
                )
            body_contact = np.asarray(contact_record.get("body", []))
            if body_contact.ndim == 2:
                annotations.append(
                    make_annotation(
                        dataset=self.record.key,
                        sample_id=sample_id,
                        source="grab.contact.body",
                        record_key="body_contact_availability",
                        ordinal=ordinal + 1,
                        level="metadata",
                        type="contact_availability",
                        text="Per-frame body-mesh contact labels are available",
                        bodypart="interaction",
                        provenance="native",
                        original={"shape": list(body_contact.shape), "threshold": contact_record.get("threshold")},
                    )
                )
                body_availability, body_ref, body_reason, body_audit = contact_storage(body_contact)
                body_active_counts = np.count_nonzero(body_contact, axis=1).astype(np.int32)
                channels.append(
                    make_channel(
                        dataset=self.record.key,
                        sample_id=sample_id,
                        source="grab.contact.body",
                        record_key="native_body_contact_map",
                        ordinal=4,
                        kind="contact",
                        availability=body_availability,
                        representation="categorical_per_element",
                        timebase={"start_frame": 0, "end_frame": int(body_contact.shape[0]), "interval": "half_open"},
                        fps=fps,
                        frame_count=int(body_contact.shape[0]),
                        shape=list(body_contact.shape),
                        coordinate_system="grab_body_mesh_vertices",
                        unit="contact_category",
                        data_ref=body_ref,
                        reason_unavailable=body_reason,
                        preview={
                            "active_element_count": body_active_counts.tolist(),
                            "max_label": int(body_contact.max(initial=0)),
                            "min_label": int(body_contact.min(initial=0)),
                        },
                        extras={
                            "element_ids": "implicit_zero_based_body_vertex_index",
                            "dtype": str(body_contact.dtype),
                            "no_contact_value": 0,
                            "label_range": [
                                int(body_contact.min(initial=0)),
                                int(body_contact.max(initial=0)),
                            ],
                            "label_map": None,
                            "threshold": contact_record.get("threshold"),
                            "preview_is_derived_aggregate": True,
                            "heatmap_supported": False,
                            "heatmap_unsupported_reason": "The archive contact element count is not proven to match the preview body mesh topology.",
                            **body_audit,
                        },
                    )
                )
        return RawClip(sample=sample, motion=motion, annotations=annotations, channels=channels).limited(max_frames)
