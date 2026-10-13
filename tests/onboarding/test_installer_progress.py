"""Installer progress must reach the observer while the child is still running."""

import os
import sys
import threading
from pathlib import Path

import pytest
from virea_bootstrap import process_progress as progress

from scripts.setup.console import progress_line


def test_uv_measured_download_and_rate(monkeypatch):
    clock = iter([10.0, 12.0])
    monkeypatch.setattr(progress.time, "monotonic", lambda: next(clock))
    parser = progress.InstallerProgress()
    first = parser.feed("\x1b[2Ktorch ━━━━━ 1.00 MiB/10.00 MiB\x1b[0m")
    second = parser.feed("torch ━━━━━━━━━━ 5.00 MiB/10.00 MiB")
    assert first["percent"] == 10
    assert second["file"] == "torch"
    assert second["percent"] == 50
    assert second["bytes_per_second"] == 2 * 1048576
    assert second["eta_seconds"] == 2
    assert "50.0%" in progress_line("CUDA", second)
    assert "5.0/10.0 MiB" in progress_line("CUDA", second)


@pytest.mark.parametrize(
    "line,phase,done,total",
    [
        ("Preparing packages... (2/8)", "prepare", 2, 8),
        ("[3/8] torch==2.7.1", "install", 3, 8),
        ("Installed 8 packages in 3.1s", "install", 8, 8),
        ("Progress: resolved 10, reused 2, downloaded 8, added 7", "install", 7, 10),
    ],
)
def test_package_counts(line, phase, done, total):
    event = progress.InstallerProgress().feed(line)
    assert (event["phase"], event["completed"], event["total"]) == (phase, done, total)
    assert event["percent"] == 100 * done / total


def test_unknown_total_is_not_a_fake_percentage():
    event = progress.InstallerProgress().feed("weights 42B/0B")
    assert event["percent"] is None
    assert "active" in progress.progress_text(event)
    assert progress.InstallerProgress().feed("Still resolving dependencies") is None


def test_terminal_secrets_are_redacted():
    assert (
        progress.clean_output(
            "token abcdefgh https://user:pass@host/file", ["abcdefgh"]
        )
        == "token [redacted] https://[redacted]@host/file"
    )


@pytest.mark.parametrize("terminal", [False, True])
def test_cr_progress_is_live_and_terminal_environment_is_scoped(tmp_path, terminal):
    acknowledged = tmp_path / "observed"
    child = tmp_path / "child.py"
    child.write_text(
        "import os,pathlib,time\n"
        f"assert bool(os.environ.get('RUST_LOG')) == {not terminal!r}\n"
        "print('torch 2MiB/8MiB', end='\\r', flush=True)\n"
        f"flag=pathlib.Path({str(acknowledged)!r})\n"
        "deadline=time.monotonic()+8\n"
        "while not flag.exists() and time.monotonic()<deadline: time.sleep(.02)\n"
        "assert flag.exists(), 'progress was buffered until exit'\n",
        encoding="utf-8",
    )
    env = dict(os.environ, RUST_LOG="warn")
    events = []

    def observe(event):
        events.append(event)
        acknowledged.touch()

    with progress.observe_installers(observe):
        progress.run_installer(
            [sys.executable, str(child)], env=env, terminal=terminal, timeout=20
        )
    assert env["RUST_LOG"] == "warn"
    assert events[0]["percent"] == 25


def test_silent_child_timeout_and_partial_utf8_failure():
    with pytest.raises(progress.InstallerError, match="timed out"):
        progress.run_installer(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            env=os.environ,
            timeout=0.2,
            terminal=False,
        )
    with pytest.raises(progress.InstallerError, match=r"failed \(7\)") as result:
        progress.run_installer(
            [
                sys.executable,
                "-c",
                "import sys;sys.stdout.buffer.write(bytes([0x82]));sys.exit(7)",
            ],
            env=os.environ,
            terminal=False,
        )
    assert "\ufffd" in str(result.value)


def test_precancel_does_not_launch(tmp_path):
    event = threading.Event()
    event.set()
    artifact = tmp_path / "must-not-exist"
    with pytest.raises(progress.InstallerError, match="cancelled"):
        progress.run_installer(
            [
                sys.executable,
                "-c",
                f"from pathlib import Path;Path({str(artifact)!r}).touch()",
            ],
            env=os.environ,
            cancel_event=event,
        )
    assert not Path(artifact).exists()


def test_console_keeps_working_in_legacy_windows_output(monkeypatch):
    import io

    from scripts.setup.console import LiveProgress

    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="gbk", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    display = LiveProgress()
    display.log("✓ built in 1s")
    display.update({"phase": "install", "completed": 2, "total": 4, "percent": 50})
    stream.flush()
    assert b"built in 1s" in buffer.getvalue()
    assert b"50.0%" in buffer.getvalue()
