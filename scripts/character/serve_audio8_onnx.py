"""Official Audio8 ONNX graphs with an explicit CPU or CUDA session factory."""

import argparse
import base64
import gc
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import uvicorn
from dots_service import create_app
from dots_voice_store import VoiceImport, VoiceStore


class Audio8OnnxRuntime:
    sample_rate = 44100

    def __init__(self, root, voice_directory, device="cpu"):
        import arktts_runtime.runtime as runtime_module
        import onnxruntime as ort

        self.device = device
        self.provider = (
            "CUDAExecutionProvider" if device == "cuda" else "CPUExecutionProvider"
        )
        self.dll_directories = []
        if device == "cuda":
            if os.name == "nt":
                import site

                # cuDNN loads its engines on first inference, after ORT's initial
                # preload. Keep wheel DLL directories available for that load.
                directories = [
                    p
                    for base in site.getsitepackages()
                    for p in Path(base).glob("nvidia/*/bin")
                    if p.is_dir()
                ]
                os.environ["PATH"] = (
                    os.pathsep.join(map(str, directories))
                    + os.pathsep
                    + os.environ.get("PATH", "")
                )
                self.dll_directories = [
                    os.add_dll_directory(str(p)) for p in directories
                ]
            ort.preload_dlls(directory="")
        if self.provider not in ort.get_available_providers():
            raise RuntimeError(f"Requested {self.provider} is unavailable")
        # The pinned upstream package centralizes its synthesis sessions here.
        # Override only that factory in this isolated worker, never ort itself.
        runtime_module._session = self.session

        self.root = root
        self.encoded = voice_directory / "audio8-onnx"
        self.model = root / "model"
        self.runtime_type = runtime_module.ArkTtsRuntime
        self.runtime = None
        self.load()

    def load(self):
        self.sessions = []
        self.runtime = self.runtime_type(
            self.model, self.encoded, threads=min(8, os.cpu_count() or 4)
        )

    def metrics(self):
        providers = sorted({session.get_providers()[0] for session in self.sessions})
        return {
            "execution_provider": providers[0] if len(providers) == 1 else providers,
            "requested_device": self.device,
            "quantization": "int4",
            "reference_encoder_device": "cpu",
        }

    def session(self, path, threads=None):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.log_severity_level = 3
        if threads:
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = max(1, threads // 2)
        providers = [self.provider]
        if self.device == "cuda":
            providers.append("CPUExecutionProvider")
        session = ort.InferenceSession(
            str(path), sess_options=options, providers=providers
        )
        if session.get_providers()[0] != self.provider:
            raise RuntimeError(
                f"ONNX could not initialize {self.provider}; CPU fallback was not accepted"
            )
        session.disable_fallback()
        self.sessions.append(session)
        return session

    def generate_stream(self, *, text, prompt_audio_path, prompt_text):
        from arktts_runtime.registration import VoiceRegistration

        source = Path(prompt_audio_path)
        content = source.read_bytes()
        name = hashlib.sha256(content + prompt_text.encode()).hexdigest()[:48]
        if not (self.encoded / name / "meta.json").is_file():
            # Bound memory just as the official service does: unload synthesis
            # sessions while the reference encoder is in use.
            self.runtime = None
            self.sessions.clear()
            gc.collect()
            try:
                manifest = json.loads(
                    (self.model / "runtime_manifest.json").read_text(encoding="utf-8")
                )
                VoiceRegistration(
                    self.model / "registration",
                    self.encoded,
                    manifest["model_fingerprint"],
                ).register(content, source.name, prompt_text, name, False)
            finally:
                self.load()
        for item in self.runtime.stream(text=text, voice=name, max_new_tokens=640):
            if item["type"] == "audio_chunk":
                samples = np.asarray(item["audio"])
                if not np.isfinite(samples).all():
                    raise ValueError("Audio8 returned nonfinite samples")
                yield (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18083)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    sys.path.insert(0, str(args.runtime_root / "source/onnx_runtime"))
    directory = Path(os.environ["VIREA_HOME"]) / "characters/voices"
    store = VoiceStore(directory)
    if not store.list():
        reference = (
            args.runtime_root
            / "source/docs/audio/cases/reference/classical_polyphone_zh_01.mp3"
        )
        store.add(
            VoiceImport(
                name="Audio8 · 官方中文示例",
                transcript="根据最新气象资料，本周末北方多地将迎来降温，出行前请及时查看天气预报。",
                audio=base64.b64encode(reference.read_bytes()).decode(),
            )
        )
    print(f"Loading Audio8 INT4 · {args.device.upper()} · 44.1 kHz", flush=True)
    app = create_app(
        directory=directory,
        model="audio8/tts-0.6b",
        provider="audio8-tts",
        sample_rate=44100,
        precision="int4",
        max_characters=150,
        runtime_factory=lambda: Audio8OnnxRuntime(
            args.runtime_root, directory, args.device
        ),
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
