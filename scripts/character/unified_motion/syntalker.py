"""Full H3D SynTalker: TMR prompts, speech features, RVQ-VAE, latent diffusion.

Per-time CFG and x0 prefix anchoring extend the official sample-level guidance.
No trainer/dataset/ground-truth poses or simplified co-speech demo are required.
"""

import os
import pickle
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np

from .conditioning import beat_audio_features, conditions, h3d_part_indices
from .provenance import verify_source


def portable_codebook(self):
    """Allocate on CPU first; checkpoint loading and .to(device) own placement."""
    import torch

    self.init, self.code_sum, self.code_count = False, None, None
    self.register_buffer("codebook", torch.zeros(self.nb_code, self.code_dim))


class SynTalkerEngine:
    backend = "syntalker"
    representation = "h3d623"
    source_revision = "4301ada4d5affe6a77beaf5f8e19bc1904d3ea41"
    window_frames = 128
    history_frames = 16

    def __init__(self, settings):
        import torch
        import yaml

        self.torch = torch
        self.device = torch.device(settings.get("device", "cuda"))
        source = Path(settings["source"]).resolve(strict=True)
        verify_source(source, self.source_revision)
        assets = Path(settings["assets"]).resolve(strict=True)
        sys.path[:0] = [str(source), str(source / "models")]
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from diffusion.model_util import create_gaussian_diffusion
        from models.denoiser_h3d import MDM
        from models.temos.textencoder.distillbert_actor import (
            DistilbertActorAgnosticEncoder,
        )
        from models.vq.model import RVQVAE
        from models.vq.quantizer import QuantizeEMAReset

        cfg = yaml.safe_load(
            (source / "configs/diffusion_h3d.yaml").read_text(encoding="utf-8")
        )
        for key in (
            "test_ckpt",
            "vqvae_upper_path",
            "vqvae_hands_path",
            "vqvae_lower_path",
            "tmr_base_path",
            "mean_pose_path",
            "std_pose_path",
            "data_path",
        ):
            cfg[key] = str(assets / cfg[key].removeprefix("./"))
        cfg["data_path"] += os.sep
        cfg.update(
            num_quantizers=6,
            shared_codebook=False,
            quantize_dropout_prob=0.2,
            mu=0.99,
            nb_code=512,
            code_dim=512,
            down_t=2,
            stride_t=2,
            width=512,
            depth=3,
            dilation_growth_rate=3,
            vq_act="relu",
            vq_norm=None,
        )
        args = SimpleNamespace(**cfg)

        def load(path, key=None):
            state = torch.load(path, map_location="cpu", weights_only=True)
            if key:
                state = state[key]
            return {k.removeprefix("module."): v for k, v in state.items()}

        state = load(args.test_ckpt, "model_state")
        # MDM only uses the vocabulary pickle to initialize this embedding, then
        # the checkpoint overwrites it. Recreate that bootstrap from safe tensor
        # state locally; never deserialize an external dataset pickle.
        with TemporaryDirectory(prefix="virea-syntalker-vocab-") as temporary:
            weights = Path(temporary) / "weights"
            weights.mkdir()
            with (weights / "vocab.pkl").open("wb") as stream:
                pickle.dump(
                    SimpleNamespace(
                        word_embedding_weights=state["text_pre_encoder_body.weight"]
                        .cpu()
                        .numpy()
                    ),
                    stream,
                )
            args.data_path = temporary + os.sep
            self.model = MDM(args)
        self.model.load_state_dict(state, strict=True)
        self.model.eval().to(self.device)
        del state
        self.vq = []
        self.indices = h3d_part_indices()
        for part, size in (("upper", 156), ("hands", 360), ("lower", 107)):
            args.body_part = part
            original_reset = QuantizeEMAReset.reset_codebook
            try:
                QuantizeEMAReset.reset_codebook = portable_codebook
                model = RVQVAE(args, size, 512, 512, 512, 2, 2, 512, 3, 3, "relu", None)
            finally:
                QuantizeEMAReset.reset_codebook = original_reset
            model.load_state_dict(
                load(getattr(args, f"vqvae_{part}_path"), "net"), strict=True
            )
            self.vq.append(model.eval().to(self.device))
        self.text = DistilbertActorAgnosticEncoder(
            str(assets / "ckpt/distilbert-base-uncased"), num_layers=4
        )
        self.text.load_state_dict(
            load(Path(args.tmr_base_path) / "text_epoch=299.ckpt"), strict=True
        )
        self.text.eval().to(self.device)
        self.diffusion = create_gaussian_diffusion(use_ddim=True)
        self.mean = np.load(args.mean_pose_path, allow_pickle=False).reshape(-1)
        self.std = np.load(args.std_pose_path, allow_pickle=False).reshape(-1)
        if (
            self.mean.shape != (623,)
            or self.std.shape != (623,)
            or not np.isfinite(self.mean).all()
            or not np.all(self.std > 0)
        ):
            raise ValueError("SynTalker checkpoint requires valid H3D623 statistics")
        self.prompt_scale = float(settings.get("prompt_scale", args.prompt_scale))
        self.audio_scale = float(settings.get("audio_scale", args.audio_scale))
        self.facts = {
            "device": str(self.device),
            "torch_version": torch.__version__,
            "speech_words": "null_tokens_no_forced_alignment",
            "face": False,
            "finalize_required": True,
            "decoder_context": "complete_latent_sequence",
        }

    def audio_features(self, waveform):
        # Match the released training extractor, including its frame-index onset
        # placement. A corrected onset extractor requires a separately evaluated checkpoint.
        return beat_audio_features(waveform)

    def generate(self, request, state):
        torch, device = self.torch, self.device
        waveform, mask, prompts = conditions(request, self.window_frames)
        prefix = request.start_frame - request.audio_start_frame
        if prefix != (self.history_frames if state else 0) or request.frames % 4:
            raise ValueError(
                "SynTalker windows require contiguous four-frame latent boundaries"
            )
        torch.manual_seed((request.seed + request.sequence) % 2147483647)
        with torch.inference_mode():
            seed = (
                state["latent"]
                if state
                else torch.cat(
                    [
                        model.map2latent(
                            torch.zeros(1, 16, len(indices), device=device)
                        )
                        for model, indices in zip(self.vq, self.indices)
                    ],
                    dim=-1,
                )
                / 10
            )
            audio = torch.as_tensor(self.audio_features(waveform), device=device)[None]
            latent_mask = torch.as_tensor(
                mask.reshape(32, 4).mean(-1), device=device
            ).view(1, 1, 1, 32)
            text = [
                (
                    self.text([p]).loc,
                    torch.as_tensor(w.reshape(32, 4).mean(-1), device=device).view(
                        1, 1, 1, 32
                    ),
                )
                for p, w in prompts.items()
            ]
            common = dict(
                audio=audio,
                word=torch.zeros(1, 128, dtype=torch.long, device=device),
                seed=seed,
                mask=torch.ones(1, 1, 1, 128, dtype=torch.bool, device=device),
            )

            def denoise(x, timesteps, **kwargs):
                y = dict(common, style_feature=text[0][0])
                uncond = self.model(
                    x, timesteps, y=dict(y, uncond=True, uncond_audio=True)
                )
                output = uncond.clone()
                for feature, weights in text:
                    pred = self.model(
                        x,
                        timesteps,
                        y=dict(y, style_feature=feature, uncond_audio=True),
                    )
                    output += weights * self.prompt_scale * (pred - uncond)
                if mask.any():
                    speech = self.model(x, timesteps, y=dict(y, uncond=True))
                    output += latent_mask * self.audio_scale * (speech - uncond)
                if state:
                    output[..., :4] = seed.permute(0, 2, 1).unsqueeze(2)
                return output

            sample = self.diffusion.ddim_sample_loop(
                denoise,
                (1, 1536, 1, 32),
                device=device,
                clip_denoised=False,
                progress=False,
                model_kwargs={"y": {}},
            )
            latent = sample[:, :, 0].permute(0, 2, 1)
            normalized = torch.zeros(1, 128, 623, device=device)
            for index, (model, indices) in enumerate(zip(self.vq, self.indices)):
                decoded = model.latent2origin(
                    latent[..., index * 512 : (index + 1) * 512] * 10
                )[0]
                normalized[..., indices] = decoded
            end = prefix + request.frames
            result = normalized[0, prefix:end].cpu().numpy() * self.std + self.mean
            chunks = list(state["chunks"]) if state else []
            chunks.append(latent[:, prefix // 4 : end // 4].detach().clone())
            state = {
                "latent": latent[:, end // 4 - 4 : end // 4].detach().clone(),
                "chunks": chunks,
            }
        return result, state

    def finalize(self, state):
        """Match upstream: concatenate latents before the temporal RVQ decoder.

        Window outputs are provisional: convolution padding changes their edges.
        Retargeting and playback must consume this complete decode instead.
        """
        torch = self.torch
        with torch.inference_mode():
            latent = torch.cat(state["chunks"], dim=1)
            normalized = torch.zeros(1, latent.shape[1] * 4, 623, device=self.device)
            for index, (model, indices) in enumerate(zip(self.vq, self.indices)):
                normalized[..., indices] = model.latent2origin(
                    latent[..., index * 512 : (index + 1) * 512] * 10
                )[0]
            return normalized[0].cpu().numpy() * self.std + self.mean
