"""Offline JSON Schema helpers shared by the repository test suite.

The helpers intentionally use development-only dependencies and load every
schema from the checked-out repository. They are not part of VIREA's runtime
package API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_FILENAMES = (
    "annotation.schema.json",
    "canonical_artifact.schema.json",
    "channel.schema.json",
    "dataset_manifest.schema.json",
    "dataset_profile.schema.json",
    "motion_sample.schema.json",
    "preview_payload.schema.json",
    "quality_report.schema.json",
)


def repository_schema_root() -> Path:
    """Return the schema directory in the current source checkout."""

    root = Path(__file__).resolve().parents[1] / "schemas"
    if not root.is_dir():
        raise FileNotFoundError(
            "repository schemas are unavailable; pass an explicit schema_root"
        )
    return root


def load_schema_document(
    filename: str,
    *,
    schema_root: Path | None = None,
) -> dict[str, Any]:
    root = (schema_root or repository_schema_root()).resolve()
    if filename not in SCHEMA_FILENAMES:
        raise ValueError(f"unknown VIREA schema filename: {filename}")
    document = json.loads((root / filename).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"schema must be a JSON object: {filename}")
    return document


def local_schema_registry(*, schema_root: Path | None = None) -> Registry:
    """Build a closed local registry containing every VIREA schema resource."""

    registry: Registry = Registry()
    seen: set[str] = set()
    for filename in SCHEMA_FILENAMES:
        document = load_schema_document(filename, schema_root=schema_root)
        identifier = document.get("$id")
        if not isinstance(identifier, str) or not identifier.startswith(
            "urn:virea:schema:"
        ):
            raise ValueError(f"schema $id must be a versioned VIREA URN: {filename}")
        if identifier in seen:
            raise ValueError(f"duplicate schema $id: {identifier}")
        seen.add(identifier)
        registry = registry.with_resource(identifier, Resource.from_contents(document))
    return registry


def validator_for_schema(
    filename: str,
    *,
    schema_root: Path | None = None,
) -> Draft202012Validator:
    """Return a Draft 2020-12 validator with network retrieval disabled."""

    document = load_schema_document(filename, schema_root=schema_root)
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(
        document,
        registry=local_schema_registry(schema_root=schema_root),
    )


def validate_schema_instance(
    instance: Any,
    filename: str,
    *,
    schema_root: Path | None = None,
) -> None:
    """Validate one instance against a named local schema or raise ValidationError."""

    validator_for_schema(filename, schema_root=schema_root).validate(instance)
