"""Convert installed SentiAvatar weights with the official llama.cpp converter.

Use the b11146 source archive with the matching llama-server binary. Output is a
local derivative of the upstream noncommercial model, with license and hashes.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(home, llama_source, output):
    home, llama_source, output = (
        home.resolve(),
        llama_source.resolve(),
        output.resolve(),
    )
    roots = None
    for manifest in sorted(
        (home / "model-store/snapshots").glob("*/internal-artifact-roots.json"),
        reverse=True,
    ):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            data.get("model_id") == "sentiavatar-susu"
            and data.get("plugin_version") == "0.3.0"
        ):
            roots = {a["id"]: home / a["asset_locator"] for a in data["artifacts"]}
            break
    if roots is None:
        raise ValueError("Install the pinned SentiAvatar Runtime first")
    model = roots["sentiavatar-checkpoints"] / "llm"
    converter = llama_source / "convert_hf_to_gguf.py"
    runtime = home / "runtimes/sentiavatar-susu-cu128"
    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    environment = dict(
        os.environ,
        PYTHONPATH=str(llama_source / "gguf-py"),
        PYTHONDONTWRITEBYTECODE="1",
        HF_HUB_OFFLINE="1",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "uv",
            "run",
            "--python",
            str(python),
            "--with",
            "sentencepiece==0.2.1",
            "--no-project",
            "python",
            "-B",
            str(converter),
            str(model),
            "--outfile",
            str(output),
            "--outtype",
            "f16",
        ],
        env=environment,
        check=True,
    )
    license_path = roots["sentiavatar-source"] / "source/LICENSE"
    shutil.copyfile(license_path, output.with_suffix(".LICENSE"))
    output.with_suffix(".provenance.json").write_text(
        json.dumps(
            {
                "source": "https://huggingface.co/Chuhaojin/SentiAvatar/tree/242b2031a913dd1b25f43fe1f3e112611864c9cc",
                "converter": "https://github.com/ggml-org/llama.cpp/tree/b11146",
                "modification": "BF16 safetensors converted to FP16 GGUF; no fine-tuning",
                "weights_sha256": digest(model / "model.safetensors"),
                "tokenizer_sha256": digest(model / "tokenizer.json"),
                "converter_sha256": digest(converter),
                "gguf_sha256": digest(output),
                "license": "SentiPulse Non-Commercial Source License v1.0",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--llama-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.home, args.llama_source, args.output)
