from __future__ import annotations

import hashlib
import json
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import numpy as np


CANONICAL_ARTIFACT_SCHEMA_VERSION = "virea.canonical_artifact.v1.0.0"


def _plain_json(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _plain_json(value.tolist())
    if isinstance(value, np.generic):
        return _plain_json(value.item())
    if isinstance(value, Path):
        return unicodedata.normalize("NFC", value.as_posix())
    if isinstance(value, dict):
        return {
            unicodedata.normalize("NFC", str(key)): _plain_json(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return unicodedata.normalize("NFC", str(value))


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _plain_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def array_descriptor(value: np.ndarray) -> dict[str, Any]:
    array = np.ascontiguousarray(value)
    if array.dtype.hasobject:
        raise ValueError("canonical artifact arrays must not use object dtype")
    raw = array.tobytes(order="C")
    return {
        "dtype": array.dtype.str,
        "shape": [int(size) for size in array.shape],
        "byte_length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def build_manifest(
    payload: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
) -> dict[str, Any]:
    """Build a canonical manifest whose digest commits to metadata and raw arrays."""
    basis = deepcopy(dict(payload))
    basis.pop("manifest_sha256", None)
    ordered_arrays = {key: np.ascontiguousarray(arrays[key]) for key in sorted(arrays)}
    basis["arrays"] = {
        key: array_descriptor(value)
        for key, value in ordered_arrays.items()
    }
    hasher = hashlib.sha256()
    hasher.update(canonical_json_bytes(basis))
    for key, value in ordered_arrays.items():
        raw = value.tobytes(order="C")
        header = canonical_json_bytes(
            {
                "key": key,
                "dtype": value.dtype.str,
                "shape": [int(size) for size in value.shape],
                "byte_length": len(raw),
            }
        )
        hasher.update(len(header).to_bytes(8, "big"))
        hasher.update(header)
        hasher.update(len(raw).to_bytes(8, "big"))
        hasher.update(raw)
    basis["manifest_sha256"] = hasher.hexdigest()
    return _plain_json(basis)


def verify_manifest(
    manifest: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
) -> list[str]:
    errors: list[str] = []
    expected_arrays = manifest.get("arrays")
    if not isinstance(expected_arrays, dict):
        return ["canonical artifact manifest has no array descriptors"]
    actual_descriptors = {
        key: array_descriptor(np.asarray(value))
        for key, value in sorted(arrays.items())
    }
    if expected_arrays != actual_descriptors:
        errors.append("canonical artifact array dtype, shape, length, or SHA-256 mismatch")
    rebuilt = build_manifest(manifest, arrays)
    if str(manifest.get("manifest_sha256") or "") != rebuilt["manifest_sha256"]:
        errors.append("canonical artifact manifest SHA-256 mismatch")
    return errors


def load_npz_arrays(files: Mapping[str, Path]) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    for file_key, path in sorted(files.items()):
        with np.load(path, allow_pickle=False) as payload:
            for array_key in sorted(payload.files):
                arrays[f"{file_key}.{array_key}"] = np.asarray(payload[array_key])
    return arrays
