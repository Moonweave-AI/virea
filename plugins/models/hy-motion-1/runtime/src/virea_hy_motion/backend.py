from __future__ import annotations

import gc
import os
from dataclasses import dataclass
from typing import Any

import numpy as np
from virea_model_sdk.upstream_runtime import (
    InstalledArtifactRoots,
    upstream_import_scope,
)
from virea_model_sdk.worker import WorkerFailure

SOURCE_REVISION = "4e426f5a1021cbcf7f375458c37b840ee7225229"
MODEL_REVISION = "620dd559f8d964aac2f82f1204fe6a35ad8ad14d"
QWEN_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
CLIP_REVISION = "32bd64288804d66eefd0ccbe215aa642df71cc41"

ARTIFACT_REQUIREMENTS = {
    "hy-motion-source": (
        "source/hymotion/utils/t2m_runtime.py",
        "source/hymotion/pipeline/motion_diffusion.py",
        "source/stats/Mean.npy",
        "source/stats/Std.npy",
        "source/scripts/gradio/static/assets/dump_wooden/v_template.bin",
    ),
    "hy-motion-1-standard": (
        "HY-Motion-1.0/config.yml",
        "HY-Motion-1.0/latest.ckpt",
    ),
    "hy-motion-qwen3-8b": (
        "config.json",
        "model.safetensors.index.json",
        "tokenizer.json",
    ),
    "hy-motion-clip-vit-large-patch14": (
        "config.json",
        "model.safetensors",
        "tokenizer.json",
    ),
}


@dataclass(frozen=True, slots=True)
class HyMotionGeneration:
    translation_m: np.ndarray
    rotations_6d: np.ndarray
    latent_denorm: np.ndarray
    keypoints3d: np.ndarray


class HyMotionBackend:
    """Narrow wrapper around the pinned official ``MotionFlowMatching.generate``."""

    def __init__(self, roots: InstalledArtifactRoots | None = None) -> None:
        self.roots = roots or InstalledArtifactRoots.from_environment(
            ARTIFACT_REQUIREMENTS
        )
        self.source_root = self.roots["hy-motion-source"] / "source"
        self.model_root = self.roots["hy-motion-1-standard"] / "HY-Motion-1.0"
        self._runtime: Any | None = None
        self._torch: Any | None = None
        self._device = "unloaded"

    @property
    def loaded(self) -> bool:
        return self._runtime is not None

    @property
    def device_facts(self) -> dict[str, Any]:
        return {
            "device": self._device,
            "memory_strategy": os.getenv("VIREA_MEMORY_STRATEGY", "cpu"),
            "implicit_network_access": False,
            "source_revision": SOURCE_REVISION,
            "checkpoint_revision": MODEL_REVISION,
            "qwen_revision": QWEN_REVISION,
            "clip_revision": CLIP_REVISION,
        }

    def load(self) -> None:
        if self.loaded:
            return
        strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cpu")
        force_cpu = strategy == "cpu"
        environment = {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "USE_HF_MODELS": "0",
            "TOKENIZERS_PARALLELISM": "false",
        }
        with upstream_import_scope(
            self.source_root,
            working_directory=self.source_root,
            environment=environment,
        ):
            try:
                import torch
                from hymotion.network.text_encoders import text_encoder
                from hymotion.utils import t2m_runtime
            except Exception as exc:
                raise WorkerFailure(
                    "UPSTREAM_IMPORT_FAILED",
                    f"HY-Motion source import failed: {type(exc).__name__}: {exc}",
                ) from exc

            text_encoder.LLM_ENCODER_LAYOUT["qwen3"]["module_path"] = str(
                self.roots["hy-motion-qwen3-8b"]
            )
            text_encoder.SENTENCE_EMB_LAYOUT["clipl"]["module_path"] = str(
                self.roots["hy-motion-clip-vit-large-patch14"]
            )
            # ``hostname -I`` is absent on native Windows and macOS. It is used
            # only for a log label and must not gate official local inference.
            t2m_runtime._get_local_ip = lambda: "localhost"
            try:
                runtime = t2m_runtime.T2MRuntime(
                    config_path=str(self.model_root / "config.yml"),
                    ckpt_name=str(self.model_root / "latest.ckpt"),
                    force_cpu=force_cpu,
                    disable_prompt_engineering=True,
                )
            except Exception as exc:
                if "out of memory" in str(exc).lower():
                    raise WorkerFailure("WORKER_OOM", str(exc), retryable=True) from exc
                raise WorkerFailure(
                    "MODEL_LOAD_FAILED",
                    f"HY-Motion load failed: {type(exc).__name__}: {exc}",
                ) from exc
        self._runtime = runtime
        self._torch = torch
        pipeline = runtime.pipelines[0]
        self._device = str(next(pipeline.parameters()).device)

    def unload(self) -> None:
        runtime, torch_module = self._runtime, self._torch
        self._runtime = None
        self._torch = None
        self._device = "unloaded"
        del runtime
        gc.collect()
        if torch_module is not None and torch_module.cuda.is_available():
            torch_module.cuda.empty_cache()

    def generate(
        self,
        prompt: str,
        *,
        duration_seconds: float,
        seed: int,
        guidance_scale: float,
    ) -> HyMotionGeneration:
        if self._runtime is None:
            raise WorkerFailure("MODEL_NOT_LOADED", "HY-Motion is not loaded")
        runtime = self._runtime
        with upstream_import_scope(
            self.source_root,
            working_directory=self.source_root,
            environment={
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "USE_HF_MODELS": "0",
                "TOKENIZERS_PARALLELISM": "false",
            },
        ):
            pipeline_index = runtime._acquire_pipeline()
            try:
                pipeline = runtime.pipelines[pipeline_index]
                pipeline.eval()
                output = pipeline.generate(
                    prompt,
                    [seed],
                    duration_seconds,
                    cfg_scale=guidance_scale,
                    use_special_game_feat=False,
                )
            except Exception as exc:
                if "out of memory" in str(exc).lower():
                    raise WorkerFailure("WORKER_OOM", str(exc), retryable=True) from exc
                raise
            finally:
                runtime._release_pipeline(pipeline_index)

        def array(name: str, expected_tail: tuple[int, ...]) -> np.ndarray:
            value = output[name]
            if hasattr(value, "detach"):
                value = value.detach().cpu().numpy()
            result = np.asarray(value, dtype=np.float32)
            if result.ndim != len(expected_tail) + 2 or result.shape[0] != 1:
                raise WorkerFailure(
                    "NATIVE_OUTPUT_INVALID",
                    f"HY-Motion {name} has shape {result.shape}",
                )
            result = np.ascontiguousarray(result[0])
            if result.shape[1:] != expected_tail or not np.isfinite(result).all():
                raise WorkerFailure(
                    "NATIVE_OUTPUT_INVALID",
                    f"HY-Motion {name} has shape {result.shape}",
                )
            return result

        translation = array("transl", (3,))
        rotations = array("rot6d", (22, 6))
        latent = array("latent_denorm", (201,))
        keypoints = array("keypoints3d", (22, 3))
        frame_count = translation.shape[0]
        if not (
            rotations.shape[0] == latent.shape[0] == keypoints.shape[0] == frame_count
        ):
            raise WorkerFailure(
                "NATIVE_OUTPUT_INVALID", "HY-Motion decoded streams disagree in length"
            )
        return HyMotionGeneration(translation, rotations, latent, keypoints)
