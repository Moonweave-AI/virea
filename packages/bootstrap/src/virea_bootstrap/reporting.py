from __future__ import annotations

from pathlib import Path

from virea_contracts.machine import MachineReport
from virea_core.atomic import atomic_create_json, atomic_write_json
from virea_core.paths import VireaPaths, safe_component


def record_machine_report(paths: VireaPaths, report: MachineReport) -> Path:
    """Persist one append-only machine report, then update the latest pointer."""

    report_id = safe_component(report.report_id, name="machine report id")
    payload = report.model_dump(mode="json")
    report_path = paths.machine / "reports" / f"{report_id}.json"
    atomic_create_json(report_path, payload)
    atomic_write_json(paths.machine / "latest.json", payload)
    return report_path
