from __future__ import annotations

import gc
import importlib
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from virea_model_sdk import WorkerFailure

from .artifacts import ArtifactRoots, MaterializedArtifacts, materialize_artifacts


@dataclass(frozen=True, slots=True)
class GenerationOutput:
    denormalized_vector263: np.ndarray
    mean: np.ndarray
    std: np.ndarray
    requested_frames: int
    generated_frames: int


class CmdmBackend:
    """Loads and executes the exact pinned CMDM Causal-DiT/MAC-VAE path."""

    def __init__(self, roots: ArtifactRoots) -> None:
        self.roots = roots
        self._artifacts: MaterializedArtifacts | None = None
        self._autoencoder = None
        self._model = None
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
            raise WorkerFailure("MODEL_NOT_LOADED", "CMDM artifacts are not loaded")
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
        for namespace in ("models", "diffusions"):
            existing = sys.modules.get(namespace)
            if existing is not None and not self._module_belongs_to(
                existing, source_root
            ):
                raise WorkerFailure(
                    "UPSTREAM_NAMESPACE_CONFLICT",
                    f"Python namespace {namespace!r} was imported outside pinned CMDM source",
                )
        rendered = str(source_root)
        if rendered not in sys.path:
            sys.path.insert(0, rendered)
        importlib.invalidate_caches()
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
    def _load_normalization(path: Path, *, label: str) -> np.ndarray:
        value = np.asarray(np.load(path, allow_pickle=False), dtype=np.float32).reshape(
            -1
        )
        if value.shape != (263,) or not np.isfinite(value).all():
            raise WorkerFailure(
                "NORMALIZATION_CONTRACT_MISMATCH",
                f"{label} must be one finite float32 vector of width 263",
            )
        return value

    @staticmethod
    def _require_blackwell_capable_torch(version: str) -> None:
        match = re.match(r"^(\d+)\.(\d+)", version)
        if match is None or tuple(map(int, match.groups())) < (2, 7):
            raise WorkerFailure(
                "RUNTIME_VERSION_UNSUPPORTED",
                f"CMDM requires PyTorch >=2.7 for the Blackwell-capable runtime, got {version}",
            )

    def load(self) -> None:
        memory_strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cuda_full").strip()
        if memory_strategy not in {"cuda_full", "cpu"}:
            raise WorkerFailure(
                "UNSUPPORTED_MEMORY_STRATEGY",
                "CMDM implements only cuda_full and whole-model cpu strategies",
            )
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            import torch
        except ImportError as exc:
            raise WorkerFailure(
                "RUNTIME_DEPENDENCY_MISSING", "PyTorch is not installed"
            ) from exc
        self._require_blackwell_capable_torch(str(torch.__version__))
        if memory_strategy == "cuda_full" and not torch.cuda.is_available():
            raise WorkerFailure(
                "CUDA_UNAVAILABLE", "cuda_full requires a CUDA-capable NVIDIA GPU"
            )

        try:
            artifacts = materialize_artifacts(self.roots)
            self._activate_upstream_source(artifacts.source_root)
            bert_module = importlib.import_module("models.BERT.BERT_encoder")
            dit_module = importlib.import_module("models.Causal_DiT")
            vae_module = importlib.import_module("models.VAE")

            # The pinned source hardcodes the Hub id. Redirect only that locator
            # to the installed immutable snapshot; model/tokenizer construction
            # and all forward mathematics remain upstream code.
            upstream_load_bert = bert_module.load_bert

            def load_installed_bert(_model_path: str, cond_len=None):
                return upstream_load_bert(str(artifacts.text_encoder_root), cond_len)

            dit_module.load_bert = load_installed_bert

            if memory_strategy == "cuda_full":
                device_index = torch.cuda.current_device()
                properties = torch.cuda.get_device_properties(device_index)
                device = torch.device("cuda", device_index)
                self._device_facts = {
                    "device": f"cuda:{device_index}",
                    "gpu_name": str(properties.name),
                    "gpu_compute_capability": (
                        f"{properties.major}.{properties.minor}"
                    ),
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
                }
            )

            autoencoder = vae_module.vae(input_width=263, output_emb_width=64)
            vae_payload = self._load_state(artifacts.vae_checkpoint)
            autoencoder.load_state_dict(
                self._require_state(vae_payload, "ae", label="MAC-VAE"),
                strict=True,
                assign=True,
            )
            del vae_payload

            model = dit_module.dit(
                input_dim=autoencoder.output_emb_width,
                cond_mode="text",
                chunk_size=49,
                n_tokens=49,
                max_length=49,
            )
            model_payload = self._load_state(artifacts.dit_checkpoint)
            missing, unexpected = model.load_state_dict(
                self._require_state(
                    model_payload, "ema_model", label="CMDM Causal-DiT"
                ),
                strict=False,
                assign=True,
            )
            if unexpected or any(not key.startswith("clip_model.") for key in missing):
                raise WorkerFailure(
                    "CHECKPOINT_CONTRACT_MISMATCH",
                    "CMDM state differs from the released architecture: "
                    f"missing={list(missing)}, unexpected={list(unexpected)}",
                )
            del model_payload

            mean = self._load_normalization(artifacts.mean, label="HumanML3D mean")
            std = self._load_normalization(artifacts.std, label="HumanML3D std")
            if np.any(std <= 0):
                raise WorkerFailure(
                    "NORMALIZATION_CONTRACT_MISMATCH",
                    "HumanML3D standard deviation must be strictly positive",
                )

            autoencoder.to(device).eval()
            model.to(device).eval()
            self._artifacts = artifacts
            self._autoencoder = autoencoder
            self._model = model
            self._mean = mean
            self._std = std
        except WorkerFailure:
            self.unload()
            raise
        except Exception as exc:
            self.unload()
            raise WorkerFailure(
                "MODEL_LOAD_FAILED",
                f"failed to load pinned CMDM: {type(exc).__name__}: {exc}",
            ) from exc

    def unload(self) -> None:
        self._autoencoder = None
        self._model = None
        self._mean = None
        self._std = None
        self._artifacts = None
        self._device_facts = {}
        source_root = self._source_root
        self._source_root = None
        if source_root is not None:
            upstream_modules = [
                name
                for name, module in list(sys.modules.items())
                if self._module_belongs_to(module, source_root)
            ]
            for name in sorted(
                upstream_modules, key=lambda value: value.count("."), reverse=True
            ):
                sys.modules.pop(name, None)
            rendered = str(source_root)
            sys.path[:] = [entry for entry in sys.path if entry != rendered]
            importlib.invalidate_caches()
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    @staticmethod
    def _set_seed(seed: int) -> None:
        import torch

        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.benchmark = False
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
            or self._mean is None
            or self._std is None
        ):
            raise WorkerFailure("MODEL_NOT_LOADED", "CMDM model is not loaded")
        if cfg == 1.0:
            raise WorkerFailure(
                "UPSTREAM_CFG_UNSUPPORTED",
                "the pinned CMDM generate method cannot execute cfg exactly 1.0",
            )

        import torch

        self._set_seed(seed)
        device = next(self._model.parameters()).device
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
            self._device_facts["gpu_memory_allocated_before_inference_bytes"] = int(
                torch.cuda.memory_allocated(device)
            )
        token_length = motion_length_frames // 4
        with torch.inference_mode():
            latent_lengths = torch.tensor(
                [token_length], device=device, dtype=torch.long
            )
            latents = self._model.generate([prompt], latent_lengths, cfg)
            if latents.ndim != 4 or latents.shape[2] != 1:
                raise WorkerFailure(
                    "MODEL_OUTPUT_CONTRACT_MISMATCH",
                    f"CMDM latent output must be [B,L,1,64], got {tuple(latents.shape)}",
                )
            decoded = self._autoencoder.decode(latents.squeeze(2))
            normalized = decoded.detach().float().cpu().numpy()[0, :, 0, :]
        if device.type == "cuda":
            # The device-to-host copy above is a synchronization boundary, so
            # this is the real allocator peak for the complete released CMDM
            # generate + MAC-VAE decode call, including resident weights.
            self._device_facts["gpu_peak_memory_allocated_bytes"] = int(
                torch.cuda.max_memory_allocated(device)
            )

        normalized = np.ascontiguousarray(normalized, dtype=np.float32)
        if normalized.shape != (motion_length_frames, 263):
            raise WorkerFailure(
                "MODEL_OUTPUT_CONTRACT_MISMATCH",
                "CMDM decoder output must have shape "
                f"({motion_length_frames}, 263), got {normalized.shape}",
            )
        if not np.isfinite(normalized).all():
            raise WorkerFailure(
                "MODEL_OUTPUT_NON_FINITE",
                "CMDM decoder output contains NaN or infinity",
            )
        denormalized = np.ascontiguousarray(
            normalized * self._std + self._mean,
            dtype=np.float32,
        )
        if not np.isfinite(denormalized).all():
            raise WorkerFailure(
                "MODEL_OUTPUT_NON_FINITE",
                "CMDM inverse-normalized output contains NaN or infinity",
            )
        return GenerationOutput(
            denormalized_vector263=denormalized,
            mean=self._mean.copy(),
            std=self._std.copy(),
            requested_frames=motion_length_frames,
            generated_frames=motion_length_frames,
        )
