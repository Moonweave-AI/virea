from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from virea_cli.main import build_parser
from virea_cli.retention import (
    apply_retention_candidates,
    collect_retention_candidates,
    retention_report,
)
from virea_core import StateStore, VireaPaths
from virea_model_pool.pool import _create_directory_reference


def _make_old(path: Path, *, hours: float = 48.0) -> None:
    timestamp = time.time() - (hours * 3600.0)
    if path.is_dir():
        for entry in path.rglob("*"):
            os.utime(entry, (timestamp, timestamp))
    os.utime(path, (timestamp, timestamp))


def test_retention_is_dry_run_by_default_and_apply_is_explicit() -> None:
    parser = build_parser()

    default = parser.parse_args(["model", "gc"])
    apply = parser.parse_args(["model", "gc", "--apply"])
    state = parser.parse_args(["state", "gc", "--older-than-hours", "24"])

    assert default.dry_run is True
    assert default.older_than_hours == 168.0
    assert apply.dry_run is False
    assert state.dry_run is True
    assert state.older_than_hours == 24.0


def test_retention_reclaims_only_old_unreferenced_managed_data(tmp_path: Path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)

    old_temporary = paths.temporary / "install-old-unreferenced"
    old_temporary.mkdir()
    (old_temporary / "weights.part").write_bytes(b"temporary")
    _make_old(old_temporary)

    referenced = paths.temporary / "install-still-referenced"
    referenced.mkdir()
    (referenced / "weights.bin").write_bytes(b"referenced")
    _make_old(referenced)
    store.create_installation_transaction(
        installation_id="install-still-referenced",
        state="DOWNLOADING",
        payload={"model_id": "model-a", "locator": "tmp/install-still-referenced"},
    )

    recent = paths.temporary / "runtime-recent"
    recent.mkdir()
    (recent / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    failed_runtime = paths.runtimes / "runtime-a.failed-01"
    failed_runtime.mkdir()
    (failed_runtime / "python.exe").write_bytes(b"runtime")
    _make_old(failed_runtime)

    old_log = paths.logs / "workers" / "terminal.stdout.log"
    old_log.parent.mkdir(parents=True)
    old_log.write_text("old worker output", encoding="utf-8")
    _make_old(old_log)

    active_log = paths.logs / "workers" / "worker-live.stdout.log"
    active_log.write_text("active worker output", encoding="utf-8")
    _make_old(active_log)
    store.create_worker_instance(
        instance_id="worker-live",
        pid=os.getpid(),
        state="RUNNING",
        started_at="2026-08-21T00:00:00+00:00",
        diagnostics={},
    )

    partial_download = paths.cache / "downloads" / "checkpoint.part"
    partial_download.write_bytes(b"partial")
    _make_old(partial_download)

    dry_run = retention_report(
        paths,
        store,
        dry_run=True,
        older_than_hours=24.0,
    )
    locators = {item["locator"] for item in dry_run["candidates"]}
    assert locators == {
        "cache/downloads/checkpoint.part",
        "logs/workers/terminal.stdout.log",
        "runtimes/runtime-a.failed-01",
        "tmp/install-old-unreferenced",
    }
    assert dry_run["candidate_bytes"] > 0
    assert old_temporary.exists()

    applied = retention_report(
        paths,
        store,
        dry_run=False,
        older_than_hours=24.0,
    )
    assert applied["failures"] == []
    assert set(applied["removed"]) == locators
    assert not old_temporary.exists()
    assert not failed_runtime.exists()
    assert not old_log.exists()
    assert not partial_download.exists()
    assert referenced.exists()
    assert recent.exists()
    assert active_log.exists()


def test_retention_terminal_installation_locator_is_reclaimable(tmp_path: Path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    removed = paths.temporary / "removed-installation"
    removed.mkdir()
    (removed / "manifest.json").write_text("{}", encoding="utf-8")
    _make_old(removed)
    store.create_installation_transaction(
        installation_id="removed-installation",
        state="CANCELLED",
        payload={"model_id": "model-a", "locator": "tmp/removed-installation"},
    )

    report = retention_report(paths, store, dry_run=False, older_than_hours=24.0)

    assert report["failures"] == []
    assert report["removed"] == ["tmp/removed-installation"]
    assert not removed.exists()


def test_retention_apply_revalidates_database_references(tmp_path: Path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    candidate = paths.temporary / "install-became-referenced"
    candidate.mkdir()
    (candidate / "weights.bin").write_bytes(b"weights")
    _make_old(candidate)
    collected, warnings = collect_retention_candidates(
        paths, store, older_than_hours=24.0
    )
    assert warnings == []
    assert [item.locator for item in collected] == ["tmp/install-became-referenced"]
    store.create_installation_transaction(
        installation_id="install-became-referenced",
        state="DOWNLOADING",
        payload={
            "model_id": "model-a",
            "locator": candidate.relative_to(paths.root).as_posix(),
        },
    )

    removed, failures = apply_retention_candidates(
        paths,
        store,
        collected,
        older_than_hours=24.0,
    )

    assert removed == []
    assert failures == ["refused stale candidate: tmp/install-became-referenced"]
    assert candidate.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions are Windows-only")
def test_retention_removes_nested_junction_node_without_touching_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    external = tmp_path / "external-artifacts"
    external.mkdir()
    protected = external / "weights.bin"
    protected.write_bytes(b"must survive retention")

    def deny_symbolic_link(*_args, **_kwargs) -> None:
        raise OSError("force the Windows junction fallback")

    monkeypatch.setattr(Path, "symlink_to", deny_symbolic_link)
    removed_snapshot = paths.temporary / "removed-installation"
    artifact_parent = removed_snapshot / "artifacts"
    artifact_parent.mkdir(parents=True)
    linked = artifact_parent / "weights"
    assert _create_directory_reference(linked, external) == "junction"
    assert linked.is_junction()
    timestamp = time.time() - (48.0 * 3600.0)
    os.utime(removed_snapshot, (timestamp, timestamp))

    top_level_link = paths.temporary / "untrusted-top-level-reference"
    assert _create_directory_reference(top_level_link, external) == "junction"
    report = retention_report(paths, store, dry_run=False, older_than_hours=24.0)

    assert report["failures"] == []
    assert "tmp/removed-installation" in report["removed"]
    assert not removed_snapshot.exists()
    assert top_level_link.is_junction()
    assert any("reparse point" in warning for warning in report["warnings"])
    assert protected.read_bytes() == b"must survive retention"


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions are Windows-only")
def test_retention_refuses_managed_root_junction_without_scanning_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    external = tmp_path / "external-tmp"
    external.mkdir()
    sentinel = external / "external-child"
    sentinel.mkdir()
    (sentinel / "keep.bin").write_bytes(b"must survive")
    _make_old(sentinel)

    paths.temporary.rmdir()

    def deny_symbolic_link(*_args, **_kwargs) -> None:
        raise OSError("force the Windows junction fallback")

    monkeypatch.setattr(Path, "symlink_to", deny_symbolic_link)
    assert _create_directory_reference(paths.temporary, external) == "junction"

    dry_run = retention_report(paths, store, dry_run=True, older_than_hours=24.0)
    applied = retention_report(paths, store, dry_run=False, older_than_hours=24.0)

    assert dry_run["candidates"] == []
    assert applied["removed"] == []
    assert any("unsafe managed retention root" in item for item in dry_run["warnings"])
    assert any("unsafe managed retention root" in item for item in applied["warnings"])
    assert (sentinel / "keep.bin").read_bytes() == b"must survive"
