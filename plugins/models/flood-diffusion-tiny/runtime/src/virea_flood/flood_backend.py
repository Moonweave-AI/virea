from __future__ import annotations

import gc
import importlib
import random
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from .config import MODEL_SPECS, Settings
from .timeline import FloodTimeline

Progress = Callable[[str, float, str], None]
_MISSING = object()


@contextmanager
def _hide_classic_flash_attention(enabled: bool):
    """Make FloodDiffusion select its built-in PyTorch SDPA fallback.

    The official attention module uses optional imports and falls back to
    torch.nn.functional.scaled_dot_product_attention when neither FA2 nor FA3
    is importable.  RTX 50-series is routed here by default because a package
    can import successfully while still lacking a working SM12x kernel.
    """

    if not enabled:
        yield
        return
    names = ("flash_attn", "flash_attn_interface")
    previous = {name: sys.modules.get(name, _MISSING) for name in names}
    try:
        for name in names:
            sys.modules[name] = None
        yield
    finally:
        for name, value in previous.items():
            if value is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


class FloodBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._execution_device = str(
            getattr(settings, "execution_device", "cuda")
        ).lower()
        self._model = None
        self._variant: str | None = None
        self._snapshot: Path | None = None
        self._lock = threading.RLock()

    @staticmethod
    def _purge_modules_from(root: Path | None) -> None:
        if root is None:
            return
        try:
            root = root.resolve()
        except OSError:
            return
        for name, module in list(sys.modules.items()):
            module_file = getattr(module, "__file__", None)
            if not module_file:
                continue
            try:
                candidate = Path(module_file).resolve()
                belongs = candidate.is_relative_to(root)
            except (OSError, ValueError):
                belongs = False
            if belongs:
                sys.modules.pop(name, None)
        retained: list[str] = []
        for item in sys.path:
            try:
                belongs = Path(item).resolve().is_relative_to(root)
            except (OSError, ValueError):
                belongs = False
            if not belongs:
                retained.append(item)
        sys.path[:] = retained
        importlib.invalidate_caches()

    def unload(self) -> None:
        with self._lock:
            previous_snapshot = self._snapshot
            self._model = None
            self._variant = None
            self._snapshot = None
            gc.collect()
            try:
                import torch

                if self._execution_device == "cuda" and torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            self._purge_modules_from(previous_snapshot)

    def _resolved_attention_backend(self) -> str:
        requested = self.settings.attention_backend
        if self._execution_device == "cpu":
            return "sdpa"
        if requested in {"sdpa", "flash"}:
            return requested
        try:
            import torch

            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                if props.major >= 12:
                    return "sdpa"
        except Exception:
            pass
        return "auto"

    @staticmethod
    def _required_snapshot_files(snapshot: Path) -> tuple[Path, ...]:
        return tuple(
            snapshot / name
            for name in (
                "config.json",
                "ldf.yaml",
                "model.safetensors",
                "vae.safetensors",
            )
        )

    def _materialize_snapshot(self, variant: str) -> Path:
        """Return a pinned, physical-file snapshot suitable for Windows.

        ``local_dir`` deliberately avoids the Hub cache's symlink-based
        snapshot layout.  The exact upstream revision remains fixed by the
        model specification.
        """

        spec = MODEL_SPECS[variant]
        snapshot = self.settings.model_dir(variant).resolve()
        if all(path.is_file() for path in self._required_snapshot_files(snapshot)):
            return snapshot

        from huggingface_hub import snapshot_download

        snapshot = Path(
            snapshot_download(
                repo_id=spec.repo_id,
                revision=spec.revision,
                local_dir=str(snapshot),
            )
        ).resolve()
        missing = [
            path.name
            for path in self._required_snapshot_files(snapshot)
            if not path.is_file()
        ]
        if missing:
            raise RuntimeError(
                f"incomplete {spec.label} snapshot; missing required files: {', '.join(missing)}"
            )
        return snapshot

    @staticmethod
    def _activate_official_sdpa_fallback(snapshot: Path) -> None:
        """Route Wan attention calls to FloodDiffusion's bundled SDPA path.

        The pinned upstream snapshot ships a PyTorch SDPA implementation in
        ``ldf_models.tools.attention`` but imports ``flash_attention`` directly
        in ``wan_model``.  On Windows/SM12x there is no compatible official
        FlashAttention wheel.  Rebinding that call site to the snapshot's own
        ``attention`` dispatcher preserves scaled-dot-product attention while
        selecting the bundled CUDA-independent backend.
        """

        snapshot = snapshot.resolve()
        attention_module_found = False
        wan_modules: list[object] = []
        for module in tuple(sys.modules.values()):
            module_file = getattr(module, "__file__", None)
            if not module_file:
                continue
            try:
                belongs = Path(module_file).resolve().is_relative_to(snapshot)
            except (OSError, ValueError):
                belongs = False
            if not belongs:
                continue
            name = getattr(module, "__name__", "")
            if name.endswith("ldf_models.tools.attention"):
                attention_module_found = callable(getattr(module, "attention", None))
            elif name.endswith("ldf_models.tools.wan_model"):
                wan_modules.append(module)

        if not attention_module_found or not wan_modules:
            raise RuntimeError(
                "the pinned FloodDiffusion snapshot did not expose its SDPA fallback"
            )
        for module in wan_modules:
            setattr(module, "flash_attention", FloodBackend._masked_sdpa_attention)

    @staticmethod
    def _masked_sdpa_attention(
        q,
        k,
        v,
        q_lens=None,
        k_lens=None,
        dropout_p=0.0,
        softmax_scale=None,
        q_scale=None,
        causal=False,
        window_size=(-1, -1),
        deterministic=False,
        dtype=None,
        version=None,
    ):
        """Mathematically equivalent PyTorch SDPA for the pinned Wan blocks.

        Unlike the snapshot's current fallback, this preserves the variable
        key-length mask and casts the result back to the query dtype, matching
        the contract of its ``flash_attention`` function.  ``deterministic``
        and ``version`` select FlashAttention implementations and therefore do
        not alter this backend.
        """

        del deterministic, version
        import torch
        import torch.nn.functional as functional

        output_dtype = q.dtype
        compute_dtype = FloodBackend._attention_compute_dtype(torch, q, dtype)
        q = q.to(compute_dtype)
        k = k.to(compute_dtype)
        v = v.to(compute_dtype)
        if q_scale is not None:
            q = q * q_scale

        batch, query_length = q.shape[:2]
        key_length = k.shape[1]
        q = q.transpose(1, 2)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)

        mask = None
        if k_lens is not None:
            lengths = torch.as_tensor(k_lens, device=q.device, dtype=torch.long).view(
                batch
            )
            key_positions = torch.arange(key_length, device=q.device).view(1, 1, 1, -1)
            mask = key_positions < lengths.view(batch, 1, 1, 1)
        if q_lens is not None:
            lengths = torch.as_tensor(q_lens, device=q.device, dtype=torch.long).view(
                batch
            )
            query_positions = torch.arange(query_length, device=q.device).view(
                1, 1, -1, 1
            )
            query_mask = query_positions < lengths.view(batch, 1, 1, 1)
            mask = query_mask if mask is None else mask & query_mask

        left, right = window_size
        if (left, right) != (-1, -1):
            query_positions = torch.arange(query_length, device=q.device).view(
                1, 1, -1, 1
            )
            key_positions = torch.arange(key_length, device=q.device).view(1, 1, 1, -1)
            window_mask = torch.ones(
                (1, 1, query_length, key_length), dtype=torch.bool, device=q.device
            )
            if left >= 0:
                window_mask &= key_positions >= query_positions - left
            if right >= 0:
                window_mask &= key_positions <= query_positions + right
            mask = window_mask if mask is None else mask & window_mask
        if causal:
            query_positions = torch.arange(query_length, device=q.device).view(
                1, 1, -1, 1
            )
            key_positions = torch.arange(key_length, device=q.device).view(1, 1, 1, -1)
            causal_mask = key_positions <= query_positions
            mask = causal_mask if mask is None else mask & causal_mask

        output = functional.scaled_dot_product_attention(
            q,
            k,
            v,
            attn_mask=mask,
            dropout_p=dropout_p,
            is_causal=False,
            scale=softmax_scale,
        )
        return output.transpose(1, 2).contiguous().to(output_dtype)

    @staticmethod
    def _attention_compute_dtype(torch_module, query, requested_dtype=None):
        if query.device.type == "cpu":
            return torch_module.float32
        return requested_dtype or torch_module.bfloat16

    @staticmethod
    def _configure_cpu_execution(model, *, torch_module=None) -> None:
        """Normalize the pinned pipeline's host path to CPU float32.

        Flood already selects CPU when CUDA is unavailable.  Its UMT5 wrapper,
        however, constructs the text encoder as bfloat16 regardless of device.
        This narrow policy changes placement and dtype only; sampling, masks,
        schedules, and model calls remain the pinned upstream implementation.
        """

        if torch_module is None:
            import torch as torch_module

        device = torch_module.device("cpu")
        model.float().to(device)
        ldf_model = getattr(model, "ldf_model", None)
        vae = getattr(model, "vae", None)
        if ldf_model is None or vae is None:
            raise RuntimeError(
                "the pinned FloodDiffusion pipeline did not materialize LDF/VAE components"
            )
        ldf_model.to(device=device, dtype=torch_module.float32)
        vae.to(device=device, dtype=torch_module.float32)
        ldf_model.param_dtype = torch_module.float32
        text_encoder = getattr(ldf_model, "text_encoder", None)
        text_model = getattr(text_encoder, "model", None)
        if text_encoder is None or text_model is None:
            raise RuntimeError(
                "the pinned FloodDiffusion pipeline did not expose its UMT5 encoder"
            )
        text_model.to(device=device, dtype=torch_module.float32)
        text_encoder.device = device
        text_encoder.dtype = torch_module.float32

    def _load(self, variant: str, progress: Progress | None = None):
        if variant not in MODEL_SPECS:
            raise ValueError(f"unknown model variant: {variant}")
        if self._model is not None and self._variant == variant:
            return self._model

        self.unload()
        spec = MODEL_SPECS[variant]
        if progress:
            progress("download", 0.12, f"正在校验/下载 {spec.label}（固定 revision）")
        try:
            from transformers import AutoModel
        except ImportError as exc:
            raise RuntimeError("缺少模型依赖，请执行 scripts/bootstrap_wsl.sh") from exc

        snapshot = self._materialize_snapshot(variant)
        attention_backend = self._resolved_attention_backend()
        if progress:
            label = {
                "sdpa": "PyTorch SDPA（RTX 50 系默认兼容路径）",
                "flash": "FlashAttention（显式请求）",
                "auto": "自动：可用时 FlashAttention，否则 PyTorch SDPA",
            }[attention_backend]
            progress("load", 0.22, f"Attention backend: {label}")
            progress(
                "load",
                0.25,
                f"正在加载 {spec.label} 到 {self._execution_device.upper()}",
            )
        try:
            with _hide_classic_flash_attention(attention_backend == "sdpa"):
                model = AutoModel.from_pretrained(
                    str(snapshot),
                    trust_remote_code=True,
                    local_files_only=True,
                )
            if attention_backend == "sdpa":
                self._activate_official_sdpa_fallback(snapshot)
            if self._execution_device == "cpu":
                self._configure_cpu_execution(model)
        except ImportError as exc:
            if "flash" in str(exc).lower():
                raise RuntimeError(
                    "当前 FloodDiffusion snapshot 未能启用其 PyTorch SDPA fallback。"
                    "请保留 VFR_ATTENTION_BACKEND=auto/sdpa，或在受支持 GPU 上安装 FlashAttention。"
                ) from exc
            raise
        self._model = model
        self._variant = variant
        self._snapshot = snapshot
        return model

    def _set_seed(self, seed: int) -> None:
        random.seed(seed)
        np.random.seed(seed)
        try:
            import torch

            torch.manual_seed(seed)
            if self._execution_device == "cuda" and torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)
        except Exception:
            pass

    def generate(
        self,
        timeline: FloodTimeline,
        *,
        variant: str,
        seed: int,
        denoise_steps: int | None,
        progress: Progress | None = None,
    ) -> np.ndarray:
        with self._lock:
            model = self._load(variant, progress)
            self._set_seed(seed)
            if progress:
                progress(
                    "generate",
                    0.42,
                    f"正在生成约 {timeline.expected_seconds:.1f}s 连续动作",
                )
            kwargs = {
                "text": [list(timeline.prompts)],
                "length": [timeline.total_tokens],
                "text_end": [list(timeline.text_end)],
                "output_joints": False,
            }
            if denoise_steps is not None:
                kwargs["num_denoise_steps"] = int(denoise_steps)
            try:
                attention_backend = self._resolved_attention_backend()
                with _hide_classic_flash_attention(attention_backend == "sdpa"):
                    output = model(**kwargs)
            except RuntimeError as exc:
                message = str(exc).lower()
                if "out of memory" in message:
                    self.unload()
                    resource = (
                        "CPU 内存" if self._execution_device == "cpu" else "GPU 显存"
                    )
                    raise RuntimeError(
                        f"{resource}不足。缩短时长或减少 denoise steps。"
                    ) from exc
                if "no kernel image" in message or "invalid argument" in message:
                    self.unload()
                    raise RuntimeError(
                        "检测到 Attention CUDA 内核与当前 GPU 不兼容。"
                        "对 RTX 5090 请设置 VFR_ATTENTION_BACKEND=sdpa 并重启服务。"
                    ) from exc
                raise
            if isinstance(output, list):
                if not output:
                    raise RuntimeError("模型返回空列表")
                output = output[0]
            if hasattr(output, "detach"):
                output = output.detach().float().cpu().numpy()
            motion = np.asarray(output, dtype=np.float32)
            if motion.ndim == 3 and motion.shape[0] == 1:
                motion = motion[0]
            if motion.ndim != 2 or motion.shape[1] != 263:
                raise RuntimeError(f"模型输出应为 (T,263)，实际为 {motion.shape}")
            if motion.shape[0] < 2 or not np.isfinite(motion).all():
                raise RuntimeError("模型输出为空或含 NaN/Inf")
            if progress:
                progress(
                    "generate", 0.68, f"已生成 {motion.shape[0]} 帧 HumanML3D 动作"
                )
            return motion
