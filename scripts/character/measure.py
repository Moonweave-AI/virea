"""Observe a live rendered character session; never manufacture benchmark passes."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

import httpx


async def gpu_sample() -> list[dict]:
    try:
        process = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=uuid,name,memory.total,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=5)
        samples = []
        for line in output.decode().splitlines():
            uuid, name, total, used, utilization = [
                value.strip() for value in line.split(",")
            ]
            samples.append(
                {
                    "uuid": uuid,
                    "name": name,
                    "total_mib": int(total),
                    "used_mib": int(used),
                    "utilization_percent": int(utilization),
                }
            )
        return samples
    except (OSError, ValueError, asyncio.TimeoutError):
        if "process" in locals() and process.returncode is None:
            process.kill()
            await process.wait()
        return []


async def measure(args) -> dict:
    started = monotonic()
    samples = []
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        while monotonic() - started < args.seconds:
            response = await client.get(
                f"{args.url.rstrip('/')}/api/v1/characters/{args.session}"
            )
            response.raise_for_status()
            state = response.json()
            samples.append(
                {
                    "elapsed_seconds": monotonic() - started,
                    "status": state["status"],
                    "metrics": state["metrics"],
                    "gpu": await gpu_sample(),
                }
            )
            await asyncio.sleep(1)
    used = [gpu["used_mib"] for sample in samples for gpu in sample["gpu"]]
    return {
        "schema_version": "virea.character_measurement.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "session_id": args.session,
        "samples": samples,
        "system_gpu_peak_used_mib": max(used) if used else None,
        "scope": "whole-device sampled usage, including desktop and other processes",
        "renderer_concurrency": "must be independently verified with browser evidence",
        "native_history_verified": False,
        "twelve_gib_verified": False,
        "target_first_expression_seconds": 2.0,
        "target_rtf": 0.7,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--session", required=True)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("measurement duration must be 1–3600 seconds")
    report = asyncio.run(measure(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(args.output)
