"""Durable, immutable reference voices for the isolated dots.tts service."""

from __future__ import annotations

import base64
import binascii
import io
import json
import re
import threading
from pathlib import Path
from uuid import uuid4

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_AUDIO_BYTES = 12 * 1024 * 1024
MAX_IMPORT_BYTES = 16 * 1024 * 1024 + 65536


class VoiceImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    transcript: str = Field(min_length=1, max_length=2000)
    audio: str = Field(min_length=1, max_length=16 * 1024 * 1024)

    @field_validator("name", "transcript")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("声线名称与参考音频逐字文本不能为空")
        return value


class VoiceStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def path(self, voice: str, suffix: str) -> Path:
        if not re.fullmatch(r"ref_[0-9a-f]{32}", voice):
            raise ValueError("参考声线不存在，请重新导入")
        return self.directory / (voice + suffix)

    def get(self, voice: str | None) -> dict:
        with self.lock:
            if not voice:
                voices = self.list()
                if not voices:
                    raise ValueError("请先在角色与设置中导入参考音频和对应文本")
                voice = voices[0]["id"]
            path = self.path(voice, ".json")
            if not path.is_file() or not self.path(voice, ".wav").is_file():
                raise ValueError("参考声线不存在，请重新导入")
            record = json.loads(path.read_text(encoding="utf-8"))
            # Never use a filesystem path supplied in metadata or an API request.
            record["id"] = voice
            return record

    def list(self) -> list[dict]:
        with self.lock:
            return [
                self.get(path.stem)
                for path in sorted(self.directory.glob("ref_*.json"))
            ]

    def add(self, data: VoiceImport) -> dict:
        import soundfile as sf

        try:
            payload = base64.b64decode(data.audio, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("参考音频编码无效") from exc
        if not payload or len(payload) > MAX_AUDIO_BYTES:
            raise ValueError("参考音频必须小于 12 MiB")
        try:
            with sf.SoundFile(io.BytesIO(payload)) as source:
                duration = source.frames / source.samplerate
                if not 3 <= duration <= 30:
                    raise ValueError("请选择 3–30 秒的参考音频，建议约 10 秒")
                if not 8000 <= source.samplerate <= 96000 or source.channels not in (
                    1,
                    2,
                ):
                    raise ValueError("参考音频须为 8–96 kHz 的单声道或双声道录音")
                rate = source.samplerate
                samples = source.read(dtype="float32", always_2d=True).mean(axis=1)
        except (RuntimeError, sf.LibsndfileError) as exc:
            raise ValueError("无法解码参考音频，请使用 WAV、FLAC、MP3 或 OGG") from exc
        if not np.isfinite(samples).all() or np.max(np.abs(samples), initial=0) < 0.001:
            raise ValueError("参考音频为空、静音或包含无效采样")
        warnings = []
        if float(np.mean(np.abs(samples) >= 0.999)) > 0.01:
            warnings.append("录音存在削波失真，建议更换清晰录音")
        if rate < 24000:
            warnings.append("录音采样率较低，建议使用 24 kHz 或更高采样率")
        voice = "ref_" + uuid4().hex
        record = dict(
            id=voice,
            name=data.name,
            transcript=data.transcript,
            language="auto",
            seconds=duration,
            sample_rate=rate,
            warnings=warnings,
            kind="reference",
        )
        audio_path, metadata_path = self.path(voice, ".wav"), self.path(voice, ".json")
        temporary = self.path(voice, ".tmp")
        with self.lock:
            if len(list(self.directory.glob("ref_*.json"))) >= 32:
                raise ValueError("最多保存 32 条参考声线，请先删除不再使用的声线")
            try:
                sf.write(
                    temporary,
                    np.clip(samples, -1, 1),
                    rate,
                    format="WAV",
                    subtype="PCM_16",
                )
                temporary.replace(audio_path)
                temporary.write_text(
                    json.dumps(record, ensure_ascii=False), encoding="utf-8"
                )
                temporary.replace(metadata_path)
            except Exception:
                audio_path.unlink(missing_ok=True)
                raise
            finally:
                temporary.unlink(missing_ok=True)
        return record

    def delete(self, voice: str) -> None:
        with self.lock:
            self.get(voice)
            self.path(voice, ".json").unlink()
            self.path(voice, ".wav").unlink(missing_ok=True)
