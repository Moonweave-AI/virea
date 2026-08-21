"""Characterization tests for stable schema, CLI, and HTTP route surfaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from virea.cli import build_parser
from virea.data.annotations import PREVIEW_SCHEMA_VERSION
from virea.motion.canonical import (
    CANONICAL_ROTATION_SEMANTICS,
    CANONICAL_SCHEMA_VERSION,
    CANONICAL_SKELETON_ID,
    FRAME_DIM,
)
from virea.pipelines.artifact_manifest import (
    CANONICAL_ARTIFACT_SCHEMA_VERSION,
    CANONICAL_PROCESSING_VERSION,
    MOTION_SAMPLE_SCHEMA_VERSION,
)
from virea.server.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_schema(name: str) -> dict[str, object]:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))


def test_schema_uris_and_cross_schema_canonical_contract_are_stable() -> None:
    canonical_artifact = _load_schema("canonical_artifact.schema.json")
    motion_sample = _load_schema("motion_sample.schema.json")
    preview_payload = _load_schema("preview_payload.schema.json")

    assert canonical_artifact["$id"] == "urn:virea:schema:canonical-artifact:3.0.0"
    assert motion_sample["$id"] == "urn:virea:schema:motion-sample:3.0.0"
    assert preview_payload["$id"] == "urn:virea:schema:preview-payload:1.0.0"

    assert (
        canonical_artifact["properties"]["schema_version"]["const"]
        == CANONICAL_ARTIFACT_SCHEMA_VERSION
    )
    assert (
        canonical_artifact["properties"]["processing_version"]["const"]
        == CANONICAL_PROCESSING_VERSION
    )
    canonical = canonical_artifact["properties"]["canonical"]["properties"]
    assert canonical["schema_version"]["const"] == CANONICAL_SCHEMA_VERSION
    assert canonical["skeleton_id"]["const"] == CANONICAL_SKELETON_ID
    assert canonical["rotation_semantics"]["const"] == CANONICAL_ROTATION_SEMANTICS
    assert canonical["frame_dim"]["const"] == FRAME_DIM
    assert canonical["dtype"]["const"] == "<f4"
    assert canonical["quaternion_order"]["const"] == "xyzw"

    sample_properties = motion_sample["properties"]
    assert sample_properties["schema_version"]["const"] == MOTION_SAMPLE_SCHEMA_VERSION
    assert (
        sample_properties["artifact_schema_version"]["const"]
        == CANONICAL_ARTIFACT_SCHEMA_VERSION
    )

    assert (
        preview_payload["properties"]["schema_version"]["const"]
        == PREVIEW_SCHEMA_VERSION
    )
    vrm_motion = preview_payload["$defs"]["vrmMotionV3"]["properties"]
    assert vrm_motion["schema_version"]["const"] == "virea.vrm_motion_payload.v3.0.0"
    assert vrm_motion["canonical_schema_version"]["const"] == CANONICAL_SCHEMA_VERSION
    assert vrm_motion["rotation_semantics"]["const"] == CANONICAL_ROTATION_SEMANTICS


def test_cli_command_names_handlers_and_default_parser_values_are_stable() -> None:
    parser = build_parser()
    assert parser.prog == "virea"
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert tuple(subparsers.choices) == ("process", "serve", "build-demo")

    process = parser.parse_args(["process"])
    assert process.func.__name__ == "_cmd_process"
    assert vars(process) == {
        "command": "process",
        "data_source": "",
        "datasets": [],
        "query": "",
        "limit_per_dataset": 0,
        "max_frames": None,
        "workers": 0,
        "skip_existing": True,
        "force": False,
        "func": process.func,
    }

    serve = parser.parse_args(["serve"])
    assert serve.func.__name__ == "_cmd_serve"
    assert vars(serve) == {
        "command": "serve",
        "data_source": "demo",
        "host": "",
        "port": None,
        "reload": False,
        "func": serve.func,
    }

    build_demo = parser.parse_args(["build-demo"])
    assert build_demo.func.__name__ == "_cmd_build_demo"
    assert vars(build_demo) == {
        "command": "build-demo",
        "samples_per_dataset": 100,
        "overwrite": False,
        "func": build_demo.func,
    }


def test_preview_http_route_contract_is_stable_without_loading_data() -> None:
    app = create_app()
    actual = [
        (route.path, tuple(sorted(route.methods or ())), route.name)
        for route in app.routes
        if route.path == "/" or route.path.startswith("/api/")
    ]
    assert actual == [
        ("/", ("GET",), "root"),
        ("/api/health", ("GET",), "health"),
        ("/api/catalog", ("GET",), "catalog"),
        ("/api/artifacts/sidecars/{digest}", ("GET",), "artifact_sidecar"),
        ("/api/datasets", ("GET",), "datasets"),
        ("/api/samples", ("GET",), "samples"),
        ("/api/preview/source", ("GET",), "preview_source"),
        ("/api/preview/processed", ("GET",), "preview_processed"),
        ("/api/preview/motion", ("GET",), "preview_motion"),
        ("/api/preview/quality", ("GET",), "preview_quality_endpoint"),
        ("/api/preview/source/binary", ("GET",), "preview_source_binary"),
        ("/api/preview/processed/binary", ("GET",), "preview_processed_binary"),
        ("/api/preview/on-demand", ("GET",), "preview_on_demand"),
        ("/api/preview", ("GET",), "preview_legacy"),
        ("/api/process", ("POST",), "process"),
        ("/api/batch", ("POST",), "batch_process"),
    ]
