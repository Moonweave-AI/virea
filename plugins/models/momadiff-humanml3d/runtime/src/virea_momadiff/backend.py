from __future__ import annotations

import gc
import importlib
import itertools
import pickle
import random
import sys
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
from virea_model_sdk import RuntimeResourceStage

SOURCE_REVISION = "6dd9bea254bbca6cf19756ac3ee037cbf4f6021c"
CHECKPOINT_REVISION = "daf83c1441fbb9e8bacd377e28f557b54080c2a1"
CLIP_REVISION = "d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"
FEATURE_DIM = 263
FPS = 20.0
UNIT_LENGTH = 4
MAX_FRAMES = 196
MAX_TOKEN_LENGTH = MAX_FRAMES // UNIT_LENGTH
DEFAULT_MASK_STEPS = 7
DEFAULT_GUIDANCE_SCALE = 3.0
DEFAULT_DDIM_STEPS = 100

SOURCE_REQUIRED_FILES = (
    "LICENSE",
    "NOTICE",
    "configs/t2m.yaml",
    "diffusion/gaussian_diffusion.py",
    "models/diffusion/mlp.py",
    "models/klvae/autoencoder.py",
    "models/length_est.py",
    "models/mask_transformer/latent_transformer.py",
    "utils/diffusion.py",
)
CHECKPOINT_REQUIRED_FILES = (
    "t2m/Trans-B_EMA_klv0-stable_masked-only_diff1000/model/latest_ema.tar",
    "t2m/kl_vae_ver0-stable/args_for_pretrained_klvae.pkl",
    "t2m/kl_vae_ver0-stable/meta/mean.npy",
    "t2m/kl_vae_ver0-stable/meta/std.npy",
    "t2m/kl_vae_ver0-stable/net_last.pth",
    "t2m/length_estimator/model/finest.tar",
)
CLIP_REQUIRED_FILES = ("ViT-B-32.pt",)


@dataclass(frozen=True, slots=True)
class MoMADiffPaths:
    source_root: Path
    checkpoint_root: Path
    clip_root: Path

    def validate(self) -> "MoMADiffPaths":
        return MoMADiffPaths(
            source_root=_require_tree(
                self.source_root, SOURCE_REQUIRED_FILES, "MoMADiff source"
            ),
            checkpoint_root=_require_tree(
                self.checkpoint_root,
                CHECKPOINT_REQUIRED_FILES,
                "MoMADiff HumanML3D checkpoints",
            ),
            clip_root=_require_tree(
                self.clip_root, CLIP_REQUIRED_FILES, "OpenAI CLIP ViT-B/32"
            ),
        )

    @property
    def clip_checkpoint(self) -> Path:
        return self.clip_root / CLIP_REQUIRED_FILES[0]


@dataclass(frozen=True, slots=True)
class MoMADiffGeneration:
    motion: np.ndarray
    token_length: int
    length_source: str
    mask_steps: int
    guidance_scale: float
    ddim_steps: int


def _require_tree(root: Path, required: tuple[str, ...], label: str) -> Path:
    resolved = root.expanduser().resolve(strict=False)
    if not resolved.is_dir():
        raise FileNotFoundError(f"{label} root is not a directory: {resolved}")
    missing = [relative for relative in required if not (resolved / relative).is_file()]
    if missing:
        raise FileNotFoundError(
            f"{label} is incomplete; missing: " + ", ".join(missing)
        )
    return resolved


def _module_from_source(name: str, source_root: Path) -> ModuleType:
    module = importlib.import_module(name)
    origin_value = getattr(module, "__file__", None)
    if not origin_value:
        raise RuntimeError(f"official module has no source location: {name}")
    origin = Path(origin_value).resolve(strict=True)
    try:
        origin.relative_to(source_root)
    except ValueError as exc:
        raise RuntimeError(
            f"module {name!r} resolved outside the pinned MoMADiff source: {origin}"
        ) from exc
    return module


def _load_checkpoint(torch: Any, path: Path) -> Any:
    # PyTorch 2.6+ defaults to weights_only=True.  These are the official,
    # revision-pinned MoMADiff checkpoint containers used by the notebook.
    return torch.load(path, map_location="cpu", weights_only=False)


def _load_kl_options(path: Path) -> Any:
    # The released KLVAE architecture is stored as an argparse Namespace.
    with path.open("rb") as handle:
        options = pickle.load(handle)  # noqa: S301 - official pinned artifact contract
    required = (
        "dataset_name",
        "output_emb_width",
        "down_t",
        "stride_t",
        "width",
        "depth",
        "dilation_growth_rate",
        "vae_kl_weight",
    )
    missing = [name for name in required if not hasattr(options, name)]
    if missing:
        raise RuntimeError(
            "released KLVAE options are incomplete: " + ", ".join(missing)
        )
    if options.dataset_name != "t2m":
        raise RuntimeError(
            f"released KLVAE targets {options.dataset_name!r}, expected 't2m'"
        )
    return options


def _load_model_options(
    source_root: Path, checkpoint_root: Path, device: Any
) -> Namespace:
    import yaml

    config_path = source_root / "configs" / "t2m.yaml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("official configs/t2m.yaml must contain a mapping")
    payload.update(
        {
            "checkpoints_dir": str(checkpoint_root),
            "dataset_name": "t2m",
            "name": "Trans-B_EMA_klv0-stable_masked-only_diff1000",
            "kl_name": "kl_vae_ver0-stable",
            "meta_dir": str(checkpoint_root / "t2m" / "kl_vae_ver0-stable" / "meta"),
            "device": device,
            "unconstrained": False,
            "use_ema": True,
            "ema_decay": 0.999,
            "diffusion_steps": 1000,
            "ddim_steps": DEFAULT_DDIM_STEPS,
            "diff_dropout": 0.0,
            "loss_strategy": "masked",
        }
    )
    return Namespace(**payload)


def validate_native_motion(value: Any, *, expected_frames: int) -> np.ndarray:
    motion = np.asarray(value, dtype=np.float32)
    if motion.ndim != 2 or motion.shape != (expected_frames, FEATURE_DIM):
        raise RuntimeError(
            "MoMADiff KLVAE produced an invalid native carrier: "
            f"expected ({expected_frames}, {FEATURE_DIM}), got {motion.shape}"
        )
    if not np.isfinite(motion).all():
        raise RuntimeError("MoMADiff native carrier contains non-finite values")
    return np.ascontiguousarray(motion, dtype=np.float32)


class MoMADiffBackend:
    """Exact released text-to-motion graph with local, pinned artifacts only."""

    def __init__(
        self,
        paths: MoMADiffPaths,
        *,
        memory_strategy: str,
    ) -> None:
        if memory_strategy not in {"cuda_full", "cpu"}:
            raise ValueError(
                "MoMADiff implements only cuda_full and whole-model cpu execution"
            )
        self.paths = paths
        self.memory_strategy = memory_strategy
        self.device_name = "cuda:0" if memory_strategy == "cuda_full" else "cpu"
        self.device_facts: dict[str, Any] = {}
        self._torch: Any | None = None
        self._latent_transformer: Any | None = None
        self._diff_model: Any | None = None
        self._diffusion: Any | None = None
        self._encdec_model: Any | None = None
        self._length_estimator: Any | None = None
        self._mean: np.ndarray | None = None
        self._std: np.ndarray | None = None
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
        self.device_facts["resource_measurement"] = self._resource_measurement

    def load(self) -> None:
        paths = self.paths.validate()
        import torch
        from torch_ema import ExponentialMovingAverage

        if self.memory_strategy == "cuda_full" and not torch.cuda.is_available():
            raise RuntimeError("cuda_full was selected but PyTorch cannot use CUDA")
        # Match the released fixseed.py inference setup.
        torch.backends.cudnn.benchmark = False
        device = torch.device(self.device_name)
        measurement = RuntimeResourceStage(
            "load",
            torch=torch if self.memory_strategy == "cuda_full" else None,
            device=device if self.memory_strategy == "cuda_full" else None,
        )
        measurement.__enter__()
        if str(paths.source_root) not in sys.path:
            sys.path.insert(0, str(paths.source_root))

        autoencoder_module = _module_from_source(
            "models.klvae.autoencoder", paths.source_root
        )
        transformer_module = _module_from_source(
            "models.mask_transformer.latent_transformer", paths.source_root
        )
        length_module = _module_from_source("models.length_est", paths.source_root)
        diffusion_module = _module_from_source("utils.diffusion", paths.source_root)

        options = _load_model_options(paths.source_root, paths.checkpoint_root, device)
        kl_root = paths.checkpoint_root / "t2m" / "kl_vae_ver0-stable"
        kl_options = _load_kl_options(kl_root / "args_for_pretrained_klvae.pkl")

        try:
            encdec_model = autoencoder_module.AutoencoderKL(
                kl_options,
                kl_options.output_emb_width,
                kl_options.down_t,
                kl_options.stride_t,
                kl_options.width,
                kl_options.depth,
                kl_options.dilation_growth_rate,
            )
            kl_checkpoint = _load_checkpoint(torch, kl_root / "net_last.pth")
            encdec_model.load_state_dict(kl_checkpoint["net"], strict=True)
            del kl_checkpoint

            diff_model, diffusion = diffusion_module.create_model_and_diffusion(options)
            latent_transformer = transformer_module.MaskLatentTransformer(
                code_dim=options.code_dim,
                cond_mode="text",
                latent_dim=options.latent_dim,
                ff_size=options.ff_size,
                num_layers=options.n_layers,
                num_heads=options.n_heads,
                dropout=options.dropout,
                clip_dim=512,
                cond_drop_prob=options.cond_drop_prob,
                opt=options,
                clip_version=str(paths.clip_checkpoint),
                use_ema=True,
            )
            transformer_checkpoint = _load_checkpoint(
                torch,
                paths.checkpoint_root
                / "t2m"
                / "Trans-B_EMA_klv0-stable_masked-only_diff1000"
                / "model"
                / "latest_ema.tar",
            )
            ema = ExponentialMovingAverage(
                itertools.chain(
                    latent_transformer.parameters(), diff_model.parameters()
                ),
                decay=options.ema_decay,
            )
            ema.load_state_dict(transformer_checkpoint)
            ema.copy_to(
                itertools.chain(
                    latent_transformer.parameters(), diff_model.parameters()
                )
            )
            del ema, transformer_checkpoint

            diffusion = diffusion_module.create_gaussian_diffusion_ddim(
                options, DEFAULT_DDIM_STEPS
            )
            length_estimator = length_module.LengthEstimator(512, 50)
            length_checkpoint = _load_checkpoint(
                torch,
                paths.checkpoint_root
                / "t2m"
                / "length_estimator"
                / "model"
                / "finest.tar",
            )
            length_estimator.load_state_dict(
                length_checkpoint["estimator"], strict=True
            )
            del length_checkpoint

            mean = np.load(kl_root / "meta" / "mean.npy", allow_pickle=False)
            std = np.load(kl_root / "meta" / "std.npy", allow_pickle=False)
            if mean.shape != (FEATURE_DIM,) or std.shape != (FEATURE_DIM,):
                raise RuntimeError(
                    "released HumanML3D statistics must both have shape (263,)"
                )
            if not np.isfinite(mean).all() or not np.isfinite(std).all():
                raise RuntimeError(
                    "released HumanML3D statistics contain non-finite values"
                )
            if np.any(std <= 0):
                raise RuntimeError(
                    "released HumanML3D standard deviations must be positive"
                )

            for model in (
                latent_transformer,
                diff_model,
                encdec_model,
                length_estimator,
            ):
                model.to(device)
                model.eval()

            self._torch = torch
            self._latent_transformer = latent_transformer
            self._diff_model = diff_model
            self._diffusion = diffusion
            self._encdec_model = encdec_model
            self._length_estimator = length_estimator
            self._mean = np.asarray(mean, dtype=np.float32)
            self._std = np.asarray(std, dtype=np.float32)
            self.device_facts = {
                "memory_strategy": self.memory_strategy,
                "torch_version": str(torch.__version__),
                "torch_cuda_version": str(torch.version.cuda),
                "device": self.device_name,
            }
            if self.memory_strategy == "cuda_full":
                properties = torch.cuda.get_device_properties(0)
                self.device_facts.update(
                    {
                        "gpu_name": str(properties.name),
                        "gpu_compute_capability": (
                            f"{properties.major}.{properties.minor}"
                        ),
                        "gpu_total_memory_bytes": int(properties.total_memory),
                    }
                )
        except Exception:
            self.unload()
            raise
        finally:
            error_info = sys.exc_info()
            measurement.__exit__(*error_info)
            if error_info[0] is None:
                self._record_resource_stage("load", measurement)

    def unload(self) -> None:
        torch = self._torch
        self._latent_transformer = None
        self._diff_model = None
        self._diffusion = None
        self._encdec_model = None
        self._length_estimator = None
        self._mean = None
        self._std = None
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        self._torch = None

    def generate(
        self,
        prompt: str,
        *,
        seed: int,
        motion_length_frames: int | None,
        mask_steps: int = DEFAULT_MASK_STEPS,
        guidance_scale: float = DEFAULT_GUIDANCE_SCALE,
    ) -> MoMADiffGeneration:
        torch = self._torch
        transformer = self._latent_transformer
        diff_model = self._diff_model
        diffusion = self._diffusion
        encdec = self._encdec_model
        length_estimator = self._length_estimator
        mean = self._mean
        std = self._std
        if any(
            value is None
            for value in (
                torch,
                transformer,
                diff_model,
                diffusion,
                encdec,
                length_estimator,
                mean,
                std,
            )
        ):
            raise RuntimeError("MoMADiff backend is not loaded")

        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if self.memory_strategy == "cuda_full":
            torch.cuda.manual_seed_all(seed)

        device = torch.device(self.device_name)
        measurement = RuntimeResourceStage(
            "inference",
            torch=torch if self.memory_strategy == "cuda_full" else None,
            device=device if self.memory_strategy == "cuda_full" else None,
        )
        measurement.__enter__()
        try:
            with torch.inference_mode():
                if motion_length_frames is None:
                    text_embedding = transformer.encode_text(prompt)
                    logits = length_estimator(text_embedding)
                    probabilities = torch.nn.functional.softmax(logits, dim=-1)
                    token_length = int(
                        torch.distributions.Categorical(probabilities)
                        .sample()[0]
                        .item()
                    )
                    length_source = "released_length_estimator"
                    if token_length < 1 or token_length > MAX_TOKEN_LENGTH:
                        raise RuntimeError(
                            "released length estimator selected an invalid token length: "
                            f"{token_length}"
                        )
                else:
                    if (
                        motion_length_frames < UNIT_LENGTH
                        or motion_length_frames > MAX_FRAMES
                        or motion_length_frames % UNIT_LENGTH
                    ):
                        raise ValueError(
                            "motion_length_frames must be a multiple of four in [4, 196]"
                        )
                    token_length = motion_length_frames // UNIT_LENGTH
                    length_source = "request"

                token_lengths = torch.tensor(
                    [token_length], device=device, dtype=torch.long
                )
                predicted_latent, _ = transformer.generate(
                    [prompt],
                    token_lengths,
                    mask_steps,
                    guidance_scale,
                    diffusion=diffusion,
                    diff_model=diff_model,
                    output_inference_step=True,
                    noise_schedule=None,
                )
                normalized = encdec.decode(predicted_latent).detach().cpu().numpy()
        finally:
            error_info = sys.exc_info()
            measurement.__exit__(*error_info)
            if error_info[0] is None:
                self._record_resource_stage("inference", measurement)

        expected_frames = token_length * UNIT_LENGTH
        if normalized.ndim != 3 or normalized.shape[0] != 1:
            raise RuntimeError(
                f"MoMADiff KLVAE produced an invalid batch shape: {normalized.shape}"
            )
        if normalized.shape[1:] != (expected_frames, FEATURE_DIM):
            raise RuntimeError(
                "MoMADiff KLVAE produced an invalid normalized carrier: "
                f"expected (1, {expected_frames}, {FEATURE_DIM}), got {normalized.shape}"
            )
        native = normalized[0] * std + mean
        return MoMADiffGeneration(
            motion=validate_native_motion(native, expected_frames=expected_frames),
            token_length=token_length,
            length_source=length_source,
            mask_steps=mask_steps,
            guidance_scale=guidance_scale,
            ddim_steps=DEFAULT_DDIM_STEPS,
        )
