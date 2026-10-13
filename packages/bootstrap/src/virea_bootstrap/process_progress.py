"""Stream installer diagnostics and measured progress, even outside a terminal.

This module has no workspace imports: the first-run launcher can load it before
the project environment exists. Windows uses ConPTY; POSIX uses a PTY. Commands
remain argument arrays and cancellation terminates the entire process group.
"""

from __future__ import annotations

import codecs
import contextlib
import contextvars
import os
import queue
import re
import signal
import subprocess
import threading
import time
from collections import deque

_sink = contextvars.ContextVar("installer_progress_sink", default=None)
_ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")
_size = re.compile(r"([\d.]+)\s*([KMGT]?i?B)\s*/\s*([\d.]+)\s*([KMGT]?i?B)")
_count = re.compile(r"[\[(](\d+)\s*/\s*(\d+)[\])]")


@contextlib.contextmanager
def observe_installers(callback):
    token = _sink.set(callback)
    try:
        yield
    finally:
        _sink.reset(token)


def clean_output(text, secrets=()):
    text = _ansi.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    for secret in sorted((s for s in secrets if len(s) >= 4), key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text)
    return re.sub(r"(?i)\b(?:sk-|hf_)[a-z0-9_-]{12,}", "[redacted]", text).strip()


def _bytes(value, unit):
    power = "BKMGT".index(unit[0])
    return round(float(value) * (1024 if "i" in unit else 1000) ** power)


class InstallerProgress:
    """Parse uv/pip download bytes and uv/pnpm package counts, never fake time %."""

    def __init__(self):
        self.samples = {}
        self.phase = "resolve"

    def feed(self, line):
        line = clean_output(line)
        if not line:
            return None
        now = time.monotonic()
        size = _size.search(line)
        if size:
            received, total = _bytes(*size.group(1, 2)), _bytes(*size.group(3, 4))
            file = re.sub(r"[-━─█░▓▒\s]+$", "", line[: size.start()]).strip()
            # uv puts the package name before the bar. Pip can omit it.
            file = file.split()[0] if file else "Download"
            history = self.samples.setdefault(file, deque(maxlen=80))
            if history and received < history[-1][1]:
                history.clear()
            history.append((now, received))
            while len(history) > 2 and history[1][0] < now - 5:
                history.popleft()
            elapsed = now - history[0][0]
            rate = max(0, (received - history[0][1]) / elapsed) if elapsed else 0
            self.phase = "download"
            return dict(
                phase=self.phase,
                file=file,
                completed_bytes=received,
                total_bytes=total,
                percent=min(100, received / total * 100) if total else None,
                bytes_per_second=round(rate),
                eta_seconds=round((total - received) / rate)
                if rate > 0 and total > received
                else None,
            )
        lower = line.lower()
        count = _count.search(line)
        if count:
            done, total = map(int, count.groups())
            phase = "prepare" if "prepar" in lower else "install"
            self.phase = phase
            return dict(
                phase=phase,
                completed=done,
                total=total,
                percent=100 * done / total if total else None,
                file=line[count.end() :].strip(),
            )
        pnpm = re.search(
            r"Progress: resolved (\d+), reused (\d+), downloaded (\d+), added (\d+)",
            line,
        )
        if pnpm:
            resolved, reused, downloaded, added = map(int, pnpm.groups())
            return dict(
                phase="install",
                completed=added,
                total=resolved,
                reused=reused,
                downloaded=downloaded,
                percent=100 * added / resolved if resolved else None,
            )
        for prefix, phase in (
            ("Resolved ", "resolve"),
            ("Prepared ", "prepare"),
            ("Installed ", "install"),
            ("Audited ", "reuse"),
        ):
            match = re.match(prefix + r"(\d+) packages?", line)
            if match:
                total = int(match[1])
                self.phase = phase
                return dict(phase=phase, completed=total, total=total, percent=100)
        return None


class InstallerError(RuntimeError):
    pass


def progress_text(event, width=24):
    value = event.get("percent")
    filled = round(max(0, min(100, value)) * width / 100) if value is not None else 0
    bar = "=" * filled + "-" * (width - filled)
    label = f"{value:5.1f}%" if value is not None else " active"
    amount = ""
    if event.get("total_bytes"):
        amount = f" {event.get('completed_bytes', 0) / 1048576:.1f}/{event['total_bytes'] / 1048576:.1f} MiB"
    elif event.get("total"):
        amount = f" [{event.get('completed', 0)}/{event['total']} packages]"
    rate = event.get("bytes_per_second", 0)
    if rate:
        amount += f" {rate / 1048576:.1f} MiB/s"
    if event.get("eta_seconds") is not None:
        amount += f" ~{event['eta_seconds']}s remaining"
    return f"[{bar}] {label} {event.get('phase', 'install')} {event.get('file', '')}{amount}".strip()


def run_installer(
    argv,
    *,
    env,
    cwd=None,
    timeout=3600,
    cancel_event=None,
    on_line=None,
    on_progress=None,
    terminal=True,
):
    """Run synchronously, draining output on a bounded reader thread.

    Callbacks execute in the caller's thread. A silent child is still cancellable
    and times out. Only installer child environments lose RUST_LOG: uv interprets
    any value of that variable as a request to hide its progress bars.
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if cancel_event is not None and cancel_event.is_set():
        raise InstallerError("Installation cancelled")
    command = list(map(str, argv))
    environment = dict(env)
    environment.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if terminal:
        environment.pop("RUST_LOG", None)
        environment.pop("UV_NO_PROGRESS", None)
        environment.pop("NO_COLOR", None)
        environment["TERM"] = "xterm-256color"
        environment["COLUMNS"] = "160"
    secrets = [
        v
        for k, v in environment.items()
        if any(s in k.upper() for s in ("KEY", "TOKEN", "PASSWORD", "SECRET"))
    ]
    callback = on_progress or _sink.get()
    parser, tail = InstallerProgress(), deque(maxlen=80)
    messages = queue.Queue(maxsize=512)
    stopped = threading.Event()
    master = None
    windows_pty = terminal and os.name == "nt"
    if windows_pty:
        from winpty import PtyProcess

        process = PtyProcess.spawn(
            command,
            cwd=str(cwd) if cwd else None,
            env=environment,
            dimensions=(48, 160),
        )

        def read():
            return process.read(8192)

        alive = process.isalive
    else:
        if terminal:
            import pty

            master, slave = pty.openpty()
            # A fixed width makes installer rows complete instead of wrapping.
            import fcntl
            import struct
            import termios

            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 48, 160, 0, 0))
            output = slave
        else:
            output = subprocess.PIPE
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except BaseException:
            if master is not None:
                os.close(master)
            raise
        finally:
            if terminal:
                os.close(slave)

        def read():
            return (
                os.read(master, 8192)
                if master is not None
                else process.stdout.read1(8192)
            )

        def alive():
            return process.poll() is None

    def drain():
        try:
            while not stopped.is_set():
                block = read()
                if not block:
                    break
                while not stopped.is_set():
                    try:
                        messages.put(block, timeout=0.1)
                        break
                    except queue.Full:
                        pass
        except (EOFError, OSError):
            pass
        finally:
            while not stopped.is_set():
                try:
                    messages.put(None, timeout=0.1)
                    break
                except queue.Full:
                    pass

    def stop():
        if not alive():
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
                check=False,
            )
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)

    last_publish = [0.0, None]

    def emit(line):
        clean = clean_output(line, secrets)
        if not clean:
            return
        event = parser.feed(clean)
        if not event:
            # Tools without a measurable total still expose their actual operation.
            phases = {
                "resolving": "resolve",
                "downloading": "download",
                "building": "build",
                "preparing": "prepare",
                "installing": "install",
                "unpacking": "extract",
                "extracting": "extract",
                "using": "resolve",
            }
            first = clean.split()[0].lower()
            if first in phases:
                event = dict(phase=phases[first], percent=None, file=clean)
        if event:
            key = (event["phase"], event.get("file"))
            now = time.monotonic()
            if (
                key == last_publish[1]
                and now - last_publish[0] < 0.2
                and event.get("percent") != 100
            ):
                return
            last_publish[:] = [now, key]
            if callback:
                callback(dict(event, message=clean, updated_at=time.time()))
        if not tail or tail[-1] != clean:
            tail.append(clean)
            if on_line:
                on_line(clean)

    reader = threading.Thread(target=drain, daemon=True, name="virea-installer-output")
    reader.start()
    decoder, pending = codecs.getincrementaldecoder("utf-8")("replace"), ""
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise InstallerError("Installation cancelled")
            if time.monotonic() >= deadline:
                raise InstallerError(f"Installation timed out after {timeout:g}s")
            try:
                block = messages.get(timeout=0.1)
            except queue.Empty:
                continue
            if block is None:
                emit(pending + decoder.decode(b"", final=True))
                break
            pending += block if isinstance(block, str) else decoder.decode(block)
            lines = re.split(r"[\r\n]", pending)
            pending = lines.pop()
            for line in lines:
                emit(line)
            if len(pending) > 32768:
                emit(pending)
                pending = ""
        code = (
            process.exitstatus
            if windows_pty
            else process.wait(timeout=max(0.1, deadline - time.monotonic()))
        )
        if code != 0:
            raise InstallerError(
                f"Installer failed ({code})\n" + "\n".join(tail)[-4000:]
            )
        return code
    finally:
        stopped.set()
        stop()
        if windows_pty:
            process.close()
        elif master is not None:
            os.close(master)
        elif process.stdout:
            process.stdout.close()
        reader.join(timeout=2)
