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

REMOMASK_SOURCE_REVISION = "630eda1f825bcc2ffb613a7270e1f5b6ac8baea2"
REMOMASK_MODEL_REVISION = "e4b8dd8479e70cbe16015024e0ccbe55d923a7ab"
OPENAI_CLIP_REVISION = "d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"

MODEL_ARTIFACT_ID = "remomask-models-database-and-clip"
SOURCE_ARTIFACT_ID = "remomask-source"
SOURCE_ARCHIVE = f"{REMOMASK_SOURCE_REVISION}.zip"
SOURCE_PREFIX = f"ReMoMask-{REMOMASK_SOURCE_REVISION}/"

MODEL_FILES = {
    "vq_opt": "logs/humanml3d/pretrain_vq/opt.txt",
    "vq_checkpoint": "logs/humanml3d/pretrain_vq/model/net_best_fid.tar",
    "mean": "logs/humanml3d/pretrain_vq/meta/mean.npy",
    "std": "logs/humanml3d/pretrain_vq/meta/std.npy",
    "mask_opt": "logs/humanml3d/pretrain_mtrans/opt.txt",
    "mask_checkpoint": "logs/humanml3d/pretrain_mtrans/model/net_best_fid.tar",
    "residual_opt": "logs/humanml3d/pretrain_rtrans/opt.txt",
    "residual_checkpoint": "logs/humanml3d/pretrain_rtrans/model/net_best_fid.tar",
    "length_checkpoint": "checkpoints/humanml3d/length_estimator/model/finest.tar",
    "retriever_config": "Part_TMR/checkpoints/exp_for_mtrans/HumanML3D/.hydra/config.yaml",
    "retriever_checkpoint": "Part_TMR/checkpoints/exp_for_mtrans/HumanML3D/best_model.pt",
    "clip_checkpoint": "ViT-B-32.pt",
    "database_motion_ids": "database/motion_ids.npy",
    "database_captions": "database/all_captions.npy",
    "database_motion_features": "database/encoded_motions.npy",
    "database_text_features": "database/encoded_texts.npy",
}
REQUIRED_SOURCE_FILES = (
    "models/vq/model.py",
    "models/vq/encdec.py",
    "models/vq/quantizer.py",
    "models/vq/residual_vq.py",
    "models/vq/resnet.py",
    "models/transformer/transformer_aux.py",
    "models/transformer/transformer_ts.py",
    "models/transformer/tools.py",
    "models/transformer/semantics_modulated.py",
    "utils/get_opt.py",
    "utils/word_vectorizer.py",
)


@dataclass(frozen=True, slots=True)
class ArtifactRoots:
    models: Path
    source: Path

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
        )


@dataclass(frozen=True, slots=True)
class MaterializedArtifacts:
    source_root: Path
    vq_opt: Path
    vq_checkpoint: Path
    mean: Path
    std: Path
    mask_opt: Path
    mask_checkpoint: Path
    residual_opt: Path
    residual_checkpoint: Path
    length_checkpoint: Path
    retriever_config: Path
    retriever_checkpoint: Path
    clip_checkpoint: Path
    database_root: Path


def _require_file(root: Path, filename: str, *, label: str) -> Path:
    path = (root / Path(*PurePosixPath(filename).parts)).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkerFailure(
            "MODEL_ARTIFACT_INVALID", f"{label} path escapes its artifact root"
        ) from exc
    if not path.is_file():
        raise WorkerFailure("MODEL_ARTIFACT_INCOMPLETE", f"{label} is missing: {path}")
    return path


def _require_hf_file(root: Path, filename: str, *, revision: str, label: str) -> Path:
    path = _require_file(root, filename, label=label)
    metadata = root / ".cache" / "huggingface" / "download" / f"{filename}.metadata"
    try:
        actual = metadata.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError) as exc:
        raise WorkerFailure(
            "MODEL_REVISION_UNVERIFIED",
            f"{label} has no Hugging Face revision metadata for {revision}",
        ) from exc
    if actual != revision:
        raise WorkerFailure(
            "MODEL_REVISION_UNVERIFIED",
            f"{label} revision is {actual}, expected {revision}",
        )
    return path


def _target(root: Path, relative_name: str) -> Path:
    relative = PurePosixPath(relative_name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise WorkerFailure(
            "MODEL_ARCHIVE_INVALID", f"invalid archive member path: {relative_name!r}"
        )
    target = (root / Path(*relative.parts)).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise WorkerFailure(
            "MODEL_ARCHIVE_INVALID", f"archive member escapes cache: {relative_name!r}"
        ) from exc
    return target


def _write(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, *, root: Path, relative_name: str
) -> Path:
    target = _target(root, relative_name)
    if target.is_file() and target.stat().st_size == info.file_size:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.part-{os.getpid()}-{uuid.uuid4().hex}"
    )
    try:
        with archive.open(info) as source, temporary.open("xb") as sink:
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


def _extract_source(path: Path, target_root: Path) -> None:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise WorkerFailure(
            "MODEL_ARCHIVE_INVALID",
            f"cannot open pinned ReMoMask source archive: {type(exc).__name__}: {exc}",
        ) from exc
    with archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(SOURCE_PREFIX):
                continue
            relative = info.filename[len(SOURCE_PREFIX) :]
            if relative:
                _write(archive, info, root=target_root, relative_name=relative)
    missing = [
        name for name in REQUIRED_SOURCE_FILES if not (target_root / name).is_file()
    ]
    if missing:
        raise WorkerFailure(
            "MODEL_ARCHIVE_INCOMPLETE",
            f"pinned ReMoMask source archive is missing: {', '.join(missing)}",
        )


def materialize_artifacts(
    roots: ArtifactRoots, *, cache_root: Path
) -> MaterializedArtifacts:
    version_root = (
        cache_root.expanduser().resolve(strict=False)
        / "remomask-humanml3d"
        / REMOMASK_SOURCE_REVISION
    )
    source_root = version_root / "source"
    _extract_source(
        _require_file(
            roots.source, SOURCE_ARCHIVE, label="pinned ReMoMask source archive"
        ),
        source_root,
    )
    files = {
        key: _require_hf_file(
            roots.models,
            filename,
            revision=REMOMASK_MODEL_REVISION,
            label=f"ReMoMask {key}",
        )
        for key, filename in MODEL_FILES.items()
    }
    return MaterializedArtifacts(
        source_root=source_root,
        vq_opt=files["vq_opt"],
        vq_checkpoint=files["vq_checkpoint"],
        mean=files["mean"],
        std=files["std"],
        mask_opt=files["mask_opt"],
        mask_checkpoint=files["mask_checkpoint"],
        residual_opt=files["residual_opt"],
        residual_checkpoint=files["residual_checkpoint"],
        length_checkpoint=files["length_checkpoint"],
        retriever_config=files["retriever_config"],
        retriever_checkpoint=files["retriever_checkpoint"],
        clip_checkpoint=files["clip_checkpoint"],
        database_root=files["database_motion_ids"].parent,
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
