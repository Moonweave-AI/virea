from __future__ import annotations

import gc
import importlib
import os
import random
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from virea_model_sdk import RuntimeResourceStage, WorkerFailure
from virea_model_sdk.upstream_runtime import (
    InstalledArtifactRoots,
    upstream_import_scope,
)

from .audio import finedance_music_features, load_mono_audio
from .portable_moe import install_portable_tutel
from .portable_rotations import install_portable_pytorch3d_transforms

SOURCE_REVISION = "a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9"
CLIP_SOURCE_REVISION = "d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"
CHECKPOINT_REVISION = "google-drive-folder-1cY7JFtmqBEsI2R_UKcIzxcsLETw1OXwF"

_SOURCE_SENTINELS = (
    "source/mogen/models/architectures/diffusion_architecture.py",
    "source/mogen/models/transformers/controlnet.py",
    "source/configs/stmogen/T2M_motionx_align_Finedance_Beats2_face_no_loss_0_125b.py",
    "source/configs/stmogen/S2G_Beats2_no_face_loss_025b.py",
    "source/configs/stmogen/M2D_finedance_no_face_loss_0125b.py",
    "source/data/datasets/motionx/humanml3d_align_mean.npy",
    "source/data/datasets/motionx/humanml3d_align_std.npy",
    "source/data/datasets/beats2/mean.npy",
    "source/data/datasets/beats2/std.npy",
    "source/data/datasets/finedance/mean.npy",
    "source/data/datasets/finedance/std.npy",
)
_CHECKPOINT_SENTINELS = (
    "t2m_no_face_loss_l4_latentdim128_ffsize512/epoch_12.pth",
    "S2G_t2m_no_face_loss_l8_latentdim128_ffsize512/epoch_24.pth",
    "M2D_t2m_no_face_loss_l4_latentdim128_ffsize512/epoch_48.pth",
)


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task: str
    config: str
    checkpoint: str
    checkpoint_id: str
    mean: str
    std: str
    source_profile: str
    clip_frames: int
    overlap_frames: int


_TASKS = {
    "text_to_motion": TaskSpec(
        task="text_to_motion",
        config="configs/stmogen/T2M_motionx_align_Finedance_Beats2_face_no_loss_0_125b.py",
        checkpoint="t2m_no_face_loss_l4_latentdim128_ffsize512/epoch_12.pth",
        checkpoint_id="motioncraft-t2m-gdrive-1wexWc5TQ_ixQ6SsEwrgGOCmdghjUZWt8",
        mean="data/datasets/motionx/humanml3d_align_mean.npy",
        std="data/datasets/motionx/humanml3d_align_std.npy",
        source_profile="motionx.metric_y_up",
        clip_frames=196,
        overlap_frames=0,
    ),
    "speech_to_gesture": TaskSpec(
        task="speech_to_gesture",
        config="configs/stmogen/S2G_Beats2_no_face_loss_025b.py",
        checkpoint="S2G_t2m_no_face_loss_l8_latentdim128_ffsize512/epoch_24.pth",
        checkpoint_id="motioncraft-s2g-gdrive-1oyL8sSrIf2Hz3PUMmrMAyt-bVvqFkLpL",
        mean="data/datasets/beats2/mean.npy",
        std="data/datasets/beats2/std.npy",
        source_profile="motionx.metric_y_up",
        clip_frames=64,
        overlap_frames=4,
    ),
    "music_to_dance": TaskSpec(
        task="music_to_dance",
        config="configs/stmogen/M2D_finedance_no_face_loss_0125b.py",
        checkpoint="M2D_t2m_no_face_loss_l4_latentdim128_ffsize512/epoch_48.pth",
        checkpoint_id="motioncraft-m2d-gdrive-1pBQTu8-gNkUIWzLBJbuvYbUxoUKUhxa-",
        mean="data/datasets/finedance/mean.npy",
        std="data/datasets/finedance/std.npy",
        source_profile="motionx.metric_y_up",
        clip_frames=120,
        overlap_frames=30,
    ),
}


@dataclass(frozen=True, slots=True)
class MotionCraftGeneration:
    normalized_motion322: np.ndarray
    mean322: np.ndarray
    std322: np.ndarray
    checkpoint_id: str
    source_profile: str
    task: str
    conditioning_frames: int | None


class MotionCraftBackend:
    """Runs one released MotionCraft task graph at a time without network access."""

    def __init__(self, roots: InstalledArtifactRoots | None = None) -> None:
        self._roots = roots
        self._source_root: Path | None = None
        self._checkpoint_root: Path | None = None
        self._clip_checkpoint: Path | None = None
        self._torch: Any = None
        self._device: Any = None
        self._model: Any = None
        self._loaded_task: str | None = None
        self._device_facts: dict[str, Any] = {}

    @property
    def device_facts(self) -> dict[str, Any]:
        return dict(self._device_facts)

    @staticmethod
    def _vector(path: Path, label: str) -> np.ndarray:
        values = np.asarray(
            np.load(path, allow_pickle=False), dtype=np.float32
        ).reshape(-1)
        if values.shape != (322,) or not np.isfinite(values).all():
            raise WorkerFailure(
                "NORMALIZATION_CONTRACT_MISMATCH",
                f"{label} must be one finite 322D vector",
            )
        return np.ascontiguousarray(values)

    @staticmethod
    def _install_vis_boundary(torch: Any) -> None:
        module_name = "mogen.models.utils.vis"
        if module_name in sys.modules:
            return
        module = types.ModuleType(module_name)

        class _UnusedSMPLXSkeleton:
            def __init__(self, *_: Any, **__: Any) -> None:
                # MotionDiffusion constructs this renderer helper even though no
                # generation path calls it. Avoid importing PyTorch3D/SMPL-X.
                pass

        module.SMPLX_Skeleton = _UnusedSMPLXSkeleton
        sys.modules[module_name] = module

    @staticmethod
    def _model_options() -> SimpleNamespace:
        return SimpleNamespace(
            repaint=False,
            overlap_len=0,
            fix_very_first=False,
            same_overlap_noisy=False,
            no_resample=True,
            jump_n_sample=1,
            jump_length=1,
            addBlend=False,
            no_repaint=True,
        )

    def _resolve_roots(self) -> None:
        if self._roots is None:
            self._roots = InstalledArtifactRoots.from_environment(
                {
                    "motioncraft-source": _SOURCE_SENTINELS,
                    "motioncraft-task-checkpoints": _CHECKPOINT_SENTINELS,
                    "openai-clip-vit-b32": ("ViT-B-32.pt",),
                }
            )
        self._source_root = self._roots["motioncraft-source"] / "source"
        self._checkpoint_root = self._roots["motioncraft-task-checkpoints"]
        self._clip_checkpoint = self._roots["openai-clip-vit-b32"] / "ViT-B-32.pt"

    def load(self) -> None:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cpu").strip()
        if strategy not in {"cpu", "cuda_full"}:
            raise WorkerFailure(
                "UNSUPPORTED_MEMORY_STRATEGY",
                "MotionCraft implements whole-model CPU and cuda_full",
            )
        try:
            import torch
        except ImportError as exc:
            raise WorkerFailure(
                "RUNTIME_DEPENDENCY_MISSING", "PyTorch is not installed"
            ) from exc
        if strategy == "cuda_full" and not torch.cuda.is_available():
            raise WorkerFailure(
                "CUDA_UNAVAILABLE", "cuda_full requires an NVIDIA CUDA device"
            )
        self._resolve_roots()
        self._torch = torch
        if strategy == "cuda_full":
            index = torch.cuda.current_device()
            properties = torch.cuda.get_device_properties(index)
            self._device = torch.device("cuda", index)
            self._device_facts = {
                "device": f"cuda:{index}",
                "gpu_name": str(properties.name),
                "gpu_total_memory_bytes": int(properties.total_memory),
                "torch_cuda_version": str(torch.version.cuda),
            }
            measurement = RuntimeResourceStage("load", torch=torch, device=self._device)
        else:
            self._device = torch.device("cpu")
            self._device_facts = {
                "device": "cpu",
                "torch_cuda_version": str(torch.version.cuda),
            }
            measurement = RuntimeResourceStage("load")
        self._device_facts.update(
            {
                "memory_strategy": strategy,
                "resource_profile": os.getenv(
                    "VIREA_RESOURCE_PROFILE",
                    "cuda-full" if strategy == "cuda_full" else "whole-model-cpu",
                ),
                "torch_version": str(torch.__version__),
                "compute_dtype": "float32",
                "portable_tutel": True,
                "offline": True,
            }
        )
        with measurement:
            self._load_task("text_to_motion")
        self._device_facts["resource_measurement"] = measurement.result

    def unload(self) -> None:
        self._model = None
        self._loaded_task = None
        gc.collect()
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

    def _load_checkpoint_state(self, path: Path) -> dict[str, Any]:
        try:
            payload = self._torch.load(
                path,
                map_location="cpu",
                weights_only=True,
                mmap=True,
            )
        except TypeError:
            payload = self._torch.load(path, map_location="cpu")
        except Exception as exc:
            raise WorkerFailure(
                "CHECKPOINT_LOAD_FAILED",
                f"could not read official checkpoint {path.name}: {type(exc).__name__}: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH", "checkpoint must contain a mapping"
            )
        state = payload.get("state_dict", payload.get("model", payload))
        if not isinstance(state, dict) or not state:
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH", "checkpoint has no model state_dict"
            )
        normalized: dict[str, Any] = {}
        for key, value in state.items():
            if not isinstance(key, str):
                raise WorkerFailure(
                    "CHECKPOINT_CONTRACT_MISMATCH", "checkpoint keys must be text"
                )
            normalized[key.removeprefix("module.")] = value
        return normalized

    def _load_task(self, task: str) -> None:
        if self._loaded_task == task and self._model is not None:
            return
        if task not in _TASKS:
            raise WorkerFailure("INVALID_TASK", f"unsupported MotionCraft task: {task}")
        if (
            self._source_root is None
            or self._checkpoint_root is None
            or self._clip_checkpoint is None
        ):
            raise WorkerFailure(
                "MODEL_NOT_LOADED", "MotionCraft artifacts are not resolved"
            )
        self.unload()
        spec = _TASKS[task]
        install_portable_tutel(self._torch)
        install_portable_pytorch3d_transforms(self._torch)
        self._install_vis_boundary(self._torch)
        with upstream_import_scope(
            self._source_root,
            working_directory=self._source_root,
            environment={
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
        ):
            import clip
            import mmcv

            original_clip_load = clip.load

            def local_clip_load(name: str, *args: Any, **kwargs: Any) -> Any:
                if name == "ViT-B/32":
                    name = str(self._clip_checkpoint)
                return original_clip_load(name, *args, **kwargs)

            clip.load = local_clip_load
            try:
                importlib.invalidate_caches()
                models = importlib.import_module("mogen.models")
                builder = importlib.import_module("mogen.models.builder")
                config = mmcv.Config.fromfile(str(self._source_root / spec.config))
                config.model["opt"] = self._model_options()
                model = builder.build_architecture(config.model)
                if task != "text_to_motion":
                    control = importlib.import_module(
                        "mogen.models.transformers.controlnet"
                    )
                    model.model = control.ControlT2MHalf(
                        model.model,
                        copy_blocks_num=int(config.copy_blocks_num),
                        control_cond_feats=int(config.control_cond_feats),
                        cfg=config,
                    )
                del models
            finally:
                clip.load = original_clip_load
        state = self._load_checkpoint_state(self._checkpoint_root / spec.checkpoint)
        try:
            incompatible = model.load_state_dict(state, strict=False, assign=True)
        except TypeError:
            incompatible = model.load_state_dict(state, strict=False)
        missing = tuple(incompatible.missing_keys)
        unexpected = tuple(incompatible.unexpected_keys)
        if missing or unexpected:
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH",
                f"{task} state differs: missing={missing[:20]}, unexpected={unexpected[:20]}",
            )
        model.eval()
        self._model = model.to(self._device)
        self._loaded_task = task

    def _seed(self, seed: int) -> None:
        random.seed(seed)
        np.random.seed(seed % (2**32 - 1))
        self._torch.manual_seed(seed)
        if self._device.type == "cuda":
            self._torch.cuda.manual_seed_all(seed)

    def _infer_clip(
        self,
        *,
        frames: int,
        prompt: str,
        condition: np.ndarray | None,
    ) -> np.ndarray:
        motion = self._torch.zeros((1, frames, 322), device=self._device)
        mask = self._torch.ones((1, frames), device=self._device)
        arguments: dict[str, Any] = {
            "motion": motion,
            "motion_mask": mask,
            "motion_length": self._torch.tensor(
                [frames], dtype=self._torch.long, device=self._device
            ),
            "num_intervals": 1,
            "motion_metas": [{"text": prompt}],
            "inference_kwargs": {},
        }
        if condition is not None:
            arguments["c"] = (
                self._torch.from_numpy(
                    np.ascontiguousarray(condition, dtype=np.float32)
                )
                .unsqueeze(0)
                .to(self._device)
            )
        with self._torch.inference_mode():
            result = self._model(**arguments)
        if not isinstance(result, (tuple, list)) or len(result) != 1:
            raise WorkerFailure(
                "MODEL_OUTPUT_INVALID", "MotionCraft returned an invalid batch"
            )
        values = result[0].get("pred_motion") if isinstance(result[0], dict) else None
        if values is None:
            raise WorkerFailure(
                "MODEL_OUTPUT_INVALID", "MotionCraft omitted pred_motion"
            )
        array = (
            values[:frames]
            .detach()
            .float()
            .cpu()
            .numpy()
            .astype(np.float32, copy=False)
        )
        if array.shape != (frames, 322) or not np.isfinite(array).all():
            raise WorkerFailure(
                "MODEL_OUTPUT_INVALID",
                f"invalid MotionCraft output shape {array.shape}",
            )
        return np.ascontiguousarray(array)

    def _chunked_conditioned_inference(
        self,
        *,
        condition: np.ndarray,
        target_frames: int,
        condition_rows_per_frame: int,
        prompt: str,
        spec: TaskSpec,
    ) -> np.ndarray:
        if target_frames < 1:
            raise WorkerFailure(
                "INVALID_AUDIO", "audio conditioning contains no frames"
            )
        if condition_rows_per_frame < 1:
            raise WorkerFailure(
                "AUDIO_FEATURE_FAILED", "conditioning rate must be positive"
            )
        clip_frames = spec.clip_frames
        overlap = spec.overlap_frames
        stride = clip_frames - overlap
        padded_frames = max(clip_frames, target_frames)
        chunk_count = max(1, (padded_frames - overlap + stride - 1) // stride)
        required = (chunk_count - 1) * stride + clip_frames
        required_rows = required * condition_rows_per_frame
        if condition.shape[0] < required_rows:
            condition = np.pad(
                condition,
                ((0, required_rows - condition.shape[0]), (0, 0)),
            )
        chunks: list[np.ndarray] = []
        for index in range(chunk_count):
            start = index * stride
            condition_start = start * condition_rows_per_frame
            condition_end = (start + clip_frames) * condition_rows_per_frame
            current = condition[condition_start:condition_end]
            generated = self._infer_clip(
                frames=clip_frames, prompt=prompt, condition=current
            )
            chunks.append(generated if index == 0 else generated[overlap:])
        return np.ascontiguousarray(np.concatenate(chunks, axis=0)[:target_frames])

    def generate_text(
        self, prompt: str, *, frames: int, seed: int
    ) -> MotionCraftGeneration:
        spec = _TASKS["text_to_motion"]
        self._load_task(spec.task)
        self._seed(seed)
        if not 30 <= frames <= spec.clip_frames:
            raise WorkerFailure(
                "INVALID_REQUEST",
                f"motion_length_frames must be in [30, {spec.clip_frames}]",
            )
        normalized = self._infer_clip(frames=frames, prompt=prompt, condition=None)
        return self._generation(spec, normalized, conditioning_frames=None)

    def generate_speech(
        self,
        audio_path: Path,
        *,
        transcript: str,
        seed: int,
    ) -> MotionCraftGeneration:
        spec = _TASKS["speech_to_gesture"]
        self._load_task(spec.task)
        self._seed(seed)
        waveform = load_mono_audio(audio_path, sample_rate=16_000)
        target_frames = max(1, int(np.floor(waveform.shape[0] * 30.0 / 16_000.0)))
        samples_per_frame = 16_000 // 30
        required_samples = target_frames * samples_per_frame
        if waveform.shape[0] < required_samples:
            waveform = np.pad(waveform, (0, required_samples - waveform.shape[0]))
        condition = waveform[:required_samples, None]
        text = "A person is giving a speech."
        if transcript.strip():
            text = f"A person is giving a speech, and the speech content is: {transcript.strip()}"
        normalized = self._chunked_conditioned_inference(
            condition=condition,
            target_frames=target_frames,
            condition_rows_per_frame=samples_per_frame,
            prompt=text,
            spec=spec,
        )
        return self._generation(spec, normalized, conditioning_frames=target_frames)

    def generate_music(
        self,
        audio_path: Path,
        *,
        style_prompt: str,
        seed: int,
    ) -> MotionCraftGeneration:
        spec = _TASKS["music_to_dance"]
        self._load_task(spec.task)
        self._seed(seed)
        condition = finedance_music_features(audio_path)
        prompt = (
            style_prompt.strip() or "A dancer performs a whole-body dance to the music."
        )
        normalized = self._chunked_conditioned_inference(
            condition=condition,
            target_frames=int(condition.shape[0]),
            condition_rows_per_frame=1,
            prompt=prompt,
            spec=spec,
        )
        return self._generation(
            spec,
            normalized,
            conditioning_frames=int(condition.shape[0]),
        )

    def _generation(
        self,
        spec: TaskSpec,
        normalized: np.ndarray,
        *,
        conditioning_frames: int | None,
    ) -> MotionCraftGeneration:
        if self._source_root is None:
            raise WorkerFailure("MODEL_NOT_LOADED", "MotionCraft source is unavailable")
        return MotionCraftGeneration(
            normalized_motion322=normalized,
            mean322=self._vector(self._source_root / spec.mean, f"{spec.task} mean"),
            std322=self._vector(self._source_root / spec.std, f"{spec.task} std"),
            checkpoint_id=spec.checkpoint_id,
            source_profile=spec.source_profile,
            task=spec.task,
            conditioning_frames=conditioning_frames,
        )
