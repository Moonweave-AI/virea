from __future__ import annotations

import argparse
import json
import math
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
from virea_model_sdk import WorkerContext, WorkerFailure, serve_plugin

from .artifacts import (
    MODEL_REPOSITORY,
    MODEL_REVISION,
    SOURCE_REPOSITORY,
    SOURCE_REVISION,
    STATS_REPOSITORY,
    STATS_REVISION,
    TOKENIZER_REPOSITORY,
    TOKENIZER_REVISION,
    PrismArtifactRoots,
    artifact_roots_from_environment,
)
from .backend import (
    CPU_MEMORY_STRATEGY,
    CPU_MIN_FREE_RAM_GIB,
    CUDA_MEMORY_STRATEGY,
    FPS,
    MEMORY_STRATEGIES,
    MIN_FREE_RAM_GIB,
    MIN_TOTAL_RAM_GIB,
    PrismBackend,
)

MODEL_ID = "prism-tp2m-1-4b"
PLUGIN_VERSION = "0.1.0"
RUNTIME_ID = "prism-tp2m-1-4b-cu128-component-split"
REPRESENTATION_ID = "prism.smplh_body22.axis_angle69.v1"
SKELETON_ID = "smplh.body22.v1"
DEFAULT_NUM_FRAMES = 129
DEFAULT_INFERENCE_STEPS = 50
DEFAULT_GUIDANCE_SCALE = 5.0


def _require_int(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise WorkerFailure(
            "INVALID_REQUEST", f"{name} must be in [{minimum}, {maximum}]"
        )
    return value


def _require_float(value: Any, *, name: str, minimum: float, maximum: float) -> float:
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


class PrismTP2MPlugin:
    """Managed Worker for the pinned public PRISM TP2M 1.4B checkpoint."""

    def __init__(
        self,
        roots: PrismArtifactRoots,
        *,
        model_id: str = MODEL_ID,
        backend: PrismBackend | None = None,
    ) -> None:
        if model_id != MODEL_ID:
            raise WorkerFailure(
                "INVALID_MODEL_ID",
                f"this Worker serves only {MODEL_ID!r}, not {model_id!r}",
            )
        self.model_id = model_id
        self._backend = backend or PrismBackend(roots)

    def metadata(self) -> WorkerMetadata:
        active_strategy = os.getenv(
            "VIREA_MEMORY_STRATEGY", CUDA_MEMORY_STRATEGY
        ).strip()
        is_cpu = active_strategy == CPU_MEMORY_STRATEGY
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
                "accelerator": "cpu" if is_cpu else "nvidia",
                "min_vram_gib": None if is_cpu else 12.0,
                "min_ram_gib": (CPU_MIN_FREE_RAM_GIB if is_cpu else MIN_TOTAL_RAM_GIB),
                "min_available_ram_before_load_gib": (
                    CPU_MIN_FREE_RAM_GIB if is_cpu else MIN_FREE_RAM_GIB
                ),
                "memory_strategies": list(MEMORY_STRATEGIES),
                "active_memory_strategy": active_strategy,
                "resource_profile": os.getenv(
                    "VIREA_RESOURCE_PROFILE",
                    "whole-model-cpu" if is_cpu else "cuda-component-split",
                ),
                "component_placement": {
                    "umt5_text_encoder": "cpu",
                    "motion_transformer": "cpu" if is_cpu else "cuda:0",
                    "vae": "cpu" if is_cpu else "cuda:0",
                },
                "source_revision": SOURCE_REVISION,
                "checkpoint_revision": MODEL_REVISION,
                "tokenizer_revision": TOKENIZER_REVISION,
                "statistics_revision": STATS_REVISION,
                "native_shape": "T_x_69",
                "native_fps": FPS,
                "raw_public_artifact": "SMPL-X-style NPZ retained separately",
                "implicit_network_access": False,
                "smpl_geometry_required_for_generation": False,
                **self._backend.device_facts,
            },
        )

    def load(self) -> None:
        self._backend.load()

    def unload(self) -> None:
        self._backend.unload()

    def cancel(self, job_id: str) -> None:
        del job_id
        # Diffusers' denoising loop has no stable request-scoped interruption hook.
        # The supervisor can terminate this isolated Worker process tree.

    def infer(self, request: WorkerInferRequest, context: WorkerContext) -> ModelResult:
        context.raise_if_cancelled()
        if not self._backend.loaded:
            raise WorkerFailure(
                "MODEL_NOT_LOADED", "PRISM model is not loaded", retryable=True
            )
        if request.request.model_id != self.model_id:
            raise WorkerFailure("INVALID_MODEL_ID", "request targets another model")
        if request.request.task != "text_to_motion":
            raise WorkerFailure("INVALID_TASK", "PRISM Worker supports text_to_motion")
        prompt_value = request.request.input.get("prompt")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise WorkerFailure("INVALID_REQUEST", "input.prompt must be non-empty")
        prompt = prompt_value.strip()
        if len(prompt) > 8_000:
            raise WorkerFailure(
                "INVALID_REQUEST", "input.prompt exceeds 8000 characters"
            )

        parameters = request.request.parameters
        num_frames = _require_int(
            parameters.get("num_frames", DEFAULT_NUM_FRAMES),
            name="num_frames",
            minimum=33,
            maximum=961,
        )
        if (num_frames - 1) % 4:
            raise WorkerFailure(
                "INVALID_REQUEST", "num_frames must satisfy (num_frames - 1) % 4 == 0"
            )
        seed = _require_int(
            parameters.get("seed", 42),
            name="seed",
            minimum=0,
            maximum=2_147_483_647,
        )
        inference_steps = _require_int(
            parameters.get("inference_steps", DEFAULT_INFERENCE_STEPS),
            name="inference_steps",
            minimum=1,
            maximum=200,
        )
        guidance_scale = _require_float(
            parameters.get("guidance_scale", DEFAULT_GUIDANCE_SCALE),
            name="guidance_scale",
            minimum=0.0,
            maximum=20.0,
        )
        fps = _require_float(
            parameters.get("fps", FPS), name="fps", minimum=FPS, maximum=FPS
        )
        smooth_value = parameters.get("use_smooth")
        if smooth_value is not None and smooth_value is not False:
            raise WorkerFailure(
                "INVALID_REQUEST",
                "use_smooth requires an external SmoothNet checkpoint and is not part of this runtime",
            )

        try:
            generation = self._backend.generate(
                prompt,
                num_frames=num_frames,
                seed=seed,
                inference_steps=inference_steps,
                guidance_scale=guidance_scale,
            )
        except WorkerFailure:
            raise
        except RuntimeError as exc:
            if "out of memory" in str(exc).lower():
                raise WorkerFailure("WORKER_OOM", str(exc), retryable=True) from exc
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"PRISM inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        except Exception as exc:
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"PRISM inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        context.raise_if_cancelled()

        staging = context.staging_directory
        carrier_path = staging / "source_prism_smplh_body22_axis_angle69.npy"
        np.save(carrier_path, generation.carrier, allow_pickle=False)
        raw_path = staging / "source_prism_smplx_raw.npz"
        np.savez_compressed(
            raw_path,
            **generation.raw,
            fps=np.asarray([FPS], dtype=np.float32),
        )
        device_facts = self._backend.device_facts
        metadata = {
            "schema_version": "virea.prism_generation_metadata.v1.0.0",
            "job_id": request.job_id,
            "model": {
                "id": self.model_id,
                "source_revision": SOURCE_REVISION,
                "checkpoint_revision": MODEL_REVISION,
                "tokenizer_revision": TOKENIZER_REVISION,
                "statistics_revision": STATS_REVISION,
            },
            "runtime": {
                "runtime_id": os.getenv("VIREA_RUNTIME_ID", RUNTIME_ID),
                "implicit_network_access": False,
                **device_facts,
            },
            "request": {
                "prompt": prompt,
                "num_frames": num_frames,
                "seed": seed,
                "inference_steps": inference_steps,
                "guidance_scale": guidance_scale,
                "fps": fps,
            },
            "output": {
                "frame_count": generation.frame_count,
                "representation_id": REPRESENTATION_ID,
                "shape": list(generation.carrier.shape),
                "dtype": str(generation.carrier.dtype),
                "public_pipeline_payload": "transl+global_orient+body_pose axis-angle",
                "internal_motion138_exposed_as_worker_result": False,
                "raw_artifact": raw_path.name,
            },
        }
        metadata_path = staging / "generation_metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )

        locator = request.staging_locator.rstrip("/")
        artifact_base = f"virea-job://{request.job_id}/{locator}"
        frame_count = generation.frame_count
        return ModelResult(
            job_id=request.job_id,
            model=ModelIdentity(
                id=self.model_id,
                plugin_version=PLUGIN_VERSION,
                upstream_repository=SOURCE_REPOSITORY,
                upstream_revision=SOURCE_REVISION,
                runtime_id=os.getenv("VIREA_RUNTIME_ID", RUNTIME_ID),
                artifact_manifest_id="prism-tp2m-1-4b-external-assets",
            ),
            task=request.request.task,
            request_id=request.request.idempotency_key,
            native=NativeMotionDescriptor(
                representation_id=REPRESENTATION_ID,
                skeleton_id=SKELETON_ID,
                fps=FPS,
                frame_count=frame_count,
                coordinate_system="prism.smplh.right_handed_y_up_z_forward",
                units="meters",
                root_translation_semantics="public_pipeline_postprocessed_absolute_xyz",
                root_rotation_semantics="explicit_global_orientation_axis_angle_local_to_world",
                artifacts=(
                    ArtifactRef(
                        name="source_prism_smplh_body22_axis_angle69",
                        media_type="application/x-npy",
                        uri=f"{artifact_base}/{carrier_path.name}",
                        byte_length=carrier_path.stat().st_size,
                        dtype="float32",
                        shape=(frame_count, 69),
                    ),
                    ArtifactRef(
                        name="source_prism_smplx_raw",
                        media_type="application/x-npz",
                        uri=f"{artifact_base}/{raw_path.name}",
                        byte_length=raw_path.stat().st_size,
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
                precision=(
                    f"{device_facts.get('precision', 'unknown')}_components_"
                    "float32_output"
                ),
                device=str(device_facts.get("device", "unknown")),
                generation_parameters={
                    "prompt": prompt,
                    "requested_num_frames": num_frames,
                    "frame_count": frame_count,
                    "inference_steps": inference_steps,
                    "guidance_scale": guidance_scale,
                    "fps": FPS,
                    **device_facts,
                },
                sources=(
                    SourceRevision(
                        repository=SOURCE_REPOSITORY,
                        revision=SOURCE_REVISION,
                        release="arXiv 2603.08590 v3",
                    ),
                    SourceRevision(
                        repository=MODEL_REPOSITORY, revision=MODEL_REVISION
                    ),
                    SourceRevision(
                        repository=TOKENIZER_REPOSITORY, revision=TOKENIZER_REVISION
                    ),
                    SourceRevision(
                        repository=STATS_REPOSITORY, revision=STATS_REVISION
                    ),
                ),
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-prism-worker")
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
    try:
        roots = artifact_roots_from_environment()
    except WorkerFailure as exc:
        raise SystemExit(str(exc)) from exc
    serve_plugin(
        PrismTP2MPlugin(roots, model_id=args.model_id),
        host=args.host,
        port=args.port,
        job_root=args.job_root,
    )


if __name__ == "__main__":
    main()
