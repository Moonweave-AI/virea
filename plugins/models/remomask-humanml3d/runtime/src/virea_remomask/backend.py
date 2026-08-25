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
    length_was_estimated: bool
    retrieved_motion_ids: tuple[str, ...]


class _PinnedRetriever:
    """Inference-only closure matching the released BiMoCo checkpoint graph.

    The pinned release configuration and checkpoint use a fine-tuned OpenAI
    CLIP ViT-B/32 text encoder with a 512 -> 512 projection head.  The source
    tree's later ``AutoModel`` constructor is not compatible with those tensors,
    so this closure follows the immutable release configuration/state instead
    of attempting a DistilBERT substitution.
    """

    @staticmethod
    def release_model_config(path: Path) -> dict[str, Any]:
        import yaml

        try:
            release_config = yaml.safe_load(path.read_text(encoding="utf-8"))
            model_config = release_config["model"]
        except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH",
                "ReMoMask retrieval configuration is unreadable or incomplete",
            ) from exc
        expected_config = {
            "text_encoder": "ViT-B-32.pt",
            "text_embedding_dims": 512,
            "projection_dims": 512,
        }
        actual_config = {key: model_config.get(key) for key in expected_config}
        if actual_config != expected_config:
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH",
                f"ReMoMask retrieval configuration differs: {actual_config!r}",
            )
        return dict(model_config)

    @staticmethod
    def query_state(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        clip_prefix = "text_encoder.clip_model."
        projection_prefix = "text_projection."
        clip_state = {
            key.removeprefix(clip_prefix): value
            for key, value in state.items()
            if key.startswith(clip_prefix)
        }
        projection_state = {
            key.removeprefix(projection_prefix): value
            for key, value in state.items()
            if key.startswith(projection_prefix)
        }
        if not clip_state or not projection_state:
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH",
                "ReMoMask retriever checkpoint lacks the released CLIP query encoder or projection head",
            )
        return clip_state, projection_state

    def __init__(
        self,
        *,
        checkpoint: Path,
        config: Path,
        clip_checkpoint: Path,
        database_root: Path,
        device: Any,
        load_state: Any,
    ) -> None:
        import clip
        import torch

        model_config = self.release_model_config(config)

        class ProjectionHead(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.projection = torch.nn.Linear(512, 512)
                self.gelu = torch.nn.GELU()
                self.fc = torch.nn.Linear(512, 512)
                self.dropout = torch.nn.Dropout(float(model_config.get("dropout", 0.5)))
                self.layer_norm = torch.nn.LayerNorm(512)

            def forward(self, value: Any) -> Any:
                projected = self.projection(value)
                value = self.gelu(projected)
                value = self.fc(value)
                value = self.dropout(value)
                return self.layer_norm(value + projected)

        self.motion_ids = np.load(database_root / "motion_ids.npy", allow_pickle=False)
        self.captions = np.load(database_root / "all_captions.npy", allow_pickle=False)
        motion = np.load(database_root / "encoded_motions.npy", allow_pickle=False)
        text = np.load(database_root / "encoded_texts.npy", allow_pickle=False)
        if (
            motion.ndim != 3
            or text.ndim != 3
            or motion.shape[1:] != (1, 512)
            or text.shape[1:] != (1, 512)
        ):
            raise WorkerFailure(
                "RETRIEVAL_DATABASE_CONTRACT_MISMATCH",
                f"ReMoMask database features must be [N,1,512], got {motion.shape} and {text.shape}",
            )
        count = motion.shape[0]
        if (
            text.shape[0] != count
            or self.motion_ids.shape != (count,)
            or self.captions.shape != (count,)
        ):
            raise WorkerFailure(
                "RETRIEVAL_DATABASE_CONTRACT_MISMATCH",
                "ReMoMask database row counts differ",
            )
        if not np.isfinite(motion).all() or not np.isfinite(text).all():
            raise WorkerFailure(
                "RETRIEVAL_DATABASE_CONTRACT_MISMATCH",
                "ReMoMask database contains non-finite features",
            )
        self.motion_features = torch.from_numpy(
            np.asarray(motion[:, 0, :], dtype=np.float32)
        )
        self.text_features = torch.from_numpy(
            np.asarray(text[:, 0, :], dtype=np.float32)
        )
        self.device = device
        state = load_state(checkpoint)
        clip_state, projection_state = self.query_state(state)
        clip_model, _ = clip.load(str(clip_checkpoint), device="cpu", jit=False)
        projection = ProjectionHead()
        try:
            clip_model.load_state_dict(clip_state, strict=True, assign=True)
            projection.load_state_dict(projection_state, strict=True, assign=True)
        except RuntimeError as exc:
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH",
                f"ReMoMask CLIP retrieval state differs: {exc}",
            ) from exc
        self.clip = clip
        self.clip_model = clip_model.float().to(device).eval()
        self.projection = projection.float().to(device).eval()
        for module in (self.clip_model, self.projection):
            for parameter in module.parameters():
                parameter.requires_grad = False

    def features(
        self, captions: list[str], *, k: int = 1
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        import torch

        if k < 1 or k > 10:
            raise WorkerFailure("INVALID_REQUEST", "retrieval_top_k must be in [1, 10]")
        all_indexes: list[list[int]] = []
        all_names: list[str] = []
        with torch.inference_mode():
            tokens = self.clip.tokenize(captions, truncate=True).to(self.device)
            query_features = self.projection(
                self.clip_model.encode_text(tokens).float()
            )
            query_features = torch.nn.functional.normalize(query_features, dim=-1)
            motion_features = torch.nn.functional.normalize(
                self.motion_features.to(self.device), dim=-1
            )
            for query in query_features:
                scores = query.unsqueeze(0) @ motion_features.T
                indexes = torch.argsort(scores[0], descending=True).cpu().tolist()
                selected: list[int] = []
                names_seen: set[str] = set()
                for index in indexes:
                    full_name = str(self.motion_ids[index])
                    base_name = full_name.split("_")[0]
                    if base_name in names_seen:
                        continue
                    names_seen.add(base_name)
                    selected.append(index)
                    all_names.append(full_name)
                    if len(selected) == k:
                        break
                if len(selected) != k:
                    raise WorkerFailure(
                        "RETRIEVAL_DATABASE_CONTRACT_MISMATCH",
                        "ReMoMask database has too few unique motions",
                    )
                all_indexes.append(selected)
        indexes_tensor = torch.tensor(all_indexes, dtype=torch.long)
        batch, selected_count = indexes_tensor.shape
        flat = indexes_tensor.reshape(-1)
        re_motion = (
            self.motion_features[flat]
            .to(self.device)
            .reshape(batch, selected_count, 1, 512)
        )
        re_text = (
            self.text_features[flat]
            .to(self.device)
            .reshape(batch, selected_count, 1, 512)
        )
        return {"re_text": re_text, "re_motion": re_motion}, tuple(all_names)


class ReMoMaskBackend:
    """Loads the immutable official ReMoMask generator and retrieval graph."""

    def __init__(self, roots: ArtifactRoots, cache_root: Path) -> None:
        self.roots = roots
        self.cache_root = cache_root
        self._artifacts: MaterializedArtifacts | None = None
        self._vq_model: Any = None
        self._mask_aux: Any = None
        self._mask_ts: Any = None
        self._residual_aux: Any = None
        self._residual_ts: Any = None
        self._length_estimator: Any = None
        self._retriever: _PinnedRetriever | None = None
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
        return self._mask_ts is not None and self._retriever is not None

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
        for namespace in ("models", "utils"):
            existing = sys.modules.get(namespace)
            if existing is not None and not self._module_belongs_to(existing, root):
                raise WorkerFailure(
                    "UPSTREAM_NAMESPACE_CONFLICT",
                    f"Python namespace {namespace!r} was imported outside pinned ReMoMask source",
                )
        rendered = str(root)
        if rendered not in sys.path:
            sys.path.insert(0, rendered)
        importlib.invalidate_caches()
        self._source_root = root

    @staticmethod
    def _load_state(path: Path) -> dict[str, Any]:
        import torch

        state = torch.load(path, map_location="cpu", weights_only=True)
        if not isinstance(state, dict):
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH",
                f"checkpoint does not contain a mapping: {path}",
            )
        return state

    @staticmethod
    def _state(payload: dict[str, Any], *keys: str, label: str) -> dict[str, Any]:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, dict):
                return value
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

    @staticmethod
    def _configure_quantizer_initialization(module: Any) -> None:
        """Remove the released constructor's placement-only `.cuda()` call."""
        import torch

        def reset_codebook(instance: Any) -> None:
            instance.init = False
            instance.code_sum = None
            instance.code_count = None
            instance.register_buffer(
                "codebook",
                torch.zeros(instance.nb_code, instance.code_dim, requires_grad=False),
            )

        module.QuantizeEMAReset.reset_codebook = reset_codebook

    @staticmethod
    def _configure_clip_loaders(aux_module: Any, ts_module: Any, *, cpu: bool) -> None:
        def loader(instance: Any, clip_version: str) -> Any:
            clip_model, _ = aux_module.clip.load(clip_version, device="cpu", jit=False)
            if cpu:
                clip_model.float()
            else:
                aux_module.clip.model.convert_weights(clip_model)
            clip_model.eval()
            for parameter in clip_model.parameters():
                parameter.requires_grad = False
            return clip_model

        for cls in (
            aux_module.MaskTransformer,
            aux_module.ResidualTransformer,
            ts_module.MaskTransformer2D,
            ts_module.ResidualTransformer2D,
        ):
            cls.load_and_freeze_clip = loader

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
                "ReMoMask implements only cuda_full and whole-model cpu strategies",
            )
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
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
            get_opt = importlib.import_module("utils.get_opt").get_opt
            quantizer_module = importlib.import_module("models.vq.quantizer")
            self._configure_quantizer_initialization(quantizer_module)
            vq_module = importlib.import_module("models.vq.model")
            aux_module = importlib.import_module("models.transformer.transformer_aux")
            ts_module = importlib.import_module("models.transformer.transformer_ts")
            self._configure_clip_loaders(aux_module, ts_module, cpu=strategy == "cpu")

            vq_opt = get_opt(str(artifacts.vq_opt), device=device)
            vq_model = vq_module.RVQVAE(
                vq_opt,
                263,
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
                self._state(vq_payload, "vq_model", "net", label="ReMoMask RVQ-VAE"),
                strict=True,
                assign=True,
            )

            mask_opt = get_opt(str(artifacts.mask_opt), device=device)
            mask_opt.num_tokens1d = vq_model.num_code1d
            mask_opt.num_tokens2d = vq_model.num_code2d
            clip_path = str(artifacts.clip_checkpoint)
            mask_aux = aux_module.MaskTransformer(
                code_dim=vq_model.code_dim1d,
                cond_mode="text",
                latent_dim=mask_opt.latent_dim,
                ff_size=mask_opt.ff_size,
                num_layers=mask_opt.n_layers,
                num_heads=mask_opt.n_heads,
                dropout=mask_opt.dropout,
                clip_dim=512,
                cond_drop_prob=mask_opt.cond_drop_prob,
                clip_version=clip_path,
                opt=mask_opt,
            )
            mask_ts = ts_module.MaskTransformer2D(
                code_dim=vq_model.code_dim2d,
                cond_mode="text",
                latent_dim=mask_opt.latent_dim,
                ff_size=mask_opt.ff_size,
                num_layers=mask_opt.n_layers,
                num_heads=mask_opt.n_heads,
                dropout=mask_opt.dropout,
                clip_dim=512,
                cond_drop_prob=mask_opt.cond_drop_prob,
                clip_version=clip_path,
                opt=mask_opt,
            )
            mask_payload = self._load_state(artifacts.mask_checkpoint)
            missing_aux, unexpected_aux = mask_aux.load_state_dict(
                self._state(
                    mask_payload,
                    "t2m_transformer_aux",
                    label="ReMoMask auxiliary mask transformer",
                ),
                strict=False,
                assign=True,
            )
            missing_ts, unexpected_ts = mask_ts.load_state_dict(
                self._state(
                    mask_payload,
                    "t2m_transformer_ts",
                    label="ReMoMask 2D mask transformer",
                ),
                strict=False,
                assign=True,
            )
            if unexpected_aux or any(
                not key.startswith("clip_model.") for key in missing_aux
            ):
                raise WorkerFailure(
                    "CHECKPOINT_CONTRACT_MISMATCH",
                    f"ReMoMask auxiliary mask state differs: missing={list(missing_aux)}, unexpected={list(unexpected_aux)}",
                )
            # The pinned HF revision contains every semanticTransEncoder tensor.
            # Only the intentionally external frozen CLIP is absent; accepting
            # missing semantic tensors would silently execute random SSTA weights.
            if unexpected_ts or any(
                not key.startswith("clip_model.") for key in missing_ts
            ):
                raise WorkerFailure(
                    "CHECKPOINT_CONTRACT_MISMATCH",
                    f"ReMoMask 2D mask state differs: missing={list(missing_ts)}, unexpected={list(unexpected_ts)}",
                )

            residual_opt = get_opt(str(artifacts.residual_opt), device=device)
            residual_opt.num_quantizers = vq_opt.num_quantizers
            residual_opt.num_tokens1d = vq_model.num_code1d
            residual_opt.num_tokens2d = vq_model.num_code2d
            residual_aux = aux_module.ResidualTransformer(
                code_dim=vq_model.code_dim1d,
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
                clip_version=clip_path,
                opt=residual_opt,
            )
            residual_ts = ts_module.ResidualTransformer2D(
                code_dim=vq_model.code_dim2d,
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
                clip_version=clip_path,
                opt=residual_opt,
            )
            residual_payload = self._load_state(artifacts.residual_checkpoint)
            missing_aux, unexpected_aux = residual_aux.load_state_dict(
                self._state(
                    residual_payload,
                    "res_transformer_aux",
                    label="ReMoMask auxiliary residual transformer",
                ),
                strict=False,
                assign=True,
            )
            missing_ts, unexpected_ts = residual_ts.load_state_dict(
                self._state(
                    residual_payload,
                    "res_transformer_ts",
                    label="ReMoMask 2D residual transformer",
                ),
                strict=False,
                assign=True,
            )
            if unexpected_aux or any(
                not key.startswith("clip_model.") for key in missing_aux
            ):
                raise WorkerFailure(
                    "CHECKPOINT_CONTRACT_MISMATCH",
                    f"ReMoMask auxiliary residual state differs: missing={list(missing_aux)}, unexpected={list(unexpected_aux)}",
                )
            if unexpected_ts or any(
                not key.startswith("clip_model.") for key in missing_ts
            ):
                raise WorkerFailure(
                    "CHECKPOINT_CONTRACT_MISMATCH",
                    f"ReMoMask 2D residual state differs: missing={list(missing_ts)}, unexpected={list(unexpected_ts)}",
                )

            length_estimator = vq_module.LengthEstimator(512, 50)
            length_payload = self._load_state(artifacts.length_checkpoint)
            length_estimator.load_state_dict(
                self._state(
                    length_payload, "estimator", label="ReMoMask length estimator"
                ),
                strict=True,
                assign=True,
            )
            retriever = _PinnedRetriever(
                checkpoint=artifacts.retriever_checkpoint,
                config=artifacts.retriever_config,
                clip_checkpoint=artifacts.clip_checkpoint,
                database_root=artifacts.database_root,
                device=device,
                load_state=self._load_state,
            )
            mean = self._vector(artifacts.mean, label="ReMoMask HumanML3D mean")
            std = self._vector(artifacts.std, label="ReMoMask HumanML3D std")
            if np.any(std <= 0):
                raise WorkerFailure(
                    "NORMALIZATION_CONTRACT_MISMATCH",
                    "ReMoMask HumanML3D standard deviation must be positive",
                )
            for model in (
                vq_model,
                mask_aux,
                mask_ts,
                residual_aux,
                residual_ts,
                length_estimator,
            ):
                if strategy == "cpu":
                    model.float()
                model.to(device).eval()
            # Four released generators use the same immutable CLIP. Share one
            # frozen instance after checkpoint loading to bound RAM/VRAM.
            for model in (mask_ts, residual_aux, residual_ts):
                model.clip_model = mask_aux.clip_model
            self._artifacts = artifacts
            self._vq_model = vq_model
            self._mask_aux = mask_aux
            self._mask_ts = mask_ts
            self._residual_aux = residual_aux
            self._residual_ts = residual_ts
            self._length_estimator = length_estimator
            self._retriever = retriever
            self._mean = mean
            self._std = std
        except WorkerFailure:
            self.unload()
            raise
        except Exception as exc:
            self.unload()
            raise WorkerFailure(
                "MODEL_LOAD_FAILED",
                f"failed to load pinned ReMoMask: {type(exc).__name__}: {exc}",
            ) from exc
        finally:
            error_info = sys.exc_info()
            measurement.__exit__(*error_info)
            if error_info[0] is None:
                self._record("load", measurement)

    def unload(self) -> None:
        active_device = None
        if self._mask_ts is not None:
            try:
                active_device = next(self._mask_ts.parameters()).device.type
            except (AttributeError, StopIteration):
                pass
        self._vq_model = self._mask_aux = self._mask_ts = None
        self._residual_aux = self._residual_ts = self._length_estimator = None
        self._retriever = self._mean = self._std = self._artifacts = None
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
        motion_length_frames: int | None,
        seed: int,
        time_steps: int,
        cond_scale: float,
        temperature: float,
        topk_filter_thres: float,
        residual_cond_scale: float,
        retrieval_top_k: int,
    ) -> GenerationOutput:
        if any(
            value is None
            for value in (
                self._vq_model,
                self._mask_aux,
                self._mask_ts,
                self._residual_aux,
                self._residual_ts,
                self._length_estimator,
                self._retriever,
                self._mean,
                self._std,
            )
        ):
            raise WorkerFailure("MODEL_NOT_LOADED", "ReMoMask model is not loaded")
        import torch
        import torch.nn.functional as functional
        from torch.distributions.categorical import Categorical

        device = next(self._mask_ts.parameters()).device
        self._seed(seed, cuda=device.type == "cuda")
        measurement = (
            RuntimeResourceStage("inference", torch=torch, device=device)
            if device.type == "cuda"
            else RuntimeResourceStage("inference")
        )
        measurement.__enter__()
        try:
            with torch.inference_mode():
                if motion_length_frames is None:
                    text_embedding = self._mask_ts.encode_text([prompt])
                    token_lens = Categorical(
                        functional.softmax(
                            self._length_estimator(text_embedding), dim=-1
                        )
                    ).sample()
                    length_was_estimated = True
                else:
                    token_lens = torch.tensor(
                        [motion_length_frames // 4], dtype=torch.long, device=device
                    )
                    length_was_estimated = False
                generated_frames = int(token_lens[0].item()) * 4
                if generated_frames < 40 or generated_frames > 196:
                    raise WorkerFailure(
                        "NATIVE_OUTPUT_CONTRACT_MISMATCH",
                        f"ReMoMask selected {generated_frames} frames outside [40, 196]",
                    )
                re_dict, retrieved_ids = self._retriever.features(
                    [prompt], k=retrieval_top_k
                )
                mids_aux = self._mask_aux.generate(
                    [prompt],
                    token_lens,
                    timesteps=time_steps,
                    cond_scale=cond_scale,
                    temperature=temperature,
                    topk_filter_thres=topk_filter_thres,
                    gsample=False,
                )
                mids_ts = self._mask_ts.generate(
                    [prompt],
                    token_lens,
                    timesteps=time_steps,
                    cond_scale=cond_scale,
                    temperature=temperature,
                    topk_filter_thres=topk_filter_thres,
                    gsample=False,
                    n_j=6,
                    re_dict=re_dict,
                )
                mids_aux = self._residual_aux.generate(
                    mids_aux,
                    [prompt],
                    token_lens,
                    temperature=1.0,
                    cond_scale=residual_cond_scale,
                )
                mids_ts = self._residual_ts.generate(
                    mids_ts,
                    [prompt],
                    token_lens,
                    temperature=1.0,
                    cond_scale=residual_cond_scale,
                )
                _, normalized = self._vq_model.forward_decoder(mids_aux, mids_ts)
                normalized = (
                    normalized[:, :generated_frames]
                    .to(dtype=torch.float32)
                    .cpu()
                    .numpy()
                )
                motion = normalized * self._std.reshape(1, 1, 263) + self._mean.reshape(
                    1, 1, 263
                )
        finally:
            error_info = sys.exc_info()
            measurement.__exit__(*error_info)
            if error_info[0] is None:
                self._record("inference", measurement)
        expected = (1, generated_frames, 263)
        if motion.shape != expected:
            raise WorkerFailure(
                "NATIVE_OUTPUT_CONTRACT_MISMATCH",
                f"ReMoMask returned {motion.shape}; expected {expected}",
            )
        motion263 = np.ascontiguousarray(motion[0], dtype=np.float32)
        if not np.isfinite(motion263).all():
            raise WorkerFailure(
                "NATIVE_OUTPUT_NONFINITE", "ReMoMask returned non-finite motion"
            )
        return GenerationOutput(
            motion263=motion263,
            generated_frames=generated_frames,
            length_was_estimated=length_was_estimated,
            retrieved_motion_ids=retrieved_ids,
        )
