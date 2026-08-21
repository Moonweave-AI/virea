from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    # ``python-dotenv`` is installed by the locked Flood runtime.  Keeping
    # checkout-only configuration validation importable without that runtime
    # avoids treating an ambient developer environment as a model install.
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ModelSpec:
    key: str
    repo_id: str
    revision: str
    label: str
    estimated_download: str


MODEL_SPECS: dict[str, ModelSpec] = {
    "full": ModelSpec(
        key="full",
        repo_id="AlayaLab/FloodDiffusion",
        revision="82d5f998a20a15b534ac506f19ebb686d6a6d407",
        label="FloodDiffusion Full",
        estimated_download="~12 GB",
    ),
    "tiny": ModelSpec(
        key="tiny",
        repo_id="AlayaLab/FloodDiffusionTiny",
        revision="e86746efa2f16b94a1bb08550e3d8d4a32163f14",
        label="FloodDiffusion Tiny",
        estimated_download="~107 MB plus text encoder cache",
    ),
}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    package_root: Path
    runtime_root: Path
    output_root: Path
    hf_cache: Path
    virea_root: Path
    default_variant: str
    max_seconds: float
    max_jobs: int
    allow_remote_host: bool
    attention_backend: str

    @classmethod
    def from_env(cls) -> "Settings":
        # Console entry points and native Windows do not source .env for us.
        # Existing process variables still win.
        load_dotenv(PACKAGE_ROOT / ".env", override=False)
        package_root = (
            Path(os.getenv("VFR_PACKAGE_ROOT", PACKAGE_ROOT)).expanduser().resolve()
        )

        def resolve_path(name: str, default: Path) -> Path:
            path = Path(os.getenv(name, str(default))).expanduser()
            if not path.is_absolute():
                path = package_root / path
            return path.resolve()

        configured_home = os.getenv("VIREA_HOME")
        if os.getenv("VFR_RUNTIME_ROOT"):
            runtime_root = resolve_path("VFR_RUNTIME_ROOT", package_root)
        elif configured_home:
            runtime_root = (
                Path(configured_home).expanduser() / "runtimes" / "flood-diffusion-tiny"
            ).resolve()
        else:
            raise ValueError(
                "VIREA_HOME or VFR_RUNTIME_ROOT is required; the managed runtime "
                "never writes environments, caches, logs, or jobs into its source tree"
            )
        output_root = resolve_path("VFR_OUTPUT_ROOT", runtime_root / "jobs")
        hf_cache_default = (
            Path(configured_home).expanduser() / "cache" / "huggingface"
            if configured_home
            else runtime_root / "hf-cache"
        )
        hf_cache = resolve_path("HF_HOME", hf_cache_default)
        virea_root = resolve_path("VFR_VIREA_ROOT", package_root / "vendor" / "virea")
        variant = os.getenv("VFR_MODEL_VARIANT", "full").strip().lower()
        if variant not in MODEL_SPECS:
            choices = ", ".join(MODEL_SPECS)
            raise ValueError(f"VFR_MODEL_VARIANT must be one of: {choices}")
        return cls(
            host=os.getenv("VFR_HOST", "127.0.0.1"),
            port=int(os.getenv("VFR_PORT", "8765")),
            package_root=package_root,
            runtime_root=runtime_root,
            output_root=output_root,
            hf_cache=hf_cache,
            virea_root=virea_root,
            default_variant=variant,
            max_seconds=float(os.getenv("VFR_MAX_SECONDS", "90")),
            max_jobs=max(1, int(os.getenv("VFR_MAX_JOBS", "4"))),
            allow_remote_host=os.getenv("VFR_ALLOW_REMOTE_HOST", "0").strip().lower()
            in {"1", "true", "yes", "on"},
            attention_backend=(
                os.getenv("VFR_ATTENTION_BACKEND", "auto").strip().lower()
                if os.getenv("VFR_ATTENTION_BACKEND", "auto").strip().lower()
                in {"auto", "sdpa", "flash"}
                else "auto"
            ),
        )

    def ensure_dirs(self) -> None:
        for path in (
            self.runtime_root,
            self.output_root,
            self.hf_cache,
            self.models_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def models_root(self) -> Path:
        """Physical model snapshots used by the native Windows runtime.

        Hugging Face's cache normally materializes snapshots with symlinks.  A
        standard Windows account may not have the privilege required to create
        those links, so the runtime keeps pinned snapshots as ordinary files.
        """

        return self.runtime_root / "models"

    def model_dir(self, variant: str) -> Path:
        if variant not in MODEL_SPECS:
            raise ValueError(
                f"no physical snapshot is defined for model variant: {variant}"
            )
        return self.models_root / f"flood-diffusion-{variant}"

    @property
    def virea_src(self) -> Path:
        return self.virea_root / "src"

    @property
    def virea_viewer(self) -> Path:
        return self.virea_root / "apps" / "viewer-web"

    @property
    def three_root(self) -> Path:
        return self.virea_root / "node_modules" / "three"

    @property
    def three_vrm_root(self) -> Path:
        return self.virea_root / "node_modules" / "@pixiv" / "three-vrm"
