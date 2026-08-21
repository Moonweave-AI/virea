from __future__ import annotations

import json

import pytest
from virea_bootstrap.reporting import record_machine_report
from virea_cli.real_e2e_validator import (
    AcceptanceFailure,
    _select_preinstallation_machine_report,
)
from virea_contracts.machine import MachineReport
from virea_core.atomic import atomic_create_json
from virea_core.paths import VireaPaths


def _report(report_id: str, recorded_at: str) -> MachineReport:
    return MachineReport(
        report_id=report_id,
        recorded_at=recorded_at,
        platform="win32",
        os_name="Windows",
        os_version="test",
        architecture="AMD64",
        python_version="3.11.9",
        is_wsl=False,
        cpu_count=16,
        memory_total_bytes=64 * 1024**3,
        storage_root="D:/virea",
        storage_free_bytes=100 * 1024**3,
        accelerators=(),
        tools={"uv": "uv 0.test"},
    )


def test_validator_chooses_preinstall_report_when_latest_is_postinstall(
    tmp_path,
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    before = _report("01PREINSTALL", "2026-08-21T00:00:00+00:00")
    after = _report("01POSTINSTALL", "2026-08-21T02:00:00+00:00")
    record_machine_report(paths, before)
    record_machine_report(paths, after)

    selected, selected_path = _select_preinstallation_machine_report(
        paths.root,
        installation_created_at="2026-08-21T01:00:00+00:00",
    )

    latest = json.loads((paths.machine / "latest.json").read_text(encoding="utf-8"))
    assert latest["report_id"] == after.report_id
    assert selected == before
    assert selected_path == paths.machine / "reports" / f"{before.report_id}.json"


def test_validator_rejects_history_with_no_preinstall_report(tmp_path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    record_machine_report(
        paths,
        _report("01POSTINSTALL", "2026-08-21T02:00:00+00:00"),
    )

    with pytest.raises(
        AcceptanceFailure,
        match="doctor evidence was not recorded before installation",
    ):
        _select_preinstallation_machine_report(
            paths.root,
            installation_created_at="2026-08-21T01:00:00+00:00",
        )


@pytest.mark.parametrize(
    ("filename", "payload_update"),
    [
        ("01DIFFERENT.json", {}),
        ("01VALID.json", {"schema_version": "virea.machine_report.v0.0.0"}),
        ("01VALID.json", {"recorded_at": "2026-08-21T00:00:00"}),
    ],
)
def test_validator_excludes_reports_with_invalid_identity_schema_or_timestamp(
    tmp_path,
    filename: str,
    payload_update: dict[str, str],
) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    payload = _report(
        "01VALID",
        "2026-08-21T00:00:00+00:00",
    ).model_dump(mode="json")
    payload.update(payload_update)
    atomic_create_json(paths.machine / "reports" / filename, payload)

    with pytest.raises(
        AcceptanceFailure,
        match="doctor evidence was not recorded before installation",
    ):
        _select_preinstallation_machine_report(
            paths.root,
            installation_created_at="2026-08-21T01:00:00+00:00",
        )


def test_machine_report_history_is_append_only(tmp_path) -> None:
    paths = VireaPaths(tmp_path / "virea-home")
    report = _report("01IMMUTABLE", "2026-08-21T00:00:00+00:00")
    report_path = record_machine_report(paths, report)

    with pytest.raises(FileExistsError):
        record_machine_report(
            paths,
            report.model_copy(update={"recorded_at": "2026-08-21T00:01:00+00:00"}),
        )

    persisted = MachineReport.model_validate_json(report_path.read_text("utf-8"))
    assert persisted == report
