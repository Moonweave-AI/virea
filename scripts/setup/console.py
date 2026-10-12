"""Dependency-free setup console: useful in a terminal and readable in log files."""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from virea.workspaces import workspace_links  # noqa: E402


def tint(value, color="38;2;189;184;209"):
    if sys.stdout.isatty() and not os.getenv("NO_COLOR"):
        return f"\033[{color}m{value}\033[0m"
    return str(value)


def banner():
    print(tint("\n  V I R E A   /   MOONWEAVE AI"), flush=True)
    print("  One foundation. Multiple embodiments.\n", flush=True)


def stage(step, message, total=8):
    bar = "=" * step + "." * max(0, total - step)
    print(tint(f"  [{bar}] {step}/{total}  ") + message, flush=True)


def studio_links(port):
    return workspace_links(port)


def ready(port):
    print(tint("\n  Your workspace is ready", "38;2;201;173;184"), flush=True)
    for name, url in studio_links(port).items():
        print(f"  {name:<19} {url}", flush=True)
    print(
        "\n  Live activity below mirrors Set Up in your browser. Ctrl+C stops this launcher.\n",
        flush=True,
    )


def read_api(port, path):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/onboarding{path}",
        headers={"X-Virea-Setup": "1"},
    )
    # Loopback setup must not inherit a corporate or model-download proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        request, timeout=3
    ) as response:
        return json.load(response)


def watch(port, process=None):
    cursor, disconnected, signatures = 0, False, {}
    while process is None or process.poll() is None:
        try:
            data = read_api(port, f"/activity?after={cursor}")
            if data.get("reset"):
                cursor = 0
                continue
            for event in data["events"]:
                clock = time.strftime("%H:%M:%S", time.localtime(event["time"]))
                label = (
                    "OK"
                    if event["status"] == "succeeded"
                    else "!"
                    if event["status"] == "failed"
                    else ">"
                )
                print(
                    f"  {clock} {label:2} {event['category']:<14} {event['message']}",
                    flush=True,
                )
            cursor = data["cursor"]
            snapshot = read_api(port, "")
            for job in snapshot.get("jobs", []):
                if job["status"] != "running":
                    continue
                size = job.get("total_bytes", 0)
                received = job.get("downloaded_bytes", 0)
                transfer = (
                    f" | {received / 1048576:.1f}/{size / 1048576:.1f} MiB"
                    if size
                    else ""
                )
                speed = job.get("bytes_per_second", 0)
                if speed:
                    transfer += f" | {speed / 1048576:.1f} MiB/s"
                signature = (
                    job["step"],
                    round(received / 1048576),
                    int(job.get("elapsed_seconds", 0) // 10),
                )
                if signatures.get(job["id"]) != signature:
                    print(
                        tint(
                            f"           [{job['step']}/{job['total_steps']}] {job['percent']}% {job['request']['recipe']}{transfer} | {job.get('elapsed_seconds', 0):.0f}s"
                        ),
                        flush=True,
                    )
                    signatures[job["id"]] = signature
            for job in read_api(port, "/model-deployments"):
                if job.get("status") != "running":
                    continue
                transfer = job.get("transfer") or {}
                received, total = (
                    transfer.get("completed_bytes", 0),
                    transfer.get("total_bytes"),
                )
                signature = (
                    job.get("stage"),
                    round(received / 1048576),
                    int(time.time() - job["started_at"]) // 10,
                )
                key = "model:" + job["model_id"]
                if signatures.get(key) != signature:
                    amount = (
                        f" | {received / 1048576:.1f}/{total / 1048576:.1f} MiB"
                        if total
                        else ""
                    )
                    speed = transfer.get("bytes_per_second")
                    if speed:
                        amount += f" | {speed / 1048576:.1f} MiB/s"
                    print(
                        tint(
                            f"           {job['model_id']} / {job.get('stage', 'detect')}{amount} | {time.time() - job['started_at']:.0f}s"
                        ),
                        flush=True,
                    )
                    signatures[key] = signature
            disconnected = False
        except (OSError, ValueError, KeyError):
            if not disconnected:
                print(
                    "  Reconnecting to local activity... Deployment continues on the server.",
                    flush=True,
                )
            disconnected = True
        time.sleep(1)
    return process.returncode if process else 0
