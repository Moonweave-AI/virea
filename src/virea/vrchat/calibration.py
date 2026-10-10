"""Bounded automatic FBT setup, confirmed exclusively by fresh game feedback."""

import asyncio
import contextlib
import time

import numpy as np

from virea.motion.rotation import quat_apply_xyzw

from .async_compat import timeout
from .manual import (
    POSE_FIELDS,
    ManualRig,
    ManualState,
    look_rotation,
    manual_client_pid,
)
from .menu_vision import (
    LabelNotFound,
    calibration_hovered,
    calibration_label,
    read_labels,
)
from .views import ViewUnavailable

STEPS = (
    ("preparing", "检查 AI 身份和虚拟设备"),
    ("waking", "唤醒设备并建立身体追踪"),
    ("finding_menu", "定位游戏的全身校准入口"),
    ("aiming", "对齐射线并进入校准"),
    ("confirming", "保持 T 形并确认校准"),
    ("verifying", "等待游戏确认全身追踪"),
    ("standing", "平滑恢复自然站姿"),
    ("stabilizing", "检查站姿输出与追踪稳定性"),
)


def menu_view(pitch=0, *, stow_pointer=False):
    """Look independently of the stationary menu hand, in OpenVR standing space."""
    # Start from the visible wrist pose used by direct control at -25 degrees.
    # Preserve that world pose while scanning with the head; a flat hand hides
    # VRChat's attached panel below the desktop mirror.
    hand = quat_apply_xyzw(look_rotation(0, -25), np.array([-0.25, -0.02, -0.45]))
    offset = quat_apply_xyzw(look_rotation(0, -pitch), hand) - np.array(
        [-0.25, -0.02, -0.45]
    )
    return ManualState(
        head_pitch=pitch,
        left_hand=(*offset, 0, -25 - pitch, 0),
        right_hand=(0.5, -0.5, 0, 0, 0, 0) if stow_pointer else (0, 0, 0, 0, 0, 0),
    )


class StationaryCalibrationRig(ManualRig):
    """Calibration may aim and confirm, but cannot relocate the player."""

    def update(self, token, state, command=None):
        if any(
            getattr(state, field)
            for field in (
                "vertical",
                "horizontal",
                "turn",
                "run",
                "jump",
                "head_x",
                "head_y",
                "head_z",
            )
        ) or command not in {None, "menu", "back", "click", "confirm"}:
            raise ValueError("自动校准禁止移动、转身或跳跃；请保留镜前站位")
        return super().update(token, state, command)


class AutoCalibration:
    def __init__(
        self,
        *,
        rig=None,
        identify=manual_client_pid,
        ocr=read_labels,
        timeout_seconds=120,
    ):
        self.rig = rig or StationaryCalibrationRig()
        self.identify = identify
        self.ocr = ocr
        self.task = None
        self.attempted = None
        self.stage = "waiting"
        self.error = None
        self.pid = None
        self.avatar = None
        self.completed_at = None
        self.step = 0
        self.completed_steps = 0
        self.step_label = "等待开始自动校准"
        self.detail = None
        self.started_at = None
        self.idle_token = None
        self.timeout_seconds = timeout_seconds

    def advance(self, stage):
        self.stage = stage
        self.step = next(i for i, item in enumerate(STEPS, 1) if item[0] == stage)
        self.completed_steps = self.step - 1
        self.step_label = STEPS[self.step - 1][1]
        self.detail = None

    @property
    def active(self):
        return self.task is not None and not self.task.done()

    def snapshot(self):
        return {
            "active": self.active,
            "stage": self.stage,
            "error": self.error,
            "pid": self.pid,
            "avatar_id": self.avatar,
            "step": self.step,
            "total_steps": len(STEPS),
            "completed_steps": self.completed_steps,
            "percent": round(100 * self.completed_steps / len(STEPS)),
            "step_label": self.step_label,
            "detail": self.detail,
            "started_at": self.started_at,
            "standing_maintained": bool(self.idle_token),
            "completed_at": self.completed_at,
            "entry_method": "local_ocr_virtual_controller",
            "confirmation": "fresh_vrchat_tracking_type_6",
        }

    def key(self, transport):
        query = transport.protocol.snapshot().get("query", {})
        values = transport.protocol.values
        age = query.get("last_checked_seconds_ago")
        if (
            query.get("state") != "verified"
            or age is None
            or age >= 3
            or not transport.ready(require_full_body=False)[0]
        ):
            return None
        return query.get("pid"), values.get("avatar_id", (None,))[0]

    def start(self, config, transport, views, *, force=False):
        if self.active:
            return self.snapshot()
        key = self.key(transport)
        if not key or not all(key) or views is None:
            return self.snapshot()
        if self.idle_token and key == self.attempted and not force:
            return self.snapshot()
        if (
            key == self.attempted
            and not force
            and (self.stage in {"failed", "cancelled"} or not transport.ready()[0])
        ):
            return self.snapshot()
        self.attempted = key
        self.pid, self.avatar = key
        self.advance("preparing")
        self.error, self.completed_at, self.idle_token = None, None, None
        self.started_at = time.time()
        self.task = asyncio.create_task(
            self._run(config, transport, views, recalibrate=force),
            name="vrchat-auto-fbt",
        )
        return self.snapshot()

    async def maintain(self, transport):
        """The service renews this lease only while no other pose owner is active."""
        if self.active or not self.idle_token:
            return
        try:
            if self.key(transport) != self.attempted or not transport.ready()[0]:
                raise ValueError("全身追踪或 AI 身份已变化，站姿保持已停止，请重新校准")
            self.rig.update(
                self.idle_token, ManualState(calibration=True, relaxation=1)
            )
            if self.rig.error:
                raise ValueError(self.rig.error)
        except ValueError as exc:
            self.stage, self.error = "failed", str(exc)
            self.completed_steps = min(self.completed_steps, len(STEPS) - 1)
            self.completed_at = None
            await self.stop()

    async def stop(self):
        self.idle_token = None
        if self.active:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.stage = "cancelled"
        await self.rig.close()

    async def _run(self, config, transport, views, *, recalibrate=False):
        token = None

        async def guard():
            nonlocal token
            if self.rig.error:
                raise ValueError(self.rig.error)
            if self.key(transport) == self.attempted:
                return
            # Entering FBT reloads the avatar and briefly clears VRMode and
            # TrackingType. Release every button while waiting; never replay
            # the click, or continue onto a different client/avatar.
            saved = ManualState(
                **{
                    name: getattr(self.rig.state, name)
                    for name in (*POSE_FIELDS, "calibration", "relaxation")
                }
            )
            await self.rig.close()
            if self.stage not in {"aiming", "confirming", "verifying"}:
                raise ValueError("AI 身份或反馈已变化，自动校准停止")
            previous_detail = self.detail
            self.detail = "等待同一角色的追踪反馈恢复；已释放按键"
            # Local VRChat reloads took 4–5 seconds, followed by the next
            # OSCQuery poll. Cover that transition without an unbounded wait.
            until = time.monotonic() + 8
            while time.monotonic() < until:
                query = transport.protocol.snapshot().get("query", {})
                avatar = transport.protocol.values.get("avatar_id", (None,))[0]
                if query.get("pid") not in (None, self.pid) or avatar not in (
                    None,
                    self.avatar,
                ):
                    raise ValueError("AI 客户端或角色已变化，自动校准停止")
                if self.key(transport) == self.attempted:
                    if await self.identify(config) != self.pid:
                        raise ValueError("SteamVR 场景与 AI 客户端不一致")
                    token = self.rig.begin(config, transport, self.pid)
                    self.rig.update(token, saved)
                    self.detail = previous_detail
                    return
                await asyncio.sleep(0.05)
            raise ValueError("同一角色的追踪反馈未恢复，自动校准停止")

        async def hold(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                await guard()
                self.rig.update(token, self.rig.state)
                await asyncio.sleep(0.05)

        async def capture():
            await guard()
            changed = time.monotonic()
            while time.monotonic() - changed < 4:
                await hold(0.15)
                try:
                    target, frame = await asyncio.to_thread(
                        views.frame, "ai", config.send_port
                    )
                except ViewUnavailable:
                    continue  # A new/restarted window needs its first capture.
                if target.pid != self.pid:
                    raise ValueError("AI 画面身份发生变化，自动校准停止")
                if frame.captured_at > changed:
                    return frame
            raise ValueError("没有新的 AI 游戏画面，自动校准停止")

        async def labels_for(frame):
            # OCR can exceed the input freshness window. Keep the owned rig's
            # lease alive while inference runs, including cold model startup.
            task = asyncio.create_task(self.ocr(frame.jpeg))
            try:
                while not task.done():
                    await hold(0.05)
                return await task
            finally:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        async def find_button():
            frame = await capture()
            labels = await labels_for(frame)
            return calibration_label(labels), frame

        async def pulse(command):
            await guard()
            if command in {"menu", "back"}:
                # A short Menu press opens Quick Menu; a held Menu opens the
                # Action Menu. Renew the lease without extending this press.
                self.rig.update(token, self.rig.state, command)
                await hold(0.8)
                return
            end = time.monotonic() + 0.65
            while time.monotonic() < end:
                await guard()
                if time.monotonic() >= end:
                    break
                self.rig.update(token, self.rig.state, command)
                await asyncio.sleep(0.05)
            await hold(0.3)

        async def locate():
            for pitch in (-25, 0, 20):
                self.rig.update(token, menu_view(pitch, stow_pointer=True))
                await hold(1.2)
                try:
                    return await find_button()
                except LabelNotFound:
                    await guard()
            raise LabelNotFound("未可靠识别校准入口；已停止输入，可重试自动校准")

        try:
            async with timeout(self.timeout_seconds):
                await self.rig.close()
                if await self.identify(config) != self.pid:
                    raise ValueError("SteamVR 场景与 AI 客户端不一致")
                token = self.rig.begin(config, transport, self.pid)
                if transport.ready()[0] and not recalibrate:
                    # Already calibrated (e.g. after a model performance). Do
                    # not re-enter the menu or pretend a fresh calibration ran.
                    self.rig.update(token, ManualState(calibration=True, relaxation=1))
                    await self.finish_standing(token, transport, hold, transition=False)
                    return
                self.advance("waking")
                # Establish all trackers while keeping the menu hand in place.
                # An early T-pose moves an already open wrist menu out of view;
                # enter T-pose only after the calibration button was confirmed.
                self.rig.update(token, menu_view(-25, stow_pointer=True))
                await hold(1.5)  # all eight OSC targets must exist before opening FBT
                self.advance("finding_menu")
                # A URL launch or prior interaction can leave a nested menu
                # page open. A toggle would close that page, not open Home.
                # Normalize using only bounded Back/Menu input, never guessed
                # button coordinates. Login screens cannot pass the FBT gate.
                for attempt, command in enumerate((None, "menu", "back", "menu"), 1):
                    self.detail = f"正在检查菜单位置（{attempt}/4）"
                    self.rig.update(token, menu_view(-25, stow_pointer=True))
                    await hold(0.8)
                    if command:
                        await pulse(command)
                    await hold(1.2)
                    try:
                        await locate()
                        break
                    except LabelNotFound:
                        await guard()
                else:
                    await locate()
                self.advance("aiming")
                # In-world avatars render hands; the uncalibrated pointer at
                # eye level can cover the whole menu. Aim away until the actual
                # ray has been measured, then use the fitted eye/tip transform.
                self.rig.update(
                    token,
                    self.rig.state.model_copy(
                        update={
                            "right_hand": (0, 0, 0, 0, 0, 0),
                            "pointer_x": 0.9,
                            "pointer_y": 0.9,
                        }
                    ),
                )
                await self.rig.align_projection(token, config, views)
                button, frame = await find_button()
                self.rig.update(
                    token,
                    self.rig.state.model_copy(
                        update={
                            "pointer_x": 2 * (button.x + button.width / 2) / frame.width
                            - 1,
                            "pointer_y": 2
                            * (button.y + button.height / 2)
                            / frame.height
                            - 1,
                        }
                    ),
                )
                await hold(1.0)  # allow the game's hover tooltip to appear
                # The real ray's dot can cover the two-character button label.
                # Its exact FBT hover help is also positive evidence of aim;
                # generic screen changes or unrelated text never permit clicks.
                frame = await capture()
                if not calibration_hovered(await labels_for(frame), button):
                    raise ValueError("未确认射线指向全身校准入口，未发送点击")
                await pulse("click")
                await hold(0.7)
                # VRChat keeps the quick-menu fade-out visible during the
                # avatar reload. A newly captured frame can still contain
                # those old labels; wait for the actual menu to disappear.
                closing_until = time.monotonic() + 6
                while time.monotonic() < closing_until:
                    frame = await capture()
                    labels = await labels_for(frame)
                    try:
                        calibration_label(labels)
                    except LabelNotFound:
                        break
                    await hold(0.3)
                else:
                    raise ValueError("游戏尚未进入 FBT 校准，未发送确认")
                self.advance("confirming")
                self.rig.update(token, ManualState(calibration=True))
                await hold(1.2)
                confirmation = time.monotonic()
                await pulse("confirm")
                await hold(0.4)
                self.advance("verifying")
                while time.monotonic() - confirmation < 10:
                    await hold(0.2)
                    tracking = transport.protocol.values.get("TrackingType", (None, 0))
                    if (
                        transport.ready()[0]
                        and tracking[0] == 6
                        and tracking[1] > confirmation
                    ):
                        await self.finish_standing(token, transport, hold)
                        return
                raise ValueError("未收到新的 TrackingType=6 回传；全身校准未完成")
        except asyncio.CancelledError:
            self.stage = "cancelled"
            raise
        except asyncio.TimeoutError:
            self.stage, self.error = (
                "failed",
                f"第 {self.step}/{len(STEPS)} 步「{self.step_label}」超时；已释放所有输入",
            )
        except Exception as exc:
            self.stage, self.error = "failed", str(exc)
        finally:
            if not self.idle_token:
                await self.rig.close()

    async def finish_standing(self, token, transport, hold, *, transition=True):
        self.advance("standing")
        if transition:
            started = time.monotonic()
            while True:
                fraction = min(1.0, (time.monotonic() - started) / 1.5)
                blend = fraction * fraction * (3 - 2 * fraction)
                self.rig.update(token, ManualState(calibration=True, relaxation=blend))
                await hold(0.05)
                if fraction == 1:
                    break
        self.advance("stabilizing")
        await hold(1.0)  # release both confirmation triggers before reporting success
        status = self.rig.snapshot()
        driver = status.get("driver") or {}
        applied = status.get("applied_state") or {}
        age = driver.get("last_ack_seconds_ago")
        if (
            age is None
            or age > 0.75
            or driver.get("active_devices") != 7
            or driver.get("skeleton_devices") != 6
            or applied.get("relaxation") != 1
            or not applied.get("calibration")
        ):
            raise ValueError("自然站姿未获虚拟设备完整回执，校准未完成")
        if not transport.ready()[0]:
            raise ValueError("恢复站姿时全身追踪丢失，校准未完成")
        self.stage, self.completed_at = "completed", time.time()
        self.completed_steps = len(STEPS)
        self.step_label = "校准完成 · 自然站姿已输出"
        self.detail = "游戏已确认全身追踪；等待任务时持续保持站姿"
        self.idle_token = token
