"""Pinned official Audio8 ONNX deployment on Windows, Linux and macOS."""

import os

import httpx

from .downloads import download, huggingface_snapshot

SOURCE_REVISION = "07e40f5d0b03fc473635ef378654bfb581027ac3"
MODEL_REVISION = "818569c6b832118ad68d61bbd873abe250fcd68a"
MODEL_REPOSITORY = "Edge0/Audio8-TTS-Preview-0.6B-ONNX-INT4"


async def prepare_audio8(jobs, identifier, uv, env, repository, device="cpu"):
    root = jobs.paths.root / "managed/audio8"
    root.mkdir(parents=True, exist_ok=True)
    runtime = root / ("environment" if device == "cpu" else "environment-cuda")
    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    jobs.step(identifier, 2, f"创建 Audio8 独立环境 · {device.upper()}")
    if not python.is_file():
        await jobs.command(
            identifier,
            [uv, "venv", "--python", "3.12", runtime],
            env=env,
            cwd=repository,
        )
    await jobs.command(
        identifier,
        [
            uv,
            "pip",
            "install",
            "--python",
            python,
            "-r",
            repository / "scripts/character/requirements-audio8-onnx.txt",
        ],
        env=env,
        cwd=repository,
    )
    provider = (
        "onnxruntime-gpu[cuda,cudnn]==1.24.4"
        if device == "cuda"
        else "onnxruntime==1.24.4"
    )
    await jobs.command(
        identifier,
        [uv, "pip", "install", "--python", python, provider],
        env=env,
        cwd=repository,
    )
    jobs.step(identifier, 3, "下载 Audio8 官方运行时与参考声线")
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        response = await client.get(
            f"https://api.github.com/repos/Edge0-AI/Audio8_TTS/git/trees/{SOURCE_REVISION}",
            params={"recursive": "1"},
        )
        response.raise_for_status()
        tree = response.json()["tree"]
        sample = "docs/audio/cases/reference/classical_polyphone_zh_01.mp3"
        rows = [
            r
            for r in tree
            if r["type"] == "blob"
            and (
                r["path"].startswith("onnx_runtime/arktts_runtime/")
                or r["path"] in {"LICENSE", "NOTICE", sample}
            )
        ]
        for row in rows:
            path = (root / "source" / row["path"]).resolve()
            if not path.is_relative_to((root / "source").resolve()):
                raise ValueError("Unexpected runtime path")
            await download(
                jobs,
                identifier,
                client,
                url=f"https://raw.githubusercontent.com/Edge0-AI/Audio8_TTS/{SOURCE_REVISION}/{row['path']}",
                path=path,
                size=row["size"],
                digest=row["sha"],
                algorithm="sha1",
                git_blob=True,
            )
        jobs.step(identifier, 4, "下载并校验 Audio8 INT4 权重与声线编码器")
        await huggingface_snapshot(
            jobs, identifier, client, MODEL_REPOSITORY, MODEL_REVISION, root / "model"
        )
    return [
        python,
        repository / "scripts/character/serve_audio8_onnx.py",
        "--runtime-root",
        root,
        "--device",
        device,
        "--port",
        "18083",
    ]
