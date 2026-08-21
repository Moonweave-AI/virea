from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from virea_model_sdk import WorkerFailure

CMDM_SOURCE_REVISION = "7fac27ecd78365115db5c29937f20889c318d79d"
CMDM_MODEL_REVISION = "be818de05ee83018d25dfeb9fbcd3fadddf4ccd8"
DISTILBERT_REVISION = "12040accade4e8a0f71eabdb258fecc2e7e948be"
HUMANML3D_REVISION = "9176e8fb446b71c7d2a725eb5cf6fec1ae3b3c23"

CHECKPOINT_ARTIFACT_ID = "cmdm-humanml3d-checkpoints"
SOURCE_ARTIFACT_ID = "cmdm-source"
TEXT_ENCODER_ARTIFACT_ID = "cmdm-distilbert-base-uncased"
MEAN_ARTIFACT_ID = "cmdm-humanml3d-mean"
STD_ARTIFACT_ID = "cmdm-humanml3d-std"

DIT_CONFIG = "checkpoints/t2m/pretrained_dit/config.yaml"
DIT_CHECKPOINT = "checkpoints/t2m/pretrained_dit/model/latest.tar"
VAE_CONFIG = "checkpoints/t2m/pretrained_vae/config.yaml"
VAE_CHECKPOINT = "checkpoints/t2m/pretrained_vae/model/net_best_fid.tar"
DISTILBERT_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
)
SOURCE_FILES = (
    "LICENSE.txt",
    "NOTICE.txt",
    "models/BERT/BERT_encoder.py",
    "models/Causal_DiT.py",
    "models/Transformer.py",
    "models/VAE.py",
    "diffusions/transport/__init__.py",
    "diffusions/transport/integrators.py",
    "diffusions/transport/path.py",
    "diffusions/transport/transport.py",
    "diffusions/transport/utils.py",
)


@dataclass(frozen=True, slots=True)
class ArtifactRoots:
    checkpoints: Path
    source: Path
    text_encoder: Path
    mean: Path
    std: Path

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
            checkpoints=require(CHECKPOINT_ARTIFACT_ID),
            source=require(SOURCE_ARTIFACT_ID),
            text_encoder=require(TEXT_ENCODER_ARTIFACT_ID),
            mean=require(MEAN_ARTIFACT_ID),
            std=require(STD_ARTIFACT_ID),
        )


@dataclass(frozen=True, slots=True)
class MaterializedArtifacts:
    source_root: Path
    dit_config: Path
    dit_checkpoint: Path
    vae_config: Path
    vae_checkpoint: Path
    text_encoder_root: Path
    mean: Path
    std: Path


def _require_file(root: Path, relative: str, *, label: str) -> Path:
    canonical_root = root.resolve(strict=True)
    candidate = (canonical_root / relative).resolve(strict=False)
    try:
        candidate.relative_to(canonical_root)
    except ValueError as exc:
        raise WorkerFailure(
            "MODEL_ARTIFACT_INVALID", f"{label} path escapes its artifact root"
        ) from exc
    if not candidate.is_file():
        raise WorkerFailure(
            "MODEL_ARTIFACT_INCOMPLETE", f"{label} is missing: {candidate}"
        )
    return candidate


def _require_hf_file(
    root: Path,
    relative: str,
    *,
    revision: str,
    label: str,
) -> Path:
    candidate = _require_file(root, relative, label=label)
    metadata = (
        root / ".cache" / "huggingface" / "download" / Path(f"{relative}.metadata")
    )
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
    return candidate


def materialize_artifacts(roots: ArtifactRoots) -> MaterializedArtifacts:
    for relative in SOURCE_FILES:
        _require_file(roots.source, relative, label=f"pinned CMDM source {relative}")
    for relative in DISTILBERT_FILES:
        _require_hf_file(
            roots.text_encoder,
            relative,
            revision=DISTILBERT_REVISION,
            label=f"pinned DistilBERT file {relative}",
        )

    return MaterializedArtifacts(
        source_root=roots.source.resolve(strict=True),
        dit_config=_require_hf_file(
            roots.checkpoints,
            DIT_CONFIG,
            revision=CMDM_MODEL_REVISION,
            label="CMDM Causal-DiT config",
        ),
        dit_checkpoint=_require_hf_file(
            roots.checkpoints,
            DIT_CHECKPOINT,
            revision=CMDM_MODEL_REVISION,
            label="CMDM Causal-DiT checkpoint",
        ),
        vae_config=_require_hf_file(
            roots.checkpoints,
            VAE_CONFIG,
            revision=CMDM_MODEL_REVISION,
            label="CMDM MAC-VAE config",
        ),
        vae_checkpoint=_require_hf_file(
            roots.checkpoints,
            VAE_CHECKPOINT,
            revision=CMDM_MODEL_REVISION,
            label="CMDM MAC-VAE checkpoint",
        ),
        text_encoder_root=roots.text_encoder.resolve(strict=True),
        mean=_require_file(roots.mean, "Mean.npy", label="HumanML3D mean"),
        std=_require_file(roots.std, "Std.npy", label="HumanML3D std"),
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
