from __future__ import annotations

import argparse
import math
import os
import re
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
    SMPLX_REVISION,
    SOURCE_REVISION,
    DartBackend,
    DartTextSegment,
)

MODEL_ID = "dart-smplx"
PLUGIN_VERSION = "0.2.0"
DEFAULT_RUNTIME_ID = "dart-smplx-cpu"
REPRESENTATION_ID = "dart.smplx.body22.axis_angle_primitives.v1"
SKELETON_ID = "smplx.body22.v1"
FPS = 30.0
_TIMELINE_SEGMENT = re.compile(r"^\s*(?P<text>.+?)\s*\*\s*(?P<count>[0-9]+)\s*$")


def _float(value: Any, *, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be numeric") from exc
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise WorkerFailure(
            "INVALID_REQUEST", f"{name} must be in [{minimum:g},{maximum:g}]"
        )
    return parsed


def _primitive_count(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 64:
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be an integer in [1,64]")
    return value


def _timeline(value: Any, *, default_primitives: int) -> tuple[DartTextSegment, ...]:
    segments: list[DartTextSegment] = []
    if isinstance(value, str):
        for index, raw_segment in enumerate(value.split(","), start=1):
            raw_segment = raw_segment.strip()
            if not raw_segment:
                continue
            match = _TIMELINE_SEGMENT.fullmatch(raw_segment)
            if match is None:
                if "," in value or len(value.split(",")) > 1:
                    raise WorkerFailure(
                        "INVALID_REQUEST",
                        "each text_timeline segment must use 'action*primitive_count'",
                    )
                text = raw_segment
                count = default_primitives
            else:
                text = match.group("text").strip()
                count = _primitive_count(
                    int(match.group("count")),
                    name=f"text_timeline[{index}].primitive_count",
                )
            segments.append(DartTextSegment(text=text, primitive_count=count))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise WorkerFailure(
                    "INVALID_REQUEST", "text_timeline list entries must be objects"
                )
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                raise WorkerFailure(
                    "INVALID_REQUEST", f"text_timeline[{index}].text is required"
                )
            count = _primitive_count(
                item.get("primitive_count", default_primitives),
                name=f"text_timeline[{index}].primitive_count",
            )
            segments.append(DartTextSegment(text=text.strip(), primitive_count=count))
    else:
        raise WorkerFailure(
            "INVALID_REQUEST", "text_timeline must be a string or a list of objects"
        )
    if not segments or sum(segment.primitive_count for segment in segments) > 64:
        raise WorkerFailure(
            "INVALID_REQUEST", "text_timeline must contain 1 to 64 total primitives"
        )
    if any(len(segment.text) > 1000 for segment in segments):
        raise WorkerFailure(
            "INVALID_REQUEST",
            "each DART action description is limited to 1000 characters",
        )
    return tuple(segments)


class DartPlugin:
    def __init__(self, backend: DartBackend | None = None) -> None:
        self._backend = backend or DartBackend()

    def metadata(self) -> WorkerMetadata:
        strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cpu")
        return WorkerMetadata(
            model_id=MODEL_ID,
            plugin_version=PLUGIN_VERSION,
            tasks=("streaming_text_to_motion",),
            input_schemas=("virea.job_request.v1.0.0",),
            output_representation_id=REPRESENTATION_ID,
            output_skeleton_id=SKELETON_ID,
            supports_streaming=False,
            supports_cancel=False,
            resources={
                "accelerator": "cpu" if strategy == "cpu" else "nvidia",
                "min_vram_gib": None if strategy == "cpu" else 10.0,
                "min_ram_gib": 24.0 if strategy == "cpu" else 16.0,
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
        if job.task != "streaming_text_to_motion":
            raise WorkerFailure("INVALID_TASK", "unsupported DART task")
        default_primitives = _primitive_count(
            job.parameters.get("primitive_count", 8), name="primitive_count"
        )
        timeline_value = job.input.get("text_timeline", job.input.get("prompt"))
        segments = _timeline(timeline_value, default_primitives=default_primitives)
        seed = job.parameters.get("seed", job.input.get("seed", 0))
        if (
            isinstance(seed, bool)
            or not isinstance(seed, int)
            or not 0 <= seed <= 2_147_483_647
        ):
            raise WorkerFailure(
                "INVALID_REQUEST", "seed must be an integer in [0,2147483647]"
            )
        guidance = _float(
            job.parameters.get("guidance_scale", 5.0),
            name="guidance_scale",
            minimum=0.0,
            maximum=20.0,
        )
        fix_floor = job.parameters.get("fix_floor", False)
        if not isinstance(fix_floor, bool):
            raise WorkerFailure("INVALID_REQUEST", "fix_floor must be boolean")
        generated = self._backend.generate(
            segments,
            seed=seed,
            guidance_scale=guidance,
            fix_floor=fix_floor,
        )
        context.raise_if_cancelled()

        staging = context.staging_directory
        paths = {
            "source_dart_transl": staging / "source_dart_transl.npy",
            "source_dart_global_orient": staging / "source_dart_global_orient.npy",
            "source_dart_body_pose": staging / "source_dart_body_pose.npy",
            "source_dart_primitive_boundaries": staging
            / "source_dart_primitive_boundaries.npy",
            "source_dart_betas": staging / "source_dart_betas.npy",
        }
        arrays = {
            "source_dart_transl": generated.transl,
            "source_dart_global_orient": generated.global_orient,
            "source_dart_body_pose": generated.body_pose,
            "source_dart_primitive_boundaries": generated.primitive_boundaries,
            "source_dart_betas": generated.betas,
        }
        for name, path in paths.items():
            np.save(path, arrays[name], allow_pickle=False)
        runtime_id = os.getenv("VIREA_RUNTIME_ID", DEFAULT_RUNTIME_ID)
        metadata_path = staging / "generation_metadata.json"
        write_generation_metadata(
            metadata_path,
            {
                "schema_version": "virea.dart_generation.v1.0.0",
                "job_id": request.job_id,
                "model_id": MODEL_ID,
                "runtime_id": runtime_id,
                "rollout_reconstructed": True,
                "overlap_continuity_verified": True,
                "rollout_provenance": {
                    "upstream_revision": SOURCE_REVISION,
                    "reconstruction_entrypoint": "mld.rollout_mld.rollout",
                    "virea_wrapper": "virea_dart.backend.DartBackend._rollout",
                    "checkpoint_revision": CHECKPOINT_REVISION,
                    "continuity": generated.continuity_evidence,
                },
                "text_segments": list(generated.text_segments),
                "gender": generated.gender,
                "seed": seed,
                "guidance_scale": guidance,
                "fix_floor": fix_floor,
                "frame_count": int(generated.transl.shape[0]),
                "primitive_count": int(generated.primitive_boundaries.shape[0]),
                "device": self._backend.device_facts,
            },
        )
        frame_count = int(generated.transl.shape[0])
        locator = request.staging_locator.rstrip("/")
        base = f"virea-job://{request.job_id}/{locator}"
        artifacts: list[ArtifactRef] = []
        for name, path in paths.items():
            array = arrays[name]
            artifacts.append(
                ArtifactRef(
                    name=name,
                    media_type="application/x-npy",
                    uri=f"{base}/{path.name}",
                    byte_length=path.stat().st_size,
                    dtype=array.dtype.name,
                    shape=array.shape,
                )
            )
        artifacts.append(
            ArtifactRef(
                name="generation_metadata",
                media_type="application/json",
                uri=f"{base}/{metadata_path.name}",
                byte_length=metadata_path.stat().st_size,
            )
        )
        return native_model_result(
            job_id=request.job_id,
            request_id=job.idempotency_key,
            task=job.task,
            model_id=MODEL_ID,
            plugin_version=PLUGIN_VERSION,
            runtime_id=runtime_id,
            upstream_repository="https://github.com/zkf1997/DART",
            upstream_revision=SOURCE_REVISION,
            artifact_manifest_id="dart-babel-pinned-official-bundle",
            representation_id=REPRESENTATION_ID,
            skeleton_id=SKELETON_ID,
            fps=FPS,
            frame_count=frame_count,
            coordinate_system="amass_smplx.right_handed_z_up",
            units="meters",
            root_translation_semantics="absolute_world_smplx_transl_after_primitive_rollout_reconstruction",
            root_rotation_semantics="smplx_global_orient_axis_angle_local_to_world_after_primitive_rollout_reconstruction",
            artifacts=tuple(artifacts),
            seed=seed,
            precision="float32_output",
            device=str(self._backend.device_facts.get("device", "unknown")),
            generation_parameters={
                "text_segments": [
                    {"text": segment.text, "primitive_count": segment.primitive_count}
                    for segment in segments
                ],
                "seed": seed,
                "guidance_scale": guidance,
                "fix_floor": fix_floor,
            },
            sources=(
                SourceRevision(
                    repository="https://github.com/zkf1997/DART",
                    revision=SOURCE_REVISION,
                    release="ICLR 2025 Spotlight",
                ),
                SourceRevision(
                    repository="https://drive.google.com/drive/folders/1vJg3GFVPT6kr6cA0HrQGmiAEBE2dkaps",
                    revision=CHECKPOINT_REVISION,
                ),
                SourceRevision(
                    repository="https://smpl-x.is.tue.mpg.de/",
                    revision=SMPLX_REVISION,
                ),
                SourceRevision(
                    repository="https://github.com/openai/CLIP",
                    revision=CLIP_REVISION,
                ),
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-dart-worker")
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
    serve_plugin(DartPlugin(), host=args.host, port=args.port, job_root=args.job_root)


if __name__ == "__main__":
    main()
