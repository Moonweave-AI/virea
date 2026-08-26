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
    CLIP_REVISION,
    MODEL_REVISION,
    QWEN_REVISION,
    SOURCE_REVISION,
    HyMotionBackend,
)

MODEL_ID = "hy-motion-1"
PLUGIN_VERSION = "0.2.0"
DEFAULT_RUNTIME_ID = "hy-motion-1-cpu"
REPRESENTATION_ID = "hy_motion.body22.rot6d_translation.v1"
SKELETON_ID = "hy_motion.wooden_body22.v1"
FPS = 30.0


def _number(
    value: Any,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise WorkerFailure(
            "INVALID_REQUEST", f"{name} must be in [{minimum:g}, {maximum:g}]"
        )
    return parsed


class HyMotionPlugin:
    def __init__(self, backend: HyMotionBackend | None = None) -> None:
        self._backend = backend or HyMotionBackend()

    def metadata(self) -> WorkerMetadata:
        strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cpu")
        return WorkerMetadata(
            model_id=MODEL_ID,
            plugin_version=PLUGIN_VERSION,
            tasks=("text_to_motion",),
            input_schemas=("virea.job_request.v1.0.0",),
            output_representation_id=REPRESENTATION_ID,
            output_skeleton_id=SKELETON_ID,
            supports_streaming=False,
            supports_cancel=True,
            resources={
                "accelerator": "cpu" if strategy == "cpu" else "nvidia",
                "min_vram_gib": None if strategy == "cpu" else 26.0,
                "min_ram_gib": 40.0 if strategy == "cpu" else 24.0,
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
        # The supervisor terminates this isolated process tree if a denoising
        # request does not reach its next cooperative boundary promptly.

    def infer(self, request: WorkerInferRequest, context: WorkerContext) -> ModelResult:
        context.raise_if_cancelled()
        if request.request.model_id != MODEL_ID:
            raise WorkerFailure("INVALID_MODEL_ID", "request targets another model")
        if request.request.task != "text_to_motion":
            raise WorkerFailure("INVALID_TASK", "HY-Motion supports text_to_motion")
        prompt_value = request.request.input.get("prompt")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise WorkerFailure("INVALID_REQUEST", "input.prompt must be non-empty")
        prompt = prompt_value.strip()
        if len(prompt) > 8_000:
            raise WorkerFailure(
                "INVALID_REQUEST", "input.prompt exceeds 8000 characters"
            )
        parameters = request.request.parameters
        duration = _number(
            parameters.get(
                "duration_seconds",
                request.request.input.get("duration_seconds", 4.0),
            ),
            name="duration_seconds",
            minimum=1.0,
            maximum=12.0,
        )
        seed_raw = parameters.get("seed", request.request.input.get("seed", 42))
        if (
            isinstance(seed_raw, bool)
            or not isinstance(seed_raw, int)
            or not 0 <= seed_raw <= 2_147_483_647
        ):
            raise WorkerFailure(
                "INVALID_REQUEST", "seed must be an integer in [0, 2147483647]"
            )
        guidance = _number(
            parameters.get("guidance_scale", 5.0),
            name="guidance_scale",
            minimum=0.0,
            maximum=20.0,
        )
        try:
            generated = self._backend.generate(
                prompt,
                duration_seconds=duration,
                seed=seed_raw,
                guidance_scale=guidance,
            )
        except WorkerFailure:
            raise
        except Exception as exc:
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"HY-Motion inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        context.raise_if_cancelled()

        staging = context.staging_directory
        native_arrays = {
            "source_hy_translation_m": generated.translation_m,
            "source_hy_rotations_6d": generated.rotations_6d,
            "source_hy_latent_denorm": generated.latent_denorm,
            "source_hy_keypoints3d": generated.keypoints3d,
        }
        native_paths: dict[str, Path] = {}
        for name, values in native_arrays.items():
            path = staging / f"{name}.npy"
            np.save(
                path,
                np.ascontiguousarray(values, dtype=np.float32),
                allow_pickle=False,
            )
            native_paths[name] = path
        runtime_id = os.getenv("VIREA_RUNTIME_ID", DEFAULT_RUNTIME_ID)
        metadata_path = staging / "generation_metadata.json"
        write_generation_metadata(
            metadata_path,
            {
                "schema_version": "virea.hy_motion_generation.v1.0.0",
                "job_id": request.job_id,
                "model_id": MODEL_ID,
                "runtime_id": runtime_id,
                "smoothing_applied": True,
                "ground_alignment_applied": True,
                "request": {
                    "prompt": prompt,
                    "duration_seconds": duration,
                    "seed": seed_raw,
                    "guidance_scale": guidance,
                },
                "output": {
                    "frame_count": int(generated.translation_m.shape[0]),
                    "fps": FPS,
                    "representation_id": REPRESENTATION_ID,
                    "smoothing_applied": True,
                    "ground_alignment_applied": True,
                },
                "device": self._backend.device_facts,
            },
        )
        locator = request.staging_locator.rstrip("/")
        base = f"virea-job://{request.job_id}/{locator}"
        frame_count = int(generated.translation_m.shape[0])
        return native_model_result(
            job_id=request.job_id,
            request_id=request.request.idempotency_key,
            task=request.request.task,
            model_id=MODEL_ID,
            plugin_version=PLUGIN_VERSION,
            runtime_id=runtime_id,
            upstream_repository="https://github.com/Tencent-Hunyuan/HY-Motion-1.0",
            upstream_revision=SOURCE_REVISION,
            artifact_manifest_id="hy-motion-1-pinned-official-bundle",
            representation_id=REPRESENTATION_ID,
            skeleton_id=SKELETON_ID,
            fps=FPS,
            frame_count=frame_count,
            coordinate_system="hy_motion.right_handed_y_up_ground_aligned",
            units="meters",
            root_translation_semantics="absolute_world_translation_smoothed_and_ground_aligned",
            root_rotation_semantics="root_6d_rotation_local_to_world_smoothed_by_upstream_slerp_path",
            artifacts=(
                *(
                    ArtifactRef(
                        name=name,
                        media_type="application/x-npy",
                        uri=f"{base}/{path.name}",
                        byte_length=path.stat().st_size,
                        dtype="float32",
                        shape=tuple(int(axis) for axis in native_arrays[name].shape),
                    )
                    for name, path in native_paths.items()
                ),
                ArtifactRef(
                    name="generation_metadata",
                    media_type="application/json",
                    uri=f"{base}/{metadata_path.name}",
                    byte_length=metadata_path.stat().st_size,
                ),
            ),
            seed=seed_raw,
            precision="float32_output",
            device=str(self._backend.device_facts.get("device", "unknown")),
            generation_parameters={
                "prompt": prompt,
                "duration_seconds": duration,
                "seed": seed_raw,
                "guidance_scale": guidance,
                "fps": FPS,
                "smoothing_applied": True,
                "ground_alignment_applied": True,
            },
            sources=(
                SourceRevision(
                    repository="https://github.com/Tencent-Hunyuan/HY-Motion-1.0",
                    revision=SOURCE_REVISION,
                    release="2025-12-30",
                ),
                SourceRevision(
                    repository="tencent/HY-Motion-1.0", revision=MODEL_REVISION
                ),
                SourceRevision(repository="Qwen/Qwen3-8B", revision=QWEN_REVISION),
                SourceRevision(
                    repository="openai/clip-vit-large-patch14", revision=CLIP_REVISION
                ),
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-hy-motion-worker")
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
    for value, name in (
        (args.instance_id, "VIREA_WORKER_INSTANCE_ID"),
        (args.job_id, "VIREA_WORKER_JOB_ID"),
        (args.model_id, "VIREA_WORKER_MODEL_ID"),
        (args.runtime_id, "VIREA_RUNTIME_ID"),
        (str(args.port), "VIREA_WORKER_PORT"),
    ):
        expected = os.getenv(name)
        if value is not None and expected and str(value) != expected:
            raise SystemExit(f"Worker identity mismatch for {name}")
    serve_plugin(
        HyMotionPlugin(),
        host=args.host,
        port=args.port,
        job_root=args.job_root,
    )


if __name__ == "__main__":
    main()
