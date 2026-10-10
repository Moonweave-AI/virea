"""Explicit capabilities and calibrated output configuration for VRChat."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AVATAR_ID_PATTERN = r"^(avtr_[A-Za-z0-9-]+|local:sdk_[^\x00-\x1f\x7f/\\]+)$"
AvatarId = Annotated[str, Field(pattern=AVATAR_ID_PATTERN, max_length=200)]
FULL_BODY_TRACKER_BONES = (
    "hips",
    "leftFoot",
    "rightFoot",
    "chest",
    "leftLowerLeg",
    "rightLowerLeg",
    "leftLowerArm",
    "rightLowerArm",
)


def valid_avatar_id(value):
    return (
        isinstance(value, str)
        and len(value) <= 200
        and re.fullmatch(AVATAR_ID_PATTERN, value) is not None
    )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class BridgeConfig(StrictModel):
    target_role: Literal["independent_ai"] = "independent_ai"
    mode: Literal["desktop", "vr_trackers", "generated_vr"] = "desktop"
    pose_driver_port: int = Field(default=19030, ge=1024, le=65535)
    host: Literal["127.0.0.1"] = "127.0.0.1"
    send_port: int = Field(default=19010, ge=1024, le=65535)
    receive_port: int = Field(default=19011, ge=1024, le=65535)
    fps: int = Field(default=30, ge=10, le=60)
    audio_device: str | None = Field(default=None, max_length=240)
    audio_enabled: bool = False
    microphone: Literal["manual", "hold"] = "manual"
    chatbox: bool = False
    observer_chatbox: bool = False
    expressions: bool = True
    eyes: bool = True
    locomotion: bool = False
    # Opt in only for avatars retaining the SDK's default VRCEmote Action layer.
    desktop_emotes: bool = False
    walk_speed: float = Field(default=2.0, gt=0.1, le=10)
    turn_speed_degrees: float = Field(default=90, gt=1, le=360)
    max_axis: float = Field(default=0.65, gt=0, le=1)
    feedback_gain: float = Field(default=0.15, ge=0, le=1)
    scale: float = Field(default=1, ge=0.2, le=3)
    origin: tuple[float, float, float] = (0, 0, 0)
    yaw_degrees: float = Field(default=0, ge=-180, le=180)
    # Normalized VRM uses RH +Y up, +Z forward, anatomical left on +X.
    # Reflect X into Unity LH +Y up/+Z forward; do not reflect Euler angles.
    tracker_bones: tuple[str, ...] = ("hips", "leftFoot", "rightFoot")
    head_alignment: bool = False
    avatar_id: AvatarId | None = None
    auto_bind: bool = False
    auto_calibrate: bool = True
    oscquery: bool = False

    @model_validator(mode="after")
    def coherent(self):
        if self.mode == "generated_vr" and (
            self.desktop_emotes
            or self.locomotion
            or self.head_alignment
            or self.yaw_degrees != 0
            or any(self.origin)
        ):
            raise ValueError(
                "generated_vr uses one model tracking space: disable presets, input locomotion, "
                "head alignment, and origin/yaw offsets"
            )
        if self.pose_driver_port in {9000, 9001, self.send_port, self.receive_port}:
            raise ValueError(
                "pose driver port must be separate from both clients' OSC ports"
            )
        allowed = set(FULL_BODY_TRACKER_BONES)
        if self.mode == "generated_vr":
            if "tracker_bones" not in self.model_fields_set:
                self.tracker_bones = FULL_BODY_TRACKER_BONES
            elif set(self.tracker_bones) != allowed:
                raise ValueError(
                    "generated_vr requires all eight body targets: hips, chest, "
                    "both feet, knees and elbows"
                )
        if (
            not self.tracker_bones
            or len(set(self.tracker_bones)) != len(self.tracker_bones)
            or not set(self.tracker_bones) <= allowed
        ):
            raise ValueError("select unique supported body tracker bones")
        if self.send_port == self.receive_port:
            raise ValueError("send and receive ports must differ")
        if {self.send_port, self.receive_port} & {9000, 9001}:
            raise ValueError(
                "9000/9001 are reserved for the observer; use dedicated AI client ports"
            )
        if self.oscquery:
            raise ValueError(
                "automatic OSCQuery discovery is disabled for independent AI routing; launch the AI client with explicit --osc ports"
            )
        if self.audio_enabled and not self.audio_device:
            raise ValueError("select the virtual cable playback endpoint explicitly")
        if self.microphone == "hold" and not self.audio_enabled:
            raise ValueError("microphone hold control requires audio output")
        return self

    def capabilities(self):
        return {
            "mode": self.mode,
            "body_trackers": self.mode in {"vr_trackers", "generated_vr"},
            "body_target_bones": list(self.tracker_bones)
            if self.mode in {"vr_trackers", "generated_vr"}
            else [],
            "requires_fbt_calibration": self.mode in {"vr_trackers", "generated_vr"},
            "exact_joint_playback": False,
            "head_and_hand_devices": "generated OpenVR head, wrists and articulated fingers"
            if self.mode == "generated_vr"
            else "external VR devices required"
            if self.mode == "vr_trackers"
            else "unavailable in desktop mode",
            "arbitrary_desktop_bone_animation": False,
            "desktop_body": "SDK avatar emotes (not generated joint playback)"
            if self.desktop_emotes and self.mode == "desktop"
            else "no body-animation output",
            "world_position_observed": False,
            "voice": "selected audio endpoint" if self.audio_enabled else "disabled",
            "mouth": "VRChat microphone lip sync",
            "hands": "model joint FK through OpenVR skeletal input"
            if self.mode == "generated_vr"
            else "custom avatar pose parameters; skeletal tracking requires a separate driver",
        }


class ConversationTurn(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ConnectRequest(StrictModel):
    config: BridgeConfig = Field(default_factory=BridgeConfig)
    motion_backend: Literal["motioncraft", "syntalker"] = "motioncraft"
    voice: str | None = Field(default=None, max_length=80)
    persona: str | None = Field(default=None, max_length=4000)
    autonomous_decisions: int = Field(default=3, ge=0, le=10)
    history: list[ConversationTurn] = Field(default_factory=list, max_length=24)


class ControlRequest(StrictModel):
    action: Literal["pause", "resume", "interrupt", "disconnect"]


class SessionSettings(StrictModel):
    motion_backend: Literal["motioncraft", "syntalker"]
    voice: str | None = Field(default=None, max_length=80)
    persona: str | None = Field(default=None, max_length=4000)
    autonomous_decisions: int = Field(default=3, ge=0, le=10)
    desktop_emotes: bool = False


class MessageRequest(StrictModel):
    text: str = Field(min_length=1, max_length=4000)


FACE_PARAMETERS = {
    "AI_Smile": ("mouthSmileLeft", "mouthSmileRight"),
    "AI_Sad": ("mouthFrownLeft", "mouthFrownRight"),
    "AI_Angry": ("browDownLeft", "browDownRight"),
    "AI_Surprised": ("eyeWideLeft", "eyeWideRight"),
    "AI_BrowUp": ("browInnerUp",),
    "AI_Cheek": ("cheekSquintLeft", "cheekSquintRight"),
}
HAND_PARAMETERS = ("AI_LeftHandPose", "AI_RightHandPose")
PARAMETER_BUDGET_BITS = 1 + 8 * (len(FACE_PARAMETERS) + len(HAND_PARAMETERS))
