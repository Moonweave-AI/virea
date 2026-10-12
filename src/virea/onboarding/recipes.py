"""Allowlisted local deployments; commands are argument arrays, never shell text."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from virea_bootstrap.environment import sanitized_python_environment

from .catalog import resolve_options
from .connections import PRESETS, ConnectionInput, ConnectionStore, private_json
from .language import provider_error
from .verification import result_directory, verify_motion, verify_provider

REPOSITORY = Path(__file__).resolve().parents[3]
OLLAMA_RELEASE = "v0.40.3"


def record_connection(config, connection, verification=None):
    store = ConnectionStore(Path(config.connections_path))
    active = store.public()["active"].get(
        "language" if connection.provider == "ollama" else "speech"
    )
    store.put(connection)
    if active in {None, connection.id}:
        store.activate(connection.id, verification=verification)
    elif verification is not None:
        store.record_verification(
            connection.id, verification, expected=store.get(connection.id)
        )


async def verify_local(jobs, identifier, client, name, url, connection=None):
    config = jobs.characters.config
    jobs.step(identifier, 5, "运行真实模型生成检验；语音保持静音")
    if name in {"motioncraft", "syntalker"}:
        proof = await verify_motion(
            config,
            client,
            name,
            url,
            result_directory(config),
            lambda event, **facts: jobs.update(
                identifier, message=f"真实动作推理：已生成 {facts.get('frames', 0)} 帧"
            ),
        )
        setattr(config, f"{name}_url", url)
        return proof
    if connection is None:
        profile = {
            **PRESETS["local-speech"],
            "provider": "local-speech",
            "base_url": url + "/v1",
            "model": "kokoro" if name == "kokoro" else "auto",
        }
        options = await resolve_options(profile, client)
        connection = ConnectionInput(
            id=f"local-{name}",
            provider="local-speech",
            base_url=profile["base_url"],
            model=options["model"],
            voice=options["voice"],
        )
    profile = connection.model_dump(exclude={"api_key"})
    preset = PRESETS[connection.provider]
    profile.update(kind=preset["kind"], protocol=preset["protocol"])
    proof = await verify_provider(profile, client, result_directory(config))
    record_connection(config, connection, proof)
    return proof


def environment(paths):
    env = sanitized_python_environment()
    env.update(
        VIREA_HOME=str(paths.root),
        HF_HOME=str(paths.cache / "huggingface"),
        UV_CACHE_DIR=str(paths.cache / "uv"),
        OLLAMA_MODELS=str(paths.model_store / "ollama"),
        PYTHONUNBUFFERED="1",
        HF_HUB_DISABLE_PROGRESS_BARS="0",
        PIP_PROGRESS_BAR="on",
    )
    roots = [
        REPOSITORY,
        REPOSITORY / "src",
        *(REPOSITORY / "packages").glob("*/src"),
        REPOSITORY / "plugins/models/motioncraft-smplx/runtime/src",
    ]
    env["PYTHONPATH"] = os.pathsep.join(map(str, roots))
    env["PATH"] = os.pathsep.join(
        [str(Path.home() / ".local/bin"), env.get("PATH", "")]
    )
    return env


async def health(client, url, recipe):
    try:
        response = await client.get(
            url + ("/api/tags" if recipe == "ollama" else "/health"), timeout=2
        )
        if response.status_code != 200:
            return False
        body = response.json()
        if recipe == "ollama":
            return isinstance(body.get("models"), list)
        if recipe == "kokoro":
            return "kokoro" in str(body.get("model", "")).lower()
        if recipe == "audio8":
            return str(body.get("model", "")).lower() == "audio8/tts-0.6b"
        return (
            body.get("schema") == "virea.performance_worker.v1"
            and body.get("backend") == recipe
            and body.get("ready") is True
        )
    except (httpx.HTTPError, ValueError):
        return False


async def wait_ready(jobs, client, process, url, recipe):
    deadline = asyncio.get_running_loop().time() + 1800
    while asyncio.get_running_loop().time() < deadline:
        if process is not None and process.returncode is not None:
            raise RuntimeError(
                f"{recipe} 启动失败。请查看 {jobs.paths.logs / 'setup' / (recipe + '.log')}"
            )
        if await health(client, url, recipe):
            return
        await asyncio.sleep(2)
    raise RuntimeError("服务启动超过 30 分钟；下载缓存保留，可查看日志后重试")


async def install_ollama(jobs, identifier, uv, env):
    system, machine = platform.system(), platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "amd64"
    name = {
        "Windows": f"ollama-windows-{arch}.zip",
        "Darwin": "ollama-darwin.tgz",
        "Linux": f"ollama-linux-{arch}.tar.zst",
    }.get(system)
    if not name:
        raise ValueError("此系统尚无官方 Ollama 安装包")
    root = jobs.paths.root / "tools" / "ollama" / OLLAMA_RELEASE
    candidates = (
        [root / "ollama.exe"]
        if system == "Windows"
        else [root / "bin/ollama", root / "ollama"]
    )
    receipt = root / "installed.json"
    existing = next((p for p in candidates if p.is_file()), None)
    if existing and receipt.is_file():
        try:
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            if saved.get("asset") == name and saved.get("release") == OLLAMA_RELEASE:
                return str(existing)
        except (OSError, ValueError):
            pass
    root.mkdir(parents=True, exist_ok=True)
    download = root.parent / name
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        response = await client.get(
            f"https://api.github.com/repos/ollama/ollama/releases/tags/{OLLAMA_RELEASE}"
        )
        response.raise_for_status()
        asset = next(a for a in response.json()["assets"] if a["name"] == name)
        expected = asset.get("digest", "").removeprefix("sha256:")
        if len(expected) != 64:
            raise ValueError("官方安装包未提供 SHA256，停止安装")
        digest = hashlib.sha256()
        async with client.stream("GET", asset["browser_download_url"]) as response:
            response.raise_for_status()
            total, received = int(asset["size"]), 0
            with download.open("wb") as output:
                async for block in response.aiter_bytes(1024 * 1024):
                    output.write(block)
                    digest.update(block)
                    received += len(block)
                    jobs.update(
                        identifier,
                        stage_percent=min(100, round(received / total * 100)),
                        downloaded_bytes=received,
                        total_bytes=total,
                    )
        if digest.hexdigest() != expected:
            raise ValueError("Ollama 安装包 SHA256 不一致，请重试")
    await jobs.command(
        identifier,
        [
            uv,
            "run",
            "--no-project",
            "--python",
            "3.12",
            "--script",
            REPOSITORY / "scripts/setup/unpack.py",
            download,
            root,
        ],
        env=env,
        cwd=REPOSITORY,
    )
    installed = next((p for p in candidates if p.is_file()), None)
    if not installed:
        raise ValueError("官方安装包中没有找到 Ollama 可执行文件")
    # An interrupted extraction must not count as a completed installation merely
    # because its executable appeared before the supporting libraries did.
    private_json(
        receipt, {"release": OLLAMA_RELEASE, "asset": name, "sha256": expected}
    )
    download.unlink()
    return str(installed)


async def cuda_available(*, min_vram_gib=0.0, min_free_vram_gib=0.0):
    executable = shutil.which("nvidia-smi")
    if not executable:
        return False
    flags = {"creationflags": 0x08000000} if os.name == "nt" else {}
    process = await asyncio.create_subprocess_exec(
        executable,
        "--query-gpu=memory.total,memory.free",
        "--format=csv,noheader,nounits",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        **flags,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 8)
        if process.returncode != 0:
            return False
        # These workers use cuda:0; another card's capacity cannot qualify it.
        first = output.decode().splitlines()[0].split(",")
        total, free = (float(value.strip()) / 1024 for value in first)
        return total > 0 and total >= min_vram_gib and free >= min_free_vram_gib
    except (ValueError, IndexError):
        return False
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return False


async def deploy(jobs, identifier, request):
    from .compute import device_matches, prepare_kokoro, select_device

    name = request.recipe
    config = jobs.characters.config
    urls = {
        "ollama": "http://127.0.0.1:11434",
        "kokoro": "http://127.0.0.1:18082",
        "audio8": "http://127.0.0.1:18083",
        "motioncraft": config.motioncraft_url or "http://127.0.0.1:18086",
        "syntalker": config.syntalker_url or "http://127.0.0.1:18087",
    }
    url = urls[name]
    jobs.step(identifier, 1, "检测已安装服务与运行环境")
    local = urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}
    owned = None
    async with httpx.AsyncClient(trust_env=False) as client:
        if await health(client, url, name) and name != "ollama":
            details = (await client.get(url + "/health")).json()
            runtime = details.get("runtime")
            actual = str(
                details.get(
                    "device",
                    runtime.get("device", "") if isinstance(runtime, dict) else "",
                )
            ).split(":")[0]
            if device_matches(request.device, actual):
                jobs.update(identifier, compute_device=actual or "reported by worker")
                proof = await verify_local(jobs, identifier, client, name, url)
                return {
                    "endpoint": url,
                    "reused": True,
                    "recipe": name,
                    "compute_device": actual or "reported by worker",
                    "verification": proof,
                }
            owned = jobs.services.get(name)
            if not local or owned is None or owned.returncode is not None:
                raise ValueError(
                    f"{url} 已有外部服务使用 {actual or '未报告的设备'}；请在其启动器切换到 {request.device.upper()} 后重新检测。VIREA 不会停止外部服务。"
                )
        if not local:
            raise ValueError(f"远端 {name} 服务未就绪：{url}。请检查该服务后重新连接。")
        if not request.accepted_license:
            raise ValueError("请先阅读并勾选本地模型及依赖的使用条款，再开始下载")
        device = await select_device(request.device, name)
        jobs.update(
            identifier,
            compute_device=device,
            message=f"计算设备：{device.upper()} · 准备本地运行环境",
        )
        env = environment(jobs.paths)
        uv = shutil.which("uv", path=env["PATH"])
        if not uv:
            raise ValueError(
                "尚未找到 uv；请使用仓库的 Start-VIREA.cmd 或 start-virea.sh 启动，启动器会自动补齐"
            )
        minimum = 20 if name in {"motioncraft", "syntalker"} else 8
        if shutil.disk_usage(jobs.paths.root).free < minimum * 1024**3:
            raise ValueError(f"可用磁盘不足，请至少留出 {minimum} GiB 空间")
        if owned is not None:
            await jobs.terminate(owned)
        process = None
        try:
            if name == "ollama":
                jobs.step(identifier, 2, "准备 Ollama 运行程序")
                if not await health(client, url, name):
                    executable = shutil.which("ollama") or await install_ollama(
                        jobs, identifier, uv, env
                    )
                    env["OLLAMA_HOST"] = "127.0.0.1:11434"
                    process = await jobs.start_service(
                        name, [executable, "serve"], env, REPOSITORY, identifier
                    )
                    await wait_ready(jobs, client, process, url, name)
                jobs.step(identifier, 3, "下载或校验本地语言模型")
                async with client.stream(
                    "POST",
                    url + "/api/pull",
                    json={"model": request.model, "stream": True},
                    timeout=600,
                ) as response:
                    provider_error(response)
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        item = json.loads(line)
                        if item.get("error"):
                            raise ValueError(
                                "Ollama 下载失败：请确认模型 ID 存在且网络可达"
                            )
                        total, completed = (
                            item.get("total", 0),
                            item.get("completed", 0),
                        )
                        jobs.update(
                            identifier,
                            message=str(item.get("status", "下载中"))[:200],
                            stage_percent=min(100, round(completed / total * 100))
                            if total
                            else None,
                            downloaded_bytes=completed,
                            total_bytes=total,
                        )
                jobs.step(identifier, 5, "加载模型并验证结构化输出")
                connection = ConnectionInput(
                    id="local-ollama",
                    provider="ollama",
                    model=request.model,
                    compute_device=request.device,
                )
                proof = await verify_local(
                    jobs, identifier, client, name, url, connection
                )
            elif name == "kokoro":
                argv = await prepare_kokoro(
                    jobs, identifier, uv, env, REPOSITORY, device
                )
                jobs.step(identifier, 4, "下载 Kokoro 权重、词典与声线；完成后加载模型")
                process = await jobs.start_service(
                    name,
                    argv,
                    env,
                    REPOSITORY,
                    identifier,
                )
                await wait_ready(jobs, client, process, url, name)
                proof = await verify_local(jobs, identifier, client, name, url)
            elif name == "audio8":
                from .audio8 import prepare_audio8

                argv = await prepare_audio8(
                    jobs, identifier, uv, env, REPOSITORY, device
                )
                jobs.step(identifier, 5, "加载 Audio8 并运行真实语音生成检验；保持静音")
                process = await jobs.start_service(
                    name, argv, env, REPOSITORY, identifier
                )
                await wait_ready(jobs, client, process, url, name)
                proof = await verify_local(jobs, identifier, client, name, url)
            else:
                root = jobs.paths.root / "managed" / name
                root.mkdir(parents=True, exist_ok=True)
                runtime = root / f"environment-{device}"
                python = runtime / (
                    "Scripts/python.exe" if os.name == "nt" else "bin/python"
                )
                jobs.step(
                    identifier, 2, f"创建隔离 Python 3.11 环境 · {device.upper()}"
                )
                if not python.exists():
                    await jobs.command(
                        identifier,
                        [uv, "venv", "--python", "3.11", runtime],
                        env=env,
                        cwd=REPOSITORY,
                    )
                jobs.step(identifier, 3, "按运行时要求安装动作依赖")
                if name == "motioncraft":
                    project = (
                        REPOSITORY
                        / "plugins/models/motioncraft-smplx"
                        / ("runtime-cu128" if device == "cuda" else "runtime-cpu")
                    )
                    await jobs.command(
                        identifier,
                        [
                            uv,
                            "pip",
                            "install",
                            "--python",
                            python,
                            "setuptools<81",
                            "wheel",
                        ],
                        env=env,
                        cwd=REPOSITORY,
                    )
                    build_env = env | {"UV_PROJECT_ENVIRONMENT": str(runtime)}
                    await jobs.command(
                        identifier,
                        [
                            uv,
                            "sync",
                            "--project",
                            project,
                            "--locked",
                            "--inexact",
                            "--no-build-isolation-package",
                            "mmcv",
                        ],
                        env=build_env,
                        cwd=REPOSITORY,
                    )
                    await jobs.command(
                        identifier,
                        [
                            uv,
                            "pip",
                            "install",
                            "--python",
                            python,
                            "gdown==5.2.0",
                            "setuptools<81",
                        ],
                        env=env,
                        cwd=REPOSITORY,
                    )
                else:
                    torch = (
                        "torch==2.2.2"
                        if platform.system() == "Darwin"
                        and platform.machine().lower() == "x86_64"
                        else "torch==2.11.0"
                    )
                    args = [uv, "pip", "install", "--python", python, torch]
                    if platform.system() != "Darwin":
                        args += [
                            "--index-url",
                            "https://download.pytorch.org/whl/"
                            + ("cu128" if device == "cuda" else "cpu"),
                        ]
                    await jobs.command(identifier, args, env=env, cwd=REPOSITORY)
                    await jobs.command(
                        identifier,
                        [
                            uv,
                            "pip",
                            "install",
                            "--python",
                            python,
                            "-r",
                            REPOSITORY / "scripts/character/requirements-syntalker.txt",
                            "huggingface-hub>=0.34,<1",
                        ],
                        env=env,
                        cwd=REPOSITORY,
                    )
                jobs.step(
                    identifier, 4, "下载官方固定版本检查点并校验文件；可能需要较长时间"
                )
                await jobs.command(
                    identifier,
                    [
                        python,
                        "-m",
                        "scripts.character.unified_motion.prepare",
                        name,
                        "--root",
                        root,
                        "--device",
                        device,
                    ],
                    env=env,
                    cwd=REPOSITORY,
                    timeout=14400,
                )
                jobs.step(identifier, 5, "启动动作服务并加载真实模型")
                port = urlsplit(url).port
                process = await jobs.start_service(
                    name,
                    [
                        python,
                        "-m",
                        "scripts.character.unified_motion.server",
                        "--settings",
                        root / "worker.json",
                        "--port",
                        str(port),
                    ],
                    env,
                    REPOSITORY,
                    identifier,
                )
                await wait_ready(jobs, client, process, url, name)
                proof = await verify_local(jobs, identifier, client, name, url)
            jobs.step(identifier, 6, "保存已验证的连接与部署结果")
            return {
                "endpoint": url,
                "recipe": name,
                "reused": False,
                "compute_device": device,
                "verification": proof,
            }
        except BaseException:
            if process is not None:
                await jobs.terminate(process)
            raise
