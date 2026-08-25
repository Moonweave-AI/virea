from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Sequence

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
    SOURCE_REVISION,
    SentiAvatarBackend,
)

MODEL_ID = "sentiavatar-susu"
PLUGIN_VERSION = "0.2.0"
DEFAULT_RUNTIME_ID = "sentiavatar-susu-cpu"
REPRESENTATION_ID = "susu.body25_hands40.cont6d_root_delta.v1"
SKELETON_ID = "susu.body25_hands40.v1"
FPS = 20.0
CHECKPOINT_ID = f"Chuhaojin/SentiAvatar@{CHECKPOINT_REVISION}"


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


def _integer(
    value: Any,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise WorkerFailure(
            "INVALID_REQUEST", f"{name} must be in [{minimum}, {maximum}]"
        )
    return value


def _boolean(value: Any, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise WorkerFailure("INVALID_REQUEST", f"{name} must be true or false")


def _text(value: Any, *, name: str, maximum: int = 8_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be non-empty text")
    parsed = value.strip()
    if len(parsed) > maximum:
        raise WorkerFailure("INVALID_REQUEST", f"{name} exceeds {maximum} characters")
    return parsed


def _sequence(value: Any, *, name: str) -> tuple[Any, ...]:
    if isinstance(value, str):
        rendered = value.strip()
        if rendered.startswith("["):
            try:
                decoded = json.loads(rendered)
            except json.JSONDecodeError as exc:
                raise WorkerFailure(
                    "INVALID_REQUEST", f"{name} JSON array is invalid"
                ) from exc
            value = decoded
        else:
            return (value,)
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be a JSON array")
    result = tuple(value)
    if not result or len(result) > 64:
        raise WorkerFailure(
            "INVALID_REQUEST", f"{name} must contain between 1 and 64 items"
        )
    return result


def _task_inputs(
    request: WorkerInferRequest,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    values = request.request.input
    if request.request.task == "audio_text_to_avatar_motion":
        audio = _text(values.get("audio"), name="input.audio", maximum=96_000_000)
        dialogue = _text(values.get("dialogue_text"), name="input.dialogue_text")
        tags_raw = values.get("action_and_expression_tags", "动作：说话")
        tags = _text(tags_raw, name="input.action_and_expression_tags")
        return (audio,), (f"{tags}{dialogue}",)
    if request.request.task == "streaming_dialogue_avatar_motion":
        audio_values = _sequence(values.get("audio_chunks"), name="input.audio_chunks")
        turn_values = _sequence(
            values.get("dialogue_turns"), name="input.dialogue_turns"
        )
        audios = tuple(
            _text(value, name=f"input.audio_chunks[{index}]", maximum=96_000_000)
            for index, value in enumerate(audio_values)
        )
        turns = tuple(
            _text(value, name=f"input.dialogue_turns[{index}]")
            for index, value in enumerate(turn_values)
        )
        if len(turns) == 1 and len(audios) > 1:
            turns = turns * len(audios)
        if len(audios) != len(turns):
            raise WorkerFailure(
                "INVALID_REQUEST",
                "audio_chunks and dialogue_turns must have equal length",
            )
        return audios, tuple(f"动作：说话{turn}" for turn in turns)
    raise WorkerFailure("INVALID_TASK", "SentiAvatar task is not supported")


class SentiAvatarPlugin:
    def __init__(self, backend: SentiAvatarBackend | None = None) -> None:
        self._backend = backend or SentiAvatarBackend()

    def metadata(self) -> WorkerMetadata:
        strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cpu")
        return WorkerMetadata(
            model_id=MODEL_ID,
            plugin_version=PLUGIN_VERSION,
            tasks=(
                "audio_text_to_avatar_motion",
                "streaming_dialogue_avatar_motion",
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
                **self._backend.device_facts,
            },
        )

    def load(self) -> None:
        self._backend.load()

    def unload(self) -> None:
        self._backend.unload()

    def cancel(self, job_id: str) -> None:
        del job_id
        # The supervisor owns the isolated process tree and terminates it if an
        # upstream transformer call cannot reach a cooperative boundary promptly.

    def infer(self, request: WorkerInferRequest, context: WorkerContext) -> ModelResult:
        context.raise_if_cancelled()
        if request.request.model_id != MODEL_ID:
            raise WorkerFailure("INVALID_MODEL_ID", "request targets another model")
        audios, action_texts = _task_inputs(request)
        parameters = request.request.parameters
        seed = _integer(
            parameters.get("seed", 3407),
            name="seed",
            minimum=0,
            maximum=2_147_483_647 - len(audios),
        )
        temperature = _number(
            parameters.get("temperature", 0.2),
            name="temperature",
            minimum=0.05,
            maximum=2.0,
        )
        top_p = _number(
            parameters.get("top_p", 0.2),
            name="top_p",
            minimum=0.05,
            maximum=1.0,
        )
        generate_steps = _integer(
            parameters.get("generate_steps", 6),
            name="generate_steps",
            minimum=1,
            maximum=24,
        )
        max_new_tokens = _integer(
            parameters.get("planner_max_new_tokens", 1024),
            name="planner_max_new_tokens",
            minimum=64,
            maximum=1024,
        )
        generate_face = _boolean(
            parameters.get("generate_face", True), name="generate_face"
        )
        try:
            generated = self._backend.generate(
                audios,
                action_texts,
                seed=seed,
                temperature=temperature,
                top_p=top_p,
                generate_steps=generate_steps,
                max_new_tokens=max_new_tokens,
                generate_face=generate_face,
            )
        except WorkerFailure:
            raise
        except Exception as exc:
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"SentiAvatar inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        context.raise_if_cancelled()

        arrays = {
            "source_sentiavatar_body153_normalized": generated.body153_normalized,
            "source_sentiavatar_left_hand120_denormalized": (
                generated.left_hand120_denormalized
            ),
            "source_sentiavatar_right_hand120_denormalized": (
                generated.right_hand120_denormalized
            ),
            "source_sentiavatar_body_mean153": generated.body_mean153,
            "source_sentiavatar_body_std153": generated.body_std153,
        }
        if generated.face_arkit51 is not None:
            arrays["source_sentiavatar_face_arkit51"] = generated.face_arkit51
        staging = context.staging_directory
        paths: dict[str, Path] = {}
        for name, values in arrays.items():
            path = staging / f"{name}.npy"
            np.save(
                path, np.ascontiguousarray(values, dtype=np.float32), allow_pickle=False
            )
            paths[name] = path
        runtime_id = os.getenv("VIREA_RUNTIME_ID", DEFAULT_RUNTIME_ID)
        frame_count = int(generated.body153_normalized.shape[0])
        metadata_path = staging / "generation_metadata.json"
        write_generation_metadata(
            metadata_path,
            {
                "schema_version": "virea.sentiavatar_generation.v1.0.0",
                "job_id": request.job_id,
                "model_id": MODEL_ID,
                "runtime_id": runtime_id,
                "checkpoint_id": CHECKPOINT_ID,
                "hands_are_denormalized": True,
                "official_hand_source": (
                    "motion_generation/meta/xiu_joint_quat_vecs/Daiji_A_001_V001.npy"
                ),
                "face_generated": generated.face_arkit51 is not None,
                "chunk_count": generated.chunk_count,
                "output": {
                    "frame_count": frame_count,
                    "fps": FPS,
                    "representation_id": REPRESENTATION_ID,
                },
                "parameters": {
                    "seed": seed,
                    "temperature": temperature,
                    "top_p": top_p,
                    "generate_steps": generate_steps,
                    "planner_max_new_tokens": max_new_tokens,
                    "generate_face": generate_face,
                },
                "device": self._backend.device_facts,
            },
        )
        locator = request.staging_locator.rstrip("/")
        base = f"virea-job://{request.job_id}/{locator}"
        warnings = (
            "The released single-case pipeline supplies both hand streams from "
            "its pinned neutral-hand source asset; the body and optional face are "
            "generated from the request audio.",
        )
        return native_model_result(
            job_id=request.job_id,
            request_id=request.request.idempotency_key,
            task=request.request.task,
            model_id=MODEL_ID,
            plugin_version=PLUGIN_VERSION,
            runtime_id=runtime_id,
            upstream_repository="https://github.com/SentiAvatar/SentiAvatar",
            upstream_revision=SOURCE_REVISION,
            artifact_manifest_id="sentiavatar-susu-pinned-official-bundle",
            representation_id=REPRESENTATION_ID,
            skeleton_id=SKELETON_ID,
            fps=FPS,
            frame_count=frame_count,
            coordinate_system="susu_native_xyz",
            units="centimeters_for_native_root_channel_rotations_unitless",
            root_translation_semantics=(
                "differential_root_offsets_integrated_downstream_from_native_seed"
            ),
            root_rotation_semantics=(
                "body25_parent_local_continuous_6d_with_native_pelvis_correction"
            ),
            artifacts=(
                *(
                    ArtifactRef(
                        name=name,
                        media_type="application/x-npy",
                        uri=f"{base}/{path.name}",
                        byte_length=path.stat().st_size,
                        dtype="float32",
                        shape=tuple(int(axis) for axis in arrays[name].shape),
                    )
                    for name, path in paths.items()
                ),
                ArtifactRef(
                    name="generation_metadata",
                    media_type="application/json",
                    uri=f"{base}/{metadata_path.name}",
                    byte_length=metadata_path.stat().st_size,
                ),
            ),
            seed=seed,
            precision="float32_native_streams",
            device=str(self._backend.device_facts.get("device", "unknown")),
            generation_parameters={
                "seed": seed,
                "temperature": temperature,
                "top_p": top_p,
                "generate_steps": generate_steps,
                "planner_max_new_tokens": max_new_tokens,
                "generate_face": generate_face,
                "chunk_count": generated.chunk_count,
                "hands_are_denormalized": True,
            },
            sources=(
                SourceRevision(
                    repository="https://github.com/SentiAvatar/SentiAvatar",
                    revision=SOURCE_REVISION,
                    release="2026",
                ),
                SourceRevision(
                    repository="Chuhaojin/SentiAvatar",
                    revision=CHECKPOINT_REVISION,
                ),
            ),
            warnings=warnings,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-sentiavatar-worker")
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
        SentiAvatarPlugin(),
        host=args.host,
        port=args.port,
        job_root=args.job_root,
    )


if __name__ == "__main__":
    main()
