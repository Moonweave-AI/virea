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

ACMDM_SOURCE_REVISION = "25ed4ba22fb54d9c3e99361609ee344e7c940303"
ACMDM_MODEL_REVISION = "f7b77ecb16968afb0329a4a706978780843a1fc9"
ACMDM_AE_REVISION = "78bbd7fc5ec129a6c74812d542892939261a984f"
OPENAI_CLIP_REVISION = "d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"

MODEL_ARTIFACT_ID = "acmdm-flow-s-patchsize22"
AE_ARTIFACT_ID = "acmdm-ae-2d-causal"
SOURCE_ARTIFACT_ID = "acmdm-source"
CLIP_ARTIFACT_ID = "openai-clip-vit-b32"

MODEL_ARCHIVE = "ACMDM_Flow_S_PatchSize22.zip"
AE_ARCHIVE = "AE_2D_Causal.zip"
SOURCE_ARCHIVE = f"{ACMDM_SOURCE_REVISION}.zip"
CLIP_CHECKPOINT = "ViT-B-32.pt"

MODEL_MEMBER = "ACMDM_Flow_S_PatchSize22/model/latest.tar"
AE_MEMBER = "AE_2D_Causal/model/latest.tar"
AE_POST_MEAN_MEMBER = "AE_2D_Causal/AE_2D_Causal_Post_Mean.npy"
AE_POST_STD_MEMBER = "AE_2D_Causal/AE_2D_Causal_Post_Std.npy"
SOURCE_PREFIX = f"ACMDM-{ACMDM_SOURCE_REVISION}/"
SOURCE_FILES = (
    "LICENSE",
    "README.md",
    "models/ACMDM.py",
    "models/AE_2D_Causal.py",
    "models/ROPE.py",
    "diffusions/diffusion/__init__.py",
    "diffusions/diffusion/diffusion_utils.py",
    "diffusions/diffusion/gaussian_diffusion.py",
    "diffusions/diffusion/respace.py",
    "diffusions/transport/__init__.py",
    "diffusions/transport/integrators.py",
    "diffusions/transport/path.py",
    "diffusions/transport/transport.py",
    "diffusions/transport/utils.py",
    "utils/eval_utils.py",
    "utils/train_utils.py",
    "utils/22x3_mean_std/t2m/22x3_mean.npy",
    "utils/22x3_mean_std/t2m/22x3_std.npy",
)


@dataclass(frozen=True, slots=True)
class ArtifactRoots:
    model: Path
    autoencoder: Path
    source: Path
    clip: Path

    @classmethod
    def from_json(cls, value: str) -> ArtifactRoots:
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
            model=require(MODEL_ARTIFACT_ID),
            autoencoder=require(AE_ARTIFACT_ID),
            source=require(SOURCE_ARTIFACT_ID),
            clip=require(CLIP_ARTIFACT_ID),
        )


@dataclass(frozen=True, slots=True)
class MaterializedArtifacts:
    source_root: Path
    model_checkpoint: Path
    autoencoder_checkpoint: Path
    latent_mean: Path
    latent_std: Path
    position_mean: Path
    position_std: Path
    clip_checkpoint: Path


def _require_file(root: Path, filename: str, *, label: str) -> Path:
    canonical_root = root.resolve(strict=True)
    path = (canonical_root / filename).resolve(strict=False)
    try:
        path.relative_to(canonical_root)
    except ValueError as exc:
        raise WorkerFailure(
            "MODEL_ARTIFACT_INVALID", f"{label} path escapes its artifact root"
        ) from exc
    if not path.is_file():
        raise WorkerFailure("MODEL_ARTIFACT_INCOMPLETE", f"{label} is missing: {path}")
    return path


def _require_hf_archive(
    root: Path,
    filename: str,
    *,
    revision: str,
    label: str,
) -> Path:
    archive = _require_file(root, filename, label=label)
    metadata = root / ".cache" / "huggingface" / "download" / f"{filename}.metadata"
    try:
        actual_revision = metadata.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError) as exc:
        raise WorkerFailure(
            "MODEL_REVISION_UNVERIFIED",
            f"{label} has no Hugging Face revision metadata for {revision}",
        ) from exc
    if actual_revision != revision:
        raise WorkerFailure(
            "MODEL_REVISION_UNVERIFIED",
            f"{label} revision is {actual_revision}, expected {revision}",
        )
    return archive


def _member_target(root: Path, member: str) -> Path:
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


def _materialize_member(
    archive: zipfile.ZipFile,
    member: str,
    *,
    target_root: Path,
    output_name: str | None = None,
) -> Path:
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        raise WorkerFailure(
            "MODEL_ARCHIVE_INCOMPLETE",
            f"released archive is missing required member: {member}",
        ) from exc
    if info.is_dir():
        raise WorkerFailure(
            "MODEL_ARCHIVE_INVALID", f"required archive member is a directory: {member}"
        )
    target_root = target_root.resolve(strict=False)
    target = _member_target(target_root, output_name or member)
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
                f"materialized member length differs: {member}",
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


def materialize_artifacts(
    roots: ArtifactRoots,
    *,
    cache_root: Path,
) -> MaterializedArtifacts:
    cache = cache_root.expanduser().resolve(strict=False)
    cache.mkdir(parents=True, exist_ok=True)

    model_archive = _require_hf_archive(
        roots.model,
        MODEL_ARCHIVE,
        revision=ACMDM_MODEL_REVISION,
        label="ACMDM-S-PS22 checkpoint archive",
    )
    autoencoder_archive = _require_hf_archive(
        roots.autoencoder,
        AE_ARCHIVE,
        revision=ACMDM_AE_REVISION,
        label="ACMDM Causal-AE checkpoint archive",
    )
    source_archive = _require_file(
        roots.source,
        SOURCE_ARCHIVE,
        label="pinned ACMDM source archive",
    )
    clip_checkpoint = _require_file(
        roots.clip,
        CLIP_CHECKPOINT,
        label="OpenAI CLIP ViT-B/32 checkpoint",
    )

    version_root = cache / "acmdm-humanml3d" / ACMDM_SOURCE_REVISION
    source_root = version_root / "source"
    with _open_archive(source_archive, label="pinned ACMDM source archive") as archive:
        for relative in SOURCE_FILES:
            _materialize_member(
                archive,
                f"{SOURCE_PREFIX}{relative}",
                target_root=source_root,
                output_name=relative,
            )

    with _open_archive(
        model_archive, label="ACMDM-S-PS22 checkpoint archive"
    ) as archive:
        model_checkpoint = _materialize_member(
            archive,
            MODEL_MEMBER,
            target_root=version_root / "weights" / ACMDM_MODEL_REVISION,
        )
    with _open_archive(
        autoencoder_archive, label="ACMDM Causal-AE checkpoint archive"
    ) as archive:
        autoencoder_checkpoint = _materialize_member(
            archive,
            AE_MEMBER,
            target_root=version_root / "weights" / ACMDM_AE_REVISION,
        )
        latent_mean = _materialize_member(
            archive,
            AE_POST_MEAN_MEMBER,
            target_root=version_root / "weights" / ACMDM_AE_REVISION,
        )
        latent_std = _materialize_member(
            archive,
            AE_POST_STD_MEMBER,
            target_root=version_root / "weights" / ACMDM_AE_REVISION,
        )

    return MaterializedArtifacts(
        source_root=source_root,
        model_checkpoint=model_checkpoint,
        autoencoder_checkpoint=autoencoder_checkpoint,
        latent_mean=latent_mean,
        latent_std=latent_std,
        position_mean=(
            source_root / "utils" / "22x3_mean_std" / "t2m" / "22x3_mean.npy"
        ),
        position_std=(source_root / "utils" / "22x3_mean_std" / "t2m" / "22x3_std.npy"),
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
