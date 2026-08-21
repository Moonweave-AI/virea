from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from virea_contracts.model import ModelIdentity
from virea_contracts.provenance import GenerationProvenance, SourceRevision
from virea_contracts.result import (
    ArtifactRef,
    ModelResult,
    NativeMotionDescriptor,
    ValidSegment,
)
from virea_contracts.worker import WorkerInferRequest, WorkerMetadata
from virea_model_sdk import (
    ResourceObservationUnavailable,
    WorkerContext,
    WorkerFailure,
    serve_plugin,
)

from .backend import (
    CHECKPOINT_REVISION,
    CLIP_REVISION,
    DEFAULT_GUIDANCE_SCALE,
    DEFAULT_MASK_STEPS,
    FEATURE_DIM,
    FPS,
    MAX_FRAMES,
    SOURCE_REVISION,
    UNIT_LENGTH,
    MoMADiffBackend,
    MoMADiffPaths,
)

MODEL_ID = "momadiff-humanml3d"
PLUGIN_VERSION = "0.1.0"
RUNTIME_ID = "momadiff-humanml3d-cu128"
REPRESENTATION_ID = "humanml3d.vector263.v1"
SKELETON_ID = "humanml3d.body22.v1"
SOURCE_REPOSITORY = "https://github.com/zzysteve/MoMADiff"
CHECKPOINT_REPOSITORY = "SteveZh/momadiff_models"
CLIP_REPOSITORY = "https://github.com/openai/CLIP"
SOURCE_ARTIFACT_ID = "momadiff-upstream-source"
CHECKPOINT_ARTIFACT_ID = "momadiff-humanml3d-checkpoints"
CLIP_ARTIFACT_ID = "openai-clip-vit-b-32"
ARTIFACT_MANIFEST_ID = "momadiff-humanml3d-pinned-bundle"


def artifact_paths_from_json(payload: str) -> MoMADiffPaths:
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise WorkerFailure(
            "INVALID_RUNTIME_CONFIGURATION",
            "VIREA_ARTIFACT_ROOTS_JSON is not valid JSON",
        ) from exc
    if not isinstance(decoded, dict):
        raise WorkerFailure(
            "INVALID_RUNTIME_CONFIGURATION",
            "VIREA_ARTIFACT_ROOTS_JSON must contain an artifact-id mapping",
        )
    required = {
        SOURCE_ARTIFACT_ID,
        CHECKPOINT_ARTIFACT_ID,
        CLIP_ARTIFACT_ID,
    }
    missing = sorted(required - set(decoded))
    if missing:
        raise WorkerFailure(
            "MODEL_SNAPSHOT_INCOMPLETE",
            "installed MoMADiff bundle is missing artifact roots: "
            + ", ".join(missing),
        )
    roots: dict[str, Path] = {}
    for artifact_id in required:
        value = decoded[artifact_id]
        if not isinstance(value, str) or not value.strip():
            raise WorkerFailure(
                "INVALID_RUNTIME_CONFIGURATION",
                f"artifact root {artifact_id!r} must be a non-empty path",
            )
        roots[artifact_id] = Path(value).expanduser()
    return MoMADiffPaths(
        source_root=roots[SOURCE_ARTIFACT_ID],
        checkpoint_root=roots[CHECKPOINT_ARTIFACT_ID],
        clip_root=roots[CLIP_ARTIFACT_ID],
    )


def artifact_paths_from_environment() -> MoMADiffPaths:
    payload = os.getenv("VIREA_ARTIFACT_ROOTS_JSON")
    if not payload:
        raise WorkerFailure(
            "INVALID_RUNTIME_CONFIGURATION",
            "VIREA_ARTIFACT_ROOTS_JSON must identify the installed pinned artifacts",
        )
    return artifact_paths_from_json(payload)


def _require_int(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be an integer") from exc
    if parsed != value or parsed < minimum or parsed > maximum:
        raise WorkerFailure(
            "INVALID_REQUEST", f"{name} must be an integer in [{minimum}, {maximum}]"
        )
    return parsed


def _require_float(value: Any, *, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be numeric") from exc
    if not np.isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise WorkerFailure(
            "INVALID_REQUEST", f"{name} must be in [{minimum:g}, {maximum:g}]"
        )
    return parsed


def _resolve_motion_length_frames(
    *,
    input_frames: Any,
    seconds: Any,
    fps: float,
) -> int | None:
    motion_length_frames = (
        None
        if input_frames is None
        else _require_int(
            input_frames,
            name="input.motion_length_frames",
            minimum=UNIT_LENGTH,
            maximum=MAX_FRAMES,
        )
    )
    if motion_length_frames is not None and motion_length_frames % UNIT_LENGTH:
        raise WorkerFailure(
            "INVALID_REQUEST",
            "input.motion_length_frames must be a multiple of four",
        )
    if seconds is None:
        return motion_length_frames

    requested_seconds = _require_float(
        seconds,
        name="seconds",
        minimum=UNIT_LENGTH / FPS,
        maximum=MAX_FRAMES / FPS,
    )
    requested_frames_float = requested_seconds * fps
    requested_frames = int(round(requested_frames_float))
    if abs(requested_frames_float - requested_frames) > 1e-6:
        raise WorkerFailure(
            "INVALID_REQUEST",
            "seconds * fps must produce an integer frame count",
        )
    if requested_frames % UNIT_LENGTH:
        raise WorkerFailure(
            "INVALID_REQUEST",
            "seconds * fps must produce a frame count divisible by four",
        )
    if motion_length_frames is not None and motion_length_frames != requested_frames:
        raise WorkerFailure(
            "INVALID_REQUEST",
            "input.motion_length_frames and parameters.seconds disagree",
        )
    return requested_frames


class MoMADiffHumanML3DPlugin:
    def __init__(self, paths: MoMADiffPaths, *, model_id: str = MODEL_ID) -> None:
        if model_id != MODEL_ID:
            raise WorkerFailure(
                "INVALID_MODEL_ID",
                f"this worker serves only {MODEL_ID!r}, not {model_id!r}",
            )
        self.model_id = model_id
        self.paths = paths
        self._backend: MoMADiffBackend | None = None
        self._device_facts: dict[str, Any] = {}

    @property
    def memory_strategy(self) -> str:
        return os.getenv("VIREA_MEMORY_STRATEGY", "cuda_full").strip()

    def metadata(self) -> WorkerMetadata:
        return WorkerMetadata(
            model_id=self.model_id,
            plugin_version=PLUGIN_VERSION,
            tasks=("text_to_motion",),
            input_schemas=("virea.job_request.v1.0.0",),
            output_representation_id=REPRESENTATION_ID,
            output_skeleton_id=SKELETON_ID,
            supports_streaming=False,
            supports_cancel=True,
            resources={
                "memory_strategies": ["cuda_full", "cpu"],
                "active_memory_strategy": self.memory_strategy,
                "resource_profile": os.getenv("VIREA_RESOURCE_PROFILE", "cuda-full"),
                "source_revision": SOURCE_REVISION,
                "checkpoint_repository": CHECKPOINT_REPOSITORY,
                "checkpoint_revision": CHECKPOINT_REVISION,
                "clip_revision": CLIP_REVISION,
                "native_feature_dim": FEATURE_DIM,
                "native_fps": FPS,
                "max_motion_frames": MAX_FRAMES,
                "cancel_semantics": (
                    "checked_before_and_after_non_preemptive_model_inference"
                ),
                **self._device_facts,
            },
        )

    def load(self) -> None:
        strategy = self.memory_strategy
        if strategy not in {"cuda_full", "cpu"}:
            raise WorkerFailure(
                "UNSUPPORTED_MEMORY_STRATEGY",
                "MoMADiff implements only cuda_full and whole-model cpu execution",
            )
        try:
            backend = MoMADiffBackend(self.paths, memory_strategy=strategy)
            backend.load()
            self._backend = backend
            self._device_facts = dict(backend.device_facts)
        except (FileNotFoundError, ValueError) as exc:
            self.unload()
            raise WorkerFailure(
                "MODEL_SNAPSHOT_INCOMPLETE",
                f"pinned MoMADiff artifacts are unusable: {exc}",
            ) from exc
        except ResourceObservationUnavailable as exc:
            self.unload()
            raise WorkerFailure("RESOURCE_OBSERVATION_UNAVAILABLE", str(exc)) from exc
        except WorkerFailure:
            raise
        except Exception as exc:
            self.unload()
            raise WorkerFailure(
                "MODEL_LOAD_FAILED",
                f"failed to load pinned MoMADiff artifacts: {type(exc).__name__}: {exc}",
            ) from exc

    def unload(self) -> None:
        if self._backend is not None:
            self._backend.unload()
            self._backend = None

    def cancel(self, job_id: str) -> None:
        # The official generate call has no safe mid-step cancellation hook.
        # VIREA can terminate this isolated per-job Worker process after its
        # cooperative cancellation boundary has been crossed.
        return None

    def infer(self, request: WorkerInferRequest, context: WorkerContext) -> ModelResult:
        context.raise_if_cancelled()
        backend = self._backend
        if backend is None:
            raise WorkerFailure(
                "MODEL_NOT_LOADED", "model is not loaded", retryable=True
            )
        if request.request.model_id != self.model_id:
            raise WorkerFailure(
                "INVALID_MODEL_ID",
                f"request targets {request.request.model_id!r}; worker serves {self.model_id!r}",
            )
        if request.request.task != "text_to_motion":
            raise WorkerFailure(
                "INVALID_TASK", "MoMADiff HumanML3D supports only text_to_motion"
            )

        prompt_value = request.request.input.get("prompt")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise WorkerFailure("INVALID_REQUEST", "input.prompt must be non-empty")
        prompt = prompt_value.strip()
        if len(prompt) > 8_000:
            raise WorkerFailure(
                "INVALID_REQUEST", "input.prompt exceeds 8000 characters"
            )

        parameters = request.request.parameters
        seed = _require_int(
            parameters.get("seed", 42),
            name="seed",
            minimum=0,
            maximum=2_147_483_647,
        )
        requested_fps = _require_float(
            parameters.get("fps", FPS), name="fps", minimum=FPS, maximum=FPS
        )
        motion_length_frames = _resolve_motion_length_frames(
            input_frames=request.request.input.get("motion_length_frames"),
            seconds=parameters.get("seconds"),
            fps=requested_fps,
        )
        mask_steps = _require_int(
            parameters.get("mask_steps", DEFAULT_MASK_STEPS),
            name="mask_steps",
            minimum=1,
            maximum=32,
        )
        guidance_scale = _require_float(
            parameters.get("guidance_scale", DEFAULT_GUIDANCE_SCALE),
            name="guidance_scale",
            minimum=0.0,
            maximum=10.0,
        )

        try:
            generation = backend.generate(
                prompt,
                seed=seed,
                motion_length_frames=motion_length_frames,
                mask_steps=mask_steps,
                guidance_scale=guidance_scale,
            )
        except ResourceObservationUnavailable as exc:
            raise WorkerFailure("RESOURCE_OBSERVATION_UNAVAILABLE", str(exc)) from exc
        except ValueError as exc:
            raise WorkerFailure("INVALID_REQUEST", str(exc)) from exc
        except RuntimeError as exc:
            lowered = str(exc).lower()
            if "out of memory" in lowered:
                raise WorkerFailure("WORKER_OOM", str(exc), retryable=True) from exc
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"MoMADiff inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        except Exception as exc:
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"MoMADiff inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        context.raise_if_cancelled()
        self._device_facts = dict(backend.device_facts)

        motion = generation.motion
        frame_count = int(motion.shape[0])
        motion_path = (
            context.staging_directory
            / "native__momadiff-humanml3d__humanml3d-body22__vector263.npy"
        )
        np.save(motion_path, motion, allow_pickle=False)

        run_metadata = {
            "schema_version": "virea.momadiff_generation_metadata.v1.0.0",
            "job_id": request.job_id,
            "model": {
                "id": self.model_id,
                "source_repository": SOURCE_REPOSITORY,
                "source_revision": SOURCE_REVISION,
                "checkpoint_repository": CHECKPOINT_REPOSITORY,
                "checkpoint_revision": CHECKPOINT_REVISION,
                "clip_repository": CLIP_REPOSITORY,
                "clip_revision": CLIP_REVISION,
            },
            "runtime": {
                "runtime_id": os.getenv("VIREA_RUNTIME_ID", RUNTIME_ID),
                "resource_profile": os.getenv("VIREA_RESOURCE_PROFILE", "cuda-full"),
                **self._device_facts,
            },
            "request": {
                "prompt": prompt,
                "seed": seed,
                "requested_motion_length_frames": motion_length_frames,
                "fps": requested_fps,
                "mask_steps": mask_steps,
                "guidance_scale": guidance_scale,
            },
            "output": {
                "representation_id": REPRESENTATION_ID,
                "skeleton_id": SKELETON_ID,
                "frame_count": frame_count,
                "fps": FPS,
                "dtype": str(motion.dtype),
                "shape": list(motion.shape),
                "token_length": generation.token_length,
                "length_source": generation.length_source,
                "ddim_steps": generation.ddim_steps,
            },
        }
        metadata_path = context.staging_directory / "generation_metadata.json"
        metadata_path.write_text(
            json.dumps(run_metadata, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )

        locator = request.staging_locator.rstrip("/")
        artifact_base = f"virea-job://{request.job_id}/{locator}"
        return ModelResult(
            job_id=request.job_id,
            model=ModelIdentity(
                id=self.model_id,
                plugin_version=PLUGIN_VERSION,
                upstream_repository=SOURCE_REPOSITORY,
                upstream_revision=SOURCE_REVISION,
                runtime_id=os.getenv("VIREA_RUNTIME_ID", RUNTIME_ID),
                artifact_manifest_id=ARTIFACT_MANIFEST_ID,
            ),
            task=request.request.task,
            request_id=request.request.idempotency_key,
            native=NativeMotionDescriptor(
                representation_id=REPRESENTATION_ID,
                skeleton_id=SKELETON_ID,
                fps=FPS,
                frame_count=frame_count,
                coordinate_system="humanml3d.right_handed_y_up_z_forward",
                units="meters",
                root_translation_semantics=(
                    "relative_root_facing_xz_velocity_integrated_from_origin_with_absolute_y_height"
                ),
                root_rotation_semantics=(
                    "yaw_integrated_from_relative_angular_velocity_with_initial_identity"
                ),
                artifacts=(
                    ArtifactRef(
                        name="native_momadiff_humanml3d_vector263",
                        media_type="application/x-npy",
                        uri=f"{artifact_base}/{motion_path.name}",
                        byte_length=motion_path.stat().st_size,
                        dtype="float32",
                        shape=(frame_count, FEATURE_DIM),
                    ),
                    ArtifactRef(
                        name="generation_metadata",
                        media_type="application/json",
                        uri=f"{artifact_base}/{metadata_path.name}",
                        byte_length=metadata_path.stat().st_size,
                    ),
                ),
            ),
            segments=(ValidSegment(start_frame=0, end_frame=frame_count),),
            provenance=GenerationProvenance(
                seed=seed,
                precision="float32_output",
                device=backend.device_name,
                generation_parameters={
                    "prompt": prompt,
                    "frame_count": frame_count,
                    "motion_length_frames": frame_count,
                    "length_source": generation.length_source,
                    "token_length": generation.token_length,
                    "mask_steps": generation.mask_steps,
                    "guidance_scale": generation.guidance_scale,
                    "ddim_steps": generation.ddim_steps,
                    "fps": FPS,
                    **self._device_facts,
                },
                sources=(
                    SourceRevision(
                        repository=SOURCE_REPOSITORY,
                        revision=SOURCE_REVISION,
                        release="ACM Multimedia 2025",
                    ),
                    SourceRevision(
                        repository=CHECKPOINT_REPOSITORY,
                        revision=CHECKPOINT_REVISION,
                    ),
                    SourceRevision(
                        repository=CLIP_REPOSITORY,
                        revision=CLIP_REVISION,
                    ),
                ),
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-momadiff-worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--model-id", default=MODEL_ID)
    parser.add_argument("--instance-id")
    parser.add_argument("--job-id")
    parser.add_argument("--runtime-id")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    for value, environment_name in (
        (args.instance_id, "VIREA_WORKER_INSTANCE_ID"),
        (args.job_id, "VIREA_WORKER_JOB_ID"),
        (args.model_id, "VIREA_WORKER_MODEL_ID"),
        (args.runtime_id, "VIREA_RUNTIME_ID"),
        (str(args.port), "VIREA_WORKER_PORT"),
    ):
        expected = os.getenv(environment_name)
        if value is not None and expected and str(value) != expected:
            raise SystemExit(f"Worker identity mismatch for {environment_name}")
    serve_plugin(
        MoMADiffHumanML3DPlugin(
            artifact_paths_from_environment(), model_id=args.model_id
        ),
        host=args.host,
        port=args.port,
        job_root=args.job_root,
    )


if __name__ == "__main__":
    main()
