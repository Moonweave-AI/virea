from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace

from virea.pipelines.batch import BatchReport
from virea.pipelines.catalog import CatalogPipeline
from virea.reporting import portable_path_reference, sanitize_report_paths
from virea.verification import write_verification_report
from scripts import smoke_pipeline


def _assert_no_absolute_path_values(value: object) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_absolute_path_values(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_absolute_path_values(item)
    elif isinstance(value, str):
        assert not PureWindowsPath(value).is_absolute(), value
        assert not PurePosixPath(value).is_absolute(), value


def test_processed_root_reference_is_portable_on_windows_and_posix() -> None:
    assert portable_path_reference(
        r"D:\private\processed\canonical\v0.2.0\clip.npz",
        base=r"D:\private\processed",
    ) == "canonical/v0.2.0/clip.npz"
    assert portable_path_reference(
        "/srv/private/processed/canonical/v0.2.0/clip.npz",
        base="/srv/private/processed",
    ) == "canonical/v0.2.0/clip.npz"
    assert portable_path_reference(
        r"D:\private\processed\..\raw\clip.npz",
        base=r"D:\private\processed",
    ).startswith("clip.npz@sha256-")
    assert portable_path_reference("../raw/clip.npz").startswith("clip.npz@sha256-")
    assert sanitize_report_paths(
        {"canonical_motion": "../raw/clip.npz"},
        relative_base="/srv/private/processed",
    )["canonical_motion"].startswith("clip.npz@sha256-")


def test_report_path_sanitizer_preserves_urls_urns_and_api_routes() -> None:
    values = (
        "https://example.com/path/to?q=1",
        "https://example.com/redirect?next=/api/v1/motions",
        "http://127.0.0.1:8000/api",
        "urn:virea:motion:clip-1",
        "/api/v1/motions",
        "/v1/motions",
    )
    assert tuple(sanitize_report_paths(value) for value in values) == values
    sentence = "endpoint https://example.com/redirect?next=/api/v1; local /srv/private/raw/clip.npz"
    sanitized = sanitize_report_paths(sentence)
    assert "https://example.com/redirect?next=/api/v1" in sanitized
    assert "/srv/private/raw" not in sanitized


def test_write_verification_report_never_serializes_machine_absolute_paths(tmp_path: Path) -> None:
    raw_root = r"D:\private\datasets\raw"
    processed_root = r"D:\private\runtime\processed"
    model_root = r"C:\Users\private-user\Downloads\VRM-Model-1.vrm"
    posix_raw_root = "/srv/private/datasets/raw"
    report = {
        "schema_version": "virea.verification_report.v0.1.0",
        "reports": [
            {
                "files": {
                    "canonical_motion": processed_root + r"\canonical\v0.2.0\clip.npz",
                    "source": raw_root + r"\amass\clip.npz",
                },
                "error": f"failed to read {raw_root}\\amass\\clip.npz and {posix_raw_root}/clip.npz",
            }
        ],
        "vrm_control_rest_audit": {
            "source": {"vrm_model_root": model_root},
            "descriptors": [{"avatar_path": model_root}],
        },
    }

    output = write_verification_report(report, tmp_path / "verification.json")
    serialized = output.read_text(encoding="utf-8")
    payload = json.loads(serialized)

    for secret in (raw_root, processed_root, model_root, posix_raw_root):
        assert secret not in serialized
        assert secret.replace("\\", "/") not in serialized.replace("\\", "/")
    assert payload["reports"][0]["files"]["canonical_motion"].startswith("clip.npz@sha256-")
    assert payload["vrm_control_rest_audit"]["descriptors"][0]["avatar_path"].startswith(
        "VRM-Model-1.vrm@sha256-"
    )
    _assert_no_absolute_path_values(payload)


def test_batch_report_serialization_redacts_nested_absolute_paths() -> None:
    report = BatchReport(
        processed_root=r"D:\private\runtime\processed",
        total=1,
        processed=1,
        items=[
            {
                "files": {"canonical_motion": "/srv/private/processed/canonical/clip.npz"},
                "error": r"reader failed at C:\private\raw\clip.npz",
            }
        ],
    ).to_dict()

    assert str(report["processed_root"]).startswith("processed@sha256-")
    assert str(report["items"][0]["files"]["canonical_motion"]).startswith("clip.npz@sha256-")
    assert "C:\\private\\raw" not in str(report["items"][0]["error"])
    _assert_no_absolute_path_values(report)


def test_catalog_uses_source_tokens_and_dataset_relative_paths(tmp_path: Path) -> None:
    raw_root = tmp_path / "private" / "raw"
    processed_root = tmp_path / "private" / "processed"
    dataset_root = raw_root / "amass"
    dataset_root.mkdir(parents=True)
    (dataset_root / "clip.npz").write_bytes(b"fixture")
    record = SimpleNamespace(raw_dir="amass", to_dict=lambda: {"key": "amass"})
    registry = SimpleNamespace(
        paths=SimpleNamespace(
            data_source="full",
            raw_root=raw_root,
            processed_root=processed_root,
        ),
        iter_records=lambda: iter((record,)),
    )

    payload = CatalogPipeline(registry).summary()

    assert payload["raw_root"] == "data-source/full/raw"
    assert payload["processed_root"] == "data-source/full/processed"
    assert payload["raw_root_status"] == "configured"
    assert payload["processed_root_status"] == "missing"
    assert payload["datasets"][0]["raw_root"] == "amass"
    assert payload["datasets"][0]["raw_path_base"] == "data-source/full/raw"
    assert str(raw_root) not in json.dumps(payload)
    assert str(processed_root) not in json.dumps(payload)


def test_smoke_report_uses_source_tokens_without_root_paths(tmp_path: Path, monkeypatch) -> None:
    raw_root = tmp_path / "private" / "raw"
    processed_root = tmp_path / "private" / "processed"
    raw_root.mkdir(parents=True)
    registry = SimpleNamespace(
        paths=SimpleNamespace(raw_root=raw_root, processed_root=processed_root),
        keys=lambda: ["amass"],
        adapter=lambda _dataset: SimpleNamespace(discover=lambda limit: []),
    )
    monkeypatch.setattr(smoke_pipeline.DatasetRegistry, "default", lambda data_source: registry)

    payload = smoke_pipeline.smoke_source("full", max_frames=8, persist=False)

    assert payload["raw_root"] == "data-source/full/raw"
    assert payload["processed_root"] == "data-source/full/processed"
    assert payload["reports"][0]["reason"] == "no sample found in configured full raw root"
    serialized = json.dumps(payload)
    assert str(raw_root) not in serialized
    assert str(processed_root) not in serialized
