"""Measured terminal acceptance, separate from semantic activity duration."""

import math

from pydantic import BaseModel, ConfigDict, Field


class SettlementPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    max_seconds: float = Field(default=16.0, ge=4, le=60)
    observation_seconds: float = Field(default=0.6, ge=0.2, le=2)
    support_height_ratio: float = Field(default=0.12, gt=0, le=0.3)
    root_speed_ratio: float = Field(default=0.18, gt=0, le=1)
    joint_speed_ratio: float = Field(default=0.32, gt=0, le=2)


def terminal_measurement(windows, floor, policy):
    """Support can be a foot, knee, hand or pelvis; no standing template is used."""
    window = windows[-1]
    count = max(2, round(policy.observation_seconds * window["fps"]) + 1)
    scale = window["hip_height"]
    roots = window["root"][-count:]
    joints = [rows[-count:] for rows in window.get("joints", {}).values()]

    def speed(rows):
        return [math.dist(a, b) * window["fps"] / scale for a, b in zip(rows, rows[1:])]

    heights = (
        [min(rows[i][1] for rows in joints) - floor for i in range(len(roots))]
        if joints
        else [math.inf]
    )
    root_speed = max(speed(roots), default=math.inf)
    joint_speeds = [v for rows in joints for v in speed(rows)]
    joint_speed = (
        math.sqrt(sum(v * v for v in joint_speeds) / len(joint_speeds))
        if joint_speeds
        else math.inf
    )
    supported = max(heights) / scale <= policy.support_height_ratio
    # Missing geometry cannot authorize a terminal hold.
    return dict(
        supported=supported,
        clearance=max(heights) if joints else None,
        root_speed=root_speed,
        joint_speed=joint_speed if joints else None,
        settled=supported
        and root_speed <= policy.root_speed_ratio
        and joint_speed <= policy.joint_speed_ratio,
    )
