"""Short-lived human control of the virtual VR rig for menus and calibration."""

import asyncio
import contextlib
import time
from typing import Annotated
from uuid import uuid4

import httpx
import numpy as np
from pydantic import Field

from virea.motion.rotation import quat_apply_xyzw, quat_multiply_xyzw

from .client_query import local_client_endpoints
from .contracts import StrictModel
from .generated_pose import GeneratedPoseClient, pose_payload, scene_process_id
from .mapping import tracker_messages
from .native_setup import prepare_virtual_runtime
from .osc import message
from .standing import standing_pose
from .timeline import Pose

LEASE_SECONDS = 10
INPUT_TIMEOUT_SECONDS = 0.4
Offset = Annotated[float, Field(ge=-0.6, le=0.6)]
Angle = Annotated[float, Field(ge=-90, le=90)]
HandAdjustment = tuple[Offset, Offset, Offset, Angle, Angle, Angle]
POSE_FIELDS = (
    "head_yaw",
    "head_pitch",
    "head_x",
    "head_y",
    "head_z",
    "left_hand",
    "right_hand",
    "pointer_x",
    "pointer_y",
    "view_aspect",
    "horizontal_fov",
    "projection_center_x",
    "projection_center_y",
)


class ManualState(StrictModel):
    head_yaw: float = Field(default=0, ge=-180, le=180)
    head_pitch: float = Field(default=0, ge=-70, le=70)
    head_x: Offset = 0
    head_y: Offset = 0
    head_z: Offset = 0
    left_hand: HandAdjustment = (0, 0, 0, 0, 0, 0)
    right_hand: HandAdjustment = (0, 0, 0, 0, 0, 0)
    pointer_x: float = Field(default=0, ge=-1, le=1)
    pointer_y: float = Field(default=0, ge=-1, le=1)
    view_aspect: float = Field(default=16 / 9, ge=0.25, le=4)
    horizontal_fov: float = Field(default=90, ge=40, le=140)
    projection_center_x: float = Field(default=0, ge=-0.25, le=0.25)
    projection_center_y: float = Field(default=0, ge=-0.25, le=0.25)
    trigger: bool = False
    trigger_left: bool = False
    vertical: float = Field(default=0, ge=-1, le=1)
    horizontal: float = Field(default=0, ge=-1, le=1)
    turn: float = Field(default=0, ge=-1, le=1)
    scroll_x: float = Field(default=0, ge=-1, le=1)
    scroll_y: float = Field(default=0, ge=-1, le=1)
    move_hold: float = Field(default=0, ge=-1, le=1)
    run: bool = False
    jump: bool = False
    grab: bool = False
    drop: bool = False
    grab_left: bool = False
    drop_left: bool = False
    calibration: bool = False
    relaxation: float = Field(default=0, ge=0, le=1)


async def manual_client_pid(config):
    """Identify a human-controlled client even before its avatar has loaded.

    This does not authorize autonomous model output. The user's dedicated UDP
    port, live OSCQuery host and SteamVR scene must all belong to the same PID.
    """
    scene = await asyncio.to_thread(scene_process_id)
    endpoints = await asyncio.to_thread(local_client_endpoints, config.send_port)
    async with httpx.AsyncClient(timeout=1.5, trust_env=False) as client:
        for pid, port in endpoints:
            if not scene or pid != scene:
                continue
            try:
                response = await client.get(f"http://127.0.0.1:{port}/?HOST_INFO")
                response.raise_for_status()
                info = response.json()
                if (
                    info.get("OSC_PORT") == config.send_port
                    and info.get("OSC_IP") == "127.0.0.1"
                    and info.get("OSC_TRANSPORT") == "UDP"
                    and str(info.get("NAME", "")).startswith("VRChat-Client-")
                ):
                    await asyncio.to_thread(prepare_virtual_runtime, pid)
                    return pid
            except (httpx.HTTPError, ValueError):
                continue
    raise ValueError("AI 尚未接入 SteamVR；请仅将专用 AI 客户端以 VR 模式启动")


def look_rotation(yaw, pitch):
    y, p = np.deg2rad([-yaw, pitch]) / 2
    return quat_multiply_xyzw(
        np.array([0, np.sin(y), 0, np.cos(y)]),
        np.array([np.sin(p), 0, 0, np.cos(p)]),
    )


def manual_payload(state, scale, ray_alignment=None):
    rest = (
        standing_pose(state.relaxation)
        if state.calibration
        else Pose(np.array([0.0, 1.0, 0.0]), {})
    )
    devices, hands = pose_payload(rest, rest.root, scale=scale)
    if not state.calibration:
        q = look_rotation(state.head_yaw, state.head_pitch)
        # Lean is relative to horizontal facing, independent of neck pitch.
        devices[0, :3] += quat_apply_xyzw(
            look_rotation(state.head_yaw, 0),
            np.array([state.head_x, state.head_y, state.head_z]),
        )
        devices[0, 3:] = q
        tangent = np.tan(np.deg2rad(state.horizontal_fov) / 2)
        x = (state.pointer_x - state.projection_center_x) * tangent
        y = -(state.pointer_y - state.projection_center_y) * tangent / state.view_aspect
        yaw = np.rad2deg(np.arctan2(x, 1))
        pitch = np.rad2deg(np.arctan2(y, np.hypot(x, 1)))
        for i in (1, 2):
            # Keep the pointer on the eye ray, eliminating lateral parallax.
            # A small forward separation avoids a coincident HMD/controller
            # while preserving the same projected ray at every UI depth.
            # Hold the menu in the visible part of the mirror, independently
            # of the pointing hand. A lowered wrist puts most of VRChat's
            # attached quick menu below the camera's bottom edge.
            offset = [-0.25, -0.02, -0.45] if i == 1 else [0, 0, 0]
            devices[i, :3] = devices[0, :3] + quat_apply_xyzw(
                q, np.array(offset) * scale
            )
            aim = (
                quat_multiply_xyzw(q, look_rotation(0, 65))
                if i == 1
                else quat_multiply_xyzw(q, look_rotation(yaw, pitch))
            )
            # Start with a camera-space aim. The game's pointer has its own
            # local origin/direction, fitted separately from the OpenVR tip.
            devices[i, 3:] = aim
            if i == 2:
                devices[i, :3] = devices[0, :3] + quat_apply_xyzw(
                    aim, np.array([0, 0, -0.16]) * scale
                )
        if ray_alignment is not None:
            from .ray_calibration import apply_ray_alignment

            apply_ray_alignment(devices, ray_alignment)
        for i, adjustment in enumerate((state.left_hand, state.right_hand), 1):
            devices[i, :3] += quat_apply_xyzw(q, np.array(adjustment[:3]))
            yaw, pitch, roll = adjustment[3:]
            angle = np.deg2rad(roll) / 2
            rotation = quat_multiply_xyzw(
                look_rotation(yaw, pitch),
                np.array([0, 0, np.sin(angle), np.cos(angle)]),
            )
            devices[i, 3:] = quat_multiply_xyzw(devices[i, 3:], rotation)
    return rest, devices, hands


def manual_input_messages(
    state, *, menu=None, turn_left=False, turn_right=False, enabled=True
):
    """Only documented OSC inputs; voice is deliberately never controlled."""
    return [
        # Pydantic does not coerce unprovided defaults: a locally constructed
        # state can contain int 0 while its HTTP equivalent contains float 0.
        # OSC type tags are part of the input contract, including neutral axes.
        message("/input/Vertical", float(state.vertical) if enabled else 0.0),
        message("/input/Horizontal", float(state.horizontal) if enabled else 0.0),
        message("/input/LookHorizontal", float(state.turn) if enabled else 0.0),
        message("/input/MoveHoldFB", float(state.move_hold) if enabled else 0.0),
        *[
            message(f"/input/{name}", int(bool(enabled and value)))
            for name, value in (
                ("Run", state.run),
                ("Jump", state.jump),
                ("GrabRight", state.grab),
                ("DropRight", state.drop),
                ("GrabLeft", state.grab_left),
                ("DropLeft", state.drop_left),
                ("ComfortLeft", turn_left),
                ("ComfortRight", turn_right),
            )
        ],
        # Native controller actions and OSC share the game's logical button.
        # Repeating OSC zero can suppress the native Quick Menu press. Only
        # write this channel for an explicit OSC command or final release.
        *(
            [message("/input/QuickMenuToggleLeft", int(bool(enabled and menu)))]
            if menu is not None or not enabled
            else []
        ),
        *([message("/input/QuickMenuToggleRight", 0)] if not enabled else []),
    ]


class ManualRig:
    def __init__(self):
        self.task = None
        self.token = None
        self.state = ManualState()
        self.updated = 0.0
        self.click_until = 0.0
        self.confirm_until = 0.0
        self.menu_until = 0.0
        self.system_until = 0.0
        self.left_click_until = 0.0
        self.button_pulses = {}
        self.error = None
        self.driver_status = None
        self.applied_state = None
        self.projection = None
        self.ai_pid = None
        self.ray_alignment = None
        self._alignment_device = None
        self._alignment_menu_hand = None

    def snapshot(self):
        return dict(
            active=bool(self.task and not self.task.done()),
            error=self.error,
            driver=self.driver_status,
            state=self.state.model_dump(),
            applied_state=self.applied_state,
            projection=self.projection,
            ray_alignment=self.ray_alignment,
        )

    def begin(self, config, transport, ai_pid):
        if self.task and not self.task.done():
            raise ValueError("AI manual controls are already open in another panel")
        self.token = uuid4().hex
        if self.ai_pid != ai_pid:
            self.projection = None
            self.ray_alignment = None
        self.ai_pid = ai_pid
        self.updated = time.monotonic()
        self.error = None
        self.driver_status = None
        self.applied_state = None
        self.click_until = self.confirm_until = self.menu_until = 0.0
        self.system_until = 0.0
        self.left_click_until = 0.0
        self.button_pulses.clear()
        # Re-entering control should not jerk the camera back to the horizon.
        self.state = ManualState(
            **{key: getattr(self.state, key) for key in POSE_FIELDS}
        )
        self.task = asyncio.create_task(
            self._run(config, transport, ai_pid), name="virea-manual-rig"
        )
        return self.token

    def update(self, token, state, command=None):
        if token != self.token or not self.task or self.task.done():
            raise ValueError("manual control expired; enable it again")
        pressed = state.trigger and not self.state.trigger
        left_pressed = state.trigger_left and not self.state.trigger_left
        self.state = state
        self.updated = time.monotonic()
        if pressed:
            # A quick web click must survive several game update frames, even
            # when two clients and model workers contend for GPU resources.
            self.click_until = self.updated + 0.15
        if left_pressed:
            self.left_click_until = self.updated + 0.15
        if command == "click":
            self.click_until = self.updated + 0.18
        elif command == "click_left":
            self.left_click_until = self.updated + 0.18
        elif command == "confirm":
            self.confirm_until = self.updated + 0.18
        elif command == "menu":
            self.menu_until = self.updated + 0.18
        elif command == "dashboard":
            self.system_until = self.updated + 0.25
        elif command in {
            "menu_right",
            "main_menu",
            "action_menu",
            "back",
            "turn_left",
            "turn_right",
        }:
            self.button_pulses[command] = self.updated + 0.18

    async def align_projection(self, token, config, views):
        """Fit the mirror camera and actual game ray, then restore the view."""
        from .view_projection import estimate_mirror_projection
        from .views import ViewUnavailable

        self.update(token, self.state)
        if self.state.calibration:
            raise ValueError("请先按 T 退出身体校准，再对齐准星")
        original = ManualState(**{key: getattr(self.state, key) for key in POSE_FIELDS})
        if any(original.right_hand):
            raise ValueError("请先按小键盘小数点还原手柄，再对齐准星")
        self.state = original
        self.click_until = self.confirm_until = self.menu_until = self.system_until = 0
        self.left_click_until = 0
        self.button_pulses.clear()
        projection = None
        alignment = None

        async def sample():
            changed = time.monotonic()
            while time.monotonic() - changed < 3:
                if token != self.token or not self.task or self.task.done():
                    raise ValueError("接管已结束，准星对齐已取消")
                self.updated = time.monotonic()
                await asyncio.sleep(0.1)
                try:
                    target, frame = await asyncio.to_thread(
                        views.frame, "ai", config.send_port
                    )
                except ViewUnavailable:
                    continue
                if target.pid != self.ai_pid:
                    raise ValueError("AI 窗口身份已变化，对齐已停止")
                if frame.captured_at > changed + 0.8:
                    return frame.jpeg
            raise ValueError("未收到新的游戏画面，无法对齐准星")

        try:
            first = await sample()
            # The menu is attached to the left wrist. Keep that wrist in world
            # space while measuring the camera rotation, otherwise most menu
            # features move with the camera and invalidate the projection fit.
            _, original_devices, _ = manual_payload(original, config.scale)
            self._alignment_menu_hand = original_devices[1].copy()
            delta = 9 if original.head_pitch < 55 else -9
            self.state = original.model_copy(
                update={"head_pitch": original.head_pitch + delta}
            )
            second = await sample()
            projection = await asyncio.to_thread(
                estimate_mirror_projection, first, second, delta
            )
            self.state = original
            from .ray_calibration import SAMPLES, detect_ray_line, fit_ray_alignment

            _, devices, _ = manual_payload(original, config.scale)
            head = devices[0].copy()
            observations = []
            baseline = None
            for x, y, z, yaw, pitch in [(0, 0, -0.3, 0, -85), *SAMPLES]:
                position = head[:3] + quat_apply_xyzw(head[3:], np.array([x, y, z]))
                rotation = quat_multiply_xyzw(head[3:], look_rotation(yaw, pitch))
                if baseline is not None:
                    rotation = quat_multiply_xyzw(rotation, look_rotation(0, 40))
                controller = np.r_[position, rotation]
                self._alignment_device = controller
                frame = await sample()
                if baseline is None:
                    baseline = frame
                    continue
                line = await asyncio.to_thread(detect_ray_line, baseline, frame)
                if line is not None:
                    observations.append((head, controller, line))
            alignment = fit_ray_alignment(observations, projection)
            self.projection, self.ray_alignment = projection, alignment
        finally:
            self._alignment_device = None
            self._alignment_menu_hand = None
            # Never restore buttons or overwrite a newly acquired lease.
            if token == self.token:
                values = (
                    {
                        key: projection[key]
                        for key in (
                            "horizontal_fov",
                            "view_aspect",
                            "projection_center_x",
                            "projection_center_y",
                        )
                    }
                    if alignment
                    else {}
                )
                self.state = original.model_copy(update=values)
                self.updated = time.monotonic()
        return self.snapshot()

    async def _run(self, config, transport, ai_pid):
        driver = GeneratedPoseClient(config.pose_driver_port, expected_pid=ai_pid)
        last_devices = last_hands = None
        pending = {}
        sent = 0
        started = time.monotonic()
        # Use one native menu source throughout the lease. VRChat can retain
        # its one-hand action set after a virtual controller wakes up; the
        # deployed bindings cover both that set and the normal global set.
        try:
            if transport.ready(require_full_body=False)[0]:
                transport.send(
                    [
                        message("/input/QuickMenuToggleLeft", 0),
                        message("/input/QuickMenuToggleRight", 0),
                    ]
                )
                await asyncio.sleep(1 / 30)
            while time.monotonic() - self.updated < LEASE_SECONDS:
                now = time.monotonic()
                fresh = now - self.updated < INPUT_TIMEOUT_SECONDS
                rest, last_devices, last_hands = manual_payload(
                    self.state, config.scale, self.ray_alignment
                )
                if self._alignment_device is not None:
                    last_devices[2] = self._alignment_device
                if self._alignment_menu_hand is not None:
                    last_devices[1] = self._alignment_menu_hand
                triggers = 0
                if fresh:
                    if self.state.trigger or now < self.click_until:
                        triggers |= 4
                    if self.state.trigger_left or now < self.left_click_until:
                        triggers |= 2
                    if now < self.confirm_until:
                        triggers = 6
                buttons = sum(
                    flag
                    for command, flag in {
                        "main_menu": 128,
                        "action_menu": 512,
                        "back": 2048,
                    }.items()
                    if fresh and now < self.button_pulses.get(command, 0)
                )
                menu_pressed = [
                    fresh and now < self.menu_until,
                    fresh and now < self.button_pulses.get("menu_right", 0),
                ]
                buttons |= (16 if menu_pressed[0] else 0) | (
                    32 if menu_pressed[1] else 0
                )
                driver.send_payload(
                    last_devices,
                    last_hands,
                    triggers=triggers,
                    system=fresh and now < self.system_until,
                    buttons=buttons,
                    scroll=(0, 0, self.state.scroll_x, self.state.scroll_y)
                    if fresh
                    else (0, 0, 0, 0),
                )
                sent += 1
                pending[sent] = self.state.model_dump()
                self.driver_status = driver.snapshot()
                acknowledged = self.driver_status.get("acknowledged", 0)
                if acknowledged in pending:
                    self.applied_state = pending[acknowledged]
                pending = {
                    seq: value for seq, value in pending.items() if seq > acknowledged
                }
                ack_age = self.driver_status["last_ack_seconds_ago"]
                if (ack_age is None and now - started > 0.75) or (
                    ack_age is not None and ack_age > 0.75
                ):
                    raise RuntimeError("virtual device driver stopped responding")
                # Calibration must send the body targets before TrackingType=6;
                # autonomous playback still requires the complete FBT gate.
                if transport.ready(require_full_body=False)[0]:
                    packets = manual_input_messages(
                        self.state,
                        enabled=fresh,
                        turn_left=now < self.button_pulses.get("turn_left", 0),
                        turn_right=now < self.button_pulses.get("turn_right", 0),
                    )
                    # Trackers must remain present while pointing at Calibrate.
                    # Otherwise they time out before the user can enter FBT.
                    packets += tracker_messages(
                        rest.root, rest.rotations, config, rest.root
                    )
                    transport.send(packets)
                await asyncio.sleep(1 / 30)
        except Exception as exc:
            self.error = str(exc)
        finally:
            if last_devices is not None:
                with contextlib.suppress(Exception):
                    driver.send_payload(last_devices, last_hands, triggers=0)
            driver.close()
            with contextlib.suppress(Exception):
                transport.send(manual_input_messages(self.state, enabled=False))
            transport.release()
            self.token = None

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        self.token = None
