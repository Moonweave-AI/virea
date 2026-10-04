# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["fastapi>=0.115,<1", "uvicorn>=0.34,<1", "kokoro==0.9.4", "misaki[zh]==0.9.4", "numpy>=1.26,<3", "torch==2.8.0"]
# [tool.uv.sources]
# torch = { index = "pytorch-cu128" }
# [[tool.uv.index]]
# name = "pytorch-cu128"
# url = "https://download.pytorch.org/whl/cu128"
# explicit = true
# ///
"""uv run --script scripts/character/serve_kokoro_cuda.py --port 8082"""

import argparse
import os

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument(
        "--precision",
        choices=["auto", "float32", "float16", "bfloat16"],
        default="auto",
    )
    args = parser.parse_args()
    os.environ["VIREA_TTS_DEVICE"] = "cuda"
    os.environ["VIREA_TTS_PRECISION"] = args.precision
    from serve_kokoro import app

    uvicorn.run(app, host="127.0.0.1", port=args.port)
