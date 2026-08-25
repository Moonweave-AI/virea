from __future__ import annotations

import gc
import importlib
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from virea_model_sdk import RuntimeResourceStage, WorkerFailure

from .artifacts import ArtifactRoots, MaterializedArtifacts, materialize_artifacts


@dataclass(frozen=True, slots=True)
class GenerationOutput:
    motion263: np.ndarray
    generated_frames: int


class DiscordBackend:
    """Pinned MoMask token generator plus official DisCoRD RF decoder."""

    def __init__(self, roots: ArtifactRoots, cache_root: Path) -> None:
        self.roots = roots
        self.cache_root = cache_root
        self._artifacts: MaterializedArtifacts | None = None
        self._vq_model: Any = None
        self._mask_transformer: Any = None
        self._residual_transformer: Any = None
        self._rf_decoder: Any = None
        self._mean: np.ndarray | None = None
        self._std: np.ndarray | None = None
        self._source_root: Path | None = None
        self._device_facts: dict[str, Any] = {}
        self._resource_measurement: dict[str, Any] = {
            "schema_version": "virea.runtime_resource_measurement.v1.0.0",
            "host": {},
            "cuda": {},
        }

    @property
    def loaded(self) -> bool:
        return self._rf_decoder is not None

    @property
    def device_facts(self) -> dict[str, Any]:
        return dict(self._device_facts)

    @staticmethod
    def _module_belongs_to(module: object, root: Path) -> bool:
        module_file = getattr(module, "__file__", None)
        if module_file:
            try:
                return Path(module_file).resolve().is_relative_to(root)
            except (OSError, ValueError):
                return False
        for item in getattr(module, "__path__", ()):
            try:
                if Path(item).resolve().is_relative_to(root):
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _activate_source(self, root: Path) -> None:
        root = root.resolve(strict=True)
        for namespace in (
            "MotionGen",
            "MotionPriors",
            "evaluation",
            "configs",
            "utils",
        ):
            existing = sys.modules.get(namespace)
            if existing is not None and not self._module_belongs_to(existing, root):
                raise WorkerFailure(
                    "UPSTREAM_NAMESPACE_CONFLICT",
                    f"Python namespace {namespace!r} was imported outside pinned DisCoRD source",
                )
        rendered = str(root)
        if rendered not in sys.path:
            sys.path.insert(0, rendered)
        importlib.invalidate_caches()
        self._source_root = root

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
    def _state(payload: dict[str, Any], *keys: str, label: str) -> dict[str, Any]:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        # The DisCoRD RF release is itself a plain state_dict.
        if (
            keys == ("__root__",)
            and payload
            and all(isinstance(key, str) for key in payload)
        ):
            return payload
        raise WorkerFailure(
            "CHECKPOINT_CONTRACT_MISMATCH",
            f"{label} checkpoint is missing state mapping {keys!r}",
        )

    @staticmethod
    def _vector(path: Path, *, label: str) -> np.ndarray:
        value = np.asarray(np.load(path, allow_pickle=False), dtype=np.float32).reshape(
            -1
        )
        if value.shape != (263,) or not np.isfinite(value).all():
            raise WorkerFailure(
                "NORMALIZATION_CONTRACT_MISMATCH",
                f"{label} must be finite float32[263]",
            )
        return value

    def _record(self, stage: str, measurement: RuntimeResourceStage) -> None:
        result = measurement.result
        self._resource_measurement["host"][stage] = result["host"]
        if "cuda" in result:
            self._resource_measurement["cuda"][stage] = result["cuda"]
        self._device_facts["resource_measurement"] = self._resource_measurement

    def load(self) -> None:
        strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cuda_full").strip()
        if strategy not in {"cuda_full", "cpu"}:
            raise WorkerFailure(
                "UNSUPPORTED_MEMORY_STRATEGY",
                "DisCoRD implements only cuda_full and whole-model cpu strategies",
            )
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
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
        if strategy == "cuda_full":
            index = torch.cuda.current_device()
            properties = torch.cuda.get_device_properties(index)
            device = torch.device("cuda", index)
            self._device_facts = {
                "device": f"cuda:{index}",
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
                "memory_strategy": strategy,
                "resource_profile": os.getenv(
                    "VIREA_RESOURCE_PROFILE",
                    "cuda-full" if strategy == "cuda_full" else "whole-model-cpu",
                ),
                "torch_version": str(torch.__version__),
                "compute_dtype": "float32"
                if strategy == "cpu"
                else "upstream_clip_float16_generator_float32",
            }
        )

        measurement.__enter__()
        try:
            artifacts = materialize_artifacts(self.roots, cache_root=self.cache_root)
            self._activate_source(artifacts.source_root)
            get_opt = importlib.import_module("evaluation.get_opt").get_opt
            trans_module = importlib.import_module(
                "MotionGen.momask_transformer.transformer"
            )
            vq_module = importlib.import_module("MotionPriors.models.vq.model")
            rf_factory = importlib.import_module("MotionPriors.models.rf_decoder")
            rf_module = importlib.import_module(
                "MotionPriors.models.rf_decoder.rectified_flow"
            )
            OmegaConf = importlib.import_module("omegaconf").OmegaConf

            vq_opt = get_opt(str(artifacts.vq_opt), device=device)
            vq_model = vq_module.RVQVAE(
                vq_opt,
                263,
                vq_opt.nb_code,
                vq_opt.code_dim,
                vq_opt.output_emb_width,
                vq_opt.down_t,
                vq_opt.stride_t,
                vq_opt.width,
                vq_opt.depth,
                vq_opt.dilation_growth_rate,
                vq_opt.vq_act,
                vq_opt.vq_norm,
            )
            vq_payload = self._load_state(artifacts.vq_checkpoint)
            vq_model.load_state_dict(
                self._state(vq_payload, "vq_model", "net", label="MoMask RVQ-VAE"),
                strict=True,
                assign=True,
            )

            mask_opt = get_opt(str(artifacts.mask_opt), device=device)
            mask_opt.num_tokens = vq_opt.nb_code
            mask_opt.num_quantizers = vq_opt.num_quantizers
            mask_opt.code_dim = vq_opt.code_dim
            mask_transformer = trans_module.MaskTransformer(
                code_dim=mask_opt.code_dim,
                cond_mode="text",
                latent_dim=mask_opt.latent_dim,
                ff_size=mask_opt.ff_size,
                num_layers=mask_opt.n_layers,
                num_heads=mask_opt.n_heads,
                dropout=mask_opt.dropout,
                clip_dim=512,
                cond_drop_prob=mask_opt.cond_drop_prob,
                clip_version=str(artifacts.clip_checkpoint),
                opt=mask_opt,
            )
            mask_payload = self._load_state(artifacts.mask_checkpoint)
            missing, unexpected = mask_transformer.load_state_dict(
                self._state(
                    mask_payload,
                    "t2m_transformer",
                    "trans",
                    label="MoMask mask transformer",
                ),
                strict=False,
                assign=True,
            )
            if unexpected or any(not key.startswith("clip_model.") for key in missing):
                raise WorkerFailure(
                    "CHECKPOINT_CONTRACT_MISMATCH",
                    f"MoMask mask-transformer state differs: missing={list(missing)}, unexpected={list(unexpected)}",
                )

            residual_opt = get_opt(str(artifacts.residual_opt), device=device)
            residual_opt.num_quantizers = vq_opt.num_quantizers
            residual_opt.num_tokens = vq_opt.nb_code
            residual_transformer = trans_module.ResidualTransformer(
                code_dim=vq_opt.code_dim,
                cond_mode="text",
                latent_dim=residual_opt.latent_dim,
                ff_size=residual_opt.ff_size,
                num_layers=residual_opt.n_layers,
                num_heads=residual_opt.n_heads,
                dropout=residual_opt.dropout,
                clip_dim=512,
                shared_codebook=vq_opt.shared_codebook,
                cond_drop_prob=residual_opt.cond_drop_prob,
                share_weight=residual_opt.share_weight,
                clip_version=str(artifacts.clip_checkpoint),
                opt=residual_opt,
            )
            residual_payload = self._load_state(artifacts.residual_checkpoint)
            missing, unexpected = residual_transformer.load_state_dict(
                self._state(
                    residual_payload,
                    "res_transformer",
                    label="MoMask residual transformer",
                ),
                strict=False,
                assign=True,
            )
            if unexpected or any(not key.startswith("clip_model.") for key in missing):
                raise WorkerFailure(
                    "CHECKPOINT_CONTRACT_MISMATCH",
                    f"MoMask residual-transformer state differs: missing={list(missing)}, unexpected={list(unexpected)}",
                )

            rf_config = OmegaConf.load(
                str(artifacts.source_root / "configs" / "config_model.yaml")
            )
            rf_decoder = rf_module.RectifiedFlowDecoder(
                model=rf_factory.get_flow_backbone(rf_config)
            )
            rf_payload = self._load_state(artifacts.rf_checkpoint)
            rf_decoder.load_state_dict(
                self._state(rf_payload, "__root__", label="DisCoRD RF decoder"),
                strict=True,
                assign=True,
            )
            mean = self._vector(artifacts.mean, label="DisCoRD HumanML3D mean")
            std = self._vector(artifacts.std, label="DisCoRD HumanML3D std")
            if np.any(std <= 0):
                raise WorkerFailure(
                    "NORMALIZATION_CONTRACT_MISMATCH",
                    "DisCoRD HumanML3D standard deviation must be positive",
                )

            for model in (vq_model, mask_transformer, residual_transformer, rf_decoder):
                if strategy == "cpu":
                    model.float()
                model.to(device).eval()
            residual_transformer.clip_model = mask_transformer.clip_model
            self._artifacts = artifacts
            self._vq_model = vq_model
            self._mask_transformer = mask_transformer
            self._residual_transformer = residual_transformer
            self._rf_decoder = rf_decoder
            self._mean = mean
            self._std = std
        except WorkerFailure:
            self.unload()
            raise
        except Exception as exc:
            self.unload()
            raise WorkerFailure(
                "MODEL_LOAD_FAILED",
                f"failed to load pinned DisCoRD: {type(exc).__name__}: {exc}",
            ) from exc
        finally:
            error_info = sys.exc_info()
            measurement.__exit__(*error_info)
            if error_info[0] is None:
                self._record("load", measurement)

    def unload(self) -> None:
        active_device = None
        if self._rf_decoder is not None:
            try:
                active_device = next(self._rf_decoder.parameters()).device.type
            except (AttributeError, StopIteration):
                pass
        self._vq_model = self._mask_transformer = self._residual_transformer = (
            self._rf_decoder
        ) = None
        self._mean = self._std = self._artifacts = None
        self._device_facts = {}
        root = self._source_root
        self._source_root = None
        if root is not None:
            for name, module in list(sys.modules.items()):
                if self._module_belongs_to(module, root):
                    sys.modules.pop(name, None)
            rendered = str(root)
            sys.path[:] = [entry for entry in sys.path if entry != rendered]
            importlib.invalidate_caches()
        gc.collect()
        try:
            import torch

            if active_device == "cuda":
                torch.cuda.empty_cache()
        except Exception:
            pass

    @staticmethod
    def _seed(seed: int, *, cuda: bool) -> None:
        import torch

        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if cuda:
            torch.cuda.manual_seed_all(seed)
            torch.backends.cudnn.benchmark = False

    def generate(
        self,
        prompt: str,
        *,
        motion_length_frames: int,
        seed: int,
        time_steps: int,
        cond_scale: float,
        temperature: float,
        topk_filter_thres: float,
        residual_cond_scale: float,
        rf_steps: int,
    ) -> GenerationOutput:
        if any(
            value is None
            for value in (
                self._vq_model,
                self._mask_transformer,
                self._residual_transformer,
                self._rf_decoder,
                self._mean,
                self._std,
            )
        ):
            raise WorkerFailure("MODEL_NOT_LOADED", "DisCoRD model is not loaded")
        import torch

        device = next(self._rf_decoder.parameters()).device
        self._seed(seed, cuda=device.type == "cuda")
        measurement = (
            RuntimeResourceStage("inference", torch=torch, device=device)
            if device.type == "cuda"
            else RuntimeResourceStage("inference")
        )
        measurement.__enter__()
        try:
            token_lens = torch.tensor(
                [motion_length_frames // 4], dtype=torch.long, device=device
            )
            with torch.inference_mode():
                base_tokens = self._mask_transformer.generate(
                    [prompt],
                    token_lens,
                    time_steps,
                    cond_scale,
                    temperature=temperature,
                    topk_filter_thres=topk_filter_thres,
                )
                pred_ids = self._residual_transformer.generate(
                    base_tokens,
                    [prompt],
                    token_lens,
                    temperature=1.0,
                    cond_scale=residual_cond_scale,
                )
                quantized = self._vq_model.quantizer.get_codes_from_indices(
                    pred_ids
                ).sum(dim=0)
                normalized = self._rf_decoder.sample(
                    quantized,
                    batch_size=1,
                    steps=rf_steps,
                    padding_mask=None,
                    text_embedding=None,
                    data_shape=(motion_length_frames, 263),
                )
                normalized = normalized.to(dtype=torch.float32).cpu().numpy()
                motion = normalized * self._std.reshape(1, 1, 263) + self._mean.reshape(
                    1, 1, 263
                )
        finally:
            error_info = sys.exc_info()
            measurement.__exit__(*error_info)
            if error_info[0] is None:
                self._record("inference", measurement)
        expected = (1, motion_length_frames, 263)
        if motion.shape != expected:
            raise WorkerFailure(
                "NATIVE_OUTPUT_CONTRACT_MISMATCH",
                f"DisCoRD returned {motion.shape}; expected {expected}",
            )
        motion263 = np.ascontiguousarray(motion[0], dtype=np.float32)
        if not np.isfinite(motion263).all():
            raise WorkerFailure(
                "NATIVE_OUTPUT_NONFINITE", "DisCoRD returned non-finite motion"
            )
        return GenerationOutput(
            motion263=motion263, generated_frames=motion_length_frames
        )
