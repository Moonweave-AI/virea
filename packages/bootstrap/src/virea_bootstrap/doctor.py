from __future__ import annotations

import argparse
import json
from pathlib import Path

from virea_core.paths import VireaPaths

from .detector import detect_machine
from .reporting import record_machine_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="virea-doctor")
    parser.add_argument(
        "--json", action="store_true", help="emit the machine report as JSON"
    )
    parser.add_argument("--virea-home", type=Path, default=None)
    parser.add_argument(
        "--record",
        action="store_true",
        help="record latest.json and an append-only versioned report under VIREA_HOME",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    paths = VireaPaths.discover(args.virea_home)
    report = detect_machine(paths)
    payload = report.model_dump(mode="json")
    if args.record:
        record_machine_report(paths, report)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"VIREA machine report {report.report_id}")
    print(f"  platform: {report.platform} {report.architecture} (WSL={report.is_wsl})")
    print(f"  Python:   {report.python_version}")
    print(f"  RAM:      {report.memory_total_bytes or 'unknown'} bytes")
    print(f"  available RAM: {report.memory_available_bytes or 'unknown'} bytes")
    print(
        f"  swap/pagefile: {report.swap_free_bytes or 0} bytes free / "
        f"{report.swap_total_bytes or 0} bytes total"
    )
    print(f"  free:     {report.storage_free_bytes} bytes at {report.storage_root}")
    for accelerator in report.accelerators:
        framework = accelerator.details.get("framework_status", "unverified")
        free = accelerator.details.get("memory_free_bytes", "unknown")
        print(
            f"  {accelerator.kind}: hardware={accelerator.status} "
            f"framework={framework} free_vram={free} {accelerator.name or ''}".rstrip()
        )
    print("  model:    unknown (resolve a concrete runtime and run real validation)")
    for warning in report.warnings:
        print(f"  warning: {warning}")


if __name__ == "__main__":
    main()
