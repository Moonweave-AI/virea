"""Portable, read-only VRM humanoid rest-pose inspection.

Only the JSON chunk of a VRM/GLB file is needed to locate humanoid nodes and
evaluate their glTF rest transforms.  Keeping this small parser in Virea means
that control-rest audits do not depend on the optional ``vrm_motion`` training
stack (or on PyTorch).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from typing import Any

import numpy as np

from virea.motion.canonical import CANONICAL_TO_VRM_BONE_NAME, CORE_BONES, HAND_BONES


_GLB_MAGIC = 0x46546C67
_GLB_VERSION = 2
_GLB_JSON_CHUNK = 0x4E4F534A
_MAX_JSON_CHUNK_BYTES = 128 * 1024 * 1024
_CANONICAL_HUMANOID_BONES = ("hips", *CORE_BONES, *HAND_BONES)


class VRMInspectionError(ValueError):
    """Raised when a file cannot safely provide a VRM humanoid rest graph."""


def _read_exact(stream: Any, byte_count: int, label: str) -> bytes:
    payload = stream.read(byte_count)
    if len(payload) != byte_count:
        raise VRMInspectionError(f"truncated {label}")
    return payload


def _load_glb_json(path: Path) -> dict[str, Any]:
    try:
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            header = _read_exact(stream, 12, "GLB header")
            magic, version, declared_length = struct.unpack("<III", header)
            if magic != _GLB_MAGIC or version != _GLB_VERSION:
                raise VRMInspectionError("file is not a glTF 2.0 binary")
            if declared_length < 20 or declared_length != file_size:
                raise VRMInspectionError("invalid GLB declared length")

            consumed = 12
            while consumed + 8 <= declared_length:
                chunk_header = _read_exact(stream, 8, "GLB chunk header")
                chunk_length, chunk_type = struct.unpack("<II", chunk_header)
                consumed += 8
                if chunk_length > declared_length - consumed:
                    raise VRMInspectionError("GLB chunk exceeds declared file length")
                if chunk_type != _GLB_JSON_CHUNK:
                    stream.seek(chunk_length, 1)
                    consumed += chunk_length
                    continue
                if chunk_length > _MAX_JSON_CHUNK_BYTES:
                    raise VRMInspectionError("GLB JSON chunk is too large")
                raw_json = _read_exact(stream, chunk_length, "GLB JSON chunk")
                try:
                    payload = json.loads(raw_json.rstrip(b"\x00 \t\r\n").decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise VRMInspectionError("invalid GLB JSON chunk") from exc
                if not isinstance(payload, dict):
                    raise VRMInspectionError("GLB JSON root must be an object")
                return payload
    except OSError as exc:
        raise VRMInspectionError("VRM file could not be read") from exc
    raise VRMInspectionError("GLB JSON chunk was not found")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise VRMInspectionError("VRM file could not be hashed") from exc
    return digest.hexdigest()


def _vrm_extension(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    extensions = payload.get("extensions")
    if not isinstance(extensions, dict):
        raise VRMInspectionError("GLB does not contain a VRM extension")
    vrm1 = extensions.get("VRMC_vrm")
    if isinstance(vrm1, dict):
        return "1.0", vrm1
    vrm0 = extensions.get("VRM")
    if isinstance(vrm0, dict):
        return "0.x", vrm0
    raise VRMInspectionError("GLB does not contain a VRM extension")


def _is_node_index(value: Any, node_count: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < node_count


def _human_bones(vrm_extension: dict[str, Any], version: str, node_count: int) -> dict[str, int]:
    humanoid = vrm_extension.get("humanoid")
    if not isinstance(humanoid, dict):
        raise VRMInspectionError("VRM humanoid definition is missing")
    raw_bones = humanoid.get("humanBones")
    result: dict[str, int] = {}
    if version == "1.0" and isinstance(raw_bones, dict):
        for raw_name, entry in raw_bones.items():
            if not isinstance(raw_name, str) or not isinstance(entry, dict):
                continue
            node_index = entry.get("node")
            if _is_node_index(node_index, node_count):
                result[raw_name] = node_index
    elif version == "0.x" and isinstance(raw_bones, list):
        for entry in raw_bones:
            if not isinstance(entry, dict):
                continue
            raw_name = entry.get("bone")
            node_index = entry.get("node")
            if isinstance(raw_name, str) and raw_name and _is_node_index(node_index, node_count):
                result[raw_name] = node_index
    if not result:
        raise VRMInspectionError("VRM does not contain valid humanoid bone nodes")
    return result


def _finite_vector(value: Any, length: int, default: tuple[float, ...], label: str) -> np.ndarray:
    if value is None:
        return np.asarray(default, dtype=np.float64)
    if not isinstance(value, list) or len(value) != length:
        raise VRMInspectionError(f"{label} must contain {length} numbers")
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise VRMInspectionError(f"{label} contains a non-number") from exc
    if vector.shape != (length,) or not np.isfinite(vector).all():
        raise VRMInspectionError(f"{label} contains an invalid number")
    return vector


def _quaternion_matrix(quaternion_xyzw: np.ndarray) -> np.ndarray:
    quaternion = np.asarray(quaternion_xyzw, dtype=np.float64)
    norm = float(np.linalg.norm(quaternion))
    if norm < 1e-12:
        raise VRMInspectionError("node rotation quaternion has zero length")
    x, y, z, w = quaternion / norm
    return np.asarray(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _node_local_matrix(node: dict[str, Any], node_index: int) -> np.ndarray:
    raw_matrix = node.get("matrix")
    if raw_matrix is not None:
        matrix_values = _finite_vector(raw_matrix, 16, tuple(np.eye(4).T.reshape(-1)), f"node {node_index} matrix")
        matrix = matrix_values.reshape(4, 4).T
        if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-7):
            raise VRMInspectionError(f"node {node_index} matrix is not affine")
        return matrix

    translation = _finite_vector(
        node.get("translation"), 3, (0.0, 0.0, 0.0), f"node {node_index} translation"
    )
    rotation = _finite_vector(
        node.get("rotation"), 4, (0.0, 0.0, 0.0, 1.0), f"node {node_index} rotation"
    )
    scale = _finite_vector(node.get("scale"), 3, (1.0, 1.0, 1.0), f"node {node_index} scale")
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = _quaternion_matrix(rotation) @ np.diag(scale)
    matrix[:3, 3] = translation
    return matrix


def _node_graph(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[int, int | None]]:
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise VRMInspectionError("GLB nodes are missing")
    nodes: list[dict[str, Any]] = []
    for node_index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            raise VRMInspectionError(f"node {node_index} must be an object")
        nodes.append(raw_node)

    parents: dict[int, int | None] = {node_index: None for node_index in range(len(nodes))}
    for parent_index, node in enumerate(nodes):
        children = node.get("children", [])
        if not isinstance(children, list):
            raise VRMInspectionError(f"node {parent_index} children must be an array")
        for child_index in children:
            if not _is_node_index(child_index, len(nodes)):
                raise VRMInspectionError(f"node {parent_index} has an invalid child")
            if parents[child_index] is not None:
                raise VRMInspectionError(f"node {child_index} has more than one parent")
            parents[child_index] = parent_index
    return nodes, parents


def _world_matrices(nodes: list[dict[str, Any]], parents: dict[int, int | None]) -> dict[int, np.ndarray]:
    cache: dict[int, np.ndarray] = {}
    resolving: set[int] = set()

    def resolve(node_index: int) -> np.ndarray:
        if node_index in cache:
            return cache[node_index]
        if node_index in resolving:
            raise VRMInspectionError("node hierarchy contains a cycle")
        resolving.add(node_index)
        local = _node_local_matrix(nodes[node_index], node_index)
        parent_index = parents[node_index]
        world = local if parent_index is None else resolve(parent_index) @ local
        resolving.remove(node_index)
        cache[node_index] = world
        return world

    for index in range(len(nodes)):
        resolve(index)
    return cache


def _canonical_aliases(canonical_name: str, version: str) -> tuple[str, ...]:
    mapped = CANONICAL_TO_VRM_BONE_NAME.get(canonical_name)
    if mapped is None or mapped == canonical_name:
        return (canonical_name,)
    # VRM 1.0 names the first thumb joint "Metacarpal"; VRM 0.x uses the
    # historical Proximal/Intermediate names.  Prefer the version-native name
    # while retaining the other spelling as a defensive fallback.
    if version == "1.0":
        return (mapped, canonical_name)
    return (canonical_name, mapped)


def _canonical_humanoid_nodes(
    nodes: list[dict[str, Any]],
    parents: dict[int, int | None],
    world_matrices: dict[int, np.ndarray],
    human_bones: dict[str, int],
    version: str,
) -> dict[str, dict[str, Any]]:
    selected: dict[str, tuple[str, int]] = {}
    for canonical_name in _CANONICAL_HUMANOID_BONES:
        for vrm_name in _canonical_aliases(canonical_name, version):
            if vrm_name in human_bones:
                selected[canonical_name] = (vrm_name, human_bones[vrm_name])
                break

    node_to_vrm = {node_index: name for name, node_index in human_bones.items()}
    node_to_canonical = {node_index: name for name, (_, node_index) in selected.items()}
    result: dict[str, dict[str, Any]] = {}
    for canonical_name in _CANONICAL_HUMANOID_BONES:
        selection = selected.get(canonical_name)
        if selection is None:
            continue
        vrm_name, node_index = selection
        parent_index = parents[node_index]
        nearest_vrm_parent: str | None = None
        nearest_canonical_parent: str | None = None
        cursor = parent_index
        while cursor is not None:
            nearest_vrm_parent = node_to_vrm.get(cursor)
            nearest_canonical_parent = node_to_canonical.get(cursor)
            if nearest_vrm_parent is not None or nearest_canonical_parent is not None:
                break
            cursor = parents[cursor]
        node = nodes[node_index]
        parent_name = nodes[parent_index].get("name") if parent_index is not None else None
        result[canonical_name] = {
            "canonical_name": canonical_name,
            "vrm_humanoid_name": vrm_name,
            "node_index": node_index,
            "node_name": str(node.get("name") or f"node_{node_index}"),
            "parent_node_index": parent_index,
            "parent_node_name": str(parent_name or f"node_{parent_index}") if parent_index is not None else None,
            "nearest_humanoid_parent_vrm": nearest_vrm_parent,
            "nearest_humanoid_parent_canonical": nearest_canonical_parent,
            "world_position": world_matrices[node_index][:3, 3].astype(np.float32).tolist(),
        }
    if "hips" not in result:
        raise VRMInspectionError("VRM humanoid does not define a valid hips node")
    return result


def inspect_vrm_avatar(vrm_path: str | Path) -> dict[str, Any]:
    """Return the portable subset of a VRM avatar rest descriptor.

    The returned graph uses Virea's canonical bone names.  Node positions are
    glTF world-space rest positions after applying every ancestor's local TRS
    or column-major ``matrix`` transform.
    """

    path = Path(vrm_path)
    payload = _load_glb_json(path)
    version, vrm_extension = _vrm_extension(payload)
    nodes, parents = _node_graph(payload)
    human_bones = _human_bones(vrm_extension, version, len(nodes))
    world_matrices = _world_matrices(nodes, parents)
    humanoid_nodes = _canonical_humanoid_nodes(
        nodes, parents, world_matrices, human_bones, version
    )
    raw_meta = vrm_extension.get("meta")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    title = meta.get("name") if version == "1.0" else meta.get("title")
    return {
        "avatar_id": path.stem,
        "avatar_file": path.name,
        "avatar_sha256": _file_sha256(path),
        "vrm_version": version,
        "humanoid_bone_nodes": humanoid_nodes,
        "metadata": {
            "title": str(title or path.stem),
            "humanoid_bone_count": len(human_bones),
            "node_count": len(nodes),
            "human_bone_map": dict(human_bones),
            "inspector": "virea.motion.vrm_inspector.v1",
        },
    }
