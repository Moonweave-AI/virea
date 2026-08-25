from __future__ import annotations

import base64
import binascii
import gc
import io
import math
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote, urlparse

import numpy as np
from virea_model_sdk.upstream_runtime import (
    InstalledArtifactRoots,
    upstream_import_scope,
)
from virea_model_sdk.worker import WorkerFailure

SOURCE_REVISION = "71c61b05a0609a41c17aa146c9f4ee7778ebc649"
CHECKPOINT_REVISION = "242b2031a913dd1b25f43fe1f3e112611864c9cc"

ARTIFACT_REQUIREMENTS = {
    "sentiavatar-source": (
        "source/motion_generation/pipeline_infer.py",
        "source/motion_generation/models/audio_motion_model.py",
        "source/motion_generation/models/rvqvae.py",
        "source/motion_generation/face_model_vq.py",
        "source/motion_generation/meta/mta_gen_demo/mean.npy",
        "source/motion_generation/meta/mta_gen_demo/std.npy",
        "source/motion_generation/meta/xiu_joint_quat_vecs/Daiji_A_001_V001.npy",
        "source/examples/demo.wav",
    ),
    "sentiavatar-checkpoints": (
        "llm/config.json",
        "llm/model.safetensors",
        "llm/tokenizer.json",
        "mask_transformer/config.json",
        "mask_transformer/model.safetensors",
        "rvqvae/opt.txt",
        "rvqvae/model/epoch_30.pth",
        "chinese-hubert-base/config.json",
        "chinese-hubert-base/preprocessor_config.json",
        "chinese-hubert-base/pytorch_model.bin",
        "hubert_kmeans/model.mdl",
        "face_vqvae/pytorch_model_face_fad2cl_260116_codesize2048_codelength512.bin",
        "face_vqvae/mat_final.npy",
        "face_vqvae/mat_final_R_I.npy",
    ),
}

_LIP_COLUMNS = (24, 26, 31, 33, 34, 42, 47, 48, 37, 39, 40, 41)
_NON_LIP_COLUMNS = tuple(
    list(range(0, 24))
    + list(range(27, 31))
    + [25, 32, 35, 36, 38, 43, 44, 45, 46, 49, 50]
)
_AUDIO_DATA_URI = re.compile(
    r"^data:audio/[A-Za-z0-9.+-]+(?:;[^,]*)?;base64,(?P<data>[A-Za-z0-9+/=\r\n]+)$"
)


@dataclass(frozen=True, slots=True)
class SentiAvatarGeneration:
    body153_normalized: np.ndarray
    left_hand120_denormalized: np.ndarray
    right_hand120_denormalized: np.ndarray
    body_mean153: np.ndarray
    body_std153: np.ndarray
    face_arkit51: np.ndarray | None
    chunk_count: int


def _safe_artifact_child(root: Path, relative: str) -> Path:
    normalized = unquote(relative).replace("\\", "/").lstrip("/")
    parts = tuple(part for part in normalized.split("/") if part not in {"", "."})
    if not parts or ".." in parts:
        raise WorkerFailure("INVALID_AUDIO_REFERENCE", "artifact audio path is unsafe")
    candidate = (root / Path(*parts)).resolve(strict=True)
    try:
        candidate.relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise WorkerFailure(
            "INVALID_AUDIO_REFERENCE", "artifact audio path escapes its root"
        ) from exc
    if not candidate.is_file():
        raise WorkerFailure("AUDIO_NOT_FOUND", "referenced audio is not a file")
    return candidate


def _audio_bytes(reference: str, roots: InstalledArtifactRoots) -> bytes:
    if not isinstance(reference, str) or not reference.strip():
        raise WorkerFailure("INVALID_REQUEST", "audio input must be a non-empty string")
    value = reference.strip()
    match = _AUDIO_DATA_URI.fullmatch(value)
    if match:
        try:
            payload = base64.b64decode(match.group("data"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise WorkerFailure(
                "INVALID_AUDIO_DATA", "audio data URI is not valid base64"
            ) from exc
        if not payload or len(payload) > 64 * 1024 * 1024:
            raise WorkerFailure(
                "INVALID_AUDIO_DATA", "inline audio must contain 1 byte to 64 MiB"
            )
        return payload
    if value.startswith("artifact://"):
        parsed = urlparse(value)
        artifact_id = parsed.netloc
        try:
            root = roots[artifact_id]
        except WorkerFailure as exc:
            raise WorkerFailure(
                "INVALID_AUDIO_REFERENCE",
                f"audio references unknown installed artifact {artifact_id!r}",
            ) from exc
        return _safe_artifact_child(root, parsed.path).read_bytes()
    if value.startswith("file://"):
        parsed = urlparse(value)
        rendered = unquote(parsed.path)
        if os.name == "nt" and rendered.startswith("/"):
            rendered = rendered[1:]
        path = Path(rendered)
    else:
        if value[0] in {'"', "'"} or value[-1] in {'"', "'"}:
            raise WorkerFailure(
                "INVALID_AUDIO_REFERENCE",
                "audio path must not include shell quote characters",
            )
        path = Path(value)
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkerFailure("AUDIO_NOT_FOUND", "audio path is unavailable") from exc
    if not resolved.is_file():
        raise WorkerFailure("AUDIO_NOT_FOUND", "audio path is not a file")
    if resolved.stat().st_size > 256 * 1024 * 1024:
        raise WorkerFailure("INVALID_AUDIO_DATA", "audio file exceeds 256 MiB")
    return resolved.read_bytes()


def _read_audio(reference: str, roots: InstalledArtifactRoots) -> np.ndarray:
    try:
        import soundfile as sf
        from scipy.signal import resample_poly

        waveform, sample_rate = sf.read(
            io.BytesIO(_audio_bytes(reference, roots)), dtype="float32", always_2d=False
        )
    except WorkerFailure:
        raise
    except Exception as exc:
        raise WorkerFailure(
            "INVALID_AUDIO_DATA",
            f"could not decode PCM audio: {type(exc).__name__}: {exc}",
        ) from exc
    values = np.asarray(waveform, dtype=np.float32)
    if values.ndim == 2:
        values = values[:, 0]
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise WorkerFailure(
            "INVALID_AUDIO_DATA", "audio must be a finite mono waveform"
        )
    if sample_rate <= 0:
        raise WorkerFailure("INVALID_AUDIO_DATA", "audio sample rate must be positive")
    if sample_rate != 16_000:
        divisor = math.gcd(int(sample_rate), 16_000)
        values = resample_poly(values, 16_000 // divisor, int(sample_rate) // divisor)
    duration = values.size / 16_000.0
    if duration < 0.6 or duration > 30.0:
        raise WorkerFailure(
            "INVALID_AUDIO_DURATION",
            "each audio input must be between 0.6 and 30 seconds",
        )
    return np.ascontiguousarray(values, dtype=np.float32)


class SentiAvatarBackend:
    """Runs the immutable public SentiAvatar graph without a network service."""

    def __init__(self, roots: InstalledArtifactRoots | None = None) -> None:
        self.roots = roots or InstalledArtifactRoots.from_environment(
            ARTIFACT_REQUIREMENTS
        )
        self.source_root = self.roots["sentiavatar-source"] / "source"
        self.motion_root = self.source_root / "motion_generation"
        self.checkpoint_root = self.roots["sentiavatar-checkpoints"]
        self._torch: Any | None = None
        self._pipeline: Any | None = None
        self._tokenizer: Any | None = None
        self._planner: Any | None = None
        self._hubert_extractor: Any | None = None
        self._hubert: Any | None = None
        self._kmeans_centers: np.ndarray | None = None
        self._mask_model: Any | None = None
        self._rvqvae: Any | None = None
        self._face_model: Any | None = None
        self._mean: np.ndarray | None = None
        self._std: np.ndarray | None = None
        self._left_hand: np.ndarray | None = None
        self._right_hand: np.ndarray | None = None
        self._device = "unloaded"

    @property
    def loaded(self) -> bool:
        return self._planner is not None

    @property
    def device_facts(self) -> dict[str, Any]:
        return {
            "device": self._device,
            "memory_strategy": os.getenv("VIREA_MEMORY_STRATEGY", "cpu"),
            "implicit_network_access": False,
            "external_vllm_service": False,
            "source_revision": SOURCE_REVISION,
            "checkpoint_revision": CHECKPOINT_REVISION,
        }

    @staticmethod
    def _checkpoint_state(torch_module: Any, path: Path) -> dict[str, Any]:
        payload = torch_module.load(path, map_location="cpu", weights_only=False)
        if not isinstance(payload, dict):
            raise WorkerFailure(
                "CHECKPOINT_CONTRACT_MISMATCH",
                f"checkpoint is not a mapping: {path.name}",
            )
        for key in ("model_state_dict", "model", "state_dict"):
            state = payload.get(key)
            if isinstance(state, dict):
                return state
        return payload

    @staticmethod
    def _validated_vector(path: Path, *, label: str) -> np.ndarray:
        vector = np.asarray(np.load(path, allow_pickle=False), dtype=np.float32)
        if vector.shape != (153,) or not np.isfinite(vector).all():
            raise WorkerFailure(
                "NORMALIZATION_CONTRACT_MISMATCH",
                f"{label} must be a finite float32 [153] vector",
            )
        return np.ascontiguousarray(vector)

    def _load_rvqvae(self, config_module: Any, rvq_module: Any, device: Any) -> Any:
        config = config_module.Config()
        config.data.body_dim = 153
        config.data.left_dim = 120
        config.data.right_dim = 120
        config.data.whole_dim = 393
        config.data.fps = 20
        config.model.nb_code = 512
        config.model.code_dim = 512
        config.model.down_t = 1
        config.model.stride_t = 2
        config.model.width = 512
        config.model.depth = 3
        config.model.dilation_growth_rate = 3
        config.model.vq_act = "relu"
        config.model.vq_norm = None
        config.model.vq_cnn_depth = 3
        config.model.num_quantizers = 4
        config.model.shared_codebook = False
        config.model.quantize_dropout_prob = 0.8
        config.model.quantize_dropout_cutoff_index = 1
        model = rvq_module.RVQVAE(
            config=config,
            input_dim=393,
            nb_code=512,
            code_dim=512,
            output_dim=512,
            down_t=1,
            stride_t=2,
            width=512,
            depth=3,
            dilation_growth_rate=3,
            activation="relu",
            norm=None,
        )
        checkpoint = self.checkpoint_root / "rvqvae/model/epoch_30.pth"
        model.load_state_dict(
            self._checkpoint_state(self._torch, checkpoint), strict=True
        )
        return model.float().to(device).eval()

    def _load_face_model(self, face_module: Any, device: Any) -> Any:
        from types import SimpleNamespace

        arguments = SimpleNamespace(
            vae_test_dim=51,
            vae_length=512,
            vae_codebook_size=2048,
            vae_layer=2,
            vae_stride=2,
            pose_dims=102,
            audio_feat_dims=768,
            vae_quantizer_lambda=1.0,
            facial_norm=False,
        )
        model = face_module.Af2FaceVQVAEConvZeroStrideV3(arguments)
        checkpoint = self.checkpoint_root / (
            "face_vqvae/pytorch_model_face_fad2cl_260116_codesize2048_codelength512.bin"
        )
        model.load_state_dict(
            self._torch.load(checkpoint, map_location="cpu", weights_only=False),
            strict=True,
        )
        return model.float().to(device).eval()

    def load(self) -> None:
        if self.loaded:
            return
        strategy = os.getenv("VIREA_MEMORY_STRATEGY", "cpu").strip()
        if strategy not in {"cpu", "cuda_full"}:
            raise WorkerFailure(
                "UNSUPPORTED_MEMORY_STRATEGY",
                "SentiAvatar implements whole-model CPU and CUDA-full strategies",
            )
        environment = {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
        try:
            with upstream_import_scope(
                self.motion_root,
                working_directory=self.motion_root,
                environment=environment,
            ):
                import face_model_vq
                import joblib
                import pipeline_infer
                import torch
                from models import rvqvae
                from transformers import (
                    AutoModelForCausalLM,
                    AutoTokenizer,
                    HubertModel,
                    Wav2Vec2FeatureExtractor,
                )

                from configs import default_config

                if strategy == "cuda_full":
                    if not torch.cuda.is_available():
                        raise WorkerFailure(
                            "CUDA_UNAVAILABLE",
                            "cuda_full requires an NVIDIA CUDA device",
                        )
                    device = torch.device("cuda", torch.cuda.current_device())
                    planner_dtype = (
                        torch.bfloat16
                        if torch.cuda.is_bf16_supported()
                        else torch.float16
                    )
                else:
                    device = torch.device("cpu")
                    planner_dtype = torch.float32
                self._torch = torch
                llm_root = self.checkpoint_root / "llm"
                tokenizer = AutoTokenizer.from_pretrained(
                    llm_root,
                    local_files_only=True,
                    trust_remote_code=False,
                    padding_side="left",
                )
                planner = (
                    AutoModelForCausalLM.from_pretrained(
                        llm_root,
                        local_files_only=True,
                        trust_remote_code=False,
                        dtype=planner_dtype,
                        low_cpu_mem_usage=True,
                    )
                    .to(device)
                    .eval()
                )
                hubert_root = self.checkpoint_root / "chinese-hubert-base"
                hubert_extractor = Wav2Vec2FeatureExtractor.from_pretrained(
                    hubert_root, local_files_only=True
                )
                hubert = (
                    HubertModel.from_pretrained(
                        hubert_root, local_files_only=True, dtype=torch.float32
                    )
                    .to(device)
                    .eval()
                )
                mask_model = pipeline_infer.load_mask_transformer(
                    str(self.checkpoint_root / "mask_transformer"), device=device
                )
                rvq_model = self._load_rvqvae(default_config, rvqvae, device)
                face_model = self._load_face_model(face_model_vq, device)
                kmeans = joblib.load(self.checkpoint_root / "hubert_kmeans/model.mdl")
                centers = np.asarray(kmeans.cluster_centers_, dtype=np.float32)
                if centers.ndim != 2 or centers.shape[1] != 768:
                    raise WorkerFailure(
                        "CHECKPOINT_CONTRACT_MISMATCH",
                        f"HuBERT K-means centers have shape {centers.shape}",
                    )
                mean = self._validated_vector(
                    self.motion_root / "meta/mta_gen_demo/mean.npy", label="body mean"
                )
                std = self._validated_vector(
                    self.motion_root / "meta/mta_gen_demo/std.npy", label="body std"
                )
                if np.any(std <= 0):
                    raise WorkerFailure(
                        "NORMALIZATION_CONTRACT_MISMATCH",
                        "body standard deviation must be strictly positive",
                    )
                placeholder = np.load(
                    self.motion_root / "meta/xiu_joint_quat_vecs/Daiji_A_001_V001.npy",
                    allow_pickle=True,
                ).item()
                left = self._validated_hands(placeholder, "left")
                right = self._validated_hands(placeholder, "right")
        except WorkerFailure:
            self.unload()
            raise
        except Exception as exc:
            self.unload()
            code = (
                "WORKER_OOM"
                if "out of memory" in str(exc).lower()
                else "MODEL_LOAD_FAILED"
            )
            raise WorkerFailure(
                code,
                f"SentiAvatar load failed: {type(exc).__name__}: {exc}",
                retryable=code == "WORKER_OOM",
            ) from exc
        self._pipeline = pipeline_infer
        self._tokenizer = tokenizer
        self._planner = planner
        self._hubert_extractor = hubert_extractor
        self._hubert = hubert
        self._kmeans_centers = np.ascontiguousarray(centers)
        self._mask_model = mask_model
        self._rvqvae = rvq_model
        self._face_model = face_model
        self._mean = mean
        self._std = std
        self._left_hand = left
        self._right_hand = right
        self._device = str(device)

    @staticmethod
    def _validated_hands(placeholder: Any, key: str) -> np.ndarray:
        if not isinstance(placeholder, dict) or key not in placeholder:
            raise WorkerFailure(
                "SOURCE_ASSET_CONTRACT_MISMATCH",
                f"official hand template lacks {key!r}",
            )
        values = np.asarray(placeholder[key], dtype=np.float32)
        if values.ndim != 2 or values.shape[1] != 120 or not np.isfinite(values).all():
            raise WorkerFailure(
                "SOURCE_ASSET_CONTRACT_MISMATCH",
                f"official {key} hand template has shape {values.shape}",
            )
        return np.ascontiguousarray(values)

    def unload(self) -> None:
        torch_module = self._torch
        self._torch = None
        self._pipeline = None
        self._tokenizer = None
        self._planner = None
        self._hubert_extractor = None
        self._hubert = None
        self._kmeans_centers = None
        self._mask_model = None
        self._rvqvae = None
        self._face_model = None
        self._mean = None
        self._std = None
        self._left_hand = None
        self._right_hand = None
        self._device = "unloaded"
        for name in tuple(sys.modules):
            module = sys.modules.get(name)
            module_file = getattr(module, "__file__", None)
            if module_file:
                try:
                    Path(module_file).resolve().relative_to(self.motion_root.resolve())
                except (OSError, ValueError):
                    continue
                sys.modules.pop(name, None)
        gc.collect()
        if torch_module is not None and torch_module.cuda.is_available():
            torch_module.cuda.empty_cache()

    def _seed(self, seed: int) -> None:
        random.seed(seed)
        np.random.seed(seed)
        self._torch.manual_seed(seed)
        if self._device.startswith("cuda"):
            self._torch.cuda.manual_seed_all(seed)

    def _audio_features(self, waveform: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        torch = self._torch
        values = self._hubert_extractor(
            waveform, return_tensors="pt", sampling_rate=16_000
        ).input_values.to(self._device)
        with torch.inference_mode():
            output = self._hubert(values, output_hidden_states=True)
        layer9 = output.hidden_states[8].to(dtype=torch.float32)
        target_frames = max(1, int(round(layer9.shape[1] * (10.0 / 50.0))))
        features = torch.nn.functional.interpolate(
            layer9.permute(0, 2, 1),
            size=target_frames,
            mode="linear",
            align_corners=False,
        ).permute(0, 2, 1)[0]
        layer9_numpy = np.ascontiguousarray(features.cpu().numpy(), dtype=np.float32)
        last_hidden = output.last_hidden_state.to(dtype=torch.float32)
        return layer9_numpy, last_hidden

    def _audio_tokens(self, features: np.ndarray) -> list[int]:
        centers = self._kmeans_centers
        distances = (
            np.sum(features * features, axis=1, keepdims=True)
            - 2.0 * features @ centers.T
            + np.sum(centers * centers, axis=1, keepdims=True).T
        )
        return np.argmin(distances, axis=1).astype(np.int64).tolist()

    def _planner_tokens(
        self,
        prompt: str,
        *,
        temperature: float,
        top_p: float,
        max_new_tokens: int,
    ) -> dict[str, list[int]]:
        pipeline = self._pipeline
        formatted = f"Human: {prompt}<|im_end|>\nAssistant:"
        encoded = self._tokenizer(formatted, return_tensors="pt")
        encoded = {key: value.to(self._device) for key, value in encoded.items()}
        stop_id = self._tokenizer.convert_tokens_to_ids("<|im_end|>")
        with self._torch.inference_mode():
            generated = self._planner.generate(
                **encoded,
                do_sample=True,
                temperature=temperature,
                top_p=top_p,
                max_new_tokens=max_new_tokens,
                eos_token_id=stop_id,
                pad_token_id=self._tokenizer.eos_token_id,
                use_cache=True,
            )
        suffix = generated[0, encoded["input_ids"].shape[1] :]
        raw = self._tokenizer.decode(suffix, skip_special_tokens=False)
        cleaned = raw.split("<|im_end|>", 1)[0].replace("<unk>", "").replace(" ", "")
        motion_clean = cleaned.replace("[res_", "[res")
        selected = motion_clean
        for separator in ("[step_4]", "[STEP_4]", "[step_1]", "[STEP_1]"):
            index = selected.lower().rfind(separator.lower())
            if index >= 0:
                selected = selected[index + len(separator) :]
                break
        parsed = pipeline.extract_mids_from_string(selected)
        tokens = {
            "res_1": parsed.get("res1", []),
            "res_2": parsed.get("res2", []),
            "res_3": parsed.get("res3", []),
            "res_4": parsed.get("res4", []),
        }
        common_length = min((len(values) for values in tokens.values()), default=0)
        tokens = {key: values[:common_length] for key, values in tokens.items()}
        if common_length < 2:
            raise WorkerFailure(
                "PLANNER_OUTPUT_INVALID",
                "SentiAvatar planner returned fewer than two aligned keyframes",
                retryable=True,
            )
        if any(
            value < 0 or value >= 512 for values in tokens.values() for value in values
        ):
            raise WorkerFailure(
                "PLANNER_OUTPUT_INVALID",
                "SentiAvatar planner returned a token outside [0, 511]",
            )
        return tokens

    def _decode_body(self, dense_tokens: Sequence[Sequence[int]]) -> np.ndarray:
        token_array = np.asarray(dense_tokens, dtype=np.int64)
        if token_array.ndim != 2 or token_array.shape[1] != 4:
            raise WorkerFailure(
                "NATIVE_OUTPUT_INVALID",
                f"dense token array has shape {token_array.shape}",
            )
        tokens = self._torch.as_tensor(token_array, device=self._device).unsqueeze(0)
        with self._torch.inference_mode():
            decoded = self._rvqvae.forward_decoder({"body": tokens})
        body = np.asarray(
            decoded[0].to(dtype=self._torch.float32).cpu(), dtype=np.float32
        )
        if body.ndim != 2 or body.shape[1] != 153 or not np.isfinite(body).all():
            raise WorkerFailure(
                "NATIVE_OUTPUT_INVALID", f"SentiAvatar RVQ-VAE returned {body.shape}"
            )
        return np.ascontiguousarray(body)

    @staticmethod
    def _aligned_hand(template: np.ndarray, frame_count: int) -> np.ndarray:
        if template.shape[0] >= frame_count:
            return np.ascontiguousarray(template[:frame_count], dtype=np.float32)
        padding = np.repeat(template[-1:], frame_count - template.shape[0], axis=0)
        return np.ascontiguousarray(np.concatenate((template, padding), axis=0))

    def _face(self, last_hidden: Any, frame_count: int) -> np.ndarray:
        token_count = max(2, int(math.ceil(frame_count / 3.0)))
        tokens = np.full((token_count,), 1009, dtype=np.int64)
        tokens[:2] = 878
        tokens[-1] = 878
        token_tensor = self._torch.as_tensor(tokens, device=self._device).unsqueeze(0)
        with self._torch.inference_mode():
            output = self._face_model.decode(token_tensor, af_inputs=last_hidden)
        values = np.asarray(
            output[0].to(dtype=self._torch.float32).cpu(), dtype=np.float32
        )
        if values.ndim != 2 or values.shape[1] != 102:
            raise WorkerFailure(
                "NATIVE_OUTPUT_INVALID",
                f"SentiAvatar Face VQ-VAE returned {values.shape}",
            )
        contour = values[:, :51].copy()
        lips = values[:, 51:].copy()
        contour[:, _LIP_COLUMNS] = 0.0
        lips[:, _NON_LIP_COLUMNS] = 0.0
        face = contour + lips
        if face.shape[0] < frame_count:
            face = np.concatenate(
                (face, np.repeat(face[-1:], frame_count - face.shape[0], axis=0)),
                axis=0,
            )
        face = np.ascontiguousarray(face[:frame_count], dtype=np.float32)
        if not np.isfinite(face).all():
            raise WorkerFailure(
                "NATIVE_OUTPUT_INVALID", "face stream contains non-finite values"
            )
        return face

    def _generate_chunk(
        self,
        audio_reference: str,
        action_text: str,
        *,
        seed: int,
        temperature: float,
        top_p: float,
        generate_steps: int,
        max_new_tokens: int,
        generate_face: bool,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        self._seed(seed)
        waveform = _read_audio(audio_reference, self.roots)
        features, last_hidden = self._audio_features(waveform)
        audio_tokens = self._audio_tokens(features)
        planner_prompt, _ = self._pipeline.construct_llm_prompt(
            action_text, audio_tokens, offset=0, step=4
        )
        sparse = self._planner_tokens(
            planner_prompt,
            temperature=temperature,
            top_p=top_p,
            max_new_tokens=max_new_tokens,
        )
        keyframes = self._pipeline.sparse_to_keyframes(sparse)
        dense = self._pipeline.interpolate_sequence(
            self._mask_model,
            keyframes,
            features,
            generate_steps=generate_steps,
        )
        dense = self._pipeline.ensure_length(dense, features.shape[0])
        dense_array = np.asarray(dense)
        if (
            dense_array.ndim != 2
            or dense_array.shape[1] != 4
            or np.any(dense_array < 0)
            or np.any(dense_array >= 512)
        ):
            raise WorkerFailure(
                "INFILL_OUTPUT_INVALID",
                "SentiAvatar infill transformer returned tokens outside [0, 511]",
            )
        body = self._decode_body(dense)
        face = self._face(last_hidden, body.shape[0]) if generate_face else None
        return body, face

    def generate(
        self,
        audio_references: Sequence[str],
        action_texts: Sequence[str],
        *,
        seed: int,
        temperature: float,
        top_p: float,
        generate_steps: int,
        max_new_tokens: int,
        generate_face: bool,
    ) -> SentiAvatarGeneration:
        required = (
            self._planner,
            self._tokenizer,
            self._hubert,
            self._mask_model,
            self._rvqvae,
            self._face_model,
            self._mean,
            self._std,
            self._left_hand,
            self._right_hand,
        )
        if any(value is None for value in required):
            raise WorkerFailure("MODEL_NOT_LOADED", "SentiAvatar is not loaded")
        if not audio_references or len(audio_references) != len(action_texts):
            raise WorkerFailure(
                "INVALID_REQUEST", "audio chunks and dialogue/action texts must align"
            )
        self._seed(seed)
        bodies: list[np.ndarray] = []
        faces: list[np.ndarray] = []
        try:
            for index, (audio, action) in enumerate(
                zip(audio_references, action_texts, strict=True)
            ):
                body, face = self._generate_chunk(
                    audio,
                    action,
                    seed=seed + index,
                    temperature=temperature,
                    top_p=top_p,
                    generate_steps=generate_steps,
                    max_new_tokens=max_new_tokens,
                    generate_face=generate_face,
                )
                bodies.append(body)
                if face is not None:
                    faces.append(face)
        except WorkerFailure:
            raise
        except Exception as exc:
            code = (
                "WORKER_OOM"
                if "out of memory" in str(exc).lower()
                else "MODEL_INFERENCE_FAILED"
            )
            raise WorkerFailure(
                code,
                f"SentiAvatar inference failed: {type(exc).__name__}: {exc}",
                retryable=code in {"WORKER_OOM", "MODEL_INFERENCE_FAILED"},
            ) from exc
        body = np.ascontiguousarray(np.concatenate(bodies, axis=0), dtype=np.float32)
        frame_count = int(body.shape[0])
        face = (
            np.ascontiguousarray(np.concatenate(faces, axis=0), dtype=np.float32)
            if faces
            else None
        )
        return SentiAvatarGeneration(
            body153_normalized=body,
            left_hand120_denormalized=self._aligned_hand(self._left_hand, frame_count),
            right_hand120_denormalized=self._aligned_hand(
                self._right_hand, frame_count
            ),
            body_mean153=self._mean.copy(),
            body_std153=self._std.copy(),
            face_arkit51=face,
            chunk_count=len(bodies),
        )
