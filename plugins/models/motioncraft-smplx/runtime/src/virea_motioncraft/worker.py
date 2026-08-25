from __future__ import annotations

import argparse
import base64
import binascii
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
    CLIP_SOURCE_REVISION,
    SOURCE_REVISION,
    MotionCraftBackend,
    MotionCraftGeneration,
)

MODEL_ID = "motioncraft-smplx"
PLUGIN_VERSION = "0.2.0"
DEFAULT_RUNTIME_ID = "motioncraft-smplx-cpu"
REPRESENTATION_ID = "motionx.smplx322.v1"
SKELETON_ID = "motionx.smplx53.v1"
FPS = 30.0


def _integer(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise WorkerFailure(
            "INVALID_REQUEST", f"{name} must be in [{minimum}, {maximum}]"
        )
    return value


def _text(value: Any, *, name: str, required: bool, maximum: int = 8_000) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        qualifier = "non-empty text" if required else "text"
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be {qualifier}")
    result = value.strip()
    if len(result) > maximum:
        raise WorkerFailure("INVALID_REQUEST", f"{name} exceeds {maximum} characters")
    return result


def _audio_path(value: Any, *, staging_directory: Path) -> Path:
    rendered = _text(value, name="input.audio", required=True, maximum=96_000_000)
    if rendered.startswith("data:"):
        header, separator, encoded = rendered.partition(",")
        mime_type = header.removeprefix("data:").removesuffix(";base64").lower()
        suffixes = {
            "audio/flac": ".flac",
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "audio/wav": ".wav",
            "audio/wave": ".wav",
            "audio/x-wav": ".wav",
        }
        if not separator or not header.lower().endswith(";base64"):
            raise WorkerFailure(
                "INVALID_REQUEST", "input.audio data URI must use base64 encoding"
            )
        suffix = suffixes.get(mime_type)
        if suffix is None:
            raise WorkerFailure(
                "INVALID_REQUEST",
                f"input.audio data URI type is unsupported: {mime_type}",
            )
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise WorkerFailure(
                "INVALID_REQUEST", "input.audio data URI contains invalid base64"
            ) from exc
        if not payload or len(payload) > 64 * 1024**2:
            raise WorkerFailure(
                "INVALID_REQUEST",
                "input.audio browser payload must contain 1 byte to 64 MiB",
            )
        path = staging_directory / f"browser_audio{suffix}"
        path.write_bytes(payload)
        return path
    try:
        path = Path(rendered).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkerFailure(
            "INVALID_REQUEST", "input.audio does not identify a readable file"
        ) from exc
    if not path.is_file():
        raise WorkerFailure("INVALID_REQUEST", "input.audio must identify a file")
    if path.stat().st_size > 2 * 1024**3:
        raise WorkerFailure(
            "INVALID_REQUEST", "input.audio exceeds the 2 GiB safety limit"
        )
    return path


class MotionCraftPlugin:
    def __init__(self, backend: MotionCraftBackend | None = None) -> None:
        self._backend = backend or MotionCraftBackend()

    def metadata(self) -> WorkerMetadata:
        strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cpu")
        return WorkerMetadata(
            model_id=MODEL_ID,
            plugin_version=PLUGIN_VERSION,
            tasks=("text_to_motion", "speech_to_gesture", "music_to_dance"),
            input_schemas=("virea.job_request.v1.0.0",),
            output_representation_id=REPRESENTATION_ID,
            output_skeleton_id=SKELETON_ID,
            supports_streaming=False,
            supports_cancel=True,
            resources={
                "accelerator": "cpu" if strategy == "cpu" else "nvidia",
                "min_vram_gib": None if strategy == "cpu" else 12.0,
                "min_ram_gib": 24.0,
                "memory_strategies": ["cpu", "cuda_full"],
                "tasks_loaded_one_at_a_time": True,
                **self._backend.device_facts,
            },
        )

    def load(self) -> None:
        self._backend.load()

    def unload(self) -> None:
        self._backend.unload()

    def cancel(self, job_id: str) -> None:
        del job_id
        # The supervisor owns this isolated process tree and terminates it when a
        # diffusion step cannot reach a cooperative boundary promptly.

    def infer(self, request: WorkerInferRequest, context: WorkerContext) -> ModelResult:
        context.raise_if_cancelled()
        job_request = request.request
        if job_request.model_id != MODEL_ID:
            raise WorkerFailure("INVALID_MODEL_ID", "request targets another model")
        if job_request.task not in {
            "text_to_motion",
            "speech_to_gesture",
            "music_to_dance",
        }:
            raise WorkerFailure("INVALID_TASK", "unsupported MotionCraft task")
        seed = _integer(
            job_request.parameters.get("seed", job_request.input.get("seed", 42)),
            name="seed",
            minimum=0,
            maximum=2_147_483_647,
        )
        audio_name: str | None = None
        if job_request.task == "text_to_motion":
            prompt = _text(
                job_request.input.get("prompt"), name="input.prompt", required=True
            )
            frames_value = job_request.parameters.get(
                "motion_length_frames",
                job_request.input.get("motion_length_frames"),
            )
            if frames_value is None:
                seconds = job_request.parameters.get(
                    "duration_seconds",
                    job_request.input.get("duration_seconds", 4.0),
                )
                if isinstance(seconds, bool):
                    raise WorkerFailure(
                        "INVALID_REQUEST", "duration_seconds must be numeric"
                    )
                try:
                    duration = float(seconds)
                except (TypeError, ValueError) as exc:
                    raise WorkerFailure(
                        "INVALID_REQUEST", "duration_seconds must be numeric"
                    ) from exc
                if not math.isfinite(duration) or not 1.0 <= duration <= 196.0 / FPS:
                    raise WorkerFailure(
                        "INVALID_REQUEST",
                        f"duration_seconds must be in [1, {196.0 / FPS:.3f}]",
                    )
                frames = int(round(duration * FPS))
            else:
                frames = _integer(
                    frames_value,
                    name="motion_length_frames",
                    minimum=30,
                    maximum=196,
                )
            generated = self._backend.generate_text(prompt, frames=frames, seed=seed)
            request_summary: dict[str, Any] = {
                "prompt": prompt,
                "motion_length_frames": frames,
                "seed": seed,
            }
        elif job_request.task == "speech_to_gesture":
            audio = _audio_path(
                job_request.input.get("audio"),
                staging_directory=context.staging_directory,
            )
            audio_name = audio.name
            transcript = _text(
                job_request.input.get("transcript"),
                name="input.transcript",
                required=False,
            )
            generated = self._backend.generate_speech(
                audio,
                transcript=transcript,
                seed=seed,
            )
            request_summary = {
                "audio_filename": audio.name,
                "transcript": transcript,
                "seed": seed,
            }
        else:
            audio = _audio_path(
                job_request.input.get("audio"),
                staging_directory=context.staging_directory,
            )
            audio_name = audio.name
            style_prompt = _text(
                job_request.input.get("style_prompt"),
                name="input.style_prompt",
                required=False,
            )
            generated = self._backend.generate_music(
                audio,
                style_prompt=style_prompt,
                seed=seed,
            )
            request_summary = {
                "audio_filename": audio.name,
                "style_prompt": style_prompt,
                "seed": seed,
            }
        context.raise_if_cancelled()
        return self._publish(
            request,
            context,
            generated,
            seed=seed,
            request_summary=request_summary,
            audio_name=audio_name,
        )

    def _publish(
        self,
        request: WorkerInferRequest,
        context: WorkerContext,
        generated: MotionCraftGeneration,
        *,
        seed: int,
        request_summary: dict[str, Any],
        audio_name: str | None,
    ) -> ModelResult:
        staging = context.staging_directory
        arrays = {
            "source_motioncraft_motionx322_normalized": generated.normalized_motion322,
            "source_motioncraft_motionx_mean322": generated.mean322,
            "source_motioncraft_motionx_std322": generated.std322,
        }
        paths: dict[str, Path] = {}
        for name, values in arrays.items():
            path = staging / f"{name}.npy"
            np.save(
                path, np.ascontiguousarray(values, dtype=np.float32), allow_pickle=False
            )
            paths[name] = path
        runtime_id = os.getenv("VIREA_RUNTIME_ID", DEFAULT_RUNTIME_ID)
        metadata_path = staging / "generation_metadata.json"
        write_generation_metadata(
            metadata_path,
            {
                "schema_version": "virea.motioncraft_generation.v1.0.0",
                "job_id": request.job_id,
                "model_id": MODEL_ID,
                "runtime_id": runtime_id,
                "task": generated.task,
                "checkpoint_id": generated.checkpoint_id,
                "source_profile": generated.source_profile,
                "request": request_summary,
                "output": {
                    "frame_count": int(generated.normalized_motion322.shape[0]),
                    "fps": FPS,
                    "representation_id": REPRESENTATION_ID,
                    "conditioning_frames": generated.conditioning_frames,
                },
                "device": self._backend.device_facts,
            },
        )
        locator = request.staging_locator.rstrip("/")
        base = f"virea-job://{request.job_id}/{locator}"
        artifacts = tuple(
            ArtifactRef(
                name=name,
                media_type="application/x-npy",
                uri=f"{base}/{path.name}",
                byte_length=path.stat().st_size,
                dtype="float32",
                shape=tuple(int(axis) for axis in arrays[name].shape),
            )
            for name, path in paths.items()
        ) + (
            ArtifactRef(
                name="generation_metadata",
                media_type="application/json",
                uri=f"{base}/{metadata_path.name}",
                byte_length=metadata_path.stat().st_size,
            ),
        )
        return native_model_result(
            job_id=request.job_id,
            request_id=request.request.idempotency_key,
            task=generated.task,
            model_id=MODEL_ID,
            plugin_version=PLUGIN_VERSION,
            runtime_id=runtime_id,
            upstream_repository="https://github.com/cure-lab/MotionCraft",
            upstream_revision=SOURCE_REVISION,
            artifact_manifest_id="motioncraft-official-three-task-pinned-bundle",
            representation_id=REPRESENTATION_ID,
            skeleton_id=SKELETON_ID,
            fps=FPS,
            frame_count=int(generated.normalized_motion322.shape[0]),
            coordinate_system="motionx.right_handed_y_up_profile_defined_forward",
            units="meters_after_task_checkpoint_denormalization",
            root_translation_semantics="absolute_world_translation_features_309_to_312_with_explicit_source_profile",
            root_rotation_semantics="smplx_global_orient_axis_angle_features_0_to_3_local_to_world",
            artifacts=artifacts,
            seed=seed,
            precision="float32_output",
            device=str(self._backend.device_facts.get("device", "unknown")),
            generation_parameters={
                **request_summary,
                "audio_filename": audio_name,
                "checkpoint_id": generated.checkpoint_id,
                "source_profile": generated.source_profile,
                "fps": FPS,
            },
            sources=(
                SourceRevision(
                    repository="https://github.com/cure-lab/MotionCraft",
                    revision=SOURCE_REVISION,
                    release="AAAI 2025",
                ),
                SourceRevision(
                    repository="https://drive.google.com/drive/folders/1cY7JFtmqBEsI2R_UKcIzxcsLETw1OXwF",
                    revision=CHECKPOINT_REVISION,
                ),
                SourceRevision(
                    repository="https://github.com/openai/CLIP",
                    revision=CLIP_SOURCE_REVISION,
                ),
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-motioncraft-worker")
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
        MotionCraftPlugin(),
        host=args.host,
        port=args.port,
        job_root=args.job_root,
    )


if __name__ == "__main__":
    main()
