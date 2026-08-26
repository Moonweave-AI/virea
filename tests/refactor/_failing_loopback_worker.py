from __future__ import annotations

import argparse
from pathlib import Path

from virea_model_sdk.fake import FakeMotionPlugin
from virea_model_sdk.plugin import WorkerFailure
from virea_model_sdk.worker import serve_plugin


class FailingStartupPlugin(FakeMotionPlugin):
    def load(self) -> None:
        raise WorkerFailure(
            "STARTUP_FIXTURE_FAILED",
            "structured startup failure fixture",
            retryable=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--runtime-id", required=True)
    args = parser.parse_args()
    serve_plugin(
        FailingStartupPlugin(args.model_id),
        host=args.host,
        port=args.port,
        job_root=args.job_root,
    )


if __name__ == "__main__":
    main()
