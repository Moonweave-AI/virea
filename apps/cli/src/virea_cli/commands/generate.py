from __future__ import annotations

import json

from virea_api.service import ControlPlane
from virea_contracts.execution import ExecutionTargetSelection
from virea_contracts.job import JobRequest
from virea_core.paths import VireaPaths

from ..common import plugin_root, runtime_source_root


def run(args) -> int:
    interactive_progress = bool(getattr(args, "interactive_progress", False))
    reporter = getattr(args, "interactive_reporter", None)

    def emit(payload: object) -> None:
        if reporter is not None:
            reporter.result(payload)
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))

    def progress(stage: str, message: str) -> None:
        if reporter is not None:
            reporter.progress(stage, message)
        elif interactive_progress:
            print(f"[VIREA generate {stage}] {message}")

    control = ControlPlane(
        paths=VireaPaths.discover(args.virea_home),
        plugin_root=plugin_root(),
        runtime_source_root=runtime_source_root(),
    )
    try:
        model_id = args.model
        if model_id is None:
            ready = control.ready_real_model_ids()
            if not ready:
                emit(
                    {
                        "error": "NO_READY_REAL_MODEL",
                        "message": (
                            "no READY real model is installed; run 'virea model "
                            "install flood-diffusion-tiny --apply' or pass --model"
                        ),
                    }
                )
                return 2
            if len(ready) > 1:
                emit(
                    {
                        "error": "MODEL_SELECTION_REQUIRED",
                        "message": "multiple READY real models exist; pass --model",
                        "ready_models": list(ready),
                    }
                )
                return 2
            model_id = ready[0]
        manifest = control.catalog.get(model_id)
        if manifest.model.adapter_family == "fake-root-translation":
            emit(
                {
                    "error": "NON_REAL_MODEL_REJECTED",
                    "message": "the generate CLI accepts real model Workers only",
                }
            )
            return 2
        if not args.prompt.strip():
            emit(
                {
                    "error": "PROMPT_REQUIRED",
                    "message": "--prompt must be a non-empty string",
                }
            )
            return 2
        parameters = {
            "seconds": args.seconds,
            "fps": args.fps,
            "seed": args.seed,
        }
        if args.denoise_steps is not None:
            parameters["denoise_steps"] = args.denoise_steps
        execution_domain = getattr(args, "execution_domain", None)
        runtime_variant = getattr(args, "runtime_variant", None)
        resource_profile = getattr(args, "resource_profile", None)
        if execution_domain is None and any(
            value is not None for value in (runtime_variant, resource_profile)
        ):
            emit(
                {
                    "error": "EXECUTION_DOMAIN_REQUIRED_FOR_OVERRIDE",
                    "message": (
                        "--runtime and --resource-profile require --execution-domain"
                    ),
                }
            )
            return 2
        execution_target = (
            ExecutionTargetSelection(
                execution_domain_id=execution_domain,
                runtime_variant_id=runtime_variant,
                resource_profile_id=resource_profile,
            )
            if execution_domain is not None
            else None
        )
        request = JobRequest(
            model_id=model_id,
            task=args.task,
            input={"prompt": args.prompt.strip()},
            parameters=parameters,
            idempotency_key=args.idempotency_key,
            execution_target=execution_target,
        )
        try:
            progress("1/3", "Validating and submitting the selected model job...")
            job = control.submit(request, inference_timeout=args.timeout)
        except ValueError as exc:
            emit({"error": "INVALID_TIMEOUT", "message": str(exc)})
            return 2
        if job["state"] not in {"REJECTED", "FAILED"}:
            progress("2/3", "Running model inference in the selected Runtime...")
            job = control.wait(job["id"], timeout=args.timeout)
        progress(
            "3/3",
            (
                "Collecting Motion IR, skeleton, and VRM result artifacts..."
                if job["state"] == "SUCCEEDED"
                else "Collecting the final job state and actionable diagnostics..."
            ),
        )
        payload = {"job": job}
        result = control.store.result_for_job(job["id"])
        if result is not None:
            payload["result"] = json.loads(result["payload_json"])
        emit(payload)
        return 0 if job["state"] == "SUCCEEDED" else 2
    finally:
        control.close()
