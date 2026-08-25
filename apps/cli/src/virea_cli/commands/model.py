from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from virea_api.capabilities import model_capability
from virea_api.service import (
    ControlPlane,
    ExecutionTargetResolutionError,
    validate_inference_timeout,
)
from virea_contracts.execution import ExecutionTargetSelection
from virea_contracts.installation import InstallationState
from virea_core import StateStore, VireaPaths
from virea_model_pool import InstallOutcome, ModelCatalog, ModelPool
from virea_runtime import RuntimeBuildError

from ..common import plugin_root, registry_root, runtime_source_root
from ..retention import retention_report


def _emit(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _interactive_progress(args, stage: str, message: str) -> None:
    """Emit human progress only for the guided flow, preserving JSON CLI output."""

    reporter = getattr(args, "interactive_reporter", None)
    if reporter is not None:
        reporter.progress(stage, message)
    elif getattr(args, "interactive_progress", False):
        print(f"[VIREA install {stage}] {message}")


def _context(
    virea_home: str | Path | None,
) -> tuple[VireaPaths, ModelCatalog, ModelPool]:
    paths = VireaPaths.discover(virea_home)
    store = StateStore(paths)
    catalog = ModelCatalog.load(plugin_root())
    pool = ModelPool(paths, store, catalog)
    pool.sync_catalog()
    return paths, catalog, pool


def _summary(manifest) -> dict[str, Any]:
    return {
        "id": manifest.model.id,
        "status": manifest.model.status.value,
        "tasks": list(manifest.model.tasks),
        "adapter": manifest.model.adapter_family,
        "runtime_variants": [runtime.id for runtime in manifest.runtime_variants],
        "requires_acceptance": manifest.licenses.requires_acceptance,
        "capability": model_capability(manifest),
    }


def _outcome(outcome: InstallOutcome) -> dict[str, Any]:
    return {
        "installation_id": outcome.installation_id,
        "model_id": outcome.model_id,
        "state": outcome.state.value,
        "locator": outcome.locator,
        "diagnostics": list(outcome.diagnostics),
    }


def _installation_failure_next_action(acceptance: object) -> str:
    """Return one actionable retry instruction without exposing raw evidence."""

    error_code = (
        str(acceptance.get("error_code") or "") if isinstance(acceptance, dict) else ""
    )
    if error_code in {"INSUFFICIENT_MEMORY", "WORKER_OOM"}:
        repair = (
            "Close other RAM/VRAM-heavy programs before retrying / "
            "关闭其他占用内存或显存的程序后重试"
        )
    elif error_code in {
        "RUNTIME_NOT_BUILDABLE",
        "RUNTIME_NOT_READY",
        "WORKER_START_ERROR",
        "WORKER_START_FAILED",
    }:
        repair = (
            "Repair the Runtime issue named above before retrying / "
            "先修复上方指出的 Runtime 问题再重试"
        )
    else:
        repair = (
            "Review the acceptance error and Worker log named above, then retry / "
            "查看上方验收错误及对应 Worker 日志后重试"
        )
    return (
        f"{repair}. Run `uv run virea` again; verified downloads are reused and "
        "will not be downloaded again. / 再次运行 `uv run virea`；已验证下载会直接"
        "复用，不会重新下载。"
    )


def _acceptance_override_mismatches(args, manifest) -> dict[str, dict[str, Any]]:
    contracts = manifest.production_acceptance_contracts
    if not contracts:
        return {"production_acceptance": {"requested": None, "required": "declared"}}

    def required(getter):
        values = {
            contract.request.task: getter(contract)
            for contract in contracts
        }
        distinct = {json.dumps(value, sort_keys=True) for value in values.values()}
        return next(iter(values.values())) if len(distinct) == 1 else values

    checks = {
        "validation_prompt": (
            args.validation_prompt,
            required(lambda contract: contract.request.input.get("prompt")),
        ),
        "validation_seconds": (
            args.validation_seconds,
            required(lambda contract: contract.request.parameters.get("seconds")),
        ),
        "validation_seed": (
            args.validation_seed,
            required(lambda contract: contract.request.parameters.get("seed")),
        ),
        "validation_timeout": (
            args.validation_timeout,
            required(lambda contract: contract.timeout_seconds),
        ),
    }
    return {
        field: {"requested": requested, "required": required}
        for field, (requested, required) in checks.items()
        if requested is not None and requested != required
    }


def _declared_acceptance_payload(manifest) -> dict[str, Any] | None:
    if manifest.production_acceptance_suite is not None:
        return manifest.production_acceptance_suite.model_dump(mode="json")
    contracts = manifest.production_acceptance_contracts
    return contracts[0].model_dump(mode="json") if contracts else None


def _failed_acceptance_payload(
    manifest,
    exc: Exception,
    *,
    installation_id: str,
    artifact_identity: dict[str, str] | None,
) -> dict[str, Any]:
    contracts = manifest.production_acceptance_contracts
    if manifest.production_acceptance_suite is not None:
        return {
            "schema_version": "virea.installation_acceptance_suite_evidence.v1.0.0",
            "kind": "installation_real_e2e_suite",
            "installation_id": installation_id,
            "artifact_identity": artifact_identity,
            "model_id": manifest.model.id,
            "contract": manifest.production_acceptance_suite.model_dump(mode="json"),
            "tasks": [contract.request.task for contract in contracts],
            "task_acceptances": [],
            "installation_acceptance_succeeded": False,
            "production_e2e_succeeded": False,
            "outstanding_required_stages": [],
            "web_playback": {
                "passed": False,
                "status": "requires_external_browser_evidence",
            },
            "task_failures": [
                {
                    "task": contract.request.task,
                    "error_code": type(exc).__name__.upper(),
                    "error_message": str(exc),
                }
                for contract in contracts
            ],
        }
    return {
        "schema_version": "virea.installation_acceptance_evidence.v1.0.0",
        "kind": "installation_real_e2e",
        "installation_id": installation_id,
        "artifact_identity": artifact_identity,
        "contract": contracts[0].model_dump(mode="json") if contracts else None,
        "job_id": None,
        "job_state": "FAILED",
        "installation_acceptance_succeeded": False,
        "production_e2e_succeeded": False,
        "result_id": None,
        "error_code": type(exc).__name__.upper(),
        "error_message": str(exc),
    }
def _named_install_values(values: list[str], *, option: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        identifier, separator, payload = value.partition("=")
        identifier = identifier.strip()
        payload = payload.strip()
        if not separator or not identifier or not payload:
            raise ValueError(f"{option} requires ID=VALUE")
        if identifier in parsed:
            raise ValueError(f"{option} repeats artifact ID {identifier!r}")
        parsed[identifier] = payload
    return parsed


def _execution_target(args) -> ExecutionTargetSelection | None:
    domain = getattr(args, "execution_domain", None)
    runtime = getattr(args, "runtime_variant", None)
    profile = getattr(args, "resource_profile", None)
    if domain is None:
        if runtime is not None or profile is not None:
            raise ValueError(
                "--runtime and --resource-profile require --execution-domain"
            )
        return None
    return ExecutionTargetSelection(
        execution_domain_id=domain,
        runtime_variant_id=runtime,
        resource_profile_id=profile,
    )


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


def _install(args) -> int:
    reporter = getattr(args, "interactive_reporter", None)

    def emit(payload: object) -> None:
        if reporter is not None:
            reporter.result(payload)
        else:
            _emit(payload)

    paths, catalog, _ = _context(args.virea_home)
    manifest = catalog.get(args.model_id)
    _interactive_progress(
        args, "1/6", "Resolving the selected model, Runtime, and resources..."
    )
    try:
        execution_target = _execution_target(args)
    except ValueError as exc:
        emit(
            {
                "error": "EXECUTION_DOMAIN_REQUIRED_FOR_OVERRIDE",
                "model_id": args.model_id,
                "message": str(exc),
            }
        )
        return 2
    if manifest.model.adapter_family == "fake-root-translation":
        emit(
            {
                "error": "TEST_MODEL_DISABLED",
                "model_id": args.model_id,
                "message": "test-only models are unavailable from the production CLI",
            }
        )
        return 2
    try:
        external_roots = _named_install_values(
            list(args.artifact_root), option="--artifact-root"
        )
        external_revisions = _named_install_values(
            list(args.artifact_revision), option="--artifact-revision"
        )
    except ValueError as exc:
        emit(
            {
                "error": "INVALID_EXTERNAL_ARTIFACT_REFERENCE",
                "model_id": args.model_id,
                "message": str(exc),
            }
        )
        return 2
    plan: dict[str, Any] = {
        "apply": bool(args.apply),
        "model": _summary(manifest),
        "artifact_sources": [
            source.model_dump(mode="json") for source in manifest.artifacts
        ],
        "runtime_variants": [
            runtime.model_dump(mode="json") for runtime in manifest.runtime_variants
        ],
        "acceptance": {
            "kind": (
                "installation_real_e2e_suite"
                if manifest.production_acceptance_suite is not None
                else "installation_real_e2e"
            ),
            "contract": _declared_acceptance_payload(manifest),
            "primary_contract": (
                manifest.production_acceptance_contracts[0].model_dump(mode="json")
                if manifest.production_acceptance_contracts
                else None
            ),
            "web_playback": "separate_release_evidence_required",
        },
        "external_artifact_root_ids": sorted(external_roots),
        "execution_target": (
            execution_target.model_dump(mode="json")
            if execution_target is not None
            else None
        ),
    }
    if not args.apply:
        emit(plan)
        return 0
    capability = model_capability(manifest)
    if not capability["installable"]:
        plan["error"] = (
            "model is cataloged but has no real end-to-end acceptance runner"
        )
        plan["reasons"] = capability["reasons"]
        emit(plan)
        return 2

    if args.validation_timeout is not None:
        try:
            validate_inference_timeout(args.validation_timeout)
        except ValueError as exc:
            plan["error"] = "INVALID_VALIDATION_TIMEOUT"
            plan["message"] = str(exc)
            emit(plan)
            return 2
    mismatches = _acceptance_override_mismatches(args, manifest)
    if mismatches:
        plan["error"] = "PRODUCTION_ACCEPTANCE_REQUEST_MISMATCH"
        plan["mismatches"] = mismatches
        emit(plan)
        return 2

    control = ControlPlane(
        paths=paths,
        plugin_root=plugin_root(),
        runtime_source_root=runtime_source_root(),
    )
    try:
        _interactive_progress(
            args,
            "2/6",
            "Checking device resources and execution-domain admission...",
        )
        try:
            compatibility = (
                control.runtime_compatibility(args.model_id)
                if execution_target is None
                else control.runtime_compatibility(
                    args.model_id,
                    execution_target=execution_target,
                )
            )
        except ExecutionTargetResolutionError as exc:
            emit(
                {
                    "error": exc.code,
                    "model_id": args.model_id,
                    "message": str(exc),
                    "execution_options": list(exc.options),
                }
            )
            return 2
        plan["resource_admission"] = compatibility
        if not compatibility.get("can_build", compatibility["status"] == "ready"):
            emit(
                {
                    "error": "RUNTIME_NOT_BUILDABLE",
                    "model_id": args.model_id,
                    "compatibility": compatibility,
                }
            )
            return 2
        try:
            _interactive_progress(
                args,
                "3/6",
                "Checking required system tools inside the selected domain...",
            )
            resolved_target = (
                _pinned_target_from_compatibility(compatibility)
                if isinstance(compatibility.get("execution_target"), dict)
                else execution_target
            )
            control.preflight_runtime_build(
                args.model_id,
                execution_target=resolved_target,
            )
        except ExecutionTargetResolutionError as exc:
            emit(
                {
                    "error": exc.code,
                    "model_id": args.model_id,
                    "message": str(exc),
                    "execution_options": list(exc.options),
                }
            )
            return 2
        except (
            FileNotFoundError,
            NotImplementedError,
            OSError,
            RuntimeBuildError,
        ) as exc:
            _interactive_progress(
                args,
                "3/6",
                "System-tool preflight failed before model artifacts were staged.",
            )
            emit(
                {
                    "error": "RUNTIME_SYSTEM_DEPENDENCY_UNAVAILABLE",
                    "model_id": args.model_id,
                    "message": str(exc),
                    "resource_admission": compatibility,
                    "next_action": (
                        "Repair the named tool in the selected execution domain and "
                        "retry; no model artifact was staged by this failed preflight."
                    ),
                }
            )
            return 2
        _interactive_progress(
            args,
            "4/6",
            "Downloading, reusing, and verifying model artifacts...",
        )
        external_stage: dict[str, Any] = {}
        if external_roots or external_revisions:
            try:
                normalized, domain_id, domain_paths = (
                    control.prepare_external_artifact_roots(
                        args.model_id,
                        external_roots,
                        external_revisions,
                        execution_target=_pinned_target_from_compatibility(
                            compatibility
                        ),
                    )
                )
            except ExecutionTargetResolutionError as exc:
                emit(
                    {
                        "error": exc.code,
                        "model_id": args.model_id,
                        "message": str(exc),
                        "execution_options": list(exc.options),
                    }
                )
                return 2
            except ValueError as exc:
                plan["error"] = "INVALID_EXTERNAL_ARTIFACT_REFERENCE"
                plan["message"] = str(exc)
                emit(plan)
                return 2
            plan["external_artifact_execution_domain"] = domain_id
            external_stage = {
                "external_artifact_roots": normalized,
                "external_artifact_revisions": external_revisions,
                "external_execution_domain": domain_id,
                "external_domain_paths": domain_paths,
            }
        stage_options = dict(external_stage)
        if isinstance(compatibility.get("execution_target"), dict):
            stage_options["execution_target"] = compatibility["execution_target"]
        if reporter is not None:
            stage_options["progress"] = reporter.transfer
        outcome = control.model_pool.stage_artifacts(
            args.model_id,
            accepted_license=args.accepted_license,
            **stage_options,
        )
        if outcome.state is not InstallationState.BUILDING_RUNTIME:
            payload = _outcome(outcome)
            payload["resource_admission"] = compatibility
            emit(payload)
            return 2
        try:
            _interactive_progress(
                args,
                "5/6",
                "Building the isolated Runtime, loading the model, and running acceptance...",
            )
            acceptance = control.run_real_acceptance(outcome)
        except Exception as exc:
            try:
                artifact_identity = control.model_pool.acceptance_artifact_identity(
                    outcome
                )
            except (OSError, ValueError, json.JSONDecodeError):
                artifact_identity = None
            acceptance = _failed_acceptance_payload(
                manifest,
                exc,
                installation_id=outcome.installation_id,
                artifact_identity=artifact_identity,
            )
            failed = control.model_pool.publish_ready(
                outcome,
                acceptance=acceptance,
            )
            payload = _outcome(failed)
            payload["resource_admission"] = compatibility
            payload["acceptance"] = acceptance
            payload["diagnostics"].append(
                f"real acceptance did not complete: {type(exc).__name__}: {exc}"
            )
            payload["next_action"] = _installation_failure_next_action(acceptance)
            emit(payload)
            return 2
        _interactive_progress(
            args, "6/6", "Publishing the verified READY installation snapshot..."
        )
        ready = control.model_pool.publish_ready(
            outcome,
            acceptance=acceptance,
        )
        payload = _outcome(ready)
        payload["resource_admission"] = compatibility
        payload["acceptance"] = acceptance
        if ready.state is not InstallationState.READY:
            payload["next_action"] = _installation_failure_next_action(acceptance)
        emit(payload)
        return 0 if ready.state is InstallationState.READY else 2
    finally:
        control.close()


def _verify(args) -> int:
    _, catalog, pool = _context(args.virea_home)
    catalog.get(args.model_id)
    report = pool.verify_latest(args.model_id)
    _emit(report)
    return 0 if report["ready"] else 3


def _remove(args) -> int:
    _, catalog, pool = _context(args.virea_home)
    catalog.get(args.model_id)
    report = pool.verify_latest(args.model_id)
    if not args.apply:
        _emit({"apply": False, "action": "remove", **report})
        return 0
    removed = pool.remove_latest_ready(args.model_id)
    payload = _outcome(removed)
    payload["apply"] = True
    payload["recoverable_locator"] = payload.pop("locator")
    _emit(payload)
    return 0


def _repair(args) -> int:
    _, catalog, pool = _context(args.virea_home)
    catalog.get(args.model_id)
    report = pool.verify_latest(args.model_id)
    if report["ready"]:
        _emit({"action": "none", **report})
        return 0
    if not args.apply:
        _emit({"apply": False, "action": "install_fresh_snapshot", **report})
        return 3
    return _install(args)


def _gc(args) -> int:
    paths, _, pool = _context(args.virea_home)
    report = retention_report(
        paths,
        pool.store,
        dry_run=args.dry_run,
        older_than_hours=args.older_than_hours,
    )
    _emit(report)
    return 2 if report["failures"] else 0


def _bundle(args) -> int:
    files = sorted((registry_root() / "bundles").glob("*.yaml"))
    bundles = [yaml.safe_load(path.read_text(encoding="utf-8")) for path in files]
    if args.bundle_id is None:
        _emit(bundles)
        return 0
    for bundle in bundles:
        if bundle.get("id") == args.bundle_id:
            _emit(bundle)
            return 0
    raise KeyError(f"unknown model bundle: {args.bundle_id}")


def run(args) -> int:
    catalog = ModelCatalog.load(plugin_root())
    if args.model_command in {"list", "search"}:
        query = getattr(args, "query", "").strip().lower()
        rows = [
            _summary(manifest)
            for manifest in catalog.manifests()
            if manifest.model.adapter_family != "fake-root-translation"
            and (
                not query
                or query in manifest.model.id.lower()
                or query in manifest.model.display_name.lower()
                or query in " ".join(manifest.model.tasks).lower()
            )
        ]
        if args.json:
            _emit(rows)
        else:
            for row in rows:
                boundary = (
                    "VIREA-integrated"
                    if row["capability"]["virea_integrated"]
                    else "upstream-only"
                )
                print(
                    f"{row['id']:<30} {boundary:<18} "
                    f"{row['status']:<24} {','.join(row['tasks'])}"
                )
        return 0
    if args.model_command == "info":
        manifest = catalog.get(args.model_id)
        if manifest.model.adapter_family == "fake-root-translation":
            raise KeyError(
                f"model is test-only and unavailable from CLI: {args.model_id}"
            )
        _emit(manifest.model_dump(mode="json"))
        return 0
    if args.model_command in {"verify", "remove", "repair"}:
        manifest = catalog.get(args.model_id)
        if manifest.model.adapter_family == "fake-root-translation":
            _emit(
                {
                    "error": "TEST_MODEL_DISABLED",
                    "model_id": args.model_id,
                    "message": "test-only models are unavailable from the production CLI",
                }
            )
            return 2
    handlers = {
        "install": _install,
        "verify": _verify,
        "remove": _remove,
        "repair": _repair,
        "gc": _gc,
        "bundle": _bundle,
    }
    try:
        handler = handlers[args.model_command]
    except KeyError as exc:
        raise ValueError(f"unsupported model command: {args.model_command}") from exc
    return handler(args)
