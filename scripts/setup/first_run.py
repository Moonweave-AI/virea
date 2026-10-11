"""Standard-library first run: no preinstalled Python packages, Node, pnpm or Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NODE_MAJOR = "24"
PNPM = "10.33.0"


def progress(step, message):
    print(f"[VIREA {step}/8 - {round(step / 8 * 100)}%] {message}", flush=True)


def node_asset(system, machine, version):
    arch = "arm64" if machine.lower() in {"arm64", "aarch64"} else "x64"
    target = {"Windows": "win", "Darwin": "darwin", "Linux": "linux"}[system]
    return f"node-{version}-{target}-{arch}" + (
        ".zip" if system == "Windows" else ".tar.gz"
    )


def download(url, target):
    temporary = target.with_suffix(target.suffix + ".download")
    with (
        urllib.request.urlopen(url, timeout=60) as source,
        temporary.open("wb") as output,
    ):
        total, count, last = int(source.headers.get("Content-Length", 0)), 0, 0
        while block := source.read(1024 * 1024):
            output.write(block)
            count += len(block)
            if total and count - last >= 5 * 1024 * 1024:
                print(
                    f"  Download {count // 1048576}/{total // 1048576} MiB ({round(count / total * 100)}%)",
                    flush=True,
                )
                last = count
    temporary.replace(target)


def ensure_node(root):
    tools = root / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    receipt = tools / "node.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        node, npm = Path(saved["node"]), Path(saved["npm"])
        if node.exists() and npm.exists():
            return node, npm
    with urllib.request.urlopen(
        f"https://nodejs.org/dist/latest-v{NODE_MAJOR}.x/SHASUMS256.txt", timeout=45
    ) as response:
        checksums = response.read().decode()
    version = next(
        line.split()[-1].split("-")[1]
        for line in checksums.splitlines()
        if "-win-x64.zip" in line
    )
    name = node_asset(platform.system(), platform.machine(), version)
    expected = next(
        line.split()[0] for line in checksums.splitlines() if line.split()[-1] == name
    )
    archive = tools / name
    download(f"https://nodejs.org/dist/{version}/{name}", archive)
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if expected != actual:
        raise ValueError("Node.js SHA256 mismatch. Retry the launcher.")
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as source:
            if any(
                not (tools / i.filename).resolve().is_relative_to(tools.resolve())
                for i in source.infolist()
            ):
                raise ValueError("Unsafe Node archive")
            source.extractall(tools)
        directory = tools / name.removesuffix(".zip")
        node, npm = (
            directory / "node.exe",
            directory / "node_modules/npm/bin/npm-cli.js",
        )
    else:
        with tarfile.open(archive) as source:
            source.extractall(tools, filter="data")
        directory = tools / name.removesuffix(".tar.gz")
        node, npm = (
            directory / "bin/node",
            directory / "lib/node_modules/npm/bin/npm-cli.js",
        )
    archive.unlink()
    receipt.write_text(
        json.dumps(
            {"node": str(node), "npm": str(npm), "version": version, "sha256": expected}
        ),
        encoding="utf-8",
    )
    return node, npm


def api_ready(port):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/health", timeout=2
        ) as response:
            if json.load(response).get("control_plane_ready") is not True:
                return False
        check = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1/onboarding", headers={"X-Virea-Setup": "1"}
        )
        with urllib.request.urlopen(check, timeout=2) as response:
            return json.load(response).get("schema_version") == "virea.onboarding.v1"
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root", type=Path, default=REPO / ".virea-runtime/portable"
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Start, check the setup API, then stop (for CI)",
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    root = args.data_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_relative_to(REPO) and not root.is_relative_to(REPO / ".virea-runtime"):
        parser.error(
            "Choose .virea-runtime inside the project, or a dedicated directory outside it"
        )
    url = f"http://127.0.0.1:{args.port}/app/setup.html"
    if not args.prepare_only and api_ready(args.port):
        print(f"Existing VIREA service: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError:
            parser.error(
                "The selected port is in use; use --port with another port. Existing services were preserved."
            )
    if shutil.disk_usage(root).free < 5 * 1024**3:
        parser.error(
            "At least 5 GiB free disk is required before downloading the base environment"
        )
    env = os.environ.copy()
    env["CI"] = "true"
    for key in ("PYTHONHOME", "PYTHONPATH", "UV_INTERNAL__PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(key, None)
    env.update(
        VIREA_HOME=str(root / "home"),
        VIREA_ALLOW_CHECKOUT_RUNTIME="1",
        UV_PROJECT_ENVIRONMENT=str(root / "environment"),
        UV_CACHE_DIR=str(root / "cache/uv"),
        UV_PYTHON_INSTALL_DIR=str(root / "tools/python"),
        HF_HOME=str(root / "home/cache/huggingface"),
        NPM_CONFIG_CACHE=str(root / "cache/npm"),
        PYTHONUTF8="1",
        PYTHONUNBUFFERED="1",
    )
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Use Start-VIREA.cmd / start-virea.sh to prepare uv first")

    def run(argv):
        subprocess.run([str(x) for x in argv], cwd=REPO, env=env, check=True)

    progress(2, "Preparing an isolated Python 3.12 environment...")
    run(
        [
            uv,
            "sync",
            "--python",
            "3.12",
            "--locked",
            "--all-packages",
            *(["--extra", "vrchat"] if os.name == "nt" else []),
        ]
    )
    progress(
        3, "Preparing Node.js from the official release, with SHA256 verification..."
    )
    node, npm = ensure_node(root)
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    progress(4, "Installing the pinned web toolchain...")
    # Invoke npm's JS entry directly; no .cmd shell quoting or global package installation.
    pnpm = [node, npm, "exec", "--yes", f"--package=pnpm@{PNPM}", "--", "pnpm"]
    run([*pnpm, "install", "--frozen-lockfile"])
    progress(5, "Building the setup wizard and Studio...")
    run([*pnpm, "--filter", "@virea/web", "build"])
    python = (
        root
        / "environment"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    progress(6, "Initializing local state and detecting the machine...")
    run([python, "-m", "virea_cli.main", "setup"])
    if args.prepare_only:
        progress(8, "Preparation complete. Run the launcher again to start VIREA.")
        return 0
    progress(7, "Starting the local service...")
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen(
        [
            str(python),
            "-m",
            "uvicorn",
            "virea_api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        cwd=REPO,
        env=env,
        **flags,
    )
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError(
                    "The API exited during startup; see the diagnostic output above"
                )
            if api_ready(args.port):
                progress(8, f"Ready: {url}")
                if args.smoke_test:
                    check = urllib.request.Request(
                        f"http://127.0.0.1:{args.port}/api/v1/onboarding",
                        headers={"X-Virea-Setup": "1"},
                    )
                    with urllib.request.urlopen(check, timeout=10) as response:
                        if (
                            json.load(response).get("schema_version")
                            != "virea.onboarding.v1"
                        ):
                            raise RuntimeError("Unexpected onboarding API identity")
                    return 0
                if not args.no_browser:
                    webbrowser.open(url)
                return process.wait()
            time.sleep(1)
        raise RuntimeError("The API did not become ready within 120 seconds")
    finally:
        if process.poll() is None:
            if os.name == "nt":
                # Windows TerminateProcess alone leaves model-service descendants running.
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    check=False,
                )
            else:
                # Uvicorn handles SIGTERM and awaits the deployment manager's shutdown.
                process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(
            f"Setup stopped: {error}\nDownloaded caches are retained. Correct the problem and run the launcher again.",
            flush=True,
        )
        raise SystemExit(1) from error
