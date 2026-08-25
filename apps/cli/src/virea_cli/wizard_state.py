"""Small, durable preferences used only by the no-argument wizard."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from virea_contracts.execution import ExecutionTargetSelection
from virea_core.atomic import atomic_write_json
from virea_core.paths import VireaPaths

_SCHEMA = "virea.wizard_preferences.v1.0.0"


@dataclass(frozen=True, slots=True)
class WizardPreferences:
    model_id: str | None = None
    execution_target: ExecutionTargetSelection | None = None


def preferences_path(paths: VireaPaths) -> Path:
    return paths.config / "wizard-preferences.json"


def load_preferences(paths: VireaPaths) -> tuple[WizardPreferences, str | None]:
    """Load valid preferences; a damaged optional file never blocks the wizard."""

    path = preferences_path(paths)
    if not path.is_file():
        return WizardPreferences(), None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA:
            raise ValueError("schema version is unsupported")
        model_id = payload.get("model_id")
        if model_id is not None and (not isinstance(model_id, str) or not model_id):
            raise ValueError("model_id is invalid")
        raw_target = payload.get("execution_target")
        target = (
            ExecutionTargetSelection.model_validate(raw_target)
            if raw_target is not None
            else None
        )
        return WizardPreferences(model_id=model_id, execution_target=target), None
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return WizardPreferences(), f"{path}: {exc}"


def save_preferences(
    paths: VireaPaths,
    *,
    model_id: str,
    execution_target: ExecutionTargetSelection | None,
) -> None:
    atomic_write_json(
        preferences_path(paths),
        {
            "schema_version": _SCHEMA,
            "model_id": model_id,
            "execution_target": (
                execution_target.model_dump(mode="json")
                if execution_target is not None
                else None
            ),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def installed_target(
    pool: Any, report: dict[str, Any]
) -> ExecutionTargetSelection | None:
    """Recover the target bound to a verified READY installation snapshot."""

    installation_id = report.get("installation_id")
    if not report.get("ready") or not isinstance(installation_id, str):
        return None
    row = pool.store.installation_transaction(installation_id)
    if row is None:
        return None
    try:
        payload = json.loads(row["payload_json"])
        target = payload["execution_target"]["resolved"]
        domain = target["execution_domain"]["id"]
        return ExecutionTargetSelection(
            execution_domain_id=domain,
            runtime_variant_id=target["runtime_variant_id"],
            resource_profile_id=target["resource_profile_id"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
