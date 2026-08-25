from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from virea_contracts.model import ModelIdentity
from virea_contracts.provenance import GenerationProvenance, SourceRevision
from virea_contracts.result import (
    ArtifactRef,
    ModelResult,
    NativeMotionDescriptor,
    ValidSegment,
)

from .worker import WorkerFailure


@dataclass(frozen=True, slots=True)
class InstalledArtifactRoots:
    """Validated roots supplied by the VIREA installation supervisor.

    Model Workers must never discover checkpoints from a home directory or make an
    implicit network request.  This small boundary parses the supervisor-owned JSON,
    resolves every root, and verifies model-specific sentinel files before upstream
    code is imported.
    """

    roots: Mapping[str, Path]

    @classmethod
    def from_environment(
        cls,
        requirements: Mapping[str, Sequence[str]],
        *,
        environment_name: str = "VIREA_ARTIFACT_ROOTS_JSON",
    ) -> "InstalledArtifactRoots":
        raw = os.getenv(environment_name)
        if not raw:
            raise WorkerFailure(
                "MODEL_ARTIFACT_MISSING",
                f"{environment_name} must identify every installed artifact root",
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WorkerFailure(
                "INVALID_ARTIFACT_ROOTS",
                f"{environment_name} must contain a JSON object",
            ) from exc
        if not isinstance(payload, dict) or set(payload) != set(requirements):
            raise WorkerFailure(
                "INVALID_ARTIFACT_ROOTS",
                "installed artifact IDs differ from the pinned model manifest",
            )

        roots: dict[str, Path] = {}
        for artifact_id, sentinels in requirements.items():
            value = payload.get(artifact_id)
            if not isinstance(value, str) or not value:
                raise WorkerFailure(
                    "MODEL_ARTIFACT_MISSING",
                    f"installed artifact root is missing: {artifact_id}",
                )
            try:
                root = Path(value).expanduser().resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise WorkerFailure(
                    "MODEL_ARTIFACT_MISSING",
                    f"installed artifact root is unavailable: {artifact_id}",
                ) from exc
            if not root.is_dir():
                raise WorkerFailure(
                    "MODEL_ARTIFACT_MISSING",
                    f"installed artifact root is not a directory: {artifact_id}",
                )
            for sentinel in sentinels:
                candidate = _safe_child(root, sentinel)
                if not candidate.is_file():
                    raise WorkerFailure(
                        "MODEL_ARTIFACT_INCOMPLETE",
                        f"installed artifact is missing {artifact_id}/{sentinel}",
                    )
            roots[artifact_id] = root
        return cls(roots=roots)

    def __getitem__(self, artifact_id: str) -> Path:
        try:
            return self.roots[artifact_id]
        except KeyError as exc:
            raise WorkerFailure(
                "MODEL_ARTIFACT_MISSING",
                f"unknown installed artifact root: {artifact_id}",
            ) from exc


def _safe_child(root: Path, relative_name: str) -> Path:
    normalized = relative_name.replace("\\", "/")
    parts = tuple(part for part in normalized.split("/") if part not in {"", "."})
    if not parts or normalized.startswith("/") or ".." in parts:
        raise WorkerFailure(
            "MODEL_ARTIFACT_INVALID",
            f"artifact sentinel must be a safe relative path: {relative_name!r}",
        )
    candidate = (root / Path(*parts)).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkerFailure(
            "MODEL_ARTIFACT_INVALID",
            f"artifact sentinel escapes its root: {relative_name!r}",
        ) from exc
    return candidate


@contextmanager
def upstream_import_scope(
    source_root: Path,
    *,
    working_directory: Path | None = None,
    environment: Mapping[str, str | None] | None = None,
) -> Iterator[None]:
    """Temporarily expose a pinned upstream checkout without global leakage."""

    canonical_source = source_root.resolve(strict=True)
    canonical_working = (working_directory or source_root).resolve(strict=True)
    previous_cwd = Path.cwd()
    previous_path = list(sys.path)
    previous_environment = {key: os.environ.get(key) for key in (environment or {})}
    sys.path.insert(0, str(canonical_source))
    os.chdir(canonical_working)
    try:
        for key, value in (environment or {}).items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        os.chdir(previous_cwd)
        sys.path[:] = previous_path
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def write_generation_metadata(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def native_model_result(
    *,
    job_id: str,
    request_id: str | None,
    task: str,
    model_id: str,
    plugin_version: str,
    runtime_id: str,
    upstream_repository: str,
    upstream_revision: str,
    artifact_manifest_id: str,
    representation_id: str,
    skeleton_id: str,
    fps: float,
    frame_count: int,
    coordinate_system: str,
    units: str,
    root_translation_semantics: str,
    root_rotation_semantics: str,
    artifacts: Sequence[ArtifactRef],
    seed: int | None,
    precision: str,
    device: str,
    generation_parameters: Mapping[str, Any],
    sources: Sequence[SourceRevision],
    warnings: Sequence[str] = (),
) -> ModelResult:
    """Build the common immutable result envelope for upstream model Workers."""

    return ModelResult(
        job_id=job_id,
        model=ModelIdentity(
            id=model_id,
            plugin_version=plugin_version,
            upstream_repository=upstream_repository,
            upstream_revision=upstream_revision,
            runtime_id=runtime_id,
            artifact_manifest_id=artifact_manifest_id,
        ),
        task=task,
        request_id=request_id,
        native=NativeMotionDescriptor(
            representation_id=representation_id,
            skeleton_id=skeleton_id,
            fps=fps,
            frame_count=frame_count,
            coordinate_system=coordinate_system,
            units=units,
            root_translation_semantics=root_translation_semantics,
            root_rotation_semantics=root_rotation_semantics,
            artifacts=tuple(artifacts),
        ),
        segments=(ValidSegment(start_frame=0, end_frame=frame_count),),
        warnings=tuple(warnings),
        provenance=GenerationProvenance(
            seed=seed,
            precision=precision,
            device=device,
            generation_parameters=dict(generation_parameters),
            sources=tuple(sources),
        ),
    )
