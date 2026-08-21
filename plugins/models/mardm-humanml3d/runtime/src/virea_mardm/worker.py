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
    MARDM_AE_REVISION,
    MARDM_LENGTH_REVISION,
    MARDM_MODEL_REVISION,
    MARDM_SOURCE_REVISION,
    OPENAI_CLIP_REVISION,
    ArtifactRoots,
    artifact_roots_from_environment,
)
from .backend import MardmBackend

MODEL_ID = "mardm-humanml3d"
PLUGIN_VERSION = "0.2.0"
RUNTIME_ID = "mardm-humanml3d-cu128"
REPRESENTATION_ID = "mardm.humanml3d.ric67.v1"
SKELETON_ID = "humanml3d.body22.v1"
FPS = 20.0


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


def _require_bool(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be boolean")
    return value


def _resolve_motion_length_parameters(
    parameters: dict[str, Any],
) -> tuple[int | None, float | None]:
    length_value = parameters.get("motion_length_frames")
    seconds_value = parameters.get("seconds")
    if length_value is not None and seconds_value is not None:
        raise WorkerFailure(
            "INVALID_REQUEST",
            "provide either motion_length_frames or seconds, not both",
        )
    motion_length_frames = (
        None
        if length_value is None
        else _require_int(
            length_value,
            name="motion_length_frames",
            minimum=4,
            maximum=196,
        )
    )
    if motion_length_frames is not None and motion_length_frames % 4:
        raise WorkerFailure(
            "INVALID_REQUEST", "motion_length_frames must be a multiple of 4"
        )
    seconds = None
    if seconds_value is not None:
        seconds = _require_float(
            seconds_value,
            name="seconds",
            minimum=0.2,
            maximum=9.8,
        )
        frame_value = seconds * FPS
        rounded_frames = round(frame_value)
        if not math.isclose(frame_value, rounded_frames, rel_tol=0.0, abs_tol=1e-6):
            raise WorkerFailure(
                "INVALID_REQUEST",
                "seconds must resolve to an exact 20 FPS frame count",
            )
        if rounded_frames % 4:
            raise WorkerFailure(
                "INVALID_REQUEST",
                "seconds must resolve to a multiple of 4 MARDM frames (0.2 seconds)",
            )
        motion_length_frames = rounded_frames
    return motion_length_frames, seconds


class MardmHumanML3DPlugin:
    """Managed real-checkpoint Worker for MARDM SiT-XL HumanML3D."""

    def __init__(
        self,
        roots: ArtifactRoots,
        cache_root: str | Path,
        *,
        model_id: str = MODEL_ID,
    ) -> None:
        if model_id != MODEL_ID:
            raise WorkerFailure(
                "INVALID_MODEL_ID",
                f"this worker serves only {MODEL_ID!r}, not {model_id!r}",
            )
        self.model_id = model_id
        self._backend = MardmBackend(roots, Path(cache_root))

    def metadata(self) -> WorkerMetadata:
        active_strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cuda_full").strip()
        is_cpu = active_strategy == "cpu"
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
                "min_ram_gib": 24.0 if is_cpu else 16.0,
                "memory_strategies": ["cuda_full", "cpu"],
                "active_memory_strategy": active_strategy,
                "resource_profile": os.getenv(
                    "VIREA_RESOURCE_PROFILE",
                    "whole-model-cpu" if is_cpu else "cuda-full",
                ),
                "model_revision": MARDM_MODEL_REVISION,
                "autoencoder_revision": MARDM_AE_REVISION,
                "length_estimator_revision": MARDM_LENGTH_REVISION,
                "source_revision": MARDM_SOURCE_REVISION,
                "clip_revision": OPENAI_CLIP_REVISION,
                "native_feature_dim": 67,
                "native_fps": FPS,
                "cancel_semantics": "checked_before_and_after_non_preemptive_model_inference",
                **self._backend.device_facts,
            },
        )

    def load(self) -> None:
        self._backend.load()

    def unload(self) -> None:
        self._backend.unload()

    def cancel(self, job_id: str) -> None:
        # The released whole-sequence sampler has no safe mid-kernel
        # cancellation hook. The supervisor may terminate this isolated
        # process tree after the request boundary.
        return None

    def infer(self, request: WorkerInferRequest, context: WorkerContext) -> ModelResult:
        context.raise_if_cancelled()
        if not self._backend.loaded:
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
                "INVALID_TASK", "MARDM Worker supports only text_to_motion"
            )
        prompt_value = request.request.input.get("prompt")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise WorkerFailure(
                "INVALID_REQUEST", "input.prompt must be a non-empty string"
            )
        prompt = prompt_value.strip()
        if len(prompt) > 8_000:
            raise WorkerFailure(
                "INVALID_REQUEST", "input.prompt exceeds 8000 characters"
            )

        parameters = request.request.parameters
        motion_length_frames, seconds = _resolve_motion_length_parameters(parameters)
        seed = _require_int(
            parameters.get("seed", 3407),
            name="seed",
            minimum=0,
            maximum=2_147_483_647,
        )
        time_steps = _require_int(
            parameters.get("time_steps", 18),
            name="time_steps",
            minimum=1,
            maximum=100,
        )
        cfg = _require_float(
            parameters.get("cfg", 4.5), name="cfg", minimum=0.0, maximum=20.0
        )
        temperature = _require_float(
            parameters.get("temperature", 1.0),
            name="temperature",
            minimum=0.01,
            maximum=10.0,
        )
        hard_pseudo_reorder = _require_bool(
            parameters.get("hard_pseudo_reorder", False),
            name="hard_pseudo_reorder",
        )
        requested_fps = _require_float(
            parameters.get("fps", FPS), name="fps", minimum=FPS, maximum=FPS
        )

        try:
            generated = self._backend.generate(
                prompt,
                motion_length_frames=motion_length_frames,
                seed=seed,
                time_steps=time_steps,
                cfg=cfg,
                temperature=temperature,
                hard_pseudo_reorder=hard_pseudo_reorder,
            )
        except WorkerFailure:
            raise
        except RuntimeError as exc:
            if "out of memory" in str(exc).lower():
                raise WorkerFailure("WORKER_OOM", str(exc), retryable=True) from exc
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"MARDM inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        except Exception as exc:
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"MARDM inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        context.raise_if_cancelled()

        staging = context.staging_directory
        native_path = staging / "source_mardm_ric67_normalized.npy"
        mean_path = staging / "mardm_t2m_eval_mean.npy"
        std_path = staging / "mardm_t2m_eval_std.npy"
        np.save(native_path, generated.normalized_ric67, allow_pickle=False)
        np.save(mean_path, generated.mean, allow_pickle=False)
        np.save(std_path, generated.std, allow_pickle=False)

        device_facts = self._backend.device_facts
        run_metadata = {
            "schema_version": "virea.mardm_generation_metadata.v1.0.0",
            "job_id": request.job_id,
            "model": {
                "id": self.model_id,
                "repository": "https://github.com/neu-vi/MARDM",
                "source_revision": MARDM_SOURCE_REVISION,
                "model_revision": MARDM_MODEL_REVISION,
                "autoencoder_revision": MARDM_AE_REVISION,
                "length_estimator_revision": MARDM_LENGTH_REVISION,
                "clip_revision": OPENAI_CLIP_REVISION,
                "variant": "MARDM-SiT-XL",
            },
            "runtime": {
                "runtime_id": os.getenv("VIREA_RUNTIME_ID", RUNTIME_ID),
                **device_facts,
            },
            "request": {
                "prompt": prompt,
                "motion_length_frames": motion_length_frames,
                "seconds": seconds,
                "seed": seed,
                "time_steps": time_steps,
                "cfg": cfg,
                "temperature": temperature,
                "hard_pseudo_reorder": hard_pseudo_reorder,
                "fps": requested_fps,
            },
            "output": {
                "frame_count": generated.generated_frames,
                "fps": FPS,
                "dtype": str(generated.normalized_ric67.dtype),
                "shape": list(generated.normalized_ric67.shape),
                "normalization": "pinned_upstream_t2m_eval_mean_std",
                "length_was_estimated": generated.length_was_estimated,
            },
        }
        metadata_path = staging / "generation_metadata.json"
        metadata_path.write_text(
            json.dumps(run_metadata, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )

        locator = request.staging_locator.rstrip("/")
        artifact_base = f"virea-job://{request.job_id}/{locator}"
        frame_count = generated.generated_frames
        return ModelResult(
            job_id=request.job_id,
            model=ModelIdentity(
                id=self.model_id,
                plugin_version=PLUGIN_VERSION,
                upstream_repository="https://github.com/neu-vi/MARDM",
                upstream_revision=MARDM_SOURCE_REVISION,
                runtime_id=os.getenv("VIREA_RUNTIME_ID", RUNTIME_ID),
                artifact_manifest_id="mardm-humanml3d-pinned-bundle",
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
                        name="source_mardm_ric67_normalized",
                        media_type="application/x-npy",
                        uri=f"{artifact_base}/{native_path.name}",
                        byte_length=native_path.stat().st_size,
                        dtype="float32",
                        shape=(frame_count, 67),
                    ),
                    ArtifactRef(
                        name="mardm_t2m_eval_mean",
                        media_type="application/x-npy",
                        uri=f"{artifact_base}/{mean_path.name}",
                        byte_length=mean_path.stat().st_size,
                        dtype="float32",
                        shape=(67,),
                    ),
                    ArtifactRef(
                        name="mardm_t2m_eval_std",
                        media_type="application/x-npy",
                        uri=f"{artifact_base}/{std_path.name}",
                        byte_length=std_path.stat().st_size,
                        dtype="float32",
                        shape=(67,),
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
                device=str(device_facts.get("device", "unknown")),
                generation_parameters={
                    "prompt": prompt,
                    "motion_length_frames": motion_length_frames,
                    "seconds": seconds,
                    "frame_count": frame_count,
                    "length_was_estimated": generated.length_was_estimated,
                    "time_steps": time_steps,
                    "cfg": cfg,
                    "temperature": temperature,
                    "hard_pseudo_reorder": hard_pseudo_reorder,
                    "fps": FPS,
                    **device_facts,
                },
                sources=(
                    SourceRevision(
                        repository="https://github.com/neu-vi/MARDM",
                        revision=MARDM_SOURCE_REVISION,
                        release="CVPR 2025",
                    ),
                    SourceRevision(
                        repository="cr8br0ze/MARDM_SiT_XL",
                        revision=MARDM_MODEL_REVISION,
                    ),
                    SourceRevision(
                        repository="cr8br0ze/AE_humanml3d",
                        revision=MARDM_AE_REVISION,
                    ),
                    SourceRevision(
                        repository="cr8br0ze/length_estimator",
                        revision=MARDM_LENGTH_REVISION,
                    ),
                    SourceRevision(
                        repository="https://github.com/openai/CLIP",
                        revision=OPENAI_CLIP_REVISION,
                    ),
                ),
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-mardm-worker")
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
    hf_home = os.getenv("HF_HOME")
    if not hf_home:
        raise SystemExit("HF_HOME must identify VIREA's external managed cache")
    cache_root = Path(hf_home).expanduser().resolve(strict=False) / "virea-materialized"
    serve_plugin(
        MardmHumanML3DPlugin(
            roots,
            cache_root,
            model_id=args.model_id,
        ),
        host=args.host,
        port=args.port,
        job_root=args.job_root,
    )


if __name__ == "__main__":
    main()
