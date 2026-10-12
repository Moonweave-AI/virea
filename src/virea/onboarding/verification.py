"""Real inference checks and inspectable, server-owned result receipts."""

from __future__ import annotations

import hashlib
import io
import json
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import numpy as np

from .connections import private_json
from .language import completion
from .speech import synthesize


def result_directory(config):
    return Path(config.connections_path).parent / "verification"


def receipt(directory, kind, model, started, payload, suffix, **facts):
    identifier = uuid4().hex
    result = {
        "id": identifier,
        "kind": kind,
        "model": model,
        "ready": True,
        "generated": True,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "format": suffix,
        "artifact_url": f"/api/v1/onboarding/verification/{identifier}/artifact",
        **facts,
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{identifier}.{suffix}").write_bytes(payload)
    private_json(directory / f"{identifier}.receipt.json", result)
    return result


async def verify_provider(profile, client, directory):
    started = time.monotonic()
    if profile["kind"] == "language":
        schema = {
            "type": "object",
            "properties": {"ready": {"type": "boolean"}},
            "required": ["ready"],
            "additionalProperties": False,
        }
        result = await completion(
            profile,
            client,
            [{"role": "user", "content": 'Return exactly this JSON: {"ready":true}'}],
            schema,
            tokens=4096,
            temperature=0,
        )
        if (
            not isinstance(result, dict)
            or set(result) != {"ready"}
            or result["ready"] is not True
        ):
            raise ValueError("模型未按结构化契约返回测试结果，请更换模型或输出模式")
        compute = {}
        if profile["protocol"] == "ollama":
            response = await client.get(profile["base_url"] + "/api/ps", timeout=10)
            response.raise_for_status()
            loaded = next(
                (
                    m
                    for m in response.json().get("models", [])
                    if profile["model"] in {m.get("name"), m.get("model")}
                ),
                None,
            )
            if not loaded:
                raise ValueError("生成完成，但 Ollama 没有报告当前模型的运行设备")
            gpu_bytes = int(loaded.get("size_vram", 0))
            requested = profile.get("compute_device", "auto")
            if requested in {"gpu", "cuda"} and gpu_bytes == 0:
                raise ValueError(
                    "Ollama 已生成结果，但 GPU 未实际加载模型；请检查驱动或选择 CPU"
                )
            if requested == "cpu" and gpu_bytes > 0:
                raise ValueError("Ollama 未按 CPU 配置加载模型，请更新 Ollama 后重试")
            compute = {
                "compute_device": "gpu" if gpu_bytes else "cpu",
                "gpu_bytes": gpu_bytes,
            }
        return receipt(
            directory,
            "language",
            profile["model"],
            started,
            json.dumps(result).encode(),
            "json",
            result=result,
            structured_output=True,
            **compute,
        )
    text = "你好，这是一条真实生成的语音检验。"
    try:
        audio, seconds = await synthesize(profile, client, text)
        with wave.open(io.BytesIO(audio), "rb") as source:
            samples = np.frombuffer(
                source.readframes(source.getnframes()), dtype="<i2"
            ).astype(float)
            rate = source.getframerate()
    except (wave.Error, EOFError) as exc:
        raise ValueError("语音服务没有返回有效 WAV 音频，生成检验未通过") from exc
    if not len(samples) or np.max(np.abs(samples)) <= 1:
        raise ValueError(
            "语音接口仅返回静音或空音频，生成检验未通过；请检查模型加载和声线设置"
        )
    waveform = [
        round(float(np.max(np.abs(part))) / 32768, 4)
        for part in np.array_split(samples, min(64, len(samples)))
    ]
    compute = {}
    if profile["protocol"] == "virea_tts":
        try:
            health = await client.get(
                profile["base_url"].removesuffix("/v1") + "/health", timeout=10
            )
            if health.status_code == 200:
                details = health.json()
                if isinstance(details, dict):
                    compute = {
                        key: details[key]
                        for key in (
                            "device",
                            "execution_provider",
                            "reference_encoder_device",
                        )
                        if key in details
                    }
        except (httpx.HTTPError, ValueError):
            # Compatible speech services may have no device-telemetry endpoint.
            # A validated generated waveform remains the acceptance criterion.
            pass
    return receipt(
        directory,
        "speech",
        profile["model"],
        started,
        audio,
        "wav",
        seconds=seconds,
        sample_rate=rate,
        sample_text=text,
        voice=profile.get("voice", ""),
        waveform=waveform,
        played=False,
        **compute,
    )


async def verify_motion(config, client, backend, url, directory, record=None):
    from virea.character.performance_contracts import PerformancePlan
    from virea.character.providers.unified import UnifiedMotionProvider

    started = time.monotonic()
    effective = config.model_copy(
        update={"motion_backend": backend, f"{backend}_url": url}
    )
    plan = PerformancePlan.model_validate(
        {
            "motions": [
                {
                    "id": "generation-check",
                    "start_seconds": 0,
                    "duration_seconds": 3,
                    "prompt": "A person waves one hand.",
                }
            ]
        }
    )

    async def silence(*args):
        return []

    values, _, health = await UnifiedMotionProvider(effective, client).generate(
        plan, silence, silence, record or (lambda *args, **kwargs: None)
    )
    # generate() validates dimensions, finiteness, identity, timing, and final
    # native decoding. A constant/placeholder tensor is not generated motion.
    variation = float(np.max(np.abs(np.diff(values, axis=0))))
    if len(values) != 90 or not np.isfinite(variation) or variation <= 1e-6:
        raise ValueError("动作模型未生成有效的变化序列，生成检验未通过")
    stream = io.BytesIO()
    np.savez_compressed(stream, native=values, fps=np.array(30))
    return receipt(
        directory,
        "motion",
        backend,
        started,
        stream.getvalue(),
        "npz",
        frames=len(values),
        fps=30,
        seconds=len(values) / 30,
        dimensions=values.shape[1],
        representation=health["native_output"],
        source_revision=health.get("source_revision"),
        prompt=plan.motions[0].prompt,
        max_frame_delta=variation,
    )
