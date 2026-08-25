from __future__ import annotations

import gc
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from virea_model_sdk.upstream_runtime import (
    InstalledArtifactRoots,
    upstream_import_scope,
)
from virea_model_sdk.worker import WorkerFailure
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

SOURCE_REVISION = "bb67ae1ed6ce051080468bf15bc6e54a6c3f8417"
CHECKPOINT_REVISION = "google-drive-folder-1vJg3GFVPT6kr6cA0HrQGmiAEBE2dkaps"
CLIP_REVISION = "d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"
SMPLX_REVISION = "smplx-lockedhead-20230207-user-supplied"

ARTIFACT_REQUIREMENTS = {
    "dart-source": (
        "source/mld/rollout_mld.py",
        "source/model/mld_denoiser.py",
        "source/model/mld_vae.py",
        "source/config_files/config_hydra/motion_primitive/mp_h2_f8_r8.yaml",
    ),
    "dart-babel-checkpoints-and-runtime-data": (
        "mld_denoiser/mld_fps_clip_repeat_euler/args.yaml",
        "mld_denoiser/mld_fps_clip_repeat_euler/checkpoint_300000.pt",
        "mvae/mvae_fps_clip/args.yaml",
        "mvae/mvae_fps_clip/checkpoint_200000.pt",
        "data/stand.pkl",
        "data/seq_data_zero_male/mean_std_h2_f8.pkl",
    ),
    "dart-smplx-lockedhead-20230207": (
        "models_lockedhead/smplx/SMPLX_MALE.npz",
        "models_lockedhead/smplx/SMPLX_FEMALE.npz",
    ),
    "dart-openai-clip-vit-b32": ("ViT-B-32.pt",),
}


@dataclass(frozen=True, slots=True)
class DartTextSegment:
    text: str
    primitive_count: int


@dataclass(frozen=True, slots=True)
class DartGeneration:
    transl: np.ndarray
    global_orient: np.ndarray
    body_pose: np.ndarray
    primitive_boundaries: np.ndarray
    betas: np.ndarray
    gender: str
    text_segments: tuple[dict[str, Any], ...]
    continuity_evidence: dict[str, Any]


class _DartArgsLoader(yaml.SafeLoader):
    """Read Tyro's type-tagged YAML as inert data, never as Python objects."""


def _construct_tagged_value(
    loader: _DartArgsLoader, _tag_suffix: str, node: Any
) -> Any:
    if isinstance(node, MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, ScalarNode):
        return loader.construct_scalar(node)
    raise yaml.constructor.ConstructorError("unsupported DART args node")


_DartArgsLoader.add_multi_constructor("!", _construct_tagged_value)
_DartArgsLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/", _construct_tagged_value
)


def _yaml_mapping(path: Path) -> dict[str, Any]:
    value: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(value, str):
        value = yaml.load(value, Loader=_DartArgsLoader)
    if not isinstance(value, dict):
        raise WorkerFailure(
            "MODEL_ARTIFACT_INCOMPLETE", f"DART args file is not a mapping: {path}"
        )
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkerFailure("MODEL_LOAD_FAILED", f"DART args field {name} is invalid")
    return value


class DartBackend:
    def __init__(self, roots: InstalledArtifactRoots | None = None) -> None:
        self.roots = roots or InstalledArtifactRoots.from_environment(
            ARTIFACT_REQUIREMENTS
        )
        self.source_root = self.roots["dart-source"] / "source"
        self.bundle_root = self.roots["dart-babel-checkpoints-and-runtime-data"]
        self.body_model_root = (
            self.roots["dart-smplx-lockedhead-20230207"] / "models_lockedhead"
        )
        self.clip_checkpoint = self.roots["dart-openai-clip-vit-b32"] / "ViT-B-32.pt"
        self._torch: Any | None = None
        self._denoiser_args: dict[str, Any] | None = None
        self._denoiser: Any | None = None
        self._vae: Any | None = None
        self._diffusion: Any | None = None
        self._dataset: Any | None = None
        self._encode_text: Any | None = None
        self._compose_texts: Any | None = None
        self._transforms: Any | None = None
        self._device = "unloaded"

    @property
    def loaded(self) -> bool:
        return all(
            value is not None
            for value in (
                self._denoiser,
                self._vae,
                self._diffusion,
                self._dataset,
            )
        )

    @property
    def device_facts(self) -> dict[str, Any]:
        return {
            "device": self._device,
            "memory_strategy": os.getenv("VIREA_MEMORY_STRATEGY", "cpu"),
            "implicit_network_access": False,
            "source_revision": SOURCE_REVISION,
            "checkpoint_revision": CHECKPOINT_REVISION,
            "smplx_revision": SMPLX_REVISION,
            "clip_revision": CLIP_REVISION,
            "rotation_backend": "portable_pytorch3d_bsd_subset",
        }

    def load(self) -> None:
        if self.loaded:
            return
        denoiser_checkpoint = (
            self.bundle_root
            / "mld_denoiser/mld_fps_clip_repeat_euler/checkpoint_300000.pt"
        )
        denoiser_yaml = denoiser_checkpoint.parent / "args.yaml"
        vae_checkpoint = self.bundle_root / "mvae/mvae_fps_clip/checkpoint_200000.pt"
        vae_yaml = vae_checkpoint.parent / "args.yaml"
        denoiser_config = _yaml_mapping(denoiser_yaml)
        vae_config = _yaml_mapping(vae_yaml)

        with upstream_import_scope(
            self.source_root, working_directory=self.source_root
        ):
            try:
                import clip
                import config_files.data_paths as data_paths
                import torch

                data_paths.body_model_dir = self.body_model_root
                from data_loaders.humanml.data.dataset import SinglePrimitiveDataset
                from diffusion import gaussian_diffusion as gd
                from diffusion.respace import SpacedDiffusion, space_timesteps
                from model.mld_denoiser import DenoiserMLP, DenoiserTransformer
                from model.mld_vae import AutoMldVae
                from pytorch3d import transforms
                from utils.misc_util import (
                    compose_texts_with_and,
                    encode_text,
                )
            except Exception as exc:
                raise WorkerFailure(
                    "UPSTREAM_IMPORT_FAILED",
                    f"DART source import failed: {type(exc).__name__}: {exc}",
                ) from exc

            use_cuda = (
                os.getenv("VIREA_MEMORY_STRATEGY", "cpu") != "cpu"
                and torch.cuda.is_available()
            )
            device = torch.device("cuda:0" if use_cuda else "cpu")
            original_clip_load = clip.load
            original_convert_weights = clip.model.convert_weights

            def local_clip_load(_name: str, *args: Any, **kwargs: Any) -> Any:
                return original_clip_load(str(self.clip_checkpoint), *args, **kwargs)

            clip.load = local_clip_load
            if device.type == "cpu":
                clip.model.convert_weights = lambda _model: None
            try:
                denoiser_section = _mapping(
                    denoiser_config.get("denoiser_args"), "denoiser_args"
                )
                denoiser_model_args = _mapping(
                    denoiser_section.get("model_args"),
                    "denoiser_args.model_args",
                )
                model_type = str(denoiser_section.get("model_type", "mlp"))
                model_class = (
                    DenoiserMLP if model_type == "mlp" else DenoiserTransformer
                )
                denoiser_model = model_class(**denoiser_model_args).to(device)
                checkpoint = torch.load(
                    denoiser_checkpoint,
                    map_location=device,
                    weights_only=False,
                )
                denoiser_model.load_state_dict(checkpoint["model_state_dict"])
                denoiser_model.requires_grad_(False).eval()

                class ClassifierFreeWrapper(torch.nn.Module):
                    def __init__(self, model: Any) -> None:
                        super().__init__()
                        if model.cond_mask_prob <= 0:
                            raise ValueError(
                                "DART classifier-free checkpoint lacks condition masking"
                            )
                        self.model = model

                    def forward(
                        self,
                        values: Any,
                        timesteps: Any,
                        y: dict[str, Any] | None = None,
                    ) -> Any:
                        if y is None:
                            raise ValueError("DART denoiser requires conditioning")
                        conditioned = dict(y)
                        conditioned["uncond"] = False
                        output = self.model(values, timesteps, conditioned)
                        unconditioned = dict(y)
                        unconditioned["uncond"] = True
                        output_unconditioned = self.model(
                            values, timesteps, unconditioned
                        )
                        return output_unconditioned + y["scale"] * (
                            output - output_unconditioned
                        )

                denoiser = ClassifierFreeWrapper(denoiser_model)

                vae_model_args = _mapping(vae_config.get("model_args"), "model_args")
                vae_model = AutoMldVae(**vae_model_args).to(device)
                checkpoint = torch.load(
                    vae_checkpoint, map_location=device, weights_only=False
                )
                state = dict(checkpoint["model_state_dict"])
                state.setdefault("latent_mean", torch.tensor(0.0, device=device))
                state.setdefault("latent_std", torch.tensor(1.0, device=device))
                vae_model.load_state_dict(state)
                vae_model.latent_mean = state["latent_mean"]
                vae_model.latent_std = state["latent_std"]
                vae_model.requires_grad_(False).eval()

                diffusion_config = _mapping(
                    denoiser_section.get("diffusion_args"),
                    "denoiser_args.diffusion_args",
                )
                steps = int(diffusion_config.get("diffusion_steps", 10))
                betas = gd.get_named_beta_schedule(
                    str(diffusion_config.get("noise_schedule", "cosine")),
                    steps,
                    1.0,
                )
                diffusion = SpacedDiffusion(
                    use_timesteps=space_timesteps(steps, [steps]),
                    betas=betas,
                    model_mean_type=gd.ModelMeanType.START_X,
                    model_var_type=(
                        gd.ModelVarType.FIXED_SMALL
                        if bool(diffusion_config.get("sigma_small", True))
                        else gd.ModelVarType.FIXED_LARGE
                    ),
                    loss_type=gd.LossType.MSE,
                    rescale_timesteps=False,
                )

                vae_data = _mapping(vae_config.get("data_args"), "data_args")
                cfg_value = str(
                    vae_data.get(
                        "cfg_path",
                        "./config_files/config_hydra/motion_primitive/mp_h2_f8_r8.yaml",
                    )
                ).replace("\\", "/")
                cfg_path = self.source_root / cfg_value.removeprefix("./")
                dataset = SinglePrimitiveDataset(
                    cfg_path=cfg_path,
                    dataset_path=self.bundle_root / "data/seq_data_zero_male",
                    body_type=str(vae_data.get("body_type", "smplx")),
                    sequence_path=self.bundle_root / "data/stand.pkl",
                    batch_size=1,
                    device=device,
                    enforce_gender="male",
                    enforce_zero_beta=1,
                )
                if device.type == "cpu":
                    dataset.clip_model.float()
            except WorkerFailure:
                raise
            except Exception as exc:
                if "out of memory" in str(exc).lower():
                    raise WorkerFailure("WORKER_OOM", str(exc), retryable=True) from exc
                raise WorkerFailure(
                    "MODEL_LOAD_FAILED",
                    f"DART load failed: {type(exc).__name__}: {exc}",
                ) from exc
            finally:
                clip.load = original_clip_load
                clip.model.convert_weights = original_convert_weights

        self._torch = torch
        self._denoiser_args = denoiser_section
        self._denoiser = denoiser
        self._vae = vae_model
        self._diffusion = diffusion
        self._dataset = dataset
        self._encode_text = encode_text
        self._compose_texts = compose_texts_with_and
        self._transforms = transforms
        self._device = str(device)

    def unload(self) -> None:
        torch_module = self._torch
        self._torch = None
        self._denoiser_args = None
        self._denoiser = None
        self._vae = None
        self._diffusion = None
        self._dataset = None
        self._encode_text = None
        self._compose_texts = None
        self._transforms = None
        self._device = "unloaded"
        gc.collect()
        if torch_module is not None and torch_module.cuda.is_available():
            torch_module.cuda.empty_cache()

    def generate(
        self,
        segments: tuple[DartTextSegment, ...],
        *,
        seed: int,
        guidance_scale: float,
        fix_floor: bool,
    ) -> DartGeneration:
        if not self.loaded:
            raise WorkerFailure("MODEL_NOT_LOADED", "DART is not loaded")
        if not segments or sum(segment.primitive_count for segment in segments) > 64:
            raise WorkerFailure(
                "INVALID_REQUEST", "DART requires between 1 and 64 motion primitives"
            )
        torch = self._torch
        assert torch is not None
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        device = next(self._denoiser.parameters()).device
        if device.type == "cuda":
            torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True

        with upstream_import_scope(
            self.source_root, working_directory=self.source_root
        ):
            try:
                with torch.inference_mode():
                    result = self._rollout(
                        segments,
                        guidance_scale=guidance_scale,
                        fix_floor=fix_floor,
                    )
            except WorkerFailure:
                raise
            except Exception as exc:
                if "out of memory" in str(exc).lower():
                    raise WorkerFailure("WORKER_OOM", str(exc), retryable=True) from exc
                raise WorkerFailure(
                    "MODEL_INFERENCE_FAILED",
                    f"DART rollout failed: {type(exc).__name__}: {exc}",
                ) from exc
        return result

    def _rollout(
        self,
        segments: tuple[DartTextSegment, ...],
        *,
        guidance_scale: float,
        fix_floor: bool,
    ) -> DartGeneration:
        torch = self._torch
        dataset = self._dataset
        denoiser_args = self._denoiser_args
        assert torch is not None and dataset is not None and denoiser_args is not None
        device = next(self._denoiser.parameters()).device
        history_length = int(dataset.history_length)
        future_length = int(dataset.future_length)
        primitive_length = history_length + future_length

        primitive_texts: list[str] = []
        for segment in segments:
            composed = self._compose_texts(segment.text.split(" and "))
            primitive_texts.extend([composed] * segment.primitive_count)
        text_embeddings = self._encode_text(
            dataset.clip_model, primitive_texts, force_empty_zero=True
        ).to(dtype=torch.float32, device=device)

        batch = dataset.get_batch(batch_size=1)
        input_motions = batch[0]["motion_tensor_normalized"]
        model_values = dict(batch[0])
        model_values.pop("motion_tensor_normalized")
        gender = str(model_values["gender"][0])
        betas = model_values["betas"][:, :primitive_length, :].to(device)
        utility = dataset.primitive_utility
        pelvis_delta = utility.calc_calibrate_offset(
            {"betas": betas[:, 0, :], "gender": gender}
        )
        motion_tensor = input_motions.to(device).squeeze(2).permute(0, 2, 1)
        history = motion_tensor[:, :history_length, :]
        transform_rotation = torch.eye(3, device=device, dtype=torch.float32).unsqueeze(
            0
        )
        transform_translation = torch.zeros(1, 1, 3, device=device, dtype=torch.float32)
        if fix_floor:
            history_dict = utility.tensor_to_dict(dataset.denormalize(history))
            joints = history_dict["joints"].reshape(1, history_length, 22, 3)
            transform_translation[:, :, 2] = (
                -joints[:, 0, :, 2].amin(dim=-1).unsqueeze(-1)
            )

        denoiser_model_args = _mapping(denoiser_args.get("model_args"), "model_args")
        noise_shape = tuple(int(value) for value in denoiser_model_args["noise_shape"])
        rescale_latent = int(denoiser_args.get("rescale_latent", 1))
        motion_sequences: dict[str, Any] | None = None
        boundaries: list[tuple[int, int]] = []
        output_cursor = 0

        for primitive_index, text_embedding in enumerate(text_embeddings):
            guidance = torch.ones(1, *noise_shape, device=device) * guidance_scale
            conditioning = {
                "text_embedding": text_embedding.expand(1, -1),
                "history_motion_normalized": history,
                "scale": guidance,
            }
            latent = self._diffusion.p_sample_loop(
                self._denoiser,
                (1, *noise_shape),
                clip_denoised=False,
                model_kwargs={"y": conditioning},
                skip_timesteps=0,
                init_image=None,
                progress=False,
                dump_steps=None,
                noise=None,
                const_noise=False,
            ).permute(1, 0, 2)
            future = self._vae.decode(
                latent,
                history,
                nfuture=future_length,
                scale_latent=rescale_latent,
            )
            future_frames = dataset.denormalize(future)
            all_frames = torch.cat((dataset.denormalize(history), future_frames), dim=1)
            if primitive_index == 0:
                future_frames = all_frames
            if fix_floor:
                feature_dict = utility.tensor_to_dict(future_frames)
                joints = feature_dict["joints"].reshape(1, -1, 22, 3)
                joints = torch.einsum(
                    "bij,btkj->btki", transform_rotation, joints
                ) + transform_translation.unsqueeze(1)
                minimum_height = joints[..., 2].amin(dim=-1)
                floor_translation = torch.zeros(
                    1, joints.shape[1], 3, device=device, dtype=torch.float32
                )
                floor_translation[:, :, 2] = -minimum_height
                feature_dict["transl"] += floor_translation
                local_floor = torch.einsum(
                    "bij,bti->btj", transform_rotation, floor_translation
                )
                joints += local_floor.unsqueeze(2)
                feature_dict["joints"] = joints.reshape(1, -1, 66)
                future_frames = utility.dict_to_tensor(feature_dict)

            feature_dict = utility.tensor_to_dict(future_frames)
            feature_dict.update(
                {
                    "transf_rotmat": transform_rotation,
                    "transf_transl": transform_translation,
                    "gender": gender,
                    "betas": (
                        betas[:, :primitive_length, :]
                        if primitive_index == 0
                        else betas[:, :future_length, :]
                    ),
                    "pelvis_delta": pelvis_delta,
                }
            )
            primitive = utility.feature_dict_to_smpl_dict(feature_dict)
            primitive = utility.transform_primitive_to_world(primitive)
            contribution = int(primitive["transl"].shape[1])
            boundaries.append((output_cursor, output_cursor + contribution))
            output_cursor += contribution
            if motion_sequences is None:
                motion_sequences = primitive
            else:
                for key in ("transl", "global_orient", "body_pose", "betas", "joints"):
                    motion_sequences[key] = torch.cat(
                        (motion_sequences[key], primitive[key]), dim=1
                    )

            new_history = all_frames[:, -history_length:, :]
            history_features = utility.tensor_to_dict(new_history)
            history_features.update(
                {
                    "transf_rotmat": transform_rotation,
                    "transf_transl": transform_translation,
                    "gender": gender,
                    "betas": betas[:, :history_length, :],
                    "pelvis_delta": pelvis_delta,
                }
            )
            canonical, blended = utility.get_blended_feature(
                history_features, use_predicted_joints=0
            )
            transform_rotation = canonical["transf_rotmat"]
            transform_translation = canonical["transf_transl"]
            history = dataset.normalize(utility.dict_to_tensor(blended))

        assert motion_sequences is not None
        transl = motion_sequences["transl"][0].detach().cpu().numpy().astype(np.float32)
        global_matrices = motion_sequences["global_orient"][0]
        body_matrices = motion_sequences["body_pose"][0]
        global_orient = (
            self._transforms.matrix_to_axis_angle(global_matrices)
            .reshape(-1, 3)
            .detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        body_pose = (
            self._transforms.matrix_to_axis_angle(body_matrices)
            .reshape(-1, 63)
            .detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        shape = (
            motion_sequences["betas"][0, 0, :10]
            .detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        boundary_array = np.asarray(boundaries, dtype=np.int64)
        evidence = _continuity_evidence(
            transl, global_matrices.detach().cpu().numpy(), boundary_array
        )
        frame_segments: list[dict[str, Any]] = []
        primitive_cursor = 0
        for segment in segments:
            first = boundaries[primitive_cursor][0]
            last = boundaries[primitive_cursor + segment.primitive_count - 1][1]
            frame_segments.append(
                {
                    "text": segment.text,
                    "start_frame": int(first),
                    "end_frame": int(last),
                    "primitive_count": segment.primitive_count,
                }
            )
            primitive_cursor += segment.primitive_count
        if not all(
            np.isfinite(values).all()
            for values in (transl, global_orient, body_pose, shape)
        ):
            raise WorkerFailure(
                "NATIVE_OUTPUT_INVALID", "DART produced NaN or infinity"
            )
        return DartGeneration(
            transl=np.ascontiguousarray(transl),
            global_orient=np.ascontiguousarray(global_orient),
            body_pose=np.ascontiguousarray(body_pose),
            primitive_boundaries=boundary_array,
            betas=np.ascontiguousarray(shape),
            gender=gender,
            text_segments=tuple(frame_segments),
            continuity_evidence=evidence,
        )


def _continuity_evidence(
    transl: np.ndarray, global_matrices: np.ndarray, boundaries: np.ndarray
) -> dict[str, Any]:
    frame_deltas = np.linalg.norm(np.diff(transl, axis=0), axis=1)
    typical_delta = float(np.median(frame_deltas)) if frame_deltas.size else 0.0
    translation_limit = max(0.75, typical_delta * 25.0)
    boundary_translation: list[float] = []
    boundary_rotation: list[float] = []
    for start in boundaries[1:, 0]:
        index = int(start)
        boundary_translation.append(
            float(np.linalg.norm(transl[index] - transl[index - 1]))
        )
        relative = global_matrices[index - 1].T @ global_matrices[index]
        cosine = float(np.clip((np.trace(relative) - 1.0) * 0.5, -1.0, 1.0))
        boundary_rotation.append(float(np.arccos(cosine)))
    max_translation = max(boundary_translation, default=0.0)
    max_rotation = max(boundary_rotation, default=0.0)
    if max_translation > translation_limit or max_rotation > 1.5:
        raise WorkerFailure(
            "NATIVE_OUTPUT_INVALID",
            "DART primitive overlap continuity verification failed",
        )
    return {
        "verified": True,
        "method": "upstream_get_blended_feature_plus_boundary_jump_validation",
        "translation_limit_m": translation_limit,
        "max_boundary_translation_m": max_translation,
        "max_boundary_rotation_rad": max_rotation,
        "boundary_count": len(boundary_translation),
    }
