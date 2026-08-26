from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
from virea_contracts.provenance import SourceRevision
from virea_contracts.result import ArtifactRef, ModelResult
from virea_contracts.worker import WorkerInferRequest, WorkerMetadata
from virea_model_sdk import WorkerContext, WorkerFailure, serve_plugin
from virea_model_sdk.upstream_runtime import (
    native_model_result,
    write_generation_metadata,
)

from .backend import (
    CHECKPOINT_REVISION,
    CLIP_REVISION,
    SOURCE_REVISION,
    InterMaskBackend,
)

MODEL_ID = "intermask-interhuman"
PLUGIN_VERSION = "0.2.0"
DEFAULT_RUNTIME_ID = "intermask-interhuman-cpu"
REPRESENTATION_ID = "interhuman.motion262.v1"
SKELETON_ID = "interhuman.two_actor_smpl22.v1"
FPS = 30.0


def _float(value: Any, *, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise WorkerFailure(
            "INVALID_REQUEST", f"{name} must be in [{minimum:g}, {maximum:g}]"
        )
    return parsed


def _conditioning_motion(value: Any) -> np.ndarray:
    if isinstance(value, str):
        path = Path(value).expanduser().resolve(strict=True)
        if path.suffix.lower() != ".npy" or not path.is_file():
            raise WorkerFailure(
                "INVALID_REQUEST", "conditioning_actor_motion path must be a .npy file"
            )
        values = np.load(path, allow_pickle=False)
    else:
        values = np.asarray(value)
    result = np.asarray(values, dtype=np.float32)
    if result.ndim != 2 or result.shape[1] != 262 or not np.isfinite(result).all():
        raise WorkerFailure(
            "INVALID_REQUEST",
            "conditioning_actor_motion must contain finite [frames,262] values",
        )
    return np.ascontiguousarray(result)


class InterMaskPlugin:
    def __init__(self, backend: InterMaskBackend | None = None) -> None:
        self._backend = backend or InterMaskBackend()

    def metadata(self) -> WorkerMetadata:
        strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cpu")
        return WorkerMetadata(
            model_id=MODEL_ID,
            plugin_version=PLUGIN_VERSION,
            tasks=(
                "text_to_two_person_interaction",
                "interaction_reaction_generation",
            ),
            input_schemas=("virea.job_request.v1.0.0",),
            output_representation_id=REPRESENTATION_ID,
            output_skeleton_id=SKELETON_ID,
            supports_streaming=False,
            supports_cancel=True,
            resources={
                "accelerator": "cpu" if strategy == "cpu" else "nvidia",
                "min_vram_gib": None if strategy == "cpu" else 8.0,
                "min_ram_gib": 16.0 if strategy == "cpu" else 12.0,
                "memory_strategies": ["cpu", "cuda_full"],
                "active_memory_strategy": strategy,
                **self._backend.device_facts,
            },
        )

    def load(self) -> None:
        self._backend.load()

    def unload(self) -> None:
        self._backend.unload()

    def cancel(self, job_id: str) -> None:
        del job_id

    def infer(self, request: WorkerInferRequest, context: WorkerContext) -> ModelResult:
        context.raise_if_cancelled()
        job = request.request
        if job.model_id != MODEL_ID:
            raise WorkerFailure("INVALID_MODEL_ID", "request targets another model")
        if job.task not in {
            "text_to_two_person_interaction",
            "interaction_reaction_generation",
        }:
            raise WorkerFailure("INVALID_TASK", "unsupported InterMask task")
        prompt_value = job.input.get("prompt")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise WorkerFailure("INVALID_REQUEST", "input.prompt must be non-empty")
        prompt = prompt_value.strip()
        duration = _float(
            job.parameters.get(
                "duration_seconds", job.input.get("duration_seconds", 2.0)
            ),
            name="duration_seconds",
            minimum=1.0,
            maximum=5.0,
        )
        raw_frame_count = duration * FPS
        rounded_frame_count = round(raw_frame_count)
        if not math.isclose(raw_frame_count, rounded_frame_count, abs_tol=1e-6) or (
            rounded_frame_count % 4
        ):
            raise WorkerFailure(
                "INVALID_REQUEST",
                "duration_seconds must resolve to a whole multiple of 4 frames at 30 FPS",
            )
        frame_count = int(rounded_frame_count)
        seed = job.parameters.get("seed", 42)
        steps = job.parameters.get("sampling_steps", 20)
        if (
            isinstance(seed, bool)
            or not isinstance(seed, int)
            or not 0 <= seed <= 2_147_483_647
        ):
            raise WorkerFailure(
                "INVALID_REQUEST", "seed must be an integer in [0,2147483647]"
            )
        if (
            isinstance(steps, bool)
            or not isinstance(steps, int)
            or not 2 <= steps <= 100
        ):
            raise WorkerFailure("INVALID_REQUEST", "sampling_steps must be in [2,100]")
        guidance = _float(
            job.parameters.get("guidance_scale", 2.0),
            name="guidance_scale",
            minimum=0.0,
            maximum=10.0,
        )
        conditioning = None
        if job.task == "interaction_reaction_generation":
            if "conditioning_actor_motion" not in job.input:
                raise WorkerFailure(
                    "INVALID_REQUEST",
                    "conditioning_actor_motion is required for reaction generation",
                )
            conditioning = _conditioning_motion(job.input["conditioning_actor_motion"])
            frame_count = int(conditioning.shape[0])
            if frame_count % 4 or not 30 <= frame_count <= 150:
                raise WorkerFailure(
                    "INVALID_REQUEST",
                    "conditioning motion length must be a multiple of 4 in [30,150]",
                )
        try:
            generated = self._backend.generate(
                prompt,
                frame_count=frame_count,
                seed=seed,
                sampling_steps=steps,
                guidance_scale=guidance,
                conditioning_actor_motion=conditioning,
            )
        except WorkerFailure:
            raise
        except Exception as exc:
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"InterMask inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        context.raise_if_cancelled()

        staging = context.staging_directory
        motion_path = staging / "source_intermask_motion262.npy"
        transform_path = staging / "source_intermask_shared_frame_transform.npy"
        np.save(motion_path, generated.actors_motion262, allow_pickle=False)
        np.save(transform_path, generated.shared_frame_transform, allow_pickle=False)
        runtime_id = os.getenv("VIREA_RUNTIME_ID", DEFAULT_RUNTIME_ID)
        metadata_path = staging / "generation_metadata.json"
        write_generation_metadata(
            metadata_path,
            {
                "schema_version": "virea.intermask_generation.v1.0.0",
                "source_artifact_id": "intermask-interhuman-pretrained",
                "job_id": request.job_id,
                "model_id": MODEL_ID,
                "runtime_id": runtime_id,
                "task": job.task,
                "prompt": prompt,
                "frame_count": frame_count,
                "seed": seed,
                "sampling_steps": steps,
                "guidance_scale": guidance,
                "actor_count": 2,
                "shared_frame": "actor1_canonical_interaction_frame",
                "device": self._backend.device_facts,
            },
        )
        locator = request.staging_locator.rstrip("/")
        base = f"virea-job://{request.job_id}/{locator}"
        return native_model_result(
            job_id=request.job_id,
            request_id=job.idempotency_key,
            task=job.task,
            model_id=MODEL_ID,
            plugin_version=PLUGIN_VERSION,
            runtime_id=runtime_id,
            upstream_repository="https://github.com/gohar-malik/intermask",
            upstream_revision=SOURCE_REVISION,
            artifact_manifest_id="intermask-interhuman-pinned-official-bundle",
            representation_id=REPRESENTATION_ID,
            skeleton_id=SKELETON_ID,
            fps=FPS,
            frame_count=frame_count,
            coordinate_system="interhuman.actor1_initial_heading_positive_z_y_up",
            units="meters",
            root_translation_semantics="actor1_initial_root_xz_zeroed_and_actor2_rigidly_transformed_into_actor1_canonical_interaction_frame",
            root_rotation_semantics="root_rotation_absent_non_root_rotation6d_present_in_native_262D_channel",
            artifacts=(
                ArtifactRef(
                    name="source_intermask_motion262",
                    media_type="application/x-npy",
                    uri=f"{base}/{motion_path.name}",
                    byte_length=motion_path.stat().st_size,
                    dtype="float32",
                    shape=(2, frame_count, 262),
                ),
                ArtifactRef(
                    name="source_intermask_shared_frame_transform",
                    media_type="application/x-npy",
                    uri=f"{base}/{transform_path.name}",
                    byte_length=transform_path.stat().st_size,
                    dtype="float32",
                    shape=(4, 4),
                ),
                ArtifactRef(
                    name="generation_metadata",
                    media_type="application/json",
                    uri=f"{base}/{metadata_path.name}",
                    byte_length=metadata_path.stat().st_size,
                ),
            ),
            seed=seed,
            precision="float32_output",
            device=str(self._backend.device_facts.get("device", "unknown")),
            generation_parameters={
                "prompt": prompt,
                "frame_count": frame_count,
                "seed": seed,
                "sampling_steps": steps,
                "guidance_scale": guidance,
                "actor_count": 2,
            },
            sources=(
                SourceRevision(
                    repository="https://github.com/gohar-malik/intermask",
                    revision=SOURCE_REVISION,
                    release="ICLR 2025",
                ),
                SourceRevision(
                    repository="https://drive.google.com/drive/folders/1WCFR7Opc5S3cke26cjEhdvSOH_CXL2Ut",
                    revision=CHECKPOINT_REVISION,
                ),
                SourceRevision(
                    repository="https://github.com/openai/CLIP",
                    revision=CLIP_REVISION,
                ),
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-intermask-worker")
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
    if args.model_id != MODEL_ID:
        raise SystemExit(f"this Worker serves only {MODEL_ID}")
    serve_plugin(
        InterMaskPlugin(), host=args.host, port=args.port, job_root=args.job_root
    )


if __name__ == "__main__":
    main()
