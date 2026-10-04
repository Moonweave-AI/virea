"""Start the official Audio8 engine and VIREA's reference-voice gateway."""

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import uvicorn
from audio8_runtime import MODEL_ID, Audio8Runtime
from dots_service import create_app
from dots_voice_store import VoiceStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--backend-port", type=int, default=8086)
    parser.add_argument("--memory-fraction", type=float, default=0.9)
    parser.add_argument("--backend-url", help="Use an already supervised backend")
    parser.add_argument("--skip-warmup", action="store_true")
    args = parser.parse_args()
    if not 0.05 <= args.memory_fraction <= 0.95:
        parser.error("--memory-fraction must be between 0.05 and 0.95")
    if not (args.model / "config.json").is_file():
        parser.error("Download the pinned Audio8 model before starting")
    home = Path(os.environ.get("VIREA_HOME", str(Path.home() / ".virea")))
    logs = home / "logs" / "audio8"
    logs.mkdir(parents=True, exist_ok=True)
    base_url = args.backend_url or f"http://127.0.0.1:{args.backend_port}"
    backend = None
    output = None

    # Ensure stopping during engine startup also reaps the process group.
    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        if not args.backend_url:
            env = os.environ.copy()
            # CUDA runtime headers ship with the pinned torch wheels. Triton
            # uses its bundled compiler; this BF16 model does not use DeepGEMM.
            import nvidia.cuda_runtime

            env.setdefault(
                "CUDA_HOME", str(Path(next(iter(nvidia.cuda_runtime.__path__))))
            )
            env.update(
                SGLANG_ENABLE_JIT_DEEPGEMM="0",
                AUDIO8_TTS_STREAM_ENABLED="1",
                AUDIO8_TTS_ATTENTION_BACKEND="triton",
                AUDIO8_TTS_MEM_FRACTION_STATIC=str(args.memory_fraction),
                AUDIO8_TTS_MAX_RUNNING_REQUESTS="1",
                AUDIO8_TTS_MAX_TOTAL_NUM_TOKENS="2048",
                AUDIO8_TTS_STREAM_CHUNK_FRAMES="12",
            )
            output = (logs / "engine.log").open("w", encoding="utf-8")
            backend = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "sglang_omni.cli.cli",
                    "serve",
                    "--model-path",
                    str(args.model),
                    "--config",
                    str(
                        args.runtime_root
                        / "source/sglang_omni/configs/audio8_tts_0_6b.yaml"
                    ),
                    "--model-name",
                    MODEL_ID,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.backend_port),
                ],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            (logs / "engine.pid").write_text(str(backend.pid), encoding="ascii")
        deadline = time.monotonic() + 600
        while True:
            if backend and backend.poll() is not None:
                raise RuntimeError(
                    f"Audio8 engine exited; inspect {logs / 'engine.log'}"
                )
            try:
                with urllib.request.urlopen(
                    base_url + "/health", timeout=2
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("Audio8 engine startup timed out")
            time.sleep(0.5)
        voices = VoiceStore(home / "characters" / "voices")
        if not args.skip_warmup and voices.list():
            voice = voices.get(None)
            for _ in Audio8Runtime(base_url).generate_stream(
                text="你好。",
                prompt_audio_path=str(voices.path(voice["id"], ".wav")),
                prompt_text=voice["transcript"],
            ):
                pass
        app = create_app(
            directory=home / "characters" / "voices",
            model=MODEL_ID,
            provider="audio8-tts",
            sample_rate=44100,
            max_characters=150,
            runtime_factory=lambda: Audio8Runtime(base_url),
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    finally:
        if backend:
            try:
                os.killpg(backend.pid, signal.SIGTERM)
                backend.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(backend.pid, signal.SIGKILL)
                backend.wait()
            except ProcessLookupError:
                pass
        if output:
            output.close()


if __name__ == "__main__":
    main()
