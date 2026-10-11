"""Server-owned provider settings. Public views never contain credentials."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


def preset(name, kind, protocol, url, model, **extra):
    return dict(
        name=name, kind=kind, protocol=protocol, base_url=url, model=model, **extra
    )


PRESETS = {
    "elevenlabs": preset(
        "ElevenLabs",
        "speech",
        "elevenlabs_tts",
        "https://api.elevenlabs.io/v1",
        "eleven_multilingual_v2",
        voice="JBFqnCBsd6RMkjVDRZzb",
    ),
    "azure-speech": preset(
        "Microsoft Azure Speech",
        "speech",
        "azure_tts",
        "https://eastus.tts.speech.microsoft.com",
        "azure-neural",
        voice="zh-CN-XiaoxiaoNeural",
    ),
    "openai": preset(
        "OpenAI",
        "language",
        "openai",
        "https://api.openai.com/v1",
        "",
        structured="json_schema",
    ),
    "deepseek": preset(
        "DeepSeek",
        "language",
        "openai",
        "https://api.deepseek.com",
        "deepseek-chat",
        structured="json_object",
    ),
    "anthropic": preset(
        "Anthropic Claude", "language", "anthropic", "https://api.anthropic.com/v1", ""
    ),
    "bailian-cn": preset(
        "阿里云百炼 · 北京",
        "language",
        "openai",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-plus",
        structured="json_object",
    ),
    "bailian-intl": preset(
        "Alibaba Model Studio · Singapore",
        "language",
        "openai",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "qwen-plus",
        structured="json_object",
    ),
    "openrouter": preset(
        "OpenRouter",
        "language",
        "openai",
        "https://openrouter.ai/api/v1",
        "",
        structured="json_object",
    ),
    "groq": preset(
        "Groq",
        "language",
        "openai",
        "https://api.groq.com/openai/v1",
        "",
        structured="json_object",
    ),
    "siliconflow": preset(
        "硅基流动",
        "language",
        "openai",
        "https://api.siliconflow.cn/v1",
        "",
        structured="json_object",
    ),
    "gemini": preset(
        "Google Gemini · OpenAI compatible",
        "language",
        "openai",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "",
        structured="json_object",
    ),
    "ollama": preset(
        "Ollama · 本地模型",
        "language",
        "ollama",
        "http://127.0.0.1:11434",
        "qwen3:4b",
        local=True,
    ),
    "lmstudio": preset(
        "LM Studio · 本地模型",
        "language",
        "openai",
        "http://127.0.0.1:1234/v1",
        "",
        local=True,
        structured="json_schema",
    ),
    "llamacpp": preset(
        "llama.cpp / ik_llama · 本地模型",
        "language",
        "openai",
        "http://127.0.0.1:8080/v1",
        "",
        local=True,
        structured="json_schema",
    ),
    "custom-language": preset(
        "自定义 OpenAI 兼容接口", "language", "openai", "", "", structured="json_object"
    ),
    "openai-speech": preset(
        "OpenAI Speech",
        "speech",
        "openai_tts",
        "https://api.openai.com/v1",
        "gpt-4o-mini-tts",
        voice="alloy",
    ),
    "bailian-speech-cn": preset(
        "百炼 Qwen TTS · 北京",
        "speech",
        "dashscope_tts",
        "https://dashscope.aliyuncs.com/api/v1",
        "qwen3-tts-flash",
        voice="Cherry",
    ),
    "bailian-speech-intl": preset(
        "Qwen TTS · Singapore",
        "speech",
        "dashscope_tts",
        "https://dashscope-intl.aliyuncs.com/api/v1",
        "qwen3-tts-flash",
        voice="Cherry",
    ),
    "local-speech": preset(
        "VIREA 本地语音 / Kokoro / Audio8 / Dots",
        "speech",
        "virea_tts",
        "http://127.0.0.1:8081/v1",
        "kokoro",
        local=True,
    ),
    "custom-speech": preset(
        "自定义 OpenAI Speech 兼容接口", "speech", "openai_tts", "", "", voice=""
    ),
}


def validate_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("地址必须是 API 基础地址，不能含账号、密钥、查询参数或片段")
    if parts.scheme != "https" and not (
        parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ValueError("远程 API 必须使用 HTTPS；HTTP 仅可用于本机服务")
    _ = parts.port
    return value.rstrip("/")


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    provider: str
    base_url: str = Field(default="", max_length=1000)
    model: str = Field(min_length=1, max_length=200)
    voice: str = Field(default="", max_length=100)
    api_key: SecretStr | None = None
    api_key_env: str = Field(default="", max_length=100)
    structured: str = "auto"

    @model_validator(mode="after")
    def coherent(self):
        if self.provider not in PRESETS:
            raise ValueError("未知供应商")
        self.base_url = validate_url(
            self.base_url or PRESETS[self.provider]["base_url"]
        )
        if self.api_key_env and not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.api_key_env):
            raise ValueError("密钥环境变量名称不合法")
        if self.structured not in {"auto", "json_schema", "json_object"}:
            raise ValueError("不支持的结构化输出模式")
        self.model = self.model.strip()
        self.voice = self.voice.strip() or PRESETS[self.provider].get("voice", "")
        if not self.model:
            raise ValueError("请选择模型或填写模型 ID")
        return self


_LOCK = threading.RLock()


def private_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def protect_key(key: str, *, decrypt: bool = False) -> str:
    """Windows uses the current user's DPAPI; Unix relies on owner-only storage."""
    if os.name != "nt":
        return key
    import base64
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]

    raw = base64.b64decode(key) if decrypt else key.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    output = Blob()
    crypt = ctypes.windll.crypt32
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if not function(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)
    ):
        raise OSError("无法访问当前用户的凭证存储")
    try:
        result = ctypes.string_at(output.data, output.size)
        return (
            result.decode("utf-8")
            if decrypt
            else base64.b64encode(result).decode("ascii")
        )
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


class ConnectionStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return {"version": 1, "connections": {}, "active": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def public(self):
        with _LOCK:
            state = self.read()
            return {
                "active": state["active"],
                "connections": [
                    {k: v for k, v in row.items() if k != "secret"}
                    | {
                        "has_key": bool(
                            row.get("secret") or os.getenv(row.get("api_key_env", ""))
                        ),
                        "pending_changes": bool(
                            state.get("activated", {}).get(row["kind"])
                        )
                        and state["active"].get(row["kind"]) == row["id"]
                        and state["activated"][row["kind"]] != row,
                        "verification": state.get("verified", {})
                        .get(row["id"], {})
                        .get("result")
                        if state.get("verified", {}).get(row["id"], {}).get("profile")
                        == row
                        else None,
                    }
                    for row in state["connections"].values()
                ],
            }

    def put(self, request: ConnectionInput):
        with _LOCK:
            state = self.read()
            previous = state["connections"].get(request.id, {})
            row = request.model_dump(exclude={"api_key"})
            row.update(
                kind=PRESETS[request.provider]["kind"],
                protocol=PRESETS[request.provider]["protocol"],
            )
            if request.api_key is not None:
                key = request.api_key.get_secret_value().strip()
                row["secret"] = protect_key(key) if key else ""
            elif all(previous.get(k) == row[k] for k in ("provider", "base_url")):
                row["secret"] = previous.get("secret", "")
            state["connections"][request.id] = row
            # Keep the last tested snapshot active until the edited connection is tested again.
            private_json(self.path, state)

    def get(self, identifier: str):
        with _LOCK:
            row = dict(self.read()["connections"][identifier])
        row["api_key"] = os.getenv(row.get("api_key_env", ""), "") or (
            protect_key(row["secret"], decrypt=True) if row.get("secret") else ""
        )
        return row

    def active(self, kind: str):
        with _LOCK:
            state = self.read()
            identifier = state["active"].get(kind)
            if not identifier:
                return None
            row = dict(
                state.get("activated", {}).get(kind) or state["connections"][identifier]
            )
            row["api_key"] = os.getenv(row.get("api_key_env", ""), "") or (
                protect_key(row["secret"], decrypt=True) if row.get("secret") else ""
            )
            return row

    def activate(self, identifier: str, *, expected=None, verification=None):
        with _LOCK:
            state = self.read()
            row = state["connections"][identifier]
            if expected is not None and row != {
                k: v for k, v in expected.items() if k != "api_key"
            }:
                raise ValueError("测试期间连接设置发生变化，请重新测试并启用")
            state["active"][row["kind"]] = identifier
            state.setdefault("activated", {})[row["kind"]] = dict(row)
            if verification is not None:
                state.setdefault("verified", {})[identifier] = {
                    "profile": dict(row),
                    "result": verification,
                }
            private_json(self.path, state)

    def record_verification(self, identifier, result, *, expected):
        with _LOCK:
            state = self.read()
            row = state["connections"][identifier]
            if row != {k: v for k, v in expected.items() if k != "api_key"}:
                raise ValueError("检验期间连接设置发生变化，请重新检验")
            state.setdefault("verified", {})[identifier] = {
                "profile": dict(row),
                "result": result,
            }
            private_json(self.path, state)

    def remove(self, identifier: str):
        with _LOCK:
            state = self.read()
            state["connections"].pop(identifier)
            state.get("verified", {}).pop(identifier, None)
            state["active"] = {
                k: v for k, v in state["active"].items() if v != identifier
            }
            state["activated"] = {
                k: v
                for k, v in state.get("activated", {}).items()
                if v["id"] != identifier
            }
            private_json(self.path, state)


def selected_connection(config, kind: str):
    path = getattr(config, "connections_path", None)
    return ConnectionStore(Path(path)).active(kind) if path else None
