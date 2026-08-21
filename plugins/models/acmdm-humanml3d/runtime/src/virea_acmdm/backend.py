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
from virea_model_sdk import RuntimeResourceStage, WorkerFailure

from .artifacts import ArtifactRoots, MaterializedArtifacts, materialize_artifacts


@dataclass(frozen=True, slots=True)
class GenerationOutput:
    absolute_positions: np.ndarray
    requested_frames: int
    generated_frames: int


def _eval_decorator(function: Callable[..., Any]) -> Callable[..., Any]:
    """Exact inference-only helper from the pinned upstream eval module."""

    def inner(model, *args, **kwargs):
        was_training = model.training
        model.eval()
        output = function(model, *args, **kwargs)
        model.train(was_training)
        return output

    return inner


class AcmdmBackend:
    """Loads and executes the exact pinned ACMDM-S-PS22 release."""

    def __init__(self, roots: ArtifactRoots, cache_root: Path) -> None:
        self.roots = roots
        self.cache_root = cache_root
        self._artifacts: MaterializedArtifacts | None = None
        self._autoencoder = None
        self._model = None
        self._latent_mean: np.ndarray | None = None
        self._latent_std: np.ndarray | None = None
        self._position_mean: np.ndarray | None = None
        self._position_std: np.ndarray | None = None
        self._source_root: Path | None = None
        self._device_facts: dict[str, Any] = {}
        self._resource_measurement: dict[str, Any] = {
            "schema_version": "virea.runtime_resource_measurement.v1.0.0",
            "host": {},
            "cuda": {},
        }

    def _record_resource_stage(
        self,
        stage: str,
        measurement: RuntimeResourceStage,
    ) -> None:
        result = measurement.result
        self._resource_measurement["host"][stage] = result["host"]
        if "cuda" in result:
            self._resource_measurement["cuda"][stage] = result["cuda"]
        self._device_facts["resource_measurement"] = self._resource_measurement

    @staticmethod
    def _configure_clip_loader(acmdm_module: Any, *, memory_strategy: str) -> None:
        """Keep the released CUDA loader and provide its narrow CPU equivalent.

        The pinned ACMDM constructor loads CLIP on the host, then asserts CUDA
        availability and converts the CLIP weights to fp16.  Neither operation
        changes ACMDM's generation algorithm, but both make the otherwise
        device-derived model impossible to construct in a CPU-only runtime.
        """

        if memory_strategy == "cuda_full":
            return

        def load_and_freeze_clip(_model: Any, clip_version: str) -> Any:
            clip_model, _ = acmdm_module.clip.load(
                clip_version,
                device="cpu",
                jit=False,
            )
            clip_model.float()
            clip_model.eval()
            for parameter in clip_model.parameters():
                parameter.requires_grad = False
            return clip_model

        acmdm_module.ACMDM.load_and_freeze_clip = load_and_freeze_clip

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def device_facts(self) -> dict[str, Any]:
        return dict(self._device_facts)

    @property
    def artifacts(self) -> MaterializedArtifacts:
        if self._artifacts is None:
            raise WorkerFailure("MODEL_NOT_LOADED", "ACMDM artifacts are not loaded")
        return self._artifacts

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
                    f"Python namespace {namespace!r} was imported outside pinned ACMDM source",
                )
        rendered = str(source_root)
        if rendered not in sys.path:
            sys.path.insert(0, rendered)
        importlib.invalidate_caches()

        # models/ACMDM.py imports only eval_decorator from this large evaluation
        # module. The exact released helper is supplied without importing the
        # unrelated dataset, SciPy, evaluator, and visualization stack.
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

    @staticmethod
    def _load_normalization(path: Path, *, width: int, label: str) -> np.ndarray:
        value = np.asarray(np.load(path, allow_pickle=False), dtype=np.float32).reshape(
            -1
        )
        if value.shape != (width,) or not np.isfinite(value).all():
            raise WorkerFailure(
                "NORMALIZATION_CONTRACT_MISMATCH",
                f"{label} must be a finite float32 vector of width {width}",
            )
        return value

    def load(self) -> None:
        memory_strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cuda_full").strip()
        if memory_strategy not in {"cuda_full", "cpu"}:
            raise WorkerFailure(
                "UNSUPPORTED_MEMORY_STRATEGY",
                "ACMDM-S-PS22 implements only cuda_full and whole-model cpu strategies",
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
            measurement = RuntimeResourceStage("load", torch=torch, device=device)
        else:
            device = torch.device("cpu")
            self._device_facts = {
                "device": "cpu",
                "torch_cuda_version": str(torch.version.cuda),
            }
            measurement = RuntimeResourceStage("load")
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
        measurement.__enter__()
        try:
            artifacts = materialize_artifacts(self.roots, cache_root=self.cache_root)
            self._activate_upstream_source(artifacts.source_root)
            ae_module = importlib.import_module("models.AE_2D_Causal")
            acmdm_module = importlib.import_module("models.ACMDM")
            self._configure_clip_loader(
                acmdm_module,
                memory_strategy=memory_strategy,
            )

            autoencoder = ae_module.AE_models["AE_Model"](input_width=3)
            ae_payload = self._load_state(artifacts.autoencoder_checkpoint)
            autoencoder.load_state_dict(
                self._require_state(ae_payload, "ae", label="Causal-AE"),
                strict=True,
                assign=True,
            )
            del ae_payload

            model = acmdm_module.ACMDM_models["ACMDM-Flow-S-PatchSize22"](
                input_dim=autoencoder.output_emb_width,
                cond_mode="text",
                clip_version=str(artifacts.clip_checkpoint),
            )
            model_payload = self._load_state(artifacts.model_checkpoint)
            missing, unexpected = model.load_state_dict(
                self._require_state(model_payload, "ema_acmdm", label="ACMDM"),
                strict=False,
                assign=True,
            )
            if unexpected or any(not key.startswith("clip_model.") for key in missing):
                raise WorkerFailure(
                    "CHECKPOINT_CONTRACT_MISMATCH",
                    "ACMDM state differs from the released architecture: "
                    f"missing={list(missing)}, unexpected={list(unexpected)}",
                )
            del model_payload

            latent_mean = self._load_normalization(
                artifacts.latent_mean,
                width=4,
                label="Causal-AE post mean",
            )
            latent_std = self._load_normalization(
                artifacts.latent_std,
                width=4,
                label="Causal-AE post std",
            )
            position_mean = self._load_normalization(
                artifacts.position_mean,
                width=3,
                label="HumanML3D absolute XYZ mean",
            )
            position_std = self._load_normalization(
                artifacts.position_std,
                width=3,
                label="HumanML3D absolute XYZ std",
            )
            if np.any(latent_std <= 0) or np.any(position_std <= 0):
                raise WorkerFailure(
                    "NORMALIZATION_CONTRACT_MISMATCH",
                    "released ACMDM standard deviations must be strictly positive",
                )

            if memory_strategy == "cpu":
                autoencoder.float()
                model.float()
            autoencoder.to(device).eval()
            model.to(device).eval()
            self._artifacts = artifacts
            self._autoencoder = autoencoder
            self._model = model
            self._latent_mean = latent_mean
            self._latent_std = latent_std
            self._position_mean = position_mean
            self._position_std = position_std
        except WorkerFailure:
            self.unload()
            raise
        except Exception as exc:
            self.unload()
            raise WorkerFailure(
                "MODEL_LOAD_FAILED",
                f"failed to load pinned ACMDM-S-PS22: {type(exc).__name__}: {exc}",
            ) from exc
        finally:
            error_info = sys.exc_info()
            measurement.__exit__(*error_info)
            if error_info[0] is None:
                self._record_resource_stage("load", measurement)

    def unload(self) -> None:
        active_device_type = None
        if self._model is not None:
            try:
                active_device_type = next(self._model.parameters()).device.type
            except (AttributeError, StopIteration):
                pass
        self._autoencoder = None
        self._model = None
        self._latent_mean = None
        self._latent_std = None
        self._position_mean = None
        self._position_std = None
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
            # Preserve the released CUDA evaluation settings rather than
            # silently changing its matrix-multiplication policy.
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True

    def generate(
        self,
        prompt: str,
        *,
        motion_length_frames: int,
        seed: int,
        cfg: float,
    ) -> GenerationOutput:
        if (
            self._autoencoder is None
            or self._model is None
            or self._latent_mean is None
            or self._latent_std is None
            or self._position_mean is None
            or self._position_std is None
        ):
            raise WorkerFailure("MODEL_NOT_LOADED", "ACMDM model is not loaded")
        import torch

        device = next(self._model.parameters()).device
        self._set_seed(seed, use_cuda=device.type == "cuda")
        measurement = (
            RuntimeResourceStage("inference", torch=torch, device=device)
            if device.type == "cuda"
            else RuntimeResourceStage("inference")
        )
        measurement.__enter__()
        try:
            latent_lengths = torch.tensor(
                [motion_length_frames // 4], dtype=torch.long, device=device
            )
            with torch.inference_mode():
                normalized_latents = self._model.generate(
                    [prompt], latent_lengths, cfg, j=22
                )
                latent_array = (
                    normalized_latents.permute(0, 2, 3, 1)
                    .to(dtype=torch.float32)
                    .cpu()
                    .numpy()
                )
                latent_array = latent_array * self._latent_std.reshape(
                    1, 1, 1, 4
                ) + self._latent_mean.reshape(1, 1, 1, 4)
                latent_tensor = (
                    torch.from_numpy(np.ascontiguousarray(latent_array))
                    .to(device=device, dtype=torch.float32)
                    .permute(0, 3, 1, 2)
                )
                normalized_positions = self._autoencoder.decode(latent_tensor)
                positions = normalized_positions.to(dtype=torch.float32).cpu().numpy()
                positions = positions * self._position_std.reshape(
                    1, 1, 1, 3
                ) + self._position_mean.reshape(1, 1, 1, 3)
        finally:
            error_info = sys.exc_info()
            measurement.__exit__(*error_info)
            if error_info[0] is None:
                self._record_resource_stage("inference", measurement)

        expected_shape = (1, motion_length_frames, 22, 3)
        if positions.shape != expected_shape:
            raise WorkerFailure(
                "NATIVE_OUTPUT_CONTRACT_MISMATCH",
                f"ACMDM returned {positions.shape}; expected {expected_shape}",
            )
        absolute_positions = np.ascontiguousarray(positions[0], dtype=np.float32)
        if not np.isfinite(absolute_positions).all():
            raise WorkerFailure(
                "NATIVE_OUTPUT_NONFINITE",
                "ACMDM returned non-finite absolute joint positions",
            )
        return GenerationOutput(
            absolute_positions=absolute_positions,
            requested_frames=motion_length_frames,
            generated_frames=absolute_positions.shape[0],
        )
