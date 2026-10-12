"""Model publication must survive unavailable UI progress storage."""

import errno
import os
import time
from pathlib import Path
from types import SimpleNamespace

from test_core_bootstrap_model_pool import (
    _manifest_payload,
    _persist_completed_acceptance,
    _production_manifest,
)
from virea_contracts.installation import InstallationState
from virea_core import StateStore, VireaPaths
from virea_model_pool import ModelPool
from virea_model_pool.catalog import ModelCatalog

from virea.onboarding.model_progress import (
    installation_stage,
    installation_transfer,
    record_installation,
)


def test_model_reaches_persisted_ready_when_all_progress_replaces_fail(
    tmp_path, monkeypatch, caplog
):
    source = tmp_path / "source"
    source.mkdir()
    weights = b"unit-contract model bytes"
    (source / "weights.bin").write_bytes(weights)
    payload = _manifest_payload("local-model")
    payload["artifacts"] = [
        {
            "id": "weights",
            "kind": "local",
            "local_path": str(source),
            "expected_files": ["weights.bin"],
            "expected_total_bytes": len(weights),
        }
    ]
    manifest = _production_manifest(payload)
    paths = VireaPaths(tmp_path / "virea-home")
    store = StateStore(paths)
    pool = ModelPool(paths, store, ModelCatalog((manifest,)))
    pool.sync_catalog()
    replace = os.replace
    failures = []

    def locked_progress(source, destination):
        if Path(destination).parent == paths.root / "setup/model-progress":
            failures.append(destination)
            error = PermissionError(errno.EACCES, "progress is locked")
            error.winerror = 32
            raise error
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", locked_progress)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    @record_installation
    def install(request, control):
        installation_stage("download", "Checking local artifacts")
        staged = pool.stage_artifacts(request.model_id, progress=installation_transfer)
        assert staged.state is InstallationState.BUILDING_RUNTIME
        installation_stage("validate", "Running acceptance")
        acceptance = _persist_completed_acceptance(
            pool, manifest, installation_id=staged.installation_id
        )
        published = pool.publish_ready(staged, acceptance=acceptance)
        return {
            "state": published.state.value,
            "id": published.installation_id,
            "locator": published.locator,
        }

    result = install(
        SimpleNamespace(model_id="local-model", apply=True),
        SimpleNamespace(paths=paths),
    )
    assert failures
    assert result["state"] == "READY"
    assert store.installation_transaction(result["id"])["state"] == "READY"
    assert pool.installation_summary("local-model")["ready"]
    snapshot = paths.resolve_locator(result["locator"])
    assert (snapshot / "artifacts/weights/weights.bin").read_bytes() == weights
    assert not list((paths.root / "setup/model-progress").glob("*.tmp"))
    assert any(record.levelname == "WARNING" for record in caplog.records)
