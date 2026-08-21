from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
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

from .config import MODEL_SPECS
from .flood_backend import FloodBackend
from .timeline import build_timeline

MODEL_ID = "flood-diffusion-tiny"
PLUGIN_VERSION = "0.1.0"
RUNTIME_ID = "flood-diffusion-tiny-cu128"
VARIANT = "tiny"
FPS = 20.0
REPRESENTATION_ID = "humanml3d.vector263.v1"
SKELETON_ID = "humanml3d.body22.v1"
REQUIRED_SNAPSHOT_FILES = (
    "config.json",
    "hf_pipeline.py",
    "ldf.yaml",
    "model.safetensors",
    "vae.safetensors",
)
TEXT_ENCODER_REPOSITORY = "google/umt5-base"
TEXT_ENCODER_REVISION = "3d0f0ce00e52a86f64385e1b5d0660999c5f96da"
REQUIRED_TEXT_ENCODER_FILES = (
    "config.json",
    "model.safetensors",
    "spiece.model",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)


@dataclass(frozen=True, slots=True)
class _ExplicitSnapshotSettings:
    """The small Settings surface consumed by FloodBackend.

    A Worker must never silently switch to the package cache or download a
    different model.  The control plane installs a concrete snapshot and
    supplies its directory through VIREA_MODEL_ROOT.
    """

    snapshot: Path
    attention_backend: str
    execution_device: str

    def model_dir(self, variant: str) -> Path:
        if variant != VARIANT:
            raise ValueError(f"this worker only supports {VARIANT!r}")
        return self.snapshot


def _require_pinned_files(
    root: Path,
    *,
    label: str,
    revision: str,
    required_files: tuple[str, ...],
) -> Path:
    snapshot = root.expanduser().resolve(strict=False)
    if not snapshot.is_dir():
        raise WorkerFailure(
            "MODEL_SNAPSHOT_NOT_FOUND",
            f"{label} root is not a directory: {snapshot}",
        )

    missing = [name for name in required_files if not (snapshot / name).is_file()]
    if missing:
        raise WorkerFailure(
            "MODEL_SNAPSHOT_INCOMPLETE",
            f"the {label} snapshot is missing required files: " + ", ".join(missing),
        )

    metadata_root = snapshot / ".cache" / "huggingface" / "download"
    revision_mismatches: list[str] = []
    for name in required_files:
        metadata_path = metadata_root / f"{name}.metadata"
        try:
            actual_revision = metadata_path.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            revision_mismatches.append(f"{name}: missing revision metadata")
            continue
        if actual_revision != revision:
            revision_mismatches.append(f"{name}: {actual_revision}")
    if revision_mismatches:
        raise WorkerFailure(
            "MODEL_REVISION_UNVERIFIED",
            "snapshot files are not all attributed to pinned revision "
            f"{revision}: " + "; ".join(revision_mismatches),
        )
    return snapshot


def _require_pinned_snapshot(root: Path) -> Path:
    return _require_pinned_files(
        root,
        label="FloodDiffusionTiny",
        revision=MODEL_SPECS[VARIANT].revision,
        required_files=REQUIRED_SNAPSHOT_FILES,
    )


def _require_pinned_text_encoder(root: Path) -> Path:
    return _require_pinned_files(
        root,
        label="google/umt5-base text encoder",
        revision=TEXT_ENCODER_REVISION,
        required_files=REQUIRED_TEXT_ENCODER_FILES,
    )


@contextmanager
def _redirect_text_encoder_to_local_snapshot(root: Path):
    """Make the upstream fixed repo-id reference resolve to a local snapshot.

    Flood's pinned configuration names ``google/umt5-base`` directly.  Keep
    the upstream model code unchanged while ensuring that both tokenizer and
    encoder resolve to the separately installed, revision-pinned directory.
    """

    from transformers import AutoModel, AutoTokenizer

    original_model_descriptor = AutoModel.__dict__["from_pretrained"]
    original_tokenizer_descriptor = AutoTokenizer.__dict__["from_pretrained"]
    original_model_loader = AutoModel.from_pretrained
    original_tokenizer_loader = AutoTokenizer.from_pretrained

    def model_loader(cls, name_or_path, *args, **kwargs):
        if str(name_or_path) == TEXT_ENCODER_REPOSITORY:
            name_or_path = str(root)
            kwargs["local_files_only"] = True
        return original_model_loader(name_or_path, *args, **kwargs)

    def tokenizer_loader(cls, name_or_path, *args, **kwargs):
        if str(name_or_path) == TEXT_ENCODER_REPOSITORY:
            name_or_path = str(root)
            kwargs["local_files_only"] = True
        return original_tokenizer_loader(name_or_path, *args, **kwargs)

    try:
        AutoModel.from_pretrained = classmethod(model_loader)
        AutoTokenizer.from_pretrained = classmethod(tokenizer_loader)
        yield
    finally:
        AutoModel.from_pretrained = original_model_descriptor
        AutoTokenizer.from_pretrained = original_tokenizer_descriptor


def _require_int(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkerFailure("INVALID_REQUEST", f"{name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise WorkerFailure(
            "INVALID_REQUEST", f"{name} must be in [{minimum}, {maximum}]"
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


class FloodDiffusionTinyPlugin:
    """Real CUDA Worker for the pinned FloodDiffusionTiny checkpoint."""

    def __init__(
        self,
        model_root: str | Path,
        text_encoder_root: str | Path,
        *,
        model_id: str = MODEL_ID,
    ) -> None:
        if model_id != MODEL_ID:
            raise WorkerFailure(
                "INVALID_MODEL_ID",
                f"this worker serves only {MODEL_ID!r}, not {model_id!r}",
            )
        self.model_id = model_id
        self.snapshot = Path(model_root)
        self.text_encoder_snapshot = Path(text_encoder_root)
        self._backend: FloodBackend | None = None
        self._device_facts: dict[str, Any] = {}

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
                "min_vram_gib": None if is_cpu else 16,
                "min_ram_gib": 16.0 if is_cpu else 8.0,
                "memory_strategies": ["cuda_full", "cpu"],
                "active_memory_strategy": active_strategy,
                "resource_profile": os.getenv(
                    "VIREA_RESOURCE_PROFILE",
                    "whole-model-cpu" if is_cpu else "cuda-full",
                ),
                "variant": VARIANT,
                "snapshot_revision": MODEL_SPECS[VARIANT].revision,
                "text_encoder_repository": TEXT_ENCODER_REPOSITORY,
                "text_encoder_revision": TEXT_ENCODER_REVISION,
                "cancel_semantics": "checked_before_and_after_non_preemptive_model_inference",
                **self._device_facts,
            },
        )

    def load(self) -> None:
        memory_strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cuda_full").strip()
        if memory_strategy not in {"cuda_full", "cpu"}:
            raise WorkerFailure(
                "UNSUPPORTED_MEMORY_STRATEGY",
                "FloodDiffusionTiny implements only cuda_full and whole-model cpu strategies",
            )
        snapshot = _require_pinned_snapshot(self.snapshot)
        text_encoder_snapshot = _require_pinned_text_encoder(self.text_encoder_snapshot)
        # Imports inside the upstream model must fail locally instead of
        # consulting the Hub if either installed snapshot is incomplete.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            import torch
        except ImportError as exc:
            raise WorkerFailure(
                "RUNTIME_DEPENDENCY_MISSING", "PyTorch is not installed"
            ) from exc
        if memory_strategy == "cuda_full" and not torch.cuda.is_available():
            raise WorkerFailure(
                "CUDA_UNAVAILABLE",
                "cuda_full requires a CUDA-capable NVIDIA GPU",
            )
        try:
            if memory_strategy == "cuda_full":
                device_index = torch.cuda.current_device()
                properties = torch.cuda.get_device_properties(device_index)
                self._device_facts = {
                    "device": f"cuda:{device_index}",
                    "gpu_name": str(properties.name),
                    "gpu_compute_capability": f"{properties.major}.{properties.minor}",
                    "gpu_total_memory_bytes": int(properties.total_memory),
                    "torch_cuda_version": str(torch.version.cuda),
                }
                attention_backend = (
                    os.getenv("VFR_ATTENTION_BACKEND", "sdpa").strip().lower()
                )
                execution_device = "cuda"
            else:
                self._device_facts = {
                    "device": "cpu",
                    "torch_cuda_version": str(torch.version.cuda),
                }
                attention_backend = "sdpa"
                execution_device = "cpu"
            self._device_facts.update(
                {
                    "memory_strategy": memory_strategy,
                    "resource_profile": os.getenv(
                        "VIREA_RESOURCE_PROFILE",
                        "cuda-full"
                        if memory_strategy == "cuda_full"
                        else "whole-model-cpu",
                    ),
                    "torch_version": str(torch.__version__),
                    "compute_dtype": (
                        "upstream_cuda_mixed"
                        if memory_strategy == "cuda_full"
                        else "float32"
                    ),
                    "attention_backend": attention_backend,
                }
            )
            if attention_backend not in {"auto", "sdpa", "flash"}:
                raise WorkerFailure(
                    "INVALID_RUNTIME_CONFIGURATION",
                    "VFR_ATTENTION_BACKEND must be auto, sdpa, or flash",
                )
            backend = FloodBackend(
                _ExplicitSnapshotSettings(
                    snapshot=snapshot,
                    attention_backend=attention_backend,
                    execution_device=execution_device,
                )
            )
            with _redirect_text_encoder_to_local_snapshot(text_encoder_snapshot):
                backend._load(VARIANT)
            self._backend = backend
        except WorkerFailure:
            raise
        except Exception as exc:
            self.unload()
            raise WorkerFailure(
                "MODEL_LOAD_FAILED",
                f"failed to load pinned FloodDiffusionTiny weights: {type(exc).__name__}: {exc}",
            ) from exc

    def unload(self) -> None:
        if self._backend is not None:
            self._backend.unload()
            self._backend = None

    def cancel(self, job_id: str) -> None:
        # create_worker_app owns the per-job Event. Flood's released whole-
        # sequence callable has no safe mid-kernel cancellation API.
        return None

    def infer(self, request: WorkerInferRequest, context: WorkerContext) -> ModelResult:
        context.raise_if_cancelled()
        if self._backend is None:
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
                "INVALID_TASK", "FloodDiffusionTiny supports only text_to_motion"
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
        seconds = _require_float(
            parameters.get("seconds", 4.0), name="seconds", minimum=1.0, maximum=90.0
        )
        seed = _require_int(
            parameters.get("seed", 42),
            name="seed",
            minimum=0,
            maximum=2_147_483_647,
        )
        denoise_value = parameters.get("denoise_steps")
        denoise_steps = (
            None
            if denoise_value is None
            else _require_int(
                denoise_value, name="denoise_steps", minimum=1, maximum=200
            )
        )
        requested_fps = _require_float(
            parameters.get("fps", FPS), name="fps", minimum=FPS, maximum=FPS
        )
        timeline = build_timeline(
            prompt,
            seconds,
            pre_roll=False,
            neural_return=False,
            max_seconds=90.0,
        )

        try:
            motion = self._backend.generate(
                timeline,
                variant=VARIANT,
                seed=seed,
                denoise_steps=denoise_steps,
            )
        except RuntimeError as exc:
            lowered = str(exc).lower()
            if "out of memory" in lowered or "显存不足" in str(exc):
                raise WorkerFailure("WORKER_OOM", str(exc), retryable=True) from exc
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"FloodDiffusionTiny inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        except Exception as exc:
            raise WorkerFailure(
                "MODEL_INFERENCE_FAILED",
                f"FloodDiffusionTiny inference failed: {type(exc).__name__}: {exc}",
            ) from exc
        context.raise_if_cancelled()

        motion = np.ascontiguousarray(motion, dtype=np.float32)
        frame_count = int(motion.shape[0])
        motion_path = context.staging_directory / "source_humanml3d_263d.npy"
        np.save(motion_path, motion, allow_pickle=False)

        spec = MODEL_SPECS[VARIANT]
        run_metadata = {
            "schema_version": "virea.flood_generation_metadata.v1.0.0",
            "job_id": request.job_id,
            "model": {
                "id": self.model_id,
                "repository": spec.repo_id,
                "revision": spec.revision,
                "variant": VARIANT,
                "snapshot_root": str(self.snapshot.resolve(strict=False)),
            },
            "text_encoder": {
                "repository": TEXT_ENCODER_REPOSITORY,
                "revision": TEXT_ENCODER_REVISION,
                "snapshot_root": str(self.text_encoder_snapshot.resolve(strict=False)),
            },
            "runtime": {
                "runtime_id": os.getenv("VIREA_RUNTIME_ID", RUNTIME_ID),
                **self._device_facts,
                "attention_backend": self._device_facts.get(
                    "attention_backend", "sdpa"
                ),
            },
            "request": {
                "prompt": prompt,
                "seed": seed,
                "seconds": seconds,
                "denoise_steps": denoise_steps,
                "fps": requested_fps,
            },
            "output": {
                "frame_count": frame_count,
                "fps": FPS,
                "dtype": str(motion.dtype),
                "shape": list(motion.shape),
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
                upstream_repository=spec.repo_id,
                upstream_revision=spec.revision,
                runtime_id=os.getenv("VIREA_RUNTIME_ID", RUNTIME_ID),
                artifact_manifest_id="flood-diffusion-tiny-pinned-hf-bundle",
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
                        name="source_humanml3d_263d",
                        media_type="application/x-npy",
                        uri=f"{artifact_base}/{motion_path.name}",
                        byte_length=motion_path.stat().st_size,
                        dtype="float32",
                        shape=(frame_count, 263),
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
                device=str(self._device_facts.get("device", "unknown")),
                generation_parameters={
                    "prompt": prompt,
                    "seconds": seconds,
                    "denoise_steps": denoise_steps,
                    "fps": FPS,
                    "frame_count": frame_count,
                    **self._device_facts,
                },
                sources=(
                    SourceRevision(
                        repository=spec.repo_id,
                        revision=spec.revision,
                        release="FloodDiffusionTiny 2025",
                    ),
                    SourceRevision(
                        repository=TEXT_ENCODER_REPOSITORY,
                        revision=TEXT_ENCODER_REVISION,
                    ),
                ),
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-flood-worker")
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
    model_root = os.getenv("VIREA_MODEL_ROOT")
    if not model_root:
        raise SystemExit("VIREA_MODEL_ROOT must point to the installed pinned snapshot")
    text_encoder_root = os.getenv("VIREA_TEXT_ENCODER_ROOT")
    if not text_encoder_root:
        raise SystemExit(
            "VIREA_TEXT_ENCODER_ROOT must point to the installed pinned "
            "google/umt5-base snapshot"
        )
    serve_plugin(
        FloodDiffusionTinyPlugin(
            model_root,
            text_encoder_root,
            model_id=args.model_id,
        ),
        host=args.host,
        port=args.port,
        job_root=args.job_root,
    )


if __name__ == "__main__":
    main()
