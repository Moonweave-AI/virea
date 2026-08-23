from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .artifacts import ValidatedPrismArtifacts

_UMT5_XXL_LAYOUT = {
    "d_model": 4096,
    "d_ff": 10240,
    "d_kv": 64,
    "num_heads": 64,
    "num_layers": 24,
    "vocab_size": 256384,
}


def _resolve_torch_dtype(torch_module: Any, dtype_name: str) -> Any:
    dtype = {
        "bfloat16": torch_module.bfloat16,
        "float16": torch_module.float16,
        "float32": torch_module.float32,
    }.get(dtype_name)
    if dtype is None:
        raise RuntimeError(f"unsupported PRISM precision: {dtype_name}")
    return dtype


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return value


def _component_checkpoint(root: Path, *, label: str) -> Path:
    supported = (
        root / "model.safetensors",
        root / "diffusion_pytorch_model.safetensors",
    )
    present = [path for path in supported if path.is_file()]
    if len(present) != 1:
        names = ", ".join(path.name for path in supported)
        raise RuntimeError(
            f"PRISM {label} must contain exactly one supported Safetensors "
            f"checkpoint ({names}); found {len(present)}"
        )
    return present[0]


def _validate_component_state(
    model: Any, checkpoint: Path, *, label: str
) -> tuple[str, ...]:
    from safetensors import safe_open

    expected = {
        name: tuple(int(value) for value in tensor.shape)
        for name, tensor in model.state_dict().items()
    }
    with safe_open(str(checkpoint), framework="pt", device="cpu") as handle:
        observed_names = set(handle.keys())
        observed = {
            name: tuple(int(value) for value in handle.get_slice(name).get_shape())
            for name in observed_names
        }
    missing = sorted(set(expected) - observed_names)
    unexpected = sorted(observed_names - set(expected))
    mismatched = sorted(
        (name, expected[name], observed[name])
        for name in set(expected).intersection(observed_names)
        if expected[name] != observed[name]
    )
    problems = {
        "missing_keys": missing,
        "unexpected_keys": unexpected,
        "mismatched_keys": mismatched,
    }
    if any(problems.values()):
        details = ", ".join(
            f"{key}={values[:5]}" for key, values in problems.items() if values
        )
        raise RuntimeError(f"PRISM {label} state mismatch: {details}")
    return tuple(sorted(expected))


def _install_component_tensor(
    model: Any,
    name: str,
    value: Any,
    *,
    torch_module: Any,
) -> None:
    """Install one validated tensor without Accelerate's meta dispatch path."""

    module_name, _, attribute = name.rpartition(".")
    owner = model.get_submodule(module_name) if module_name else model
    parameter = owner._parameters.get(attribute)
    if parameter is not None:
        owner._parameters[attribute] = torch_module.nn.Parameter(
            value,
            requires_grad=parameter.requires_grad,
        )
        return
    if attribute in owner._buffers and owner._buffers[attribute] is not None:
        owner._buffers[attribute] = value
        return
    raise RuntimeError(f"PRISM state target is not a parameter or buffer: {name}")


def _materialize_component_state(
    model: Any,
    checkpoint: Path,
    names: tuple[str, ...],
    *,
    label: str,
    target: Any,
    dtype: Any,
) -> None:
    """Stage each tensor through CPU and install it directly on its final device."""

    import torch
    from safetensors import safe_open

    total = len(names)
    progress_interval = max(total // 4, 1)
    print(
        f"PRISM {label}: loading {total} validated tensors through CPU staging",
        file=sys.stderr,
        flush=True,
    )
    with safe_open(str(checkpoint), framework="pt", device="cpu") as handle:
        metadata = handle.metadata() or {}
        checkpoint_format = metadata.get("format")
        if checkpoint_format not in (None, "pt"):
            raise RuntimeError(
                f"PRISM {label} checkpoint format is not PyTorch: "
                f"{checkpoint_format}"
            )
        for index, name in enumerate(names, start=1):
            source = handle.get_tensor(name)
            # Detach the transfer from the read-only memory map. This keeps the
            # model independent of Windows mapped-file lifetime and bounds CPU
            # staging to one tensor rather than the complete F32 checkpoint.
            staged = source.clone(memory_format=torch.contiguous_format)
            target_dtype = dtype if torch.is_floating_point(staged) else staged.dtype
            materialized = staged.to(
                device=target,
                dtype=target_dtype,
                non_blocking=False,
                copy=False,
            )
            _install_component_tensor(
                model,
                name,
                materialized,
                torch_module=torch,
            )
            del source, staged, materialized
            if index == total or index % progress_interval == 0:
                print(
                    f"PRISM {label}: materialized {index}/{total} tensors",
                    file=sys.stderr,
                    flush=True,
                )
def _materialize_runtime_buffers(
    model: Any,
    checkpoint_names: tuple[str, ...],
    *,
    target: Any,
    dtype: Any,
) -> None:
    """Move non-persistent constructor buffers omitted from the state dict."""

    import torch

    persisted = set(checkpoint_names)
    for name, buffer in tuple(model.named_buffers(remove_duplicate=False)):
        if name in persisted or buffer is None:
            continue
        if buffer.device.type == "meta":
            raise RuntimeError(
                f"PRISM non-persistent buffer cannot be recovered from meta: {name}"
            )
        staged = buffer.clone(memory_format=torch.contiguous_format)
        target_dtype = dtype if torch.is_floating_point(staged) else staged.dtype
        materialized = staged.to(
            device=target,
            dtype=target_dtype,
            non_blocking=False,
            copy=False,
        )
        _install_component_tensor(
            model,
            name,
            materialized,
            torch_module=torch,
        )


def _load_diffusers_component(
    component_class: Any,
    root: Path,
    *,
    label: str,
    target: Any,
    dtype: Any,
) -> Any:
    """Load either official PRISM or standard Diffusers Safetensors layouts."""

    import torch
    from accelerate import init_empty_weights

    checkpoint = _component_checkpoint(root, label=label)
    config = dict(component_class.load_config(str(root), local_files_only=True))
    config.pop("model_type", None)
    if isinstance(config.get("patch_size"), list):
        config["patch_size"] = tuple(config["patch_size"])
    # Keep constructor-only/non-persistent buffers on CPU so their values are
    # available for bounded final-device materialization below.
    with init_empty_weights(include_buffers=False):
        model = component_class.from_config(config)
    names = _validate_component_state(model, checkpoint, label=label)
    _materialize_component_state(
        model,
        checkpoint,
        names,
        label=label,
        target=target,
        dtype=dtype,
    )
    _materialize_runtime_buffers(
        model,
        names,
        target=target,
        dtype=dtype,
    )
    if target.type == "cuda":
        torch.cuda.synchronize(target)
    component_tensors = tuple(model.named_parameters()) + tuple(model.named_buffers())
    remaining_meta = sorted(
        name
        for name, tensor in component_tensors
        if tensor.device.type == "meta"
    )
    if remaining_meta:
        raise RuntimeError(
            f"PRISM {label} remained incomplete after checkpoint load: "
            f"{remaining_meta[:5]}"
        )
    wrong_devices = sorted(
        name
        for name, tensor in component_tensors
        if tensor.device.type != target.type
        or (
            target.index is not None
            and tensor.device.index not in (None, target.index)
        )
    )
    wrong_dtypes = sorted(
        name
        for name, tensor in component_tensors
        if torch.is_floating_point(tensor) and tensor.dtype != dtype
    )
    if wrong_devices or wrong_dtypes:
        raise RuntimeError(
            f"PRISM {label} materialization differs from target: "
            f"wrong_devices={wrong_devices[:5]}, wrong_dtypes={wrong_dtypes[:5]}"
        )
    return model.eval()


def _activate_pinned_source(source: Path) -> None:
    # Model assets are immutable.  CPython otherwise creates __pycache__ beside
    # imported source on writable Windows directories and invalidates the
    # persisted asset integrity tree after an otherwise successful import.
    sys.dont_write_bytecode = True
    existing = sys.modules.get("prism")
    if existing is not None:
        origin = Path(str(getattr(existing, "__file__", ""))).resolve(strict=False)
        try:
            origin.relative_to(source)
        except ValueError as exc:
            raise RuntimeError(
                f"PRISM was imported outside the pinned source: {origin}"
            ) from exc
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    import prism

    origin = Path(prism.__file__).resolve(strict=True)
    try:
        origin.relative_to(source)
    except ValueError as exc:
        raise RuntimeError(
            f"PRISM resolved outside the pinned source: {origin}"
        ) from exc


def _validated_umt5_config(text_encoder_root: Path) -> Any:
    from safetensors import safe_open
    from transformers import UMT5Config

    weights = text_encoder_root / "model.safetensors"
    with safe_open(str(weights), framework="pt", device="cpu") as handle:
        keys = set(handle.keys())

        def shape(name: str) -> tuple[int, ...]:
            if name not in keys:
                raise RuntimeError(f"PRISM UMT5 checkpoint is missing {name}")
            return tuple(int(value) for value in handle.get_slice(name).get_shape())

        observed = {
            "shared": shape("shared.weight"),
            "query": shape("encoder.block.0.layer.0.SelfAttention.q.weight"),
            "relative_bias": shape(
                "encoder.block.0.layer.0.SelfAttention.relative_attention_bias.weight"
            ),
            "feed_forward": shape("encoder.block.0.layer.1.DenseReluDense.wi_0.weight"),
        }
        layer_ids = {
            int(name.split(".")[2])
            for name in keys
            if name.startswith("encoder.block.") and name.split(".")[2].isdigit()
        }
    expected = {
        "shared": (256384, 4096),
        "query": (4096, 4096),
        "relative_bias": (32, 64),
        "feed_forward": (10240, 4096),
    }
    if observed != expected or layer_ids != set(range(24)):
        raise RuntimeError(
            "PRISM UMT5 tensor layout differs from the pinned XXL encoder contract"
        )
    raw = _json_object(text_encoder_root / "config.json")
    raw.update(
        {
            "architectures": ["UMT5EncoderModel"],
            "model_type": "umt5",
            **_UMT5_XXL_LAYOUT,
            "num_decoder_layers": 24,
            "relative_attention_num_buckets": 32,
            "relative_attention_max_distance": 128,
            "feed_forward_proj": "gated-gelu",
            "dense_act_fn": "gelu_new",
            "is_gated_act": True,
            "is_encoder_decoder": True,
            "tie_word_embeddings": False,
            "pad_token_id": 0,
            "eos_token_id": 1,
            "decoder_start_token_id": 0,
        }
    )
    raw.pop("torch_dtype", None)
    return UMT5Config(**raw)


class ModelFreeBody22Processor:
    """PRISM normalization/postprocess math without proprietary SMPL geometry."""

    def __init__(self, statistics: Path) -> None:
        stats = _json_object(statistics)

        def block(
            name: str, width: int, subkey: str | None = None
        ) -> tuple[np.ndarray, np.ndarray]:
            payload = stats.get(name)
            if subkey is not None and isinstance(payload, dict):
                payload = payload.get(subkey) or payload.get("rot6d")
            if not isinstance(payload, dict):
                raise RuntimeError(
                    f"MotionHub statistics are missing {name}.{subkey or ''}"
                )
            mean = np.asarray(payload.get("mean"), dtype=np.float32)
            std = np.asarray(payload.get("std"), dtype=np.float32)
            if mean.shape != (width,) or std.shape != (width,):
                raise RuntimeError(f"MotionHub statistics width mismatch for {name}")
            if (
                not np.isfinite(mean).all()
                or not np.isfinite(std).all()
                or np.any(std <= 0)
            ):
                raise RuntimeError(f"MotionHub statistics are invalid for {name}")
            return mean, std

        parts = (
            block("transl", 3),
            block("transl_vel", 3),
            block("global_orient", 6, "rotation_6d"),
            block("body_pose", 126, "rotation_6d"),
        )
        self.mean = np.concatenate([item[0] for item in parts]).astype(np.float32)
        self.std = np.concatenate([item[1] for item in parts]).astype(np.float32)
        if self.mean.shape != (138,) or self.std.shape != (138,):
            raise RuntimeError("PRISM normalization vector must have width 138")

    def denormalize(self, motion: Any) -> Any:
        import torch

        mean = torch.as_tensor(self.mean, dtype=motion.dtype, device=motion.device)
        std = torch.as_tensor(self.std, dtype=motion.dtype, device=motion.device)
        return motion * std + mean

    @staticmethod
    def inv_convert_transl(transl: Any) -> Any:
        import torch

        first = transl[..., :1, :3]
        following_deltas = transl[..., 1:, 3:6]
        return torch.cumsum(torch.cat((first, following_deltas), dim=-2), dim=-2)

    @staticmethod
    def transl_pose_to_smplx_dict(
        transl: Any,
        poses: Any,
        *,
        mocap_framerate: float = 30.0,
        gender: str = "neutral",
        rot_type: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        del rot_type
        translation = np.asarray(transl.detach().float().cpu(), dtype=np.float32)
        body66 = np.asarray(poses.detach().float().cpu(), dtype=np.float32)
        if translation.ndim != 2 or translation.shape[1] != 3:
            raise RuntimeError(
                f"PRISM translation has invalid shape {translation.shape}"
            )
        if body66.shape != (translation.shape[0], 66):
            raise RuntimeError(f"PRISM body pose has invalid shape {body66.shape}")
        frame_count = int(translation.shape[0])
        full_pose = np.zeros((frame_count, 165), dtype=np.float32)
        full_pose[:, :66] = body66
        return {
            "trans": translation,
            "transl": translation,
            "poses": full_pose,
            "global_orient": body66[:, :3],
            "body_pose": body66[:, 3:66],
            "jaw_pose": full_pose[:, 66:69],
            "leye_pose": full_pose[:, 69:72],
            "reye_pose": full_pose[:, 72:75],
            "left_hand_pose": full_pose[:, 75:120],
            "right_hand_pose": full_pose[:, 120:165],
            "gender": gender,
            "betas": np.zeros((10,), dtype=np.float32),
            "expression": np.zeros((frame_count, 10), dtype=np.float32),
            "mocap_framerate": np.float32(mocap_framerate),
        }


def load_offline_prism_pipeline(
    artifacts: ValidatedPrismArtifacts,
    *,
    device: str,
    dtype_name: str,
) -> Any:
    import torch
    from diffusers import FlowMatchEulerDiscreteScheduler
    from transformers import AutoTokenizer, UMT5EncoderModel

    _activate_pinned_source(artifacts.source)
    from prism.models.autoencoders import AutoencoderKLPrism2DTK
    from prism.models.transformers.motion_prism import PrismTransformerMotionModel
    from prism.pipelines.prism_ar_t2m_pipeline import PrismARPipeline

    dtype = _resolve_torch_dtype(torch, dtype_name)
    target = torch.device(device)
    transformer = _load_diffusers_component(
        PrismTransformerMotionModel,
        artifacts.model / "transformer",
        label="transformer",
        target=target,
        dtype=dtype,
    )

    encoder_config = _validated_umt5_config(artifacts.model / "text_encoder")
    text_encoder = (
        UMT5EncoderModel.from_pretrained(
            str(artifacts.model / "text_encoder"),
            config=encoder_config,
            dtype=dtype,
            low_cpu_mem_usage=True,
            local_files_only=True,
        )
        .to("cpu")
        .eval()
    )
    tokenizer = AutoTokenizer.from_pretrained(
        str(artifacts.tokenizer), local_files_only=True
    )

    vae = _load_diffusers_component(
        AutoencoderKLPrism2DTK,
        artifacts.model / "vae",
        label="VAE",
        target=target,
        dtype=dtype,
    )

    class ComponentSplitPipeline(PrismARPipeline):
        @torch.no_grad()
        def _get_t5_prompt_embeds(
            self,
            prompt=None,
            num_motion_per_prompt: int = 1,
            max_sequence_length: int = 512,
            device=None,
            dtype=None,
        ):
            prompts = [prompt] if isinstance(prompt, str) else prompt
            encoded = self.tokenizer(
                prompts,
                padding="max_length",
                max_length=max_sequence_length,
                truncation=True,
                add_special_tokens=True,
                return_attention_mask=True,
                return_tensors="pt",
            )
            lengths = encoded.attention_mask.gt(0).sum(dim=1).long()
            embeddings = self.text_encoder(
                encoded.input_ids.to("cpu"), encoded.attention_mask.to("cpu")
            ).last_hidden_state
            embeddings = embeddings.to(dtype=dtype, device=device)
            trimmed = [value[:length] for value, length in zip(embeddings, lengths)]
            padded = torch.stack(
                [
                    torch.cat(
                        (
                            value,
                            value.new_zeros(
                                max_sequence_length - value.size(0), value.size(1)
                            ),
                        )
                    )
                    for value in trimmed
                ],
                dim=0,
            )
            _, sequence_length, width = padded.shape
            return padded.repeat(1, num_motion_per_prompt, 1).view(
                len(prompts) * num_motion_per_prompt, sequence_length, width
            )

    scheduler = FlowMatchEulerDiscreteScheduler(
        num_train_timesteps=1000,
        shift=5.0,
        use_dynamic_shifting=False,
        base_shift=0.5,
        max_shift=1.15,
    )
    pipeline = ComponentSplitPipeline(
        tokenizer=tokenizer,
        text_encoder=text_encoder,
        vae=vae,
        transformer=transformer,
        scheduler=scheduler,
        smpl_processor=ModelFreeBody22Processor(artifacts.statistics),
        expand_timesteps=True,
        dtype=dtype,
    )
    pipeline.set_progress_bar_config(disable=True)
    return pipeline
