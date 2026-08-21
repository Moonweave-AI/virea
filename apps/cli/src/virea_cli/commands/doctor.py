from __future__ import annotations

import json

from virea_bootstrap.detector import detect_machine
from virea_bootstrap.reporting import record_machine_report
from virea_core.paths import VireaPaths


def _json_field(payload: dict, key: str, fallback):
    raw = payload["tools"].get(key)
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _explanation(payload: dict) -> list[dict]:
    layers: list[dict] = []
    for accelerator in payload["accelerators"]:
        hardware = accelerator["status"]
        framework = accelerator["details"].get("framework_status", "unverified")
        if accelerator["kind"] == "cpu":
            readiness = "ready" if hardware == "available" else "not-ready"
        elif hardware == "unavailable" or framework == "not-ready":
            readiness = "not-ready"
        elif hardware == "available" and framework == "ready":
            readiness = "ready"
        else:
            readiness = "unknown"
        layers.append(
            {
                "kind": accelerator["kind"],
                "status": readiness,
                "hardware_status": hardware,
                "driver_status": "ready" if hardware == "available" else "unknown",
                "framework_status": framework,
                "model_status": "unknown",
                "model_reason": (
                    "a concrete runtime and installed model must be resolved separately"
                ),
                "probe": accelerator["probe"],
                "details": accelerator["details"],
            }
        )
    return layers


def _repair_plan(payload: dict) -> list[dict]:
    actions: list[dict] = []
    prerequisites = (
        ("uv", "install_uv", "uv is required to build isolated Python runtimes"),
        ("git", "install_git", "some pinned upstream sources require Git"),
        (
            "node",
            "install_node",
            "Node.js is required to build the Web/Viewer application",
        ),
        (
            "ffmpeg",
            "install_ffmpeg",
            "FFmpeg is required for encoded preview/video export",
        ),
    )
    for tool, action, reason in prerequisites:
        if not payload["tools"].get(tool):
            actions.append({"action": action, "automatic": False, "reason": reason})
    for accelerator in payload["accelerators"]:
        framework = accelerator["details"].get("framework_status")
        if accelerator["kind"] != "cpu" and framework != "ready":
            actions.append(
                {
                    "action": f"install_usable_{accelerator['kind']}_framework",
                    "automatic": False,
                    "reason": (
                        "hardware detection alone is insufficient; install a framework "
                        "build containing kernels for this compute architecture"
                    ),
                }
            )
    return actions


def run(args) -> int:
    paths = VireaPaths.discover(args.virea_home)
    report = detect_machine(paths)
    record_payload = report.model_dump(mode="json")
    payload = dict(record_payload)
    payload["environment_status"] = {
        "status": "ready" if payload["tools"].get("uv") else "not-ready",
        "scope": "bootstrap_only",
        "model_status": "unknown",
        "reason": (
            "model usability is only known after runtime resolution and real inference validation"
        ),
    }
    payload["python_candidates"] = _json_field(payload, "python_candidates", [])
    payload["wsl_distributions"] = _json_field(payload, "wsl_distributions", [])
    payload["cache_locations"] = _json_field(payload, "cache_locations", {})
    if args.explain:
        payload["capability_explanation"] = _explanation(payload)
    if args.repair_plan:
        payload["repair_plan"] = _repair_plan(payload)
    if args.record:
        record_machine_report(paths, report)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"VIREA {report.schema_version} / {report.report_id}")
        print(
            f"platform: {report.platform} {report.architecture} (WSL={report.is_wsl})"
        )
        print(f"python:   {report.python_version}")
        print(
            "status:   "
            f"bootstrap={payload['environment_status']['status']} model=unknown"
        )
        print(
            f"memory:   {report.memory_total_bytes or 'unknown'} bytes total, "
            f"{report.memory_available_bytes or 'unknown'} bytes available; "
            f"swap/pagefile={report.swap_free_bytes or 0}/"
            f"{report.swap_total_bytes or 0} bytes free/total"
        )
        print(
            f"storage:  {report.storage_free_bytes} bytes free at {report.storage_root}"
        )
        for accelerator in report.accelerators:
            free = accelerator.details.get("memory_free_bytes", "unknown")
            framework = accelerator.details.get("framework_status", "unverified")
            print(
                f"{accelerator.kind}: hardware={accelerator.status} "
                f"framework={framework} free_vram={free} {accelerator.name or ''}".rstrip()
            )
        for candidate in payload["python_candidates"]:
            print(
                "python-candidate: "
                f"python={candidate.get('python_status', 'unknown')} "
                f"{candidate.get('python_version', 'unknown')} "
                f"framework={candidate.get('framework_status', 'unknown')} "
                f"torch={candidate.get('torch_version', 'not-installed')} "
                f"source={candidate.get('source', 'unknown')}"
            )
        for warning in report.warnings:
            print(f"warning: {warning}")
        if args.explain:
            for layer in payload["capability_explanation"]:
                print(
                    "capability: "
                    f"{layer['kind']} status={layer['status']} "
                    f"hardware={layer['hardware_status']} "
                    f"driver={layer['driver_status']} "
                    f"framework={layer['framework_status']} model=unknown"
                )
        if args.repair_plan:
            if not payload["repair_plan"]:
                print("repair-plan: no detected bootstrap prerequisites are missing")
            for item in payload["repair_plan"]:
                print(f"repair-plan: {item['action']} (manual; {item['reason']})")
    return 0
