"""Resolve requested compute explicitly; never silently substitute CPU for GPU."""

import platform


def cuda_requirements(recipe):
    if recipe != "motioncraft":
        return 0.0, 0.0
    import yaml
    from virea_model_pool.manifest import ModelPluginManifest

    from .recipes import REPOSITORY

    manifest = ModelPluginManifest.model_validate(
        yaml.safe_load(
            (REPOSITORY / "plugins/models/motioncraft-smplx/manifest.yaml").read_text(
                encoding="utf-8"
            )
        )
    )
    runtime = next(
        r for r in manifest.runtime_variants if r.accelerator.kind == "nvidia"
    )
    return runtime.accelerator.min_vram_gib or 0.0, min(
        (p.min_free_vram_gib or 0.0 for p in runtime.resource_profiles), default=0.0
    )


def device_matches(requested, actual):
    return (
        requested == "auto"
        or requested == actual
        or (requested == "gpu" and actual in {"cuda", "mps", "rocm", "gpu"})
    )


async def select_device(requested, recipe):
    from .recipes import cuda_available

    if requested == "cpu":
        return "cpu"
    # Ollama chooses its native CUDA/ROCm/Metal backend. Its /api/ps response
    # verifies GPU offload after the actual generation request.
    if recipe == "ollama":
        return requested
    total, free = cuda_requirements(recipe)
    if await cuda_available(min_vram_gib=total, min_free_vram_gib=free):
        return "cuda"
    if (
        requested in {"auto", "gpu"}
        and recipe == "kokoro"
        and platform.system() == "Darwin"
        and platform.machine() == "arm64"
    ):
        return "mps"
    if requested != "auto":
        raise ValueError(
            "未检测到满足此运行时要求的 GPU。"
            + (
                f"需要至少 {total:g} GiB 总显存和 {free:g} GiB 可用显存。"
                if total or free
                else ""
            )
            + "请释放显存或检查显卡驱动后重新检测，也可选择 CPU。"
        )
    return "cpu"


async def prepare_kokoro(jobs, identifier, uv, env, repository, device):
    import os

    root = jobs.paths.root / "managed/kokoro" / f"environment-{device}"
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    jobs.step(identifier, 2, f"创建 Kokoro 隔离环境 · {device.upper()}")
    if not python.is_file():
        await jobs.command(
            identifier, [uv, "venv", "--python", "3.12", root], env=env, cwd=repository
        )
    jobs.step(identifier, 3, f"安装 Kokoro 与 {device.upper()} 推理依赖")
    version = (
        "2.2.2"
        if platform.system() == "Darwin" and platform.machine() == "x86_64"
        else "2.8.0"
    )
    args = [uv, "pip", "install", "--python", python, f"torch=={version}"]
    if platform.system() != "Darwin":
        args += [
            "--index-url",
            "https://download.pytorch.org/whl/"
            + ("cu128" if device == "cuda" else "cpu"),
        ]
    await jobs.command(identifier, args, env=env, cwd=repository)
    await jobs.command(
        identifier,
        [
            uv,
            "pip",
            "install",
            "--python",
            python,
            "kokoro==0.9.4",
            "misaki[zh]==0.9.4",
            "numpy>=1.26,<2",
            "fastapi>=0.115,<1",
            "uvicorn>=0.34,<1",
        ],
        env=env,
        cwd=repository,
    )
    env["VIREA_TTS_DEVICE"] = device
    return [python, repository / "scripts/character/serve_kokoro.py", "--port", "18082"]
