from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from virea_model_sdk.fake import FakeMotionPlugin
from virea_model_sdk.worker import serve_plugin


class BlockingMotionPlugin(FakeMotionPlugin):
    def __init__(self, model_id: str, job_root: Path) -> None:
        super().__init__(model_id)
        self.job_root = job_root

    def infer(self, request, context):
        child = subprocess.Popen(
            (sys.executable, "-c", "import time; time.sleep(120)"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        (self.job_root / "inference-child.pid").write_text(
            str(child.pid), encoding="ascii"
        )
        # Deliberately ignore the cooperative Worker cancellation context.  The
        # control plane must still terminate the isolated process tree.
        while True:
            time.sleep(0.1)


def _spawn_startup_child(job_root: Path) -> None:
    child = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(120)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    (job_root / "startup-child.pid").write_text(str(child.pid), encoding="ascii")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("inference", "startup"), required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--runtime-id", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    identity = {
        "VIREA_WORKER_INSTANCE_ID": args.instance_id,
        "VIREA_WORKER_JOB_ID": args.job_id,
        "VIREA_WORKER_MODEL_ID": args.model_id,
        "VIREA_RUNTIME_ID": args.runtime_id,
        "VIREA_WORKER_PORT": str(args.port),
    }
    for name, value in identity.items():
        if os.getenv(name) != value:
            raise SystemExit(f"identity mismatch: {name}")
    args.job_root.mkdir(parents=True, exist_ok=True)
    if args.mode == "startup":
        _spawn_startup_child(args.job_root)
        while True:
            time.sleep(0.1)
    serve_plugin(
        BlockingMotionPlugin(args.model_id, args.job_root),
        host=args.host,
        port=args.port,
        job_root=args.job_root,
    )


if __name__ == "__main__":
    main()
