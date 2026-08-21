from __future__ import annotations

import gc
import importlib
import os
import random
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from virea_model_sdk import WorkerFailure

from .artifacts import ArtifactRoots, MaterializedArtifacts, materialize_artifacts


@dataclass(frozen=True, slots=True)
class GenerationOutput:
    normalized_ric67: np.ndarray
    mean: np.ndarray
    std: np.ndarray
    requested_frames: int | None
    generated_frames: int
    length_was_estimated: bool


def _eval_decorator(function: Callable[..., Any]) -> Callable[..., Any]:
    """Exact inference-only helper imported by the pinned upstream model.

    Upstream keeps this six-line decorator in a large evaluation module whose
    other imports (SciPy, matplotlib, evaluators) are not used by MARDM
    generation. Supplying only this unchanged helper avoids installing the
    unrelated evaluation stack and does not alter sampling mathematics.
    """

    def inner(model, *args, **kwargs):
        was_training = model.training
        model.eval()
        output = function(model, *args, **kwargs)
        model.train(was_training)
        return output

    return inner


class MardmBackend:
    """Loads and executes the exact pinned MARDM SiT-XL source/checkpoints."""

    def __init__(self, roots: ArtifactRoots, cache_root: Path) -> None:
        self.roots = roots
        self.cache_root = cache_root
        self._artifacts: MaterializedArtifacts | None = None
        self._ae = None
        self._model = None
        self._length_estimator = None
        self._mean: np.ndarray | None = None
        self._std: np.ndarray | None = None
        self._source_root: Path | None = None
        self._device_facts: dict[str, Any] = {}

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def device_facts(self) -> dict[str, Any]:
        return dict(self._device_facts)

    @property
    def artifacts(self) -> MaterializedArtifacts:
        if self._artifacts is None:
            raise WorkerFailure("MODEL_NOT_LOADED", "MARDM artifacts are not loaded")
        return self._artifacts

    @staticmethod
    def _configure_clip_loader(mardm_module: Any, *, memory_strategy: str) -> None:
        """Keep the released CUDA loader and provide its narrow CPU equivalent."""

        if memory_strategy == "cuda_full":
            return

        def load_and_freeze_clip(_model: Any, clip_version: str) -> Any:
            clip_model, _ = mardm_module.clip.load(
                clip_version,
                device="cpu",
                jit=False,
            )
            clip_model.float()
            clip_model.eval()
            for parameter in clip_model.parameters():
                parameter.requires_grad = False
            return clip_model

        mardm_module.MARDM.load_and_freeze_clip = load_and_freeze_clip

    @staticmethod
    def _module_belongs_to(module: object, root: Path) -> bool:
        module_file = getattr(module, "__file__", None)
        if module_file:
            try:
                return Path(module_file).resolve().is_relative_to(root)
            except (OSError, ValueError):
                return False
        module_paths = getattr(module, "__path__", ())
        for item in module_paths:
            try:
                if Path(item).resolve().is_relative_to(root):
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _activate_upstream_source(self, source_root: Path) -> None:
        source_root = source_root.resolve(strict=True)
        for namespace in ("models", "diffusions", "utils"):
            existing = sys.modules.get(namespace)
            if existing is not None and not self._module_belongs_to(
                existing, source_root
            ):
                raise WorkerFailure(
                    "UPSTREAM_NAMESPACE_CONFLICT",
                    f"Python namespace {namespace!r} was imported outside pinned MARDM source",
                )
        rendered = str(source_root)
        if rendered not in sys.path:
            sys.path.insert(0, rendered)
        importlib.invalidate_caches()

        # models/MARDM.py imports only eval_decorator from utils.eval_utils.
        # Keep the released source file untouched and provide that exact helper
        # without importing its unused evaluator/plot dependencies.
        importlib.import_module("utils")
        shim = types.ModuleType("utils.eval_utils")
        shim.__file__ = str(source_root / "utils" / "eval_utils.py")
        shim.eval_decorator = _eval_decorator
        sys.modules["utils.eval_utils"] = shim
        setattr(sys.modules["utils"], "eval_utils", shim)
        self._source_root = source_root

    @staticmethod
    def _load_state(path: Path) -> dict[str, Any]:
        import torch

        payload = torch.load(path, map_location="cpu", weights_only=True)
        if not isinstance(payload, dict):
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH",
                f"checkpoint does not contain a mapping: {path}",
            )
        return payload

    @staticmethod
    def _require_state(payload: dict[str, Any], key: str, *, label: str) -> Any:
        state = payload.get(key)
        if not isinstance(state, dict):
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH",
                f"{label} checkpoint is missing state mapping {key!r}",
            )
        return state

    def load(self) -> None:
        memory_strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cuda_full").strip()
        if memory_strategy not in {"cuda_full", "cpu"}:
            raise WorkerFailure(
                "UNSUPPORTED_MEMORY_STRATEGY",
                "MARDM SiT-XL implements only cuda_full and whole-model cpu strategies",
            )
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

        if memory_strategy == "cuda_full":
            device_index = torch.cuda.current_device()
            properties = torch.cuda.get_device_properties(device_index)
            device = torch.device("cuda", device_index)
            self._device_facts = {
                "device": f"cuda:{device_index}",
                "gpu_name": str(properties.name),
                "gpu_compute_capability": f"{properties.major}.{properties.minor}",
                "gpu_total_memory_bytes": int(properties.total_memory),
                "torch_cuda_version": str(torch.version.cuda),
            }
        else:
            device = torch.device("cpu")
            self._device_facts = {
                "device": "cpu",
                "torch_cuda_version": str(torch.version.cuda),
            }
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
                    "mixed_upstream_float16"
                    if memory_strategy == "cuda_full"
                    else "float32"
                ),
            }
        )

        try:
            artifacts = materialize_artifacts(
                self.roots,
                cache_root=self.cache_root,
            )
            self._activate_upstream_source(artifacts.source_root)
            ae_module = importlib.import_module("models.AE")
            mardm_module = importlib.import_module("models.MARDM")
            length_module = importlib.import_module("models.LengthEstimator")
            self._configure_clip_loader(
                mardm_module,
                memory_strategy=memory_strategy,
            )

            ae = ae_module.AE_models["AE_Model"](input_width=67)
            ae_payload = self._load_state(artifacts.autoencoder_checkpoint)
            ae.load_state_dict(
                self._require_state(ae_payload, "ae", label="autoencoder"),
                strict=True,
                assign=True,
            )
            del ae_payload

            model = mardm_module.MARDM_models["MARDM-SiT-XL"](
                ae_dim=ae.output_emb_width,
                cond_mode="text",
                clip_version=str(artifacts.clip_checkpoint),
            )
            model_payload = self._load_state(artifacts.model_checkpoint)
            missing, unexpected = model.load_state_dict(
                self._require_state(model_payload, "ema_mardm", label="MARDM"),
                strict=False,
                assign=True,
            )
            if unexpected or any(not key.startswith("clip_model.") for key in missing):
                raise WorkerFailure(
                    "CHECKPOINT_CONTRACT_MISMATCH",
                    "MARDM state differs from the released architecture: "
                    f"missing={list(missing)}, unexpected={list(unexpected)}",
                )
            del model_payload

            length_estimator = length_module.LengthEstimator(512, 50)
            length_payload = self._load_state(artifacts.length_estimator_checkpoint)
            length_estimator.load_state_dict(
                self._require_state(
                    length_payload, "estimator", label="length estimator"
                ),
                strict=True,
                assign=True,
            )
            del length_payload

            mean = np.load(artifacts.mean, allow_pickle=False)
            std = np.load(artifacts.std, allow_pickle=False)
            mean = np.asarray(mean, dtype=np.float32).reshape(-1)
            std = np.asarray(std, dtype=np.float32).reshape(-1)
            if (
                mean.shape != (67,)
                or std.shape != (67,)
                or not np.isfinite(mean).all()
                or not np.isfinite(std).all()
                or np.any(std <= 0)
            ):
                raise WorkerFailure(
                    "NORMALIZATION_CONTRACT_MISMATCH",
                    "pinned t2m evaluation mean/std must be finite 67-vectors with positive std",
                )

            if memory_strategy == "cpu":
                ae.float()
                model.float()
                length_estimator.float()
            ae.to(device).eval()
            model.to(device).eval()
            length_estimator.to(device).eval()
            self._artifacts = artifacts
            self._ae = ae
            self._model = model
            self._length_estimator = length_estimator
            self._mean = mean
            self._std = std
        except WorkerFailure:
            self.unload()
            raise
        except Exception as exc:
            self.unload()
            raise WorkerFailure(
                "MODEL_LOAD_FAILED",
                f"failed to load pinned MARDM SiT-XL: {type(exc).__name__}: {exc}",
            ) from exc

    def unload(self) -> None:
        active_device_type = None
        if self._model is not None:
            try:
                active_device_type = next(self._model.parameters()).device.type
            except (AttributeError, StopIteration):
                pass
        self._ae = None
        self._model = None
        self._length_estimator = None
        self._mean = None
        self._std = None
        self._artifacts = None
        self._device_facts = {}
        source_root = self._source_root
        self._source_root = None
        if source_root is not None:
            for name, module in list(sys.modules.items()):
                if self._module_belongs_to(module, source_root):
                    sys.modules.pop(name, None)
            rendered = str(source_root)
            sys.path[:] = [entry for entry in sys.path if entry != rendered]
            importlib.invalidate_caches()
        gc.collect()
        try:
            import torch

            if active_device_type == "cuda":
                torch.cuda.empty_cache()
        except Exception:
            pass

    @staticmethod
    def _set_seed(seed: int, *, use_cuda: bool) -> None:
        import torch

        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if use_cuda:
            torch.cuda.manual_seed_all(seed)
            torch.backends.cudnn.benchmark = False
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False

    def generate(
        self,
        prompt: str,
        *,
        motion_length_frames: int | None,
        seed: int,
        time_steps: int,
        cfg: float,
        temperature: float,
        hard_pseudo_reorder: bool,
    ) -> GenerationOutput:
        if (
            self._ae is None
            or self._model is None
            or self._length_estimator is None
            or self._mean is None
            or self._std is None
        ):
            raise WorkerFailure("MODEL_NOT_LOADED", "MARDM model is not loaded")
        import torch
        import torch.nn.functional as functional
        from torch.distributions.categorical import Categorical

        device = next(self._model.parameters()).device
        self._set_seed(seed, use_cuda=device.type == "cuda")
        with torch.inference_mode():
            if motion_length_frames is None:
                text_embedding = self._model.encode_text([prompt])
                distribution = self._length_estimator(text_embedding)
                probabilities = functional.softmax(distribution, dim=-1)
                token_lengths = Categorical(probabilities).sample()
                requested_frames = None
                length_was_estimated = True
            else:
                token_lengths = torch.tensor(
                    [motion_length_frames // 4], device=device, dtype=torch.long
                )
                requested_frames = motion_length_frames
                length_was_estimated = False
            generated_frames = int(token_lengths[0].item()) * 4
            if generated_frames < 4 or generated_frames > 196:
                raise WorkerFailure(
                    "MODEL_LENGTH_ESTIMATION_FAILED",
                    f"released length estimator selected unsupported frame count {generated_frames}",
                )
            latents = self._model.generate(
                [prompt],
                token_lengths,
                time_steps,
                cfg,
                temperature=temperature,
                hard_pseudo_reorder=hard_pseudo_reorder,
            )
            decoded = self._ae.decode(latents)
            normalized = decoded.detach().float().cpu().numpy()[0]

        normalized = np.ascontiguousarray(
            normalized[:generated_frames], dtype=np.float32
        )
        if normalized.shape != (generated_frames, 67):
            raise WorkerFailure(
                "MODEL_OUTPUT_CONTRACT_MISMATCH",
                "MARDM decoder output must have shape "
                f"({generated_frames}, 67), got {normalized.shape}",
            )
        if not np.isfinite(normalized).all():
            raise WorkerFailure(
                "MODEL_OUTPUT_NON_FINITE",
                "MARDM decoder output contains NaN or infinity",
            )
        return GenerationOutput(
            normalized_ric67=normalized,
            mean=self._mean.copy(),
            std=self._std.copy(),
            requested_frames=requested_frames,
            generated_frames=generated_frames,
            length_was_estimated=length_was_estimated,
        )
