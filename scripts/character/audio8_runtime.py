"""Strict PCM streaming bridge to the pinned official Audio8 SGLang adapter."""

import base64
import json
import urllib.request

MODEL_ID = "audio8/tts-0.6b"
MODEL_REVISION = "f07040f3d151f1ba0253bfb92cb2f5dd38b44594"


class Audio8Runtime:
    sample_rate = 44100
    device = "cuda"

    def __init__(self, base_url: str, *, opener=urllib.request.urlopen):
        self.base_url = base_url.rstrip("/")
        self.opener = opener

    def metrics(self):
        # SGLang and the codec run in separate processes. Do not misreport the
        # gateway's CUDA allocator as total model memory.
        with self.opener(self.base_url + "/health", timeout=3) as response:
            if response.status != 200:
                raise RuntimeError("Audio8 backend is unavailable")
        return dict(
            backend="sglang-omni",
            quantization="none",
            streaming=True,
            model_revision=MODEL_REVISION,
        )

    def generate_stream(self, *, text, prompt_audio_path, prompt_text):
        request = urllib.request.Request(
            self.base_url + "/v1/audio/speech",
            data=json.dumps(
                dict(
                    model=MODEL_ID,
                    input=text,
                    stream=True,
                    response_format="pcm",
                    references=[dict(audio_path=prompt_audio_path, text=prompt_text)],
                    max_new_tokens=640,
                    temperature=0.7,
                    top_p=0.8,
                    top_k=50,
                )
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Context closure cancels the backend when the consumer disconnects.
        with self.opener(request, timeout=120) as response:
            total = 0
            while True:
                line = response.readline(4 * 1024 * 1024 + 1)
                if len(line) > 4 * 1024 * 1024:
                    raise ValueError("Audio8 SSE event exceeds size limit")
                if not line:
                    raise ValueError("Audio8 stream ended without completion")
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    if not total:
                        raise ValueError("Audio8 returned no audio")
                    return
                event = json.loads(payload)
                if event.get("error"):
                    raise ValueError("Audio8 backend reported a generation error")
                audio = event.get("audio")
                if audio is None:
                    continue
                if (
                    audio.get("format") != "pcm"
                    or audio.get("sample_rate") != self.sample_rate
                ):
                    raise ValueError("Audio8 must return PCM16 at 44100 Hz")
                pcm = base64.b64decode(audio["data"], validate=True)
                if len(pcm) % 2:
                    raise ValueError("Audio8 returned truncated PCM16")
                total += len(pcm) // 2
                if total > self.sample_rate * 30:
                    raise ValueError("Audio8 output exceeds 30 seconds")
                if pcm:
                    yield pcm
