from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from virea.data.annotations import cache_data_sidecar, make_annotation, make_channel


SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"


def _validator(name: str) -> Draft202012Validator:
    path = SCHEMA_ROOT / name
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def test_annotation_json_schema_matches_runtime_pair_and_provenance_rules() -> None:
    validator = _validator("annotation.schema.json")
    valid = make_annotation(
        dataset="babel",
        sample_id="sample",
        source="babel.frame_ann.labels",
        record_key="0",
        ordinal=0,
        level="action",
        type="action",
        text="turn",
        provenance="native",
        start_sec=0.0,
        end_sec=1.0,
        fps=30.0,
    )
    validator.validate(valid)

    unpaired = deepcopy(valid)
    unpaired["end_sec"] = None
    with pytest.raises(ValidationError):
        validator.validate(unpaired)

    bad_metadata_anchor = deepcopy(valid)
    bad_metadata_anchor["level"] = "metadata"
    bad_metadata_anchor["bodypart"] = "left_hand"
    with pytest.raises(ValidationError):
        validator.validate(bad_metadata_anchor)

    missing_reasoning = deepcopy(valid)
    missing_reasoning["provenance"] = "derived"
    missing_reasoning["reasoning"] = None
    with pytest.raises(ValidationError):
        validator.validate(missing_reasoning)


def test_channel_json_schema_matches_runtime_availability_rules() -> None:
    validator = _validator("channel.schema.json")
    missing = make_channel(
        dataset="susuinteracts",
        sample_id="sample",
        source="susuinteracts.wav_data",
        record_key="audio",
        ordinal=0,
        kind="audio",
        availability="missing",
        reason_unavailable="No WAV exists.",
    )
    validator.validate(missing)
    invalid_missing = deepcopy(missing)
    invalid_missing["reason_unavailable"] = None
    with pytest.raises(ValidationError):
        validator.validate(invalid_missing)

    data_ref = cache_data_sidecar(b"{}", media_type="application/json", encoding="utf-8", suffix=".json")
    external = make_channel(
        dataset="motionx",
        sample_id="sample",
        source="motionx.body_texts",
        record_key="body_texts",
        ordinal=0,
        kind="body_text",
        availability="external",
        representation="per_frame_text_json",
        data_ref=data_ref,
    )
    validator.validate(external)
    invalid_external = deepcopy(external)
    invalid_external["data_ref"] = None
    with pytest.raises(ValidationError):
        validator.validate(invalid_external)
    traversal = deepcopy(external)
    traversal["data_ref"]["path"] = "../outside.npy"
    with pytest.raises(ValidationError):
        validator.validate(traversal)
    backslash = deepcopy(external)
    backslash["data_ref"]["path"] = r"sidecars\outside.npy"
    with pytest.raises(ValidationError):
        validator.validate(backslash)


def test_canonical_artifact_sidecar_schema_rejects_traversal_and_backslashes() -> None:
    schema = json.loads((SCHEMA_ROOT / "canonical_artifact.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema["$defs"]["dataReference"])
    valid = cache_data_sidecar(b"canonical", media_type="application/octet-stream", encoding="binary")
    validator.validate(valid)
    for bad_path in ("../outside.npy", "sidecars/../../outside.npy", r"sidecars\outside.npy", "C:/outside.npy"):
        invalid = deepcopy(valid)
        invalid["path"] = bad_path
        with pytest.raises(ValidationError):
            validator.validate(invalid)
