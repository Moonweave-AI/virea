from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from virea_contracts import InstallationState
from virea_contracts.execution import ExecutionTargetSelection
from virea_motion_ir import CANONICAL211_PROFILE, CANONICAL211_SCHEMA

from ..dependencies import control_plane
from ..service import (
    REAL_ADAPTER_FAMILIES,
    ControlPlane,
    ExecutionTargetResolutionError,
)

router = APIRouter(prefix="/models", tags=["models"])


class InstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str
    accepted_license: bool = False
    apply: bool = False
    validation_prompt: str | None = Field(
        default=None,
        min_length=1,
        max_length=8000,
    )
    validation_seconds: float | None = Field(default=None, ge=1.0, le=90.0)
    validation_seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    validation_timeout: float | None = Field(default=None, gt=0.0, le=7200.0)
    artifact_roots: dict[str, str] = Field(default_factory=dict)
    artifact_revisions: dict[str, str] = Field(default_factory=dict)
    execution_target: ExecutionTargetSelection | None = None

    @model_validator(mode="after")
    def coherent_external_artifact_references(self) -> "InstallRequest":
        if set(self.artifact_roots) != set(self.artifact_revisions):
            raise ValueError(
                "artifact_roots and artifact_revisions must contain identical IDs"
            )
        for option, values in (
            ("artifact_roots", self.artifact_roots),
            ("artifact_revisions", self.artifact_revisions),
        ):
            if any(
                not identifier.strip() or not value.strip()
                for identifier, value in values.items()
            ):
                raise ValueError(f"{option} IDs and values must be non-empty")
        return self


def _reject_non_manifest_acceptance_request(request: InstallRequest, manifest) -> None:
    contract = manifest.production_acceptance
    if contract is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PRODUCTION_ACCEPTANCE_UNDECLARED",
                "model_id": request.model_id,
            },
        )
    expected = contract.request
    checks = {
        "validation_prompt": (
            request.validation_prompt,
            expected.input.get("prompt"),
        ),
        "validation_seconds": (
            request.validation_seconds,
            expected.parameters.get("seconds"),
        ),
        "validation_seed": (
            request.validation_seed,
            expected.parameters.get("seed"),
        ),
        "validation_timeout": (
            request.validation_timeout,
            contract.timeout_seconds,
        ),
    }
    mismatches = {
        field: {"requested": requested, "required": required}
        for field, (requested, required) in checks.items()
        if requested is not None and requested != required
    }
    if mismatches:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PRODUCTION_ACCEPTANCE_REQUEST_MISMATCH",
                "model_id": request.model_id,
                "mismatches": mismatches,
            },
        )


def _catalog_payload(manifest, control: ControlPlane) -> dict[str, Any]:
    payload = manifest.model_dump(mode="json")
    payload["result_target"] = {
        "representation_id": CANONICAL211_SCHEMA,
        "skeleton_id": CANONICAL211_PROFILE,
    }
    report = control.model_pool.verify_latest(manifest.model.id)
    latest_attempt = report.get("latest_attempt")
    installation_target = None
    installation_id = report.get("installation_id")
    if isinstance(installation_id, str) and installation_id:
        transaction = control.store.installation_transaction(installation_id)
        if transaction is not None:
            transaction_payload = json.loads(transaction["payload_json"])
            candidate = transaction_payload.get("execution_target")
            if isinstance(candidate, dict):
                installation_target = candidate
    installation = {
        "installation_id": installation_id,
        "state": report.get("state"),
        "installed": bool(report.get("installed")),
        "ready": bool(report.get("ready")),
        "locator": report.get("locator"),
        "latest_attempt": (
            {
                "installation_id": latest_attempt.get("installation_id"),
                "state": latest_attempt.get("state"),
            }
            if isinstance(latest_attempt, dict)
            else None
        ),
    }
    if installation_target is not None:
        installation["execution_target"] = installation_target
    payload["installation"] = installation
    return payload


def _pinned_target_from_compatibility(
    compatibility: dict[str, Any],
) -> ExecutionTargetSelection:
    target = compatibility.get("execution_target")
    resolved = target.get("resolved") if isinstance(target, dict) else None
    domain = resolved.get("execution_domain") if isinstance(resolved, dict) else None
    if not isinstance(domain, dict):
        raise RuntimeError("runtime compatibility did not resolve an execution domain")
    return ExecutionTargetSelection(
        execution_domain_id=domain.get("id"),
        runtime_variant_id=resolved.get("runtime_variant_id"),
        resource_profile_id=resolved.get("resource_profile_id"),
    )


@router.get("")
def models(control: ControlPlane = Depends(control_plane)) -> list[dict[str, Any]]:
    return [
        _catalog_payload(manifest, control)
        for manifest in control.catalog.manifests()
        if control.allow_test_models
        or manifest.model.adapter_family != "fake-root-translation"
    ]


@router.get("/{model_id}")
def model(
    model_id: str, control: ControlPlane = Depends(control_plane)
) -> dict[str, Any]:
    try:
        manifest = control.catalog.get(model_id)
        if (
            manifest.model.adapter_family == "fake-root-translation"
            and not control.allow_test_models
        ):
            raise KeyError(model_id)
        return _catalog_payload(manifest, control)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{model_id}/execution-options")
def execution_options(
    model_id: str, control: ControlPlane = Depends(control_plane)
) -> dict[str, Any]:
    try:
        return control.execution_options(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/install")
def install(
    request: InstallRequest, control: ControlPlane = Depends(control_plane)
) -> dict[str, Any]:
    try:
        manifest = control.catalog.get(request.model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if (
        manifest.model.adapter_family == "fake-root-translation"
        and not control.allow_test_models
    ):
        raise HTTPException(status_code=404, detail="model not found")
    if request.apply and (
        not manifest.runtime_variants
        or manifest.model.adapter_family not in REAL_ADAPTER_FAMILIES
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "model is cataloged but has no integrated VIREA runtime and "
                "real end-to-end acceptance runner"
            ),
        )
    if request.apply:
        _reject_non_manifest_acceptance_request(request, manifest)
    compatibility: dict[str, Any] | None = None
    if manifest.runtime_variants:
        try:
            compatibility = (
                control.runtime_compatibility(request.model_id)
                if request.execution_target is None
                else control.runtime_compatibility(
                    request.model_id,
                    execution_target=request.execution_target,
                )
            )
        except ExecutionTargetResolutionError as exc:
            raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    if not request.apply:
        return {
            "apply": False,
            "model_id": request.model_id,
            "status": manifest.model.status.value,
            "artifact_sources": [
                source.model_dump(mode="json") for source in manifest.artifacts
            ],
            "runtime_variants": [
                runtime.model_dump(mode="json") for runtime in manifest.runtime_variants
            ],
            "requires_acceptance": manifest.licenses.requires_acceptance,
            "external_artifact_root_ids": sorted(request.artifact_roots),
            "resource_admission": compatibility,
            "execution_target": (
                compatibility.get("execution_target")
                if compatibility is not None
                else None
            ),
        }
    assert compatibility is not None
    if not compatibility.get("can_build", compatibility["status"] == "ready"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RUNTIME_NOT_BUILDABLE",
                "model_id": request.model_id,
                "compatibility": compatibility,
            },
        )
    external_stage: dict[str, Any] = {}
    if request.artifact_roots or request.artifact_revisions:
        pinned_target = _pinned_target_from_compatibility(compatibility)
        try:
            normalized, domain_id, domain_paths = (
                control.prepare_external_artifact_roots(
                    request.model_id,
                    request.artifact_roots,
                    request.artifact_revisions,
                    execution_target=pinned_target,
                )
            )
        except ExecutionTargetResolutionError as exc:
            raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_EXTERNAL_ARTIFACT_REFERENCE",
                    "model_id": request.model_id,
                    "message": str(exc),
                },
            ) from exc
        external_stage = {
            "external_artifact_roots": normalized,
            "external_artifact_revisions": request.artifact_revisions,
            "external_execution_domain": domain_id,
            "external_domain_paths": domain_paths,
        }
    stage_options = dict(external_stage)
    if isinstance(compatibility.get("execution_target"), dict):
        stage_options["execution_target"] = compatibility["execution_target"]
    outcome = control.model_pool.stage_artifacts(
        request.model_id,
        accepted_license=request.accepted_license,
        **stage_options,
    )
    payload = {
        "installation_id": outcome.installation_id,
        "model_id": outcome.model_id,
        "state": outcome.state.value,
        "locator": outcome.locator,
        "diagnostics": list(outcome.diagnostics),
        "resource_admission": compatibility,
    }
    if outcome.state is not InstallationState.BUILDING_RUNTIME:
        return payload
    acceptance_diagnostics: list[str] = []
    try:
        acceptance = control.run_real_acceptance(outcome)
    except Exception as exc:
        acceptance = {
            "schema_version": "virea.installation_acceptance_evidence.v1.0.0",
            "kind": "installation_real_e2e",
            "contract": manifest.production_acceptance.model_dump(mode="json"),
            "job_id": None,
            "job_state": "FAILED",
            "installation_acceptance_succeeded": False,
            "production_e2e_succeeded": False,
            "result_id": None,
            "error_code": type(exc).__name__.upper(),
            "error_message": str(exc),
        }
        acceptance_diagnostics.append(
            f"real acceptance did not complete: {type(exc).__name__}: {exc}"
        )
    published = control.model_pool.publish_ready(
        outcome,
        acceptance=acceptance,
    )
    payload.update(
        {
            "state": published.state.value,
            "locator": published.locator,
            "diagnostics": [*published.diagnostics, *acceptance_diagnostics],
            "acceptance": acceptance,
        }
    )
    return payload
