"""Deterministically export the versioned embodied-runtime JSON Schemas."""

import argparse
import json
from pathlib import Path

from .performance import (
    AudioArtifactV1,
    ExecutablePerformanceV1,
    ExecutionCommandV1,
    ExecutionReceiptV1,
    InteractionRequestV1,
    MotionRequestV1,
    NativeMotionArtifactV1,
    ResponsePlanV1,
    SessionSnapshotV1,
)

MODELS = (
    InteractionRequestV1,
    ResponsePlanV1,
    MotionRequestV1,
    NativeMotionArtifactV1,
    AudioArtifactV1,
    ExecutablePerformanceV1,
    ExecutionCommandV1,
    ExecutionReceiptV1,
    SessionSnapshotV1,
)


def documents():
    for model in MODELS:
        schema = model.model_json_schema()
        name = schema["properties"]["schema_version"]["const"].split(".")[1]
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"urn:virea:schema:{name}:1.0.0",
            **schema,
        }
        yield (
            f"{name}.schema.json",
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path("packages/contracts/schemas/v1")
    )
    args = parser.parse_args()
    stale = []
    for name, content in documents():
        path = args.output / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if stale:
        parser.exit(1, "Stale runtime schemas: " + ", ".join(stale) + "\n")


if __name__ == "__main__":
    main()
