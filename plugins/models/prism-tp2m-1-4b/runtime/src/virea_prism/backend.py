from __future__ import annotations

import gc
import os
import random
from dataclasses import dataclass
from typing import Any

import numpy as np
from virea_model_sdk import WorkerFailure, host_memory_snapshot

from .artifacts import PrismArtifactRoots
from .offline_loader import load_offline_prism_pipeline

FPS = 30.0
FEATURE_WIDTH = 69
CUDA_MEMORY_STRATEGY = "cuda_component_split"
CPU_MEMORY_STRATEGY = "cpu"
MEMORY_STRATEGIES = (CUDA_MEMORY_STRATEGY, CPU_MEMORY_STRATEGY)
MIN_FREE_RAM_GIB = 28.0
MIN_POST_LOAD_AVAILABLE_RAM_GIB = 2.0
CPU_MIN_FREE_RAM_GIB = 96.0
CPU_MIN_POST_LOAD_AVAILABLE_RAM_GIB = 8.0
_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class PrismGeneration:
    carrier: np.ndarray
    raw: dict[str, np.ndarray]
    frame_count: int


def portable_memory_observation() -> dict[str, int]:
    """Read host memory through the SDK's Windows/Linux/macOS implementation."""

    try:
        return dict(host_memory_snapshot())
    except Exception as exc:
        raise WorkerFailure(
            "RESOURCE_OBSERVATION_UNAVAILABLE",
            "PRISM could not read cross-platform host memory observations",
        ) from exc


def _require_ram_headroom(
    observation: dict[str, int], *, minimum_gib: float, phase: str
) -> None:
    available = observation["system_ram_available_bytes"]
    required = int(minimum_gib * _GIB)
    if available < required:
        raise WorkerFailure(
            "INSUFFICIENT_MEMORY",
            f"PRISM {phase} requires at least {minimum_gib:g} GiB available RAM; "
            f"observed {available / _GIB:.2f} GiB",
        )


def normalize_public_output(value: Any) -> PrismGeneration:
    if not isinstance(value, dict):
        raise RuntimeError(
            f"PRISM pipeline returned {type(value).__name__}, expected dict"
        )

    def frame_array(name: str, width: int) -> np.ndarray:
        if name not in value:
            raise RuntimeError(f"PRISM public output is missing {name}")
        item = value[name]
        if hasattr(item, "detach"):
            item = item.detach().float().cpu().numpy()
        array = np.asarray(item)
        while array.ndim > 2 and array.shape[0] == 1:
            array = array[0]
        if array.ndim == 3 and array.shape[-2:] == (width // 3, 3):
            array = array.reshape(array.shape[0], width)
        if array.ndim != 2 or array.shape[1] != width:
            raise RuntimeError(
                f"PRISM {name} must have shape (T,{width}), got {array.shape}"
            )
        array = np.asarray(array, dtype=np.float32)
        if not np.isfinite(array).all():
            raise RuntimeError(f"PRISM {name} contains NaN or infinity")
        return np.ascontiguousarray(array)

    translation = frame_array("transl", 3)
    global_orient = frame_array("global_orient", 3)
    body_pose = frame_array("body_pose", 63)
    frame_count = int(translation.shape[0])
    if global_orient.shape[0] != frame_count or body_pose.shape[0] != frame_count:
        raise RuntimeError("PRISM public output has inconsistent frame counts")
    raw: dict[str, np.ndarray] = {}
    for name, item in value.items():
        if hasattr(item, "detach"):
            item = item.detach().float().cpu().numpy()
        array = np.asarray(item)
        while array.ndim > 1 and array.shape[0] == 1:
            array = array[0]
        if (
            array.ndim >= 1
            and array.shape[0] == frame_count
            and np.issubdtype(array.dtype, np.number)
        ):
            numeric = np.asarray(array, dtype=np.float32)
            if not np.isfinite(numeric).all():
                raise RuntimeError(f"PRISM raw field {name} contains NaN or infinity")
            raw[str(name)] = np.ascontiguousarray(numeric)
    raw.update(
        transl=translation,
        global_orient=global_orient,
        body_pose=body_pose,
    )
    carrier = np.concatenate((translation, global_orient, body_pose), axis=1)
    if carrier.shape != (frame_count, FEATURE_WIDTH):
        raise RuntimeError(
            f"PRISM packed public carrier has invalid shape {carrier.shape}"
        )
    return PrismGeneration(
        carrier=np.ascontiguousarray(carrier, dtype=np.float32),
        raw=raw,
        frame_count=frame_count,
    )


class PrismBackend:
    def __init__(self, roots: PrismArtifactRoots) -> None:
        self.roots = roots
        self.pipeline: Any | None = None
        self.device_facts: dict[str, Any] = {}
        self._device_type: str | None = None

    @property
    def loaded(self) -> bool:
        return self.pipeline is not None

    def load(self) -> None:
        selected = os.getenv("VIREA_MEMORY_STRATEGY", CUDA_MEMORY_STRATEGY).strip()
        if selected not in MEMORY_STRATEGIES:
            raise WorkerFailure(
                "UNSUPPORTED_MEMORY_STRATEGY",
                "PRISM implements only cuda_component_split and whole-model cpu strategies",
            )
        is_cpu = selected == CPU_MEMORY_STRATEGY
        minimum_before = CPU_MIN_FREE_RAM_GIB if is_cpu else MIN_FREE_RAM_GIB
        minimum_after = (
            CPU_MIN_POST_LOAD_AVAILABLE_RAM_GIB
            if is_cpu
            else MIN_POST_LOAD_AVAILABLE_RAM_GIB
        )
        memory_before = portable_memory_observation()
        _require_ram_headroom(
            memory_before,
            minimum_gib=minimum_before,
            phase="model load",
        )
        artifacts = self.roots.validate()
        for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "DIFFUSERS_OFFLINE"):
            os.environ[name] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        if not is_cpu:
            os.environ.setdefault(
                "PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:False"
            )
            os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:False")
        import torch

        if not is_cpu and not torch.cuda.is_available():
            raise WorkerFailure(
                "ACCELERATOR_UNAVAILABLE", "PRISM requires a CUDA device"
            )
        device = "cpu" if is_cpu else "cuda:0"
        dtype_name = "float32" if is_cpu else "bfloat16"
        try:
            self.pipeline = load_offline_prism_pipeline(
                artifacts,
                device=device,
                dtype_name=dtype_name,
            )
        except Exception:
            self.unload()
            raise
        memory_after = portable_memory_observation()
        try:
            _require_ram_headroom(
                memory_after,
                minimum_gib=minimum_after,
                phase="post-load operation",
            )
        except WorkerFailure:
            self.unload()
            raise
        self.device_facts = {
            "memory_strategy": selected,
            "device": "cpu" if is_cpu else "cuda:0+cpu:UMT5",
            "text_encoder_device": "cpu",
            "transformer_device": device,
            "vae_device": device,
            "precision": dtype_name,
            "torch_version": str(torch.__version__),
            "torch_cuda_version": str(torch.version.cuda),
            "implicit_network_access": False,
            "min_free_ram_gib": minimum_before,
            "min_post_load_available_ram_gib": minimum_after,
            "ram_before_load": memory_before,
            "ram_after_load": memory_after,
        }
        if not is_cpu:
            properties = torch.cuda.get_device_properties(0)
            self.device_facts.update(
                gpu_name=str(properties.name),
                gpu_compute_capability=f"{properties.major}.{properties.minor}",
                gpu_total_memory_bytes=int(properties.total_memory),
            )
        self._device_type = "cpu" if is_cpu else "cuda"

    def unload(self) -> None:
        active_device_type = self._device_type
        self._device_type = None
        self.pipeline = None
        gc.collect()
        try:
            import torch

            if active_device_type == "cuda":
                torch.cuda.empty_cache()
        except Exception:
            pass

    def generate(
        self,
        prompt: str,
        *,
        num_frames: int,
        seed: int,
        inference_steps: int,
        guidance_scale: float,
    ) -> PrismGeneration:
        if self.pipeline is None:
            raise RuntimeError("PRISM backend is not loaded")
        import torch

        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if self._device_type == "cuda":
            torch.cuda.manual_seed_all(seed)
        memory_before = portable_memory_observation()
        with torch.inference_mode():
            result = self.pipeline(
                prompts=prompt,
                negative_prompt="",
                first_frame_motion_path=None,
                num_frames_per_segment=num_frames,
                num_joints=23,
                num_inference_steps=inference_steps,
                guidance_scale=guidance_scale,
                use_static=False,
                use_smooth=False,
                normalize=False,
                mocap_framerate=FPS,
                gender="neutral",
                max_sequence_length=256,
                overlap_frames=1,
            )
        memory_after = portable_memory_observation()
        minimum_after = float(
            self.device_facts.get(
                "min_post_load_available_ram_gib",
                MIN_POST_LOAD_AVAILABLE_RAM_GIB,
            )
        )
        _require_ram_headroom(
            memory_after,
            minimum_gib=minimum_after,
            phase="post-inference operation",
        )
        self.device_facts.update(
            ram_before_inference=memory_before,
            ram_after_inference=memory_after,
        )
        return normalize_public_output(result)
