import os
from types import SimpleNamespace

import pytest
import virea_runtime.process_identity as identity


@pytest.mark.parametrize(
    "value", ['"C:\\Program Files\\Python\\python.exe" -m app', ""]
)
def test_self_command_line_does_not_spawn_powershell(monkeypatch, value):
    def command_line():
        return value

    monkeypatch.setattr(
        identity.ctypes,
        "WinDLL",
        lambda *args, **kwargs: SimpleNamespace(GetCommandLineW=command_line),
        raising=False,
    )

    def forbidden(*args, **kwargs):
        pytest.fail("self-inspection must not spawn PowerShell")

    monkeypatch.setattr(identity.subprocess, "run", forbidden)
    if value:
        assert identity._windows_command_line(os.getpid()) == value
    else:
        with pytest.raises(identity.ProcessInspectionError, match="no command line"):
            identity._windows_command_line(os.getpid())


@pytest.mark.skipif(os.name != "nt", reason="real Windows kernel API")
def test_real_windows_self_identity_keeps_executable_and_creation_token():
    result = identity.inspect_process(os.getpid())
    assert result is not None
    assert result.pid == os.getpid()
    assert result.creation_token
    assert result.argv
    assert identity.canonical_executable(result.argv[0]) == result.executable
