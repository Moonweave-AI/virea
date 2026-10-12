"""Resolve requested compute explicitly; never silently substitute CPU for GPU."""

import platform


async def select_device(requested, recipe):
    from .recipes import cuda_available

    if requested == "cpu":
        return "cpu"
    # Ollama chooses its native CUDA/ROCm/Metal backend. Its /api/ps response
    # verifies GPU offload after the actual generation request.
    if recipe == "ollama":
        return requested
    if await cuda_available():
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
            "未检测到此运行时支持的 GPU。请安装显卡驱动后重新检测，或选择 CPU。"
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
