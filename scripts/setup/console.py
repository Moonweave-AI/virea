"""Dependency-free setup console: useful in a terminal and readable in log files."""

import importlib.util
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from virea.workspaces import workspace_links  # noqa: E402

# This file also runs before the workspace environment has been installed.
_progress_spec = importlib.util.spec_from_file_location(
    "virea_first_run_progress",
    Path(__file__).resolve().parents[2]
    / "packages/bootstrap/src/virea_bootstrap/process_progress.py",
)
installer_progress = importlib.util.module_from_spec(_progress_spec)
_progress_spec.loader.exec_module(installer_progress)


def progress_line(label, event):
    return f"  {label}  {installer_progress.progress_text(event)}"


class LiveProgress:
    """One live terminal line, with durable readable output when redirected."""

    def __init__(self):
        # Some Windows shells redirect through a legacy code page. Installer
        # glyphs must never turn a successful deployment into an encoding error.
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        self.active = False
        self.last = None

    def finish(self):
        if self.active:
            print(flush=True)
            self.active = False

    def log(self, line):
        self.finish()
        print("  " + line, flush=True)

    def update(self, event, label=""):
        line = progress_line(label, event)
        if sys.stdout.isatty():
            print("\r\033[2K" + tint(line), end="", flush=True)
            self.active = True
        elif line != self.last:
            print(line, flush=True)
        self.last = line


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
                if event.get(
                    "kind"
                ) == "output" and installer_progress.InstallerProgress().feed(
                    event["message"]
                ):
                    continue  # The measured bar below represents this output.
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
                if job.get("process"):
                    detail = job["process"]
                    signature = (
                        detail.get("phase"),
                        detail.get("file"),
                        detail.get("percent"),
                        detail.get("completed_bytes"),
                    )
                    if signatures.get(job["id"]) != signature:
                        print(
                            tint(progress_line(job["request"]["recipe"], detail)),
                            flush=True,
                        )
                        signatures[job["id"]] = signature
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
                if job.get("process"):
                    detail = job["process"]
                    key = "model:" + job["model_id"]
                    signature = (
                        detail.get("phase"),
                        detail.get("file"),
                        detail.get("percent"),
                        detail.get("completed_bytes"),
                    )
                    if signatures.get(key) != signature:
                        print(tint(progress_line(job["model_id"], detail)), flush=True)
                        signatures[key] = signature
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
