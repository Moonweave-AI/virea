"""Exercise the real PowerShell entry point without starting a game or logging in."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PWSH = shutil.which("pwsh")
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/vrchat/start_ai_client.ps1"
pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell is not installed")


def run_launcher(
    tmp_path, *, launcher=True, profile=2, existing="", send_port=19010, vr=False
):
    game = tmp_path / "VRChat.exe"
    game.touch()
    if launcher:
        (tmp_path / "launch.exe").touch()
    env = dict(os.environ, VIREA_TEST_SCRIPT=str(SCRIPT), VIREA_TEST_GAME=str(game))
    env["VIREA_TEST_EXISTING"] = existing
    # Stub OS boundaries, preserving actual script validation and argument building.
    command = (
        r"""
function Get-NetUDPEndpoint { param($LocalPort, $ErrorAction) }
function Get-CimInstance {
    param($ClassName, $Filter)
    if ($env:VIREA_TEST_EXISTING) {
        [pscustomobject]@{CommandLine=$env:VIREA_TEST_EXISTING; ProcessId=42}
    }
}
function Start-Process {
    param($FilePath, $WorkingDirectory, $ArgumentList, [switch]$PassThru)
    Write-Output ('LAUNCH_JSON:' + (@{file=$FilePath; cwd=$WorkingDirectory; args=$ArgumentList} | ConvertTo-Json -Compress))
    [pscustomobject]@{Id=100}
}
try {
    & $env:VIREA_TEST_SCRIPT -VRChatExe $env:VIREA_TEST_GAME -Profile PROFILE -SendPort PORT VR_ARG
} catch { Write-Output $_.Exception.Message; exit 1 }
""".replace("PROFILE", str(profile))
        .replace("PORT", str(send_port))
        .replace("VR_ARG", "-VR" if vr else "")
    )
    # The launcher output is captured by the script's $process assignment, so
    # inspect its output from a separate file at the mocked OS boundary instead.
    record = tmp_path / "launch.json"
    env["VIREA_TEST_RECORD"] = str(record)
    command = command.replace(
        "Write-Output ('LAUNCH_JSON:' + (@{file=$FilePath; cwd=$WorkingDirectory; args=$ArgumentList} | ConvertTo-Json -Compress))",
        "@{file=$FilePath; cwd=$WorkingDirectory; args=$ArgumentList} | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:VIREA_TEST_RECORD",
    )
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result, json.loads(
        record.read_text(encoding="utf-8-sig")
    ) if record.exists() else None


def test_online_launch_uses_official_bootstrapper_and_isolated_ports(tmp_path):
    result, record = run_launcher(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(record["file"]).name == "launch.exe"
    assert record["cwd"] == str(tmp_path)
    assert "--profile=2" in record["args"]
    assert "--osc=19010:127.0.0.1:19011" in record["args"]
    assert "--no-vr" in record["args"]


def test_missing_bootstrapper_never_falls_back_to_offline_game(tmp_path):
    result, record = run_launcher(tmp_path, launcher=False)
    assert result.returncode == 1
    assert "official launch.exe is missing" in result.stdout
    assert record is None


def test_vr_launch_preserves_profile_and_ports_without_forcing_desktop(tmp_path):
    result, record = run_launcher(tmp_path, profile=1, send_port=19000, vr=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--no-vr" not in record["args"]
    assert "--profile=1" in record["args"]
    assert "--osc=19000:127.0.0.1:19011" in record["args"]
    assert Path(record["file"]).name == "launch.exe"


@pytest.mark.parametrize(
    "existing,profile",
    [
        ('"VRChat.exe" "--profile=2"', 2),
        ('"VRChat.exe" --no-vr', 0),
    ],
)
def test_running_profile_is_preserved(tmp_path, existing, profile):
    result, record = run_launcher(tmp_path, existing=existing, profile=profile)
    assert result.returncode == 1
    assert "already running" in result.stdout
    assert record is None


def test_observer_port_is_rejected(tmp_path):
    result, record = run_launcher(tmp_path, send_port=9000)
    assert result.returncode == 1
    assert "9000/9001 belong to the observer" in result.stdout
    assert record is None
