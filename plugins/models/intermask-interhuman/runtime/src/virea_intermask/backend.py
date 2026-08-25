from __future__ import annotations

import gc
import os
import random
from dataclasses import dataclass
from typing import Any

import numpy as np
from virea_model_sdk.upstream_runtime import (
    InstalledArtifactRoots,
    upstream_import_scope,
)
from virea_model_sdk.worker import WorkerFailure

SOURCE_REVISION = "5100c555de9839b325d0f3d6904669698c5c87f5"
CHECKPOINT_REVISION = "google-drive-folder-1WCFR7Opc5S3cke26cjEhdvSOH_CXL2Ut"
CLIP_REVISION = "d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"

ARTIFACT_REQUIREMENTS = {
    "intermask-source": (
        "source/models/vq/model.py",
        "source/models/mask_transformer/transformer.py",
        "source/data/stats/global_mean.npy",
        "source/data/stats/global_std.npy",
    ),
    "intermask-interhuman-pretrained": (
        "interhuman/trans_default/model/best_fid.tar",
        "interhuman/trans_default/opt.txt",
        "interhuman/vq_default/model/best_fid.tar",
        "interhuman/vq_default/opt.txt",
    ),
    "intermask-openai-clip-vit-l14-336": ("ViT-L-14-336px.pt",),
}


@dataclass(frozen=True, slots=True)
class InterMaskGeneration:
    actors_motion262: np.ndarray
    shared_frame_transform: np.ndarray


class InterMaskBackend:
    def __init__(self, roots: InstalledArtifactRoots | None = None) -> None:
        self.roots = roots or InstalledArtifactRoots.from_environment(
            ARTIFACT_REQUIREMENTS
        )
        self.source_root = self.roots["intermask-source"] / "source"
        self.checkpoint_root = self.roots["intermask-interhuman-pretrained"]
        self.clip_checkpoint = (
            self.roots["intermask-openai-clip-vit-l14-336"] / "ViT-L-14-336px.pt"
        )
        self._torch: Any | None = None
        self._vq: Any | None = None
        self._transformer: Any | None = None
        self._normalizer: Any | None = None
        self._device = "unloaded"

    @property
    def loaded(self) -> bool:
        return self._vq is not None and self._transformer is not None

    @property
    def device_facts(self) -> dict[str, Any]:
        return {
            "device": self._device,
            "memory_strategy": os.getenv("VIREA_MEMORY_STRATEGY", "cpu"),
            "implicit_network_access": False,
            "source_revision": SOURCE_REVISION,
            "checkpoint_revision": CHECKPOINT_REVISION,
            "clip_revision": CLIP_REVISION,
        }

    def load(self) -> None:
        if self.loaded:
            return
        with upstream_import_scope(
            self.source_root,
            working_directory=self.source_root,
            environment={"CUDA_VISIBLE_DEVICES": os.getenv("CUDA_VISIBLE_DEVICES")},
        ):
            try:
                import torch
                from data.utils import MotionNormalizer
                from models.mask_transformer.transformer import MaskTransformer
                from models.vq.model import RVQVAE
                from utils.get_opt import get_opt
            except Exception as exc:
                raise WorkerFailure(
                    "UPSTREAM_IMPORT_FAILED",
                    f"InterMask source import failed: {type(exc).__name__}: {exc}",
                ) from exc

            use_cuda = (
                os.getenv("VIREA_MEMORY_STRATEGY", "cpu") != "cpu"
                and torch.cuda.is_available()
            )
            device = torch.device("cuda:0" if use_cuda else "cpu")
            trans_opt_path = self.checkpoint_root / "interhuman/trans_default/opt.txt"
            vq_opt_path = self.checkpoint_root / "interhuman/vq_default/opt.txt"
            main_opt = get_opt(str(trans_opt_path), device)
            vq_opt = get_opt(str(vq_opt_path), device)
            main_opt.num_tokens = vq_opt.nb_code
            main_opt.code_dim = vq_opt.code_dim
            try:
                vq = RVQVAE(
                    vq_opt,
                    12,
                    vq_opt.nb_code,
                    vq_opt.code_dim,
                    vq_opt.code_dim,
                    vq_opt.down_t,
                    vq_opt.stride_t,
                    vq_opt.width,
                    vq_opt.depth,
                    vq_opt.dilation_growth_rate,
                    vq_opt.vq_act,
                    vq_opt.vq_norm,
                )
                vq_state = torch.load(
                    self.checkpoint_root / "interhuman/vq_default/model/best_fid.tar",
                    map_location="cpu",
                    weights_only=False,
                )
                vq_key = "vq_model" if "vq_model" in vq_state else "net"
                missing, unexpected = vq.load_state_dict(vq_state[vq_key], strict=False)
                if unexpected or any(
                    not (
                        key.startswith("decoder.conv")
                        or key.startswith("decoder.resnets")
                    )
                    for key in missing
                ):
                    raise RuntimeError(
                        f"RVQ-VAE state mismatch: missing={missing}, unexpected={unexpected}"
                    )
                transformer = MaskTransformer(
                    code_dim=main_opt.code_dim,
                    cond_mode="text",
                    latent_dim=main_opt.latent_dim,
                    ff_size=main_opt.ff_size,
                    num_layers=main_opt.n_layers,
                    num_heads=main_opt.n_heads,
                    dropout=main_opt.dropout,
                    clip_dim=768,
                    cond_drop_prob=main_opt.cond_drop_prob,
                    clip_version=str(self.clip_checkpoint),
                    opt=main_opt,
                )
                trans_state = torch.load(
                    self.checkpoint_root
                    / "interhuman/trans_default/model/best_fid.tar",
                    map_location="cpu",
                    weights_only=False,
                )
                trans_key = (
                    "t2m_transformer" if "t2m_transformer" in trans_state else "trans"
                )
                missing, unexpected = transformer.load_state_dict(
                    trans_state[trans_key], strict=False
                )
                if unexpected or any(not key.startswith("clip_") for key in missing):
                    raise RuntimeError(
                        f"Mask Transformer state mismatch: missing={missing}, unexpected={unexpected}"
                    )
                vq = vq.to(device).eval()
                transformer = transformer.to(device).eval()
                normalizer = MotionNormalizer()
            except Exception as exc:
                if "out of memory" in str(exc).lower():
                    raise WorkerFailure("WORKER_OOM", str(exc), retryable=True) from exc
                raise WorkerFailure(
                    "MODEL_LOAD_FAILED",
                    f"InterMask load failed: {type(exc).__name__}: {exc}",
                ) from exc
        self._torch = torch
        self._vq = vq
        self._transformer = transformer
        self._normalizer = normalizer
        self._device = str(device)

    def unload(self) -> None:
        torch_module = self._torch
        self._torch = self._vq = self._transformer = self._normalizer = None
        self._device = "unloaded"
        gc.collect()
        if torch_module is not None and torch_module.cuda.is_available():
            torch_module.cuda.empty_cache()

    def generate(
        self,
        prompt: str,
        *,
        frame_count: int,
        seed: int,
        sampling_steps: int,
        guidance_scale: float,
        conditioning_actor_motion: np.ndarray | None = None,
    ) -> InterMaskGeneration:
        if not self.loaded:
            raise WorkerFailure("MODEL_NOT_LOADED", "InterMask is not loaded")
        torch = self._torch
        assert torch is not None
        device = next(self._transformer.parameters()).device
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if device.type == "cuda":
            torch.cuda.manual_seed_all(seed)
        ids_length = torch.tensor([frame_count // 4], device=device)
        with upstream_import_scope(
            self.source_root, working_directory=self.source_root
        ):
            with torch.no_grad():
                if conditioning_actor_motion is None:
                    motion_ids = self._transformer.generate(
                        [prompt],
                        ids_length,
                        sampling_steps,
                        guidance_scale,
                        topk_filter_thres=0.9,
                        temperature=1.0,
                    )
                    ids1, ids2 = motion_ids.chunk(2, dim=1)
                    motion1 = self._vq.forward_decoder(ids1.unsqueeze(-1))
                else:
                    conditioned = np.asarray(
                        conditioning_actor_motion, dtype=np.float32
                    )
                    if conditioned.shape != (frame_count, 262):
                        raise WorkerFailure(
                            "INVALID_REQUEST",
                            "conditioning_actor_motion must have shape (frames,262)",
                        )
                    normalized = self._normalizer.forward(conditioned)
                    motion1_tensor = (
                        torch.from_numpy(normalized).unsqueeze(0).to(device)
                    )
                    code_idx1, _ = self._vq.encode(motion1_tensor)
                    motion_ids = self._transformer.generate_reaction(
                        [prompt],
                        code_idx1[..., 0],
                        ids_length,
                        sampling_steps,
                        guidance_scale,
                        topk_filter_thres=0.9,
                        temperature=1.0,
                    )
                    _, ids2 = motion_ids.chunk(2, dim=1)
                    motion1 = motion1_tensor
                motion2 = self._vq.forward_decoder(ids2.unsqueeze(-1))
                normalized_pair = torch.stack((motion1[0], motion2[0]), dim=0)
                normalized_pair = normalized_pair.detach().cpu().numpy()
        denormalized = self._normalizer.backward(normalized_pair).astype(
            np.float32, copy=False
        )
        if (
            denormalized.shape != (2, frame_count, 262)
            or not np.isfinite(denormalized).all()
        ):
            raise WorkerFailure(
                "NATIVE_OUTPUT_INVALID",
                f"InterMask produced invalid shape {denormalized.shape}",
            )
        return InterMaskGeneration(
            actors_motion262=np.ascontiguousarray(denormalized),
            shared_frame_transform=np.eye(4, dtype=np.float32),
        )
