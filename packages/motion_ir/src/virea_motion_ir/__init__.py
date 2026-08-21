"""Motion IR v2.

The in-memory model keeps numerical tensors separate from the JSON descriptor.
The public canonical211 bridge is a field-preserving compatibility transform;
it does not alter VIREA's existing retarget mathematics.
"""

from .compatibility.canonical211_v3 import (
    CANONICAL211_FRAME_DIM,
    CANONICAL211_JOINT_NAMES,
    CANONICAL211_PROFILE,
    CANONICAL211_SCHEMA,
    canonical211_to_motion_ir,
    motion_ir_to_canonical211,
)
from .model import ActorMotion, MotionIR
from .storage import load_motion_ir, save_motion_ir

__all__ = [
    "ActorMotion",
    "CANONICAL211_FRAME_DIM",
    "CANONICAL211_JOINT_NAMES",
    "CANONICAL211_PROFILE",
    "CANONICAL211_SCHEMA",
    "MotionIR",
    "canonical211_to_motion_ir",
    "load_motion_ir",
    "motion_ir_to_canonical211",
    "save_motion_ir",
]

__version__ = "0.4.0"
