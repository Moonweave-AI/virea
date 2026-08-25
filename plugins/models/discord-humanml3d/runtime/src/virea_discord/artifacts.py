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

DISCORD_SOURCE_REVISION = "782deffca1a263a2241b6321cfe6532a022f284e"
OPENAI_CLIP_REVISION = "d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"
RF_EXTERNAL_ID = "1glQFuMvWI_dKeQeS7s8V_4zdOHfIv1wS"
MOMASK_EXTERNAL_ID = "1vXS7SHJBgWPt59wupQ5UUzhFObrnGkQ0"

RF_ARTIFACT_ID = "discord-momask-rf-decoder"
MOMASK_ARTIFACT_ID = "momask-humanml3d-models"
SOURCE_ARTIFACT_ID = "discord-source"
CLIP_ARTIFACT_ID = "openai-clip-vit-b32"
RF_CHECKPOINT = "DisCoRD_Momask_RFDecoder_best.pth"
MOMASK_ARCHIVE = "humanml3d_models.zip"
SOURCE_ARCHIVE = f"{DISCORD_SOURCE_REVISION}.zip"
CLIP_CHECKPOINT = "ViT-B-32.pt"
SOURCE_PREFIX = f"DisCoRD-{DISCORD_SOURCE_REVISION}/"

VQ_NAME = "rvq_nq6_dc512_nc512_noshare_qdp0.2"
MASK_NAME = "t2m_nlayer8_nhead6_ld384_ff1024_cdp0.1_rvq6ns"
RESIDUAL_NAME = "tres_nlayer8_ld384_ff1024_rvq6ns_cdp0.2_sw"
MOMASK_MEMBERS = {
    "vq_opt": f"{VQ_NAME}/opt.txt",
    "vq_checkpoint": f"{VQ_NAME}/model/net_best_fid.tar",
    "mean": f"{VQ_NAME}/meta/mean.npy",
    "std": f"{VQ_NAME}/meta/std.npy",
    "mask_opt": f"{MASK_NAME}/opt.txt",
    "mask_checkpoint": f"{MASK_NAME}/model/latest.tar",
    "residual_opt": f"{RESIDUAL_NAME}/opt.txt",
    "residual_checkpoint": f"{RESIDUAL_NAME}/model/net_best_fid.tar",
}
REQUIRED_SOURCE_FILES = (
    "MotionGen/momask_transformer/transformer.py",
    "MotionGen/momask_transformer/tools.py",
    "MotionPriors/MotionPrior.py",
    "MotionPriors/models/rf_decoder/__init__.py",
    "MotionPriors/models/rf_decoder/DiTforflow_decoder.py",
    "MotionPriors/models/rf_decoder/helpers.py",
    "MotionPriors/models/vq/model.py",
    "MotionPriors/models/vq/encdec.py",
    "MotionPriors/models/vq/quantizer.py",
    "MotionPriors/models/vq/residual_vq.py",
    "MotionPriors/models/vq/resnet.py",
    "MotionPriors/models/rf_decoder/rectified_flow.py",
    "MotionPriors/models/rf_decoder/Unet1Dflow_decoder.py",
    "evaluation/get_opt.py",
    "utils/word_vectorizer.py",
    "configs/config_model.yaml",
    "checkpoints/Momask/configs/config_model.yaml",
)


@dataclass(frozen=True, slots=True)
class ArtifactRoots:
    rf_decoder: Path
    momask: Path
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
            rf_decoder=require(RF_ARTIFACT_ID),
            momask=require(MOMASK_ARTIFACT_ID),
            source=require(SOURCE_ARTIFACT_ID),
            clip=require(CLIP_ARTIFACT_ID),
        )


@dataclass(frozen=True, slots=True)
class MaterializedArtifacts:
    source_root: Path
    rf_checkpoint: Path
    vq_opt: Path
    vq_checkpoint: Path
    mask_opt: Path
    mask_checkpoint: Path
    residual_opt: Path
    residual_checkpoint: Path
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


def _open(path: Path, *, label: str) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise WorkerFailure(
            "MODEL_ARCHIVE_INVALID", f"cannot open {label}: {type(exc).__name__}: {exc}"
        ) from exc


def _extract_source(path: Path, target_root: Path) -> None:
    with _open(path, label="pinned DisCoRD source archive") as archive:
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
            f"pinned DisCoRD source archive is missing: {', '.join(missing)}",
        )


def materialize_artifacts(
    roots: ArtifactRoots, *, cache_root: Path
) -> MaterializedArtifacts:
    cache = cache_root.expanduser().resolve(strict=False)
    version_root = cache / "discord-humanml3d" / DISCORD_SOURCE_REVISION
    source_root = version_root / "source"
    _extract_source(
        _require_file(
            roots.source, SOURCE_ARCHIVE, label="pinned DisCoRD source archive"
        ),
        source_root,
    )
    rf_checkpoint = _require_file(
        roots.rf_decoder, RF_CHECKPOINT, label="official DisCoRD RF decoder checkpoint"
    )
    clip_checkpoint = _require_file(
        roots.clip, CLIP_CHECKPOINT, label="OpenAI CLIP ViT-B/32 checkpoint"
    )
    momask_archive = _require_file(
        roots.momask, MOMASK_ARCHIVE, label="official MoMask HumanML3D archive"
    )
    materialized: dict[str, Path] = {}
    with _open(momask_archive, label="official MoMask HumanML3D archive") as archive:
        for key, member in MOMASK_MEMBERS.items():
            try:
                info = archive.getinfo(member)
            except KeyError as exc:
                raise WorkerFailure(
                    "MODEL_ARCHIVE_INCOMPLETE",
                    f"official MoMask archive is missing: {member}",
                ) from exc
            materialized[key] = _write(
                archive, info, root=version_root / "weights", relative_name=member
            )
        # MotionPriorWrapper derives this exact official source-side config path
        # from the checkpoint. Materialize the same released VQ state there.
        vq_info = archive.getinfo(MOMASK_MEMBERS["vq_checkpoint"])
        materialized["rf_vq_checkpoint"] = _write(
            archive,
            vq_info,
            root=source_root,
            relative_name="checkpoints/Momask/checkpoints/net_best_fid.tar",
        )

    return MaterializedArtifacts(
        source_root=source_root,
        rf_checkpoint=rf_checkpoint,
        vq_opt=materialized["vq_opt"],
        vq_checkpoint=materialized["vq_checkpoint"],
        mask_opt=materialized["mask_opt"],
        mask_checkpoint=materialized["mask_checkpoint"],
        residual_opt=materialized["residual_opt"],
        residual_checkpoint=materialized["residual_checkpoint"],
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
