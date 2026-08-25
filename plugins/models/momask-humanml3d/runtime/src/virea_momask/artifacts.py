from __future__ import annotations

import json
import os
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from virea_model_sdk import WorkerFailure

MOMASK_SOURCE_REVISION = "94a6636c9c463b7a9414c3401a6f1b67e6c51824"
OPENAI_CLIP_REVISION = "d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"

MODEL_ARTIFACT_ID = "momask-humanml3d-models"
SOURCE_ARTIFACT_ID = "momask-source"
CLIP_ARTIFACT_ID = "openai-clip-vit-b32"

MODEL_ARCHIVE = "humanml3d_models.zip"
SOURCE_ARCHIVE = f"{MOMASK_SOURCE_REVISION}.zip"
CLIP_CHECKPOINT = "ViT-B-32.pt"
SOURCE_PREFIX = f"momask-codes-{MOMASK_SOURCE_REVISION}/"

VQ_NAME = "rvq_nq6_dc512_nc512_noshare_qdp0.2"
MASK_NAME = "t2m_nlayer8_nhead6_ld384_ff1024_cdp0.1_rvq6ns"
RESIDUAL_NAME = "tres_nlayer8_ld384_ff1024_rvq6ns_cdp0.2_sw"

MODEL_MEMBERS = {
    "vq_opt": f"{VQ_NAME}/opt.txt",
    "vq_checkpoint": f"{VQ_NAME}/model/net_best_fid.tar",
    "mean": f"{VQ_NAME}/meta/mean.npy",
    "std": f"{VQ_NAME}/meta/std.npy",
    "mask_opt": f"{MASK_NAME}/opt.txt",
    "mask_checkpoint": f"{MASK_NAME}/model/latest.tar",
    "residual_opt": f"{RESIDUAL_NAME}/opt.txt",
    "residual_checkpoint": f"{RESIDUAL_NAME}/model/net_best_fid.tar",
    "length_checkpoint": "length_estimator/model/finest.tar",
}

REQUIRED_SOURCE_FILES = (
    "models/mask_transformer/transformer.py",
    "models/mask_transformer/tools.py",
    "models/vq/model.py",
    "models/vq/encdec.py",
    "models/vq/quantizer.py",
    "models/vq/residual_vq.py",
    "models/vq/resnet.py",
    "utils/get_opt.py",
    "utils/word_vectorizer.py",
)


@dataclass(frozen=True, slots=True)
class ArtifactRoots:
    models: Path
    source: Path
    clip: Path

    @classmethod
    def from_json(cls, value: str) -> "ArtifactRoots":
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkerFailure(
                "INVALID_ARTIFACT_ROOTS",
                "VIREA_ARTIFACT_ROOTS_JSON must contain a JSON object",
            ) from exc
        if not isinstance(payload, dict):
            raise WorkerFailure(
                "INVALID_ARTIFACT_ROOTS",
                "VIREA_ARTIFACT_ROOTS_JSON must contain a JSON object",
            )

        def require(identifier: str) -> Path:
            raw = payload.get(identifier)
            if not isinstance(raw, str) or not raw:
                raise WorkerFailure(
                    "MODEL_ARTIFACT_MISSING",
                    f"installed artifact root is missing: {identifier}",
                )
            path = Path(raw).expanduser().resolve(strict=False)
            if not path.is_dir():
                raise WorkerFailure(
                    "MODEL_ARTIFACT_MISSING",
                    f"installed artifact root is not a directory: {identifier}: {path}",
                )
            return path

        return cls(
            models=require(MODEL_ARTIFACT_ID),
            source=require(SOURCE_ARTIFACT_ID),
            clip=require(CLIP_ARTIFACT_ID),
        )


@dataclass(frozen=True, slots=True)
class MaterializedArtifacts:
    source_root: Path
    vq_opt: Path
    vq_checkpoint: Path
    mask_opt: Path
    mask_checkpoint: Path
    residual_opt: Path
    residual_checkpoint: Path
    length_checkpoint: Path
    mean: Path
    std: Path
    clip_checkpoint: Path


def _require_file(root: Path, filename: str, *, label: str) -> Path:
    path = (root / filename).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkerFailure(
            "MODEL_ARTIFACT_INVALID", f"{label} path escapes its artifact root"
        ) from exc
    if not path.is_file():
        raise WorkerFailure("MODEL_ARTIFACT_INCOMPLETE", f"{label} is missing: {path}")
    return path


def _target_for_member(root: Path, member: str) -> Path:
    relative = PurePosixPath(member)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise WorkerFailure(
            "MODEL_ARCHIVE_INVALID", f"invalid archive member path: {member!r}"
        )
    target = (root / Path(*relative.parts)).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise WorkerFailure(
            "MODEL_ARCHIVE_INVALID", f"archive member escapes cache: {member!r}"
        ) from exc
    return target


def _write_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    target_root: Path,
    relative_name: str,
) -> Path:
    target = _target_for_member(target_root, relative_name)
    if target.is_file() and target.stat().st_size == info.file_size:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.part-{os.getpid()}-{uuid.uuid4().hex}"
    )
    try:
        with archive.open(info, mode="r") as source, temporary.open(mode="xb") as sink:
            shutil.copyfileobj(source, sink, length=8 * 1024 * 1024)
        if temporary.stat().st_size != info.file_size:
            raise WorkerFailure(
                "MODEL_ARCHIVE_INCOMPLETE",
                f"materialized member length differs: {info.filename}",
            )
        try:
            os.replace(temporary, target)
        except OSError:
            if not target.is_file() or target.stat().st_size != info.file_size:
                raise
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return target


def _open_archive(path: Path, *, label: str) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path, mode="r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise WorkerFailure(
            "MODEL_ARCHIVE_INVALID", f"cannot open {label}: {type(exc).__name__}: {exc}"
        ) from exc


def _extract_source(archive_path: Path, target_root: Path) -> None:
    with _open_archive(archive_path, label="pinned MoMask source archive") as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(SOURCE_PREFIX):
                continue
            relative = info.filename[len(SOURCE_PREFIX) :]
            if relative:
                _write_member(
                    archive, info, target_root=target_root, relative_name=relative
                )
    missing = [
        name for name in REQUIRED_SOURCE_FILES if not (target_root / name).is_file()
    ]
    if missing:
        raise WorkerFailure(
            "MODEL_ARCHIVE_INCOMPLETE",
            f"pinned MoMask source archive is missing: {', '.join(missing)}",
        )


def materialize_artifacts(
    roots: ArtifactRoots,
    *,
    cache_root: Path,
) -> MaterializedArtifacts:
    cache = cache_root.expanduser().resolve(strict=False)
    version_root = cache / "momask-humanml3d" / MOMASK_SOURCE_REVISION
    source_root = version_root / "source"
    source_archive = _require_file(
        roots.source, SOURCE_ARCHIVE, label="pinned MoMask source archive"
    )
    model_archive = _require_file(
        roots.models, MODEL_ARCHIVE, label="official HumanML3D model archive"
    )
    clip_checkpoint = _require_file(
        roots.clip, CLIP_CHECKPOINT, label="OpenAI CLIP ViT-B/32 checkpoint"
    )
    _extract_source(source_archive, source_root)

    materialized: dict[str, Path] = {}
    with _open_archive(
        model_archive, label="official HumanML3D model archive"
    ) as archive:
        for key, member in MODEL_MEMBERS.items():
            try:
                info = archive.getinfo(member)
            except KeyError as exc:
                raise WorkerFailure(
                    "MODEL_ARCHIVE_INCOMPLETE",
                    f"official HumanML3D model archive is missing: {member}",
                ) from exc
            if info.is_dir():
                raise WorkerFailure(
                    "MODEL_ARCHIVE_INVALID", f"required member is a directory: {member}"
                )
            materialized[key] = _write_member(
                archive,
                info,
                target_root=version_root / "weights",
                relative_name=member,
            )

    return MaterializedArtifacts(
        source_root=source_root,
        vq_opt=materialized["vq_opt"],
        vq_checkpoint=materialized["vq_checkpoint"],
        mask_opt=materialized["mask_opt"],
        mask_checkpoint=materialized["mask_checkpoint"],
        residual_opt=materialized["residual_opt"],
        residual_checkpoint=materialized["residual_checkpoint"],
        length_checkpoint=materialized["length_checkpoint"],
        mean=materialized["mean"],
        std=materialized["std"],
        clip_checkpoint=clip_checkpoint,
    )


def artifact_roots_from_environment(
    environment: dict[str, Any] | None = None,
) -> ArtifactRoots:
    values = os.environ if environment is None else environment
    raw = values.get("VIREA_ARTIFACT_ROOTS_JSON")
    if not isinstance(raw, str) or not raw:
        raise WorkerFailure(
            "MODEL_ARTIFACTS_NOT_CONFIGURED",
            "VIREA_ARTIFACT_ROOTS_JSON must identify the installed artifact roots",
        )
    return ArtifactRoots.from_json(raw)
