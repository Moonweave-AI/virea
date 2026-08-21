from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from virea_model_sdk import WorkerFailure

SOURCE_REPOSITORY = "https://github.com/ZeyuLing/PRISM"
SOURCE_REVISION = "3c58bc5d946f0827171a3712ed36314f4b1a5186"
MODEL_REPOSITORY = "ZeyuLing/PRISM-TP2M-1.4B"
MODEL_REVISION = "825daaa27f4f3845eb0978674c3acb378a12cda6"
TOKENIZER_REPOSITORY = "google/umt5-xxl"
TOKENIZER_REVISION = "66cb9e7e85526fe440a945569e42c72fb6cbc0ad"
STATS_REPOSITORY = "ZeyuLing/MotionHub"
STATS_REVISION = "c3f6c8eb8a4ba9e5ca521cdc0af9264756b66726"
STATS_MEMBER = "statistics/smplh_universal_stats_aug.json"

SOURCE_ARTIFACT_ID = "prism-source"
MODEL_ARTIFACT_ID = "prism-tp2m-1-4b-official-hf"
TOKENIZER_ARTIFACT_ID = "prism-umt5-xxl-tokenizer"
STATS_ARTIFACT_ID = "prism-motionhub-smplh-stats"

SOURCE_REQUIRED_FILES = (
    "prism/registry.py",
    "prism/pipelines/prism_ar_t2m_pipeline.py",
    "prism/models/autoencoders/__init__.py",
    "prism/models/transformers/motion_prism/transformer_prism.py",
    "prism/utils/geometry/rotation_convert.py",
)
MODEL_REQUIRED_FILES = (
    "config.json",
    "text_encoder/config.json",
    "text_encoder/model.safetensors",
    "transformer/config.json",
    "transformer/model.safetensors",
    "vae/config.json",
    "vae/model.safetensors",
)
TOKENIZER_REQUIRED_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "spiece.model",
)


def _require_tree(root: Path, files: tuple[str, ...], label: str) -> Path:
    resolved = root.expanduser().resolve(strict=False)
    if not resolved.is_dir():
        raise WorkerFailure(
            "ARTIFACT_INCOMPLETE", f"{label} is not a directory: {resolved}"
        )
    missing = [name for name in files if not (resolved / name).is_file()]
    if missing:
        raise WorkerFailure(
            "ARTIFACT_INCOMPLETE",
            f"{label} is incomplete; missing: {', '.join(missing)}",
        )
    return resolved


def _resolve_stats_file(root: Path) -> Path:
    candidates = (
        root / "smplh_universal_stats_aug.json",
        root / STATS_MEMBER,
        root / "stats.json",
    )
    matches = [path.resolve(strict=True) for path in candidates if path.is_file()]
    if len(matches) != 1:
        raise WorkerFailure(
            "ARTIFACT_INCOMPLETE",
            "MotionHub statistics root must contain exactly one supported stats file",
        )
    return matches[0]


@dataclass(frozen=True, slots=True)
class PrismArtifactRoots:
    source: Path
    model: Path
    tokenizer: Path
    statistics: Path

    @classmethod
    def from_json(cls, payload: str) -> "PrismArtifactRoots":
        try:
            values = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise WorkerFailure(
                "INVALID_ARTIFACT_ROOTS", "VIREA_ARTIFACT_ROOTS_JSON is invalid JSON"
            ) from exc
        if not isinstance(values, dict):
            raise WorkerFailure(
                "INVALID_ARTIFACT_ROOTS", "artifact roots must be a JSON object"
            )
        expected = {
            SOURCE_ARTIFACT_ID,
            MODEL_ARTIFACT_ID,
            TOKENIZER_ARTIFACT_ID,
            STATS_ARTIFACT_ID,
        }
        actual = set(values)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing or unexpected:
            details: list[str] = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if unexpected:
                details.append("unexpected: " + ", ".join(unexpected))
            raise WorkerFailure(
                "INVALID_ARTIFACT_ROOTS",
                "artifact root map must contain exactly the manifest artifacts; "
                + "; ".join(details),
            )
        return cls(
            source=Path(str(values[SOURCE_ARTIFACT_ID])),
            model=Path(str(values[MODEL_ARTIFACT_ID])),
            tokenizer=Path(str(values[TOKENIZER_ARTIFACT_ID])),
            statistics=Path(str(values[STATS_ARTIFACT_ID])),
        )

    def validate(self) -> "ValidatedPrismArtifacts":
        source = _require_tree(
            self.source, SOURCE_REQUIRED_FILES, "pinned PRISM source"
        )
        model = _require_tree(self.model, MODEL_REQUIRED_FILES, "PRISM checkpoint")
        tokenizer = _require_tree(
            self.tokenizer, TOKENIZER_REQUIRED_FILES, "pinned UMT5 tokenizer"
        )
        statistics_root = self.statistics.expanduser().resolve(strict=False)
        if not statistics_root.is_dir():
            raise WorkerFailure(
                "ARTIFACT_INCOMPLETE",
                f"MotionHub statistics root is not a directory: {statistics_root}",
            )
        return ValidatedPrismArtifacts(
            source=source,
            model=model,
            tokenizer=tokenizer,
            statistics=_resolve_stats_file(statistics_root),
        )


@dataclass(frozen=True, slots=True)
class ValidatedPrismArtifacts:
    source: Path
    model: Path
    tokenizer: Path
    statistics: Path


def artifact_roots_from_environment() -> PrismArtifactRoots:
    payload = os.getenv("VIREA_ARTIFACT_ROOTS_JSON")
    if not payload:
        raise WorkerFailure(
            "INVALID_ARTIFACT_ROOTS",
            "VIREA_ARTIFACT_ROOTS_JSON must identify all external PRISM assets",
        )
    return PrismArtifactRoots.from_json(payload)
