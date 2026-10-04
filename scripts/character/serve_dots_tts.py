# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["dots.tts==0.3.1", "fastapi>=0.115,<1", "uvicorn>=0.34,<1", "torch==2.8.0", "torchaudio==2.8.0", "transformers==4.57.6", "bitsandbytes==0.50.2"]
# [tool.uv.sources]
# torch = { index = "pytorch-cu128" }
# torchaudio = { index = "pytorch-cu128" }
# [[tool.uv.index]]
# name = "pytorch-cu128"
# url = "https://download.pytorch.org/whl/cu128"
# explicit = true
# ///
"""Resident dots.tts voice cloning in an isolated Python environment."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument(
        "--model",
        default=os.environ.get("VIREA_TTS_REPOSITORY", "dots-studio/dots.tts-soar"),
    )
    parser.add_argument("--revision", default=os.environ.get("VIREA_TTS_REVISION"))
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--precision", choices=["float32", "bfloat16"], default=None)
    parser.add_argument("--quantization", choices=["none", "nf4"], default=None)
    parser.add_argument(
        "--gpu-memory-gib",
        type=float,
        default=6.0,
        help="CUDA allocator limit in GiB; excludes other processes/driver memory",
    )
    parser.add_argument(
        "--optimize",
        action="store_true",
        help="Enable torch.compile; requires a supported compiler/toolchain",
    )
    parser.add_argument("--voices-dir", type=Path, default=None)
    args = parser.parse_args()
    if args.revision is None and args.model == "dots-studio/dots.tts-soar":
        args.revision = "2f9b3e18d70d670d4c701da2dc55ded5755815ce"
    if args.device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import torch
    import uvicorn
    from dots_service import create_app

    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error(
            "CUDA is not available; use --device cpu for an explicit CPU deployment"
        )
    precision = args.precision or ("bfloat16" if args.device == "cuda" else "float32")
    if args.device == "cpu" and precision != "float32":
        parser.error("CPU requires --precision float32")
    quantization = args.quantization or ("nf4" if args.device == "cuda" else "none")
    if quantization == "nf4" and (
        args.device != "cuda" or precision != "bfloat16" or args.optimize
    ):
        parser.error("NF4 requires CUDA + bfloat16 and does not support --optimize")
    if not 0 < args.gpu_memory_gib <= 1024:
        parser.error("--gpu-memory-gib must be finite and in (0, 1024]")
    home = Path(os.environ.get("VIREA_HOME", str(Path.home() / ".virea")))
    app = create_app(
        directory=args.voices_dir or home / "characters" / "voices",
        model=args.model,
        revision=args.revision,
        precision=precision,
        optimize=args.optimize,
        quantization=quantization,
        gpu_memory_gib=args.gpu_memory_gib,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
