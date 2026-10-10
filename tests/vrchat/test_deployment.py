"""Deployment boundaries: full body configuration and the real launch wrapper."""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import numpy as np
import pytest

from virea.vrchat.client_query import ClientQuery
from virea.vrchat.contracts import BridgeConfig
from virea.vrchat.mapping import tracker_messages
from virea.vrchat.osc import decode, message
from virea.vrchat.transport import OSCTransport


def test_prelogin_avatar_404_preserves_verified_endpoint_but_not_identity():
    config = BridgeConfig(mode="generated_vr", avatar_id="avtr_previous")
    transport = OSCTransport(config)
    query = ClientQuery(config, transport.protocol)
    transport.monitor = query

    def response(request):
        if request.url.path == "/":
            return httpx.Response(
                200,
                json={
                    "NAME": "VRChat-Client-test",
                    "OSC_IP": "127.0.0.1",
                    "OSC_PORT": config.send_port,
                    "OSC_TRANSPORT": "UDP",
                },
            )
        return httpx.Response(404, text="OSC Path not found")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            query.apply(await query.read(client, 12345), 42, 12345)

    asyncio.run(run())
    assert transport.protocol.query_status["state"] == "awaiting_avatar"
    assert query.verified
    assert not transport.ready()[0]


def test_prelogin_404_does_not_bypass_client_port_validation():
    config = BridgeConfig(mode="generated_vr")
    query = ClientQuery(config, OSCTransport(config).protocol)

    def response(request):
        return httpx.Response(
            200,
            json={
                "NAME": "VRChat-Client-test",
                "OSC_IP": "127.0.0.1",
                "OSC_PORT": 9000,
                "OSC_TRANSPORT": "UDP",
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            with pytest.raises(ValueError, match="dedicated AI port"):
                await query.read(client, 12345)

    asyncio.run(run())
    assert not query.verified


def test_generated_defaults_transmit_all_eight_body_targets():
    config = BridgeConfig(mode="generated_vr")
    root = np.array([0.0, 1.0, 0.0])
    messages = tracker_messages(root, {}, config, root)
    addresses = {address for packet in messages for address, _ in decode(packet)}
    assert addresses == {
        f"/tracking/trackers/{index}/{kind}"
        for index in range(1, 9)
        for kind in ("position", "rotation")
    }
    assert config.capabilities()["requires_fbt_calibration"]
    assert not config.capabilities()["exact_joint_playback"]
    assert len(config.capabilities()["body_target_bones"]) == 8


def test_generated_mode_cannot_silently_drop_arms_knees_and_chest():
    with pytest.raises(ValueError, match="all eight body targets"):
        BridgeConfig(
            mode="generated_vr", tracker_bones=("hips", "leftFoot", "rightFoot")
        )
    assert BridgeConfig(mode="vr_trackers").tracker_bones == (
        "hips",
        "leftFoot",
        "rightFoot",
    )


def test_full_body_gate_waits_for_calibration_and_closes_on_tracking_loss():
    transport = OSCTransport(BridgeConfig(mode="generated_vr", avatar_id="avtr_ai"))
    feedback = transport.protocol
    source = ("127.0.0.1", 19000)
    feedback.datagram_received(message("/avatar/change", "avtr_ai"), source)
    feedback.datagram_received(message("/avatar/parameters/VRMode", 1), source)
    for tracking in (0, 1, 2, 3, 4, 5):
        feedback.datagram_received(
            message("/avatar/parameters/TrackingType", tracking), source
        )
        assert not transport.ready()[0]
        # This exception is exclusively for the human-operated calibration rig.
        assert transport.ready(require_full_body=False)[0]
    feedback.datagram_received(message("/avatar/parameters/TrackingType", 6), source)
    assert transport.ready()[0]
    feedback.datagram_received(message("/avatar/parameters/TrackingType", 3), source)
    assert not transport.ready()[0]
    feedback.datagram_received(message("/avatar/change", "avtr_other"), source)
    assert not transport.ready(require_full_body=False)[0]


def test_prelogin_client_is_found_but_cannot_arm_autonomous_motion():
    transport = OSCTransport(BridgeConfig(mode="generated_vr", avatar_id="avtr_ai"))
    query = ClientQuery(transport.config, transport.protocol)
    transport.monitor = query
    transport.protocol.datagram_received(
        message("/avatar/change", "avtr_ai"), ("127.0.0.1", 1)
    )
    query.apply({"CONTENTS": {}}, 42, 12345)
    assert transport.protocol.query_status["state"] == "awaiting_avatar"
    assert transport.protocol.query_status["pid"] == 42
    assert transport.protocol.values == {}
    assert not transport.ready()[0]
    assert not transport.ready(require_full_body=False)[0]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell is not installed")
@pytest.mark.parametrize(
    "configured_vr,override,expected_vr",
    [
        (True, "", True),
        (False, "-VR", True),
        (True, "-VR:$false", False),
    ],
)
def test_stack_launcher_preserves_the_selected_vr_mode(
    tmp_path, configured_vr, override, expected_vr
):
    # Run unchanged production scripts in an isolated project, stubbing only OS
    # boundaries. A dropped -VR at either script boundary must fail this check.
    scripts = tmp_path / "scripts" / "vrchat"
    scripts.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "scripts" / "vrchat"
    for name in ("launch.ps1", "start.ps1", "start_ai_client.ps1"):
        shutil.copyfile(source / name, scripts / name)
    game = tmp_path / "game"
    game.mkdir()
    for name in ("VRChat.exe", "launch.exe"):
        (game / name).touch()
    settings = tmp_path / "stack.json"
    settings.write_text(
        json.dumps(
            {
                "ui": "http://127.0.0.1:18001/app/vrchat.html",
                "ai_client": {
                    "profile": 1,
                    "send_port": 19000,
                    "receive_port": 19001,
                    "vr": configured_vr,
                },
                "services": [
                    {
                        "name": "api",
                        "health": "http://127.0.0.1:18001/api/v1/vrchat",
                        "expect": {},
                        "environment": {
                            "VIREA_HOME": str(tmp_path / ".virea-runtime" / "home")
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    record = tmp_path / "launch.json"
    env = dict(
        os.environ,
        VIREA_TEST_SCRIPT=str(scripts / "launch.ps1"),
        VIREA_TEST_SETTINGS=str(settings),
        VIREA_TEST_GAME=str(game / "VRChat.exe"),
        VIREA_TEST_RECORD=str(record),
    )
    command = (
        r"""
function Invoke-RestMethod { param($Uri, $TimeoutSec) return @{} }
function Get-NetUDPEndpoint { param($LocalPort, $ErrorAction) }
function Get-CimInstance { param($ClassName, $Filter) }
function Start-Process {
    param($FilePath, $WorkingDirectory, $ArgumentList, [switch]$PassThru)
    @{file=$FilePath; args=$ArgumentList} | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:VIREA_TEST_RECORD
    [pscustomobject]@{Id=100}
}
& $env:VIREA_TEST_SCRIPT -Settings $env:VIREA_TEST_SETTINGS -VRChatExe $env:VIREA_TEST_GAME -SkipWebBuild
""".rstrip()
        + " "
        + override
    )
    result = subprocess.run(
        [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", command],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    launched = json.loads(record.read_text(encoding="utf-8-sig"))
    assert Path(launched["file"]).name == "launch.exe"
    assert ("--no-vr" not in launched["args"]) == expected_vr
    assert "--profile=1" in launched["args"]
    assert "--osc=19000:127.0.0.1:19001" in launched["args"]
