from __future__ import annotations

import argparse
import os
from pathlib import Path

from .fake import FakeMotionPlugin
from .worker import serve_plugin


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-fake-worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--model-id", default="fake-motion-v1")
    parser.add_argument("--instance-id")
    parser.add_argument("--job-id")
    parser.add_argument("--runtime-id")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    for value, environment_name in (
        (args.instance_id, "VIREA_WORKER_INSTANCE_ID"),
        (args.job_id, "VIREA_WORKER_JOB_ID"),
        (args.model_id, "VIREA_WORKER_MODEL_ID"),
        (args.runtime_id, "VIREA_RUNTIME_ID"),
        (str(args.port), "VIREA_WORKER_PORT"),
    ):
        expected = os.getenv(environment_name)
        if value is not None and expected and str(value) != expected:
            raise SystemExit(f"Worker identity mismatch for {environment_name}")
    serve_plugin(
        FakeMotionPlugin(args.model_id),
        host=args.host,
        port=args.port,
        job_root=args.job_root,
    )


if __name__ == "__main__":
    main()
