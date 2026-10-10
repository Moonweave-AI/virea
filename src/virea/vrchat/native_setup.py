"""Idempotent SteamVR setup for the explicitly selected VIREA virtual rig."""

import hashlib
import json
import threading
from pathlib import Path

import httpx

_lock = threading.Lock()
_configured = set()


def prepare_virtual_runtime(
    pid, *, system=None, apps=None, settings=None, client=None, root=None
):
    """Keep virtual controllers awake and apply this build's native bindings.

    This operates on SteamVR's local interface, not VRChat authentication or
    process memory. Physical-headset sessions are rejected before any write.
    """
    import openvr
    import psutil

    from .generated_pose import scene_process_id

    if system is None:
        if scene_process_id() != pid:
            raise RuntimeError("SteamVR 场景已变化，未修改虚拟设备设置")
        system, apps, settings = (
            openvr.VRSystem(),
            openvr.VRApplications(),
            openvr.VRSettings(),
        )
    if apps.getCurrentSceneProcessId() != pid:
        raise RuntimeError("SteamVR 场景与 AI 客户端不一致")
    if (
        system.getStringTrackedDeviceProperty(0, openvr.Prop_SerialNumber_String)
        != "VIREA-HMD-1"
    ):
        raise RuntimeError("自动设置仅适用于 VIREA 虚拟头显；未修改物理 VR 设备")
    serials = {
        system.getStringTrackedDeviceProperty(i, openvr.Prop_SerialNumber_String)
        for i in range(openvr.k_unMaxTrackedDeviceCount)
        if system.isTrackedDeviceConnected(i)
        and system.getTrackedDeviceClass(i) == openvr.TrackedDeviceClass_Controller
    }
    if serials != {"VIREA-LEFT-1", "VIREA-RIGHT-1"}:
        raise RuntimeError("需要且仅能连接 VIREA 左右虚拟手柄，自动设置已停止")
    app_key = apps.getApplicationKeyByProcessId(pid)
    if app_key not in {"steam.app.438100", "application.generated.unity.vrchat.exe"}:
        raise RuntimeError("当前 SteamVR 应用不是 VRChat，未修改按键绑定")
    root = Path(root) if root else Path(__file__).resolve().parents[3]
    binding = json.loads(
        (root / "integrations/vrchat/openvr/resources/input/vrchat.json").read_text(
            encoding="utf-8"
        )
    )
    binding["app_key"] = app_key
    payload = json.dumps(binding, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    key = (pid, psutil.Process(pid).create_time(), digest)
    with _lock:
        # A stationary generated pose must not put a virtual hand to sleep.
        # SteamVR's installed settings schema defines zero as Never.
        settings.setFloat("power", "turnOffControllersTimeout", 0)
        if key not in _configured:
            directory = root / ".virea-runtime/vrchat/openvr-bindings"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"vrchat-{digest[:16]}.json"
            if not path.exists() or path.read_bytes() != payload:
                path.write_bytes(payload)
            # A content-addressed URL avoids SteamVR retaining the previous
            # bindings when a file is overwritten under the same name.
            with httpx.Client(
                base_url="http://127.0.0.1:27062",
                trust_env=False,
                timeout=5,
                headers={
                    "Origin": "http://127.0.0.1:27062",
                    "Referer": "http://127.0.0.1:27062/dashboard/controllerbinding.html",
                },
                transport=client,
            ) as api:
                response = api.post(
                    "/input/selectconfig.action",
                    json={
                        "app_key": app_key,
                        "controller_type": binding["controller_type"],
                        "url": path.as_uri(),
                    },
                )
                if (
                    not response.is_success
                    or response.json().get("success") is not True
                ):
                    raise RuntimeError("SteamVR 未接受新版手柄绑定，自动设置未完成")
            _configured.add(key)
    return {"binding_sha256": digest, "controller_idle_timeout_seconds": 0}
