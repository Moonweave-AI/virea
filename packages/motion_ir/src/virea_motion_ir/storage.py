from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

import numpy as np
from virea_contracts.motion_ir import MotionIRDescriptor
from virea_contracts.result import ArtifactRef

from .model import ActorMotion, MotionIR

_ARRAY_MEDIA_TYPE = "application/x-npz"


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise TypeError(
        f"Motion IR metadata is not JSON-serializable: {type(value).__name__}"
    )


def _array_reference(
    name: str,
    value: np.ndarray,
    *,
    array_file: str,
) -> dict[str, Any]:
    array = np.ascontiguousarray(value)
    return ArtifactRef(
        name=name,
        media_type=_ARRAY_MEDIA_TYPE,
        uri=f"{array_file}#{name}",
        byte_length=int(array.nbytes),
        dtype=str(array.dtype),
        shape=tuple(int(item) for item in array.shape),
    ).model_dump(mode="json")


def _externalize_tracks(
    kind: str,
    tracks: tuple[dict[str, Any], ...],
    arrays: dict[str, np.ndarray],
    *,
    array_file: str,
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for index, track in enumerate(tracks):
        item = dict(track)
        values = item.pop("values", None)
        if values is not None:
            array = np.asarray(values)
            if array.dtype == object or not np.issubdtype(array.dtype, np.number):
                raise TypeError(f"{kind}[{index}].values must be a numeric array")
            if not np.isfinite(array).all():
                raise ValueError(f"{kind}[{index}].values contains NaN or infinity")
            key = f"{kind}{index}.values"
            arrays[key] = np.ascontiguousarray(array)
            item["values"] = _array_reference(
                key,
                arrays[key],
                array_file=array_file,
            )
        serialized.append(_json_safe(item))
    return serialized


def _restore_array(
    reference: ArtifactRef | dict[str, Any],
    arrays: Any,
    *,
    array_file: str,
) -> np.ndarray:
    artifact = (
        reference
        if isinstance(reference, ArtifactRef)
        else ArtifactRef.model_validate(reference)
    )
    prefix, separator, key = artifact.uri.partition("#")
    if prefix != array_file or separator != "#" or not key:
        raise ValueError(
            f"Motion IR array URI must be {array_file}#<name>: {artifact.uri}"
        )
    if key not in arrays.files:
        raise ValueError(f"Motion IR array is missing: {key}")
    value = np.asarray(arrays[key])
    if artifact.dtype is not None and str(value.dtype) != artifact.dtype:
        raise ValueError(f"Motion IR array dtype mismatch for {key}")
    if artifact.shape is not None and value.shape != tuple(artifact.shape):
        raise ValueError(f"Motion IR array shape mismatch for {key}")
    if artifact.byte_length is not None and int(value.nbytes) != artifact.byte_length:
        raise ValueError(f"Motion IR array byte length mismatch for {key}")
    return np.ascontiguousarray(value)


def _restore_tracks(
    items: tuple[dict[str, Any], ...],
    arrays: Any,
    *,
    array_file: str,
) -> tuple[dict[str, Any], ...]:
    restored: list[dict[str, Any]] = []
    for source in items:
        item = dict(source)
        values = item.get("values")
        if isinstance(values, dict) and values.get("media_type") == _ARRAY_MEDIA_TYPE:
            item["values"] = _restore_array(values, arrays, array_file=array_file)
        restored.append(item)
    return tuple(restored)


def save_motion_ir(motion: MotionIR, directory: str | Path) -> Path:
    """Persist an exact Motion IR v2 descriptor plus pickle-free NPZ arrays.

    Array fields use ``motion.npz#array-name`` ArtifactRefs. JSON is published
    last and therefore acts as the commit marker for this two-file bundle.
    """

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    descriptor_path = target / "motion.json"
    previous_array_file: str | None = None
    if descriptor_path.is_file():
        try:
            previous = MotionIRDescriptor.model_validate_json(
                descriptor_path.read_text(encoding="utf-8")
            )
            candidate, separator, _ = previous.actors[0].root_translation.uri.partition(
                "#"
            )
            if (
                separator == "#"
                and Path(candidate).name == candidate
                and Path(candidate).suffix == ".npz"
            ):
                previous_array_file = candidate
        except (OSError, ValueError):
            previous_array_file = None
    # Each publication receives an immutable array filename.  Publishing JSON
    # last can then never make an older descriptor point at newer arrays if a
    # replacement fails between the two writes.
    array_file = f"motion-{uuid4().hex}.npz"
    arrays: dict[str, np.ndarray] = {}
    actors: list[dict[str, Any]] = []
    for index, actor in enumerate(motion.actors):
        prefix = f"actor{index}"
        translation_name = f"{prefix}.root_translation_m"
        rotation_name = f"{prefix}.root_rotation_xyzw"
        arrays[translation_name] = actor.root_translation_m
        arrays[rotation_name] = actor.root_rotation_xyzw
        local_reference = None
        positions_reference = None
        confidence_reference = None
        if actor.local_rotations_xyzw is not None:
            name = f"{prefix}.local_rotations_xyzw"
            arrays[name] = actor.local_rotations_xyzw
            local_reference = _array_reference(
                name, arrays[name], array_file=array_file
            )
        if actor.global_positions_m is not None:
            name = f"{prefix}.global_positions_m"
            arrays[name] = actor.global_positions_m
            positions_reference = _array_reference(
                name,
                arrays[name],
                array_file=array_file,
            )
        if actor.confidence is not None:
            name = f"{prefix}.confidence"
            arrays[name] = actor.confidence
            confidence_reference = _array_reference(
                name,
                arrays[name],
                array_file=array_file,
            )
        actors.append(
            {
                "actor_id": actor.actor_id,
                "skeleton": {
                    "profile_id": actor.skeleton_profile_id,
                    "joint_names": list(actor.joint_names),
                    "parent_indices": list(actor.parent_indices),
                },
                "root_translation": _array_reference(
                    translation_name,
                    arrays[translation_name],
                    array_file=array_file,
                ),
                "root_rotation": _array_reference(
                    rotation_name,
                    arrays[rotation_name],
                    array_file=array_file,
                ),
                "local_rotations": local_reference,
                "global_positions": positions_reference,
                "confidence": confidence_reference,
            }
        )

    descriptor = MotionIRDescriptor.model_validate(
        {
            "schema_version": motion.schema_version,
            "motion_id": motion.motion_id,
            "time": {"frame_count": motion.frame_count, "fps": motion.fps},
            "actors": actors,
            "face_tracks": _externalize_tracks(
                "face", motion.face_tracks, arrays, array_file=array_file
            ),
            "gaze_tracks": _externalize_tracks(
                "gaze", motion.gaze_tracks, arrays, array_file=array_file
            ),
            "contact_tracks": _externalize_tracks(
                "contact", motion.contact_tracks, arrays, array_file=array_file
            ),
            "object_tracks": _externalize_tracks(
                "object", motion.object_tracks, arrays, array_file=array_file
            ),
            "annotations": _json_safe(motion.annotations),
            "segments": _json_safe(motion.segments),
            "provenance": _json_safe(motion.provenance),
            "quality": _json_safe(motion.quality),
        }
    )

    npz_path = target / array_file
    with NamedTemporaryFile(
        dir=target, prefix=".motion.", suffix=".npz", delete=False
    ) as handle:
        temporary_npz = Path(handle.name)
    try:
        np.savez(temporary_npz, **arrays)
        os.replace(temporary_npz, npz_path)
    finally:
        if temporary_npz.exists():
            temporary_npz.unlink()

    payload = json.dumps(
        descriptor.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    try:
        _atomic_bytes(descriptor_path, payload)
    except Exception:
        try:
            npz_path.unlink()
        except OSError:
            pass
        raise
    if previous_array_file and previous_array_file != array_file:
        try:
            (target / previous_array_file).unlink()
        except OSError:
            pass
    return descriptor_path


def load_motion_ir(path: str | Path) -> MotionIR:
    descriptor_path = Path(path)
    if descriptor_path.is_dir():
        descriptor_path = descriptor_path / "motion.json"
    descriptor = MotionIRDescriptor.model_validate_json(
        descriptor_path.read_text(encoding="utf-8")
    )
    array_file, separator, _ = descriptor.actors[0].root_translation.uri.partition("#")
    if (
        separator != "#"
        or not array_file
        or Path(array_file).name != array_file
        or Path(array_file).suffix != ".npz"
    ):
        raise ValueError(
            "Motion IR descriptor contains an invalid array bundle locator"
        )
    arrays_path = descriptor_path.parent / array_file
    actors: list[ActorMotion] = []
    with np.load(arrays_path, allow_pickle=False) as arrays:
        for item in descriptor.actors:
            actors.append(
                ActorMotion(
                    actor_id=item.actor_id,
                    skeleton_profile_id=item.skeleton.profile_id,
                    joint_names=item.skeleton.joint_names,
                    parent_indices=item.skeleton.parent_indices,
                    root_translation_m=_restore_array(
                        item.root_translation, arrays, array_file=array_file
                    ),
                    root_rotation_xyzw=_restore_array(
                        item.root_rotation, arrays, array_file=array_file
                    ),
                    local_rotations_xyzw=(
                        _restore_array(
                            item.local_rotations, arrays, array_file=array_file
                        )
                        if item.local_rotations is not None
                        else None
                    ),
                    global_positions_m=(
                        _restore_array(
                            item.global_positions, arrays, array_file=array_file
                        )
                        if item.global_positions is not None
                        else None
                    ),
                    confidence=(
                        _restore_array(item.confidence, arrays, array_file=array_file)
                        if item.confidence is not None
                        else None
                    ),
                )
            )
        face_tracks = _restore_tracks(
            descriptor.face_tracks, arrays, array_file=array_file
        )
        gaze_tracks = _restore_tracks(
            descriptor.gaze_tracks, arrays, array_file=array_file
        )
        contact_tracks = _restore_tracks(
            descriptor.contact_tracks, arrays, array_file=array_file
        )
        object_tracks = _restore_tracks(
            descriptor.object_tracks, arrays, array_file=array_file
        )
    if descriptor.time.fps is None:
        raise ValueError("the local Motion IR storage profile currently requires fps")
    motion = MotionIR(
        motion_id=descriptor.motion_id,
        fps=float(descriptor.time.fps),
        actors=tuple(actors),
        face_tracks=face_tracks,
        gaze_tracks=gaze_tracks,
        contact_tracks=contact_tracks,
        object_tracks=object_tracks,
        annotations=descriptor.annotations,
        segments=descriptor.segments,
        provenance=descriptor.provenance,
        quality=descriptor.quality,
    )
    if motion.frame_count != descriptor.time.frame_count:
        raise ValueError(
            "Motion IR descriptor frame_count does not match the stored arrays"
        )
    return motion
