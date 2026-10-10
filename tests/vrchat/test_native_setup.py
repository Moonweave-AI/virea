import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from virea.vrchat import native_setup


@pytest.fixture
def virtual_runtime(tmp_path, monkeypatch):
    # Unit tests exercise setup/identity policy without loading a native SDK.
    # Real OpenVR deployment is validated separately on the Windows host.
    openvr = SimpleNamespace(
        TrackedDeviceClass_Controller=2,
        TrackedDeviceClass_HMD=1,
        Prop_SerialNumber_String=1002,
        k_unMaxTrackedDeviceCount=64,
    )
    monkeypatch.setitem(sys.modules, "openvr", openvr)
    native_setup._configured.clear()
    bindings = tmp_path / "integrations/vrchat/openvr/resources/input/vrchat.json"
    bindings.parent.mkdir(parents=True)
    source = (
        Path(__file__).resolve().parents[2]
        / "integrations/vrchat/openvr/resources/input/vrchat.json"
    )
    bindings.write_bytes(source.read_bytes())
    serials = {0: "VIREA-HMD-1", 2: "VIREA-LEFT-1", 3: "VIREA-RIGHT-1"}
    system = SimpleNamespace(
        getStringTrackedDeviceProperty=lambda i, prop: serials[i],
        isTrackedDeviceConnected=lambda i: i in serials,
        getTrackedDeviceClass=lambda i: (
            openvr.TrackedDeviceClass_Controller if i else openvr.TrackedDeviceClass_HMD
        ),
    )
    settings = []
    pid = os.getpid()
    kwargs = dict(
        root=tmp_path,
        system=system,
        apps=SimpleNamespace(
            getCurrentSceneProcessId=lambda: pid,
            getApplicationKeyByProcessId=lambda _: "steam.app.438100",
        ),
        settings=SimpleNamespace(setFloat=lambda *args: settings.append(args)),
    )
    return pid, kwargs, serials, settings


def test_virtual_setup_applies_content_versioned_bindings_once(virtual_runtime):
    pid, kwargs, _, settings = virtual_runtime
    requests = []

    def reply(request):
        requests.append(request)
        value = json.loads(request.content)
        assert request.url.host == "127.0.0.1"
        assert request.headers["origin"] == "http://127.0.0.1:27062"
        assert value["app_key"] == "steam.app.438100"
        assert "/.virea-runtime/vrchat/openvr-bindings/vrchat-" in value["url"]
        return httpx.Response(200, json={"success": True})

    first = native_setup.prepare_virtual_runtime(
        pid, **kwargs, client=httpx.MockTransport(reply)
    )
    assert (
        native_setup.prepare_virtual_runtime(
            pid, **kwargs, client=httpx.MockTransport(reply)
        )
        == first
    )
    assert len(requests) == 1
    assert settings == [("power", "turnOffControllersTimeout", 0)] * 2


@pytest.mark.parametrize(
    "condition", ["other_scene", "physical_hmd", "physical_controller"]
)
def test_virtual_setup_rejects_other_devices_before_any_write(
    virtual_runtime, condition
):
    pid, kwargs, serials, settings = virtual_runtime
    if condition == "other_scene":
        kwargs["apps"].getCurrentSceneProcessId = lambda: pid + 1
    if condition == "physical_hmd":
        serials[0] = "physical-headset"
    if condition == "physical_controller":
        serials[4] = "physical-controller"
    with pytest.raises(RuntimeError):
        native_setup.prepare_virtual_runtime(pid, **kwargs)
    assert settings == []
    assert not (kwargs["root"] / ".virea-runtime").exists()


def test_failed_binding_deployment_is_not_cached(virtual_runtime):
    pid, kwargs, _, _ = virtual_runtime
    with pytest.raises(RuntimeError, match="未接受"):
        native_setup.prepare_virtual_runtime(
            pid,
            **kwargs,
            client=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"error": "Parse failed"})
            ),
        )
    assert not native_setup._configured


def test_virtual_bindings_keep_menu_and_interaction_in_one_hand_context():
    path = (
        Path(__file__).resolve().parents[2]
        / "integrations/vrchat/openvr/resources/input/vrchat.json"
    )
    config = json.loads(path.read_text())
    one_hand = config["bindings"]["/actions/one_hand"]["sources"]
    for side in ("left", "right"):
        sources = {item["path"]: item["inputs"]["click"]["output"] for item in one_hand}
        assert sources[f"/user/hand/{side}/input/quick"] == "/actions/one_hand/in/menu"
        assert (
            sources[f"/user/hand/{side}/input/trigger"]
            == "/actions/one_hand/in/interact"
        )
