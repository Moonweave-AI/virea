from __future__ import annotations

from pathlib import Path
import hashlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

import virea.server.app as server_app
from virea.data.annotations import cache_data_sidecar
from virea.data.types import SampleRef
from virea.paths import ProjectPaths


def test_server_is_local_first_and_write_api_is_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("VIREA_ENABLE_WRITE_API", raising=False)
    monkeypatch.delenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", raising=False)
    client = TestClient(server_app.create_app())

    health = client.get("/api/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["write_api_enabled"] is False
    assert payload["trusted_raw_pickle_enabled"] is False
    assert "raw_root" not in payload
    assert "processed_root" not in payload
    assert all("raw_root" not in item for item in payload["available_data_sources"].values())
    assert payload["sidecar_cache"]["status"] in {"healthy", "over_budget"}
    assert payload["sidecar_cache"]["byte_length"] >= 0
    assert payload["sidecar_cache"]["max_total_bytes"] == 256 * 1024 * 1024
    assert "path" not in payload["sidecar_cache"]

    denied = client.post(
        "/api/process",
        json={"dataset": "amass", "sample_id": "fixture", "persist": True},
    )
    assert denied.status_code == 403

    untrusted = client.get("/api/health", headers={"host": "untrusted.example"})
    assert untrusted.status_code == 400

    blocked_pickle = server_app._public_http_error(
        PermissionError(
            "susuinteracts legacy container; set VIREA_ALLOW_TRUSTED_RAW_PICKLE=1; "
            "private source path must not be exposed"
        )
    )
    assert blocked_pickle.status_code == 400
    assert "VIREA_ALLOW_TRUSTED_RAW_PICKLE=1" in blocked_pickle.detail
    assert "private source path" not in blocked_pickle.detail


def test_preview_default_preserves_full_clip_and_absolute_path_redaction(tmp_path, monkeypatch) -> None:
    raw_root = tmp_path / "raw"
    processed_root = tmp_path / "processed"
    fake_registry = SimpleNamespace(
        paths=SimpleNamespace(
            raw_root=raw_root,
            processed_root=processed_root,
            preview_max_frames=None,
        )
    )
    monkeypatch.setattr(server_app, "_registry_for", lambda _source: fake_registry)

    result = server_app._preview_query_params(None, "amass", "sample", None, True)
    assert result[4] is None

    explicit = server_app._preview_query_params(None, "amass", "sample", 1800, True)
    assert explicit[4] == 1800

    public = server_app._public_payload(
        {
            "source_path": raw_root / "amass" / "clip.npz",
            "artifact": (processed_root / "canonical" / "clip.npz").as_posix(),
            "outside": Path("C:/Users/example/private/model.vrm"),
        },
        fake_registry,
    )
    assert public["source_path"] == "raw/amass/clip.npz"
    assert public["artifact"] == "processed/canonical/clip.npz"
    assert public["outside"] == "<redacted-local-path>/model.vrm"

    error = server_app._public_http_error(
        FileNotFoundError("C:/Users/example/private/raw/humanml3d/missing.parquet"),
        404,
    )
    assert error.status_code == 404
    assert "C:/" not in str(error.detail)
    assert "Users" not in str(error.detail)


def test_project_preview_limit_supports_full_or_explicit_configuration(tmp_path) -> None:
    base = {
        "paths": {},
        "data_sources": {"full": {"raw_root": str(tmp_path / "raw")}},
    }
    assert ProjectPaths(config={**base, "runtime": {"preview_max_frames": None}}).preview_max_frames is None
    assert ProjectPaths(config={**base, "runtime": {"preview_max_frames": 1800}}).preview_max_frames == 1800


def test_sample_catalog_exposes_profile_fps_without_claiming_native_fps(tmp_path) -> None:
    raw_root = tmp_path / "raw"
    registry = SimpleNamespace(
        paths=SimpleNamespace(raw_root=raw_root, processed_root=tmp_path / "processed")
    )
    sample = SampleRef(
        dataset="beat",
        sample_id="pose/1/clip",
        source_path=raw_root / "beat" / "pose" / "1" / "clip.bvh",
        source_format="beat_bvh",
        codec_key="beat_axis_angle_body22",
        fps=None,
        metadata={"dataset_profile": "beat_bvh_full75_runtime"},
    )
    payload = server_app._public_sample_payload(sample, registry)
    assert payload["fps"] is None
    assert payload["preview_fps_fallback"] == 120.0
    assert payload["preview_fps_provenance"] == "dataset_profile:beat_bvh_full75_runtime"
    assert payload["source_path"] == "raw/beat/pose/1/clip.bvh"


def test_sidecar_read_is_content_addressed_contained_and_nosniff(tmp_path, monkeypatch) -> None:
    raw_root = tmp_path / "raw"
    processed_root = tmp_path / "processed"
    sidecars = processed_root / "sidecars"
    sidecars.mkdir(parents=True)
    content = b'{"native_record":"visible"}\n'
    digest = hashlib.sha256(content).hexdigest()
    (sidecars / f"{digest}.json").write_bytes(content)
    fake_registry = SimpleNamespace(paths=SimpleNamespace(raw_root=raw_root, processed_root=processed_root))
    monkeypatch.setattr(server_app, "_registry_for", lambda _source: fake_registry)

    client = TestClient(server_app.create_app())
    response = client.get(f"/api/artifacts/sidecars/{digest}?data_source=full")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["etag"] == f'"sha256-{digest}"'

    wrong = "0" * 64
    assert client.get(f"/api/artifacts/sidecars/{wrong}?data_source=full").status_code == 404
    assert client.get("/api/artifacts/sidecars/not-a-digest?data_source=full").status_code == 404


def test_sidecar_read_falls_back_to_verified_on_demand_cache(tmp_path, monkeypatch) -> None:
    fake_registry = SimpleNamespace(
        paths=SimpleNamespace(raw_root=tmp_path / "raw", processed_root=tmp_path / "processed")
    )
    monkeypatch.setattr(server_app, "_registry_for", lambda _source: fake_registry)
    content = b"on-demand channel bytes"
    reference = cache_data_sidecar(
        content,
        media_type="application/octet-stream",
        encoding="binary",
        suffix=".bin",
    )
    response = TestClient(server_app.create_app()).get(reference["read_api"])
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["etag"] == f'"sha256-{reference["sha256"]}"'
