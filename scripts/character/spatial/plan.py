"""Explicit spatial constraints for a bounded, interruptible action trajectory."""

import math

import numpy as np
import torch
from ardy.constraints import Root2DConstraintSet


class PointConstraints:
    def __init__(self, indices, *, root_y):
        self.frame_indices = torch.tensor(indices, dtype=torch.long)
        self.root_y = root_y

    def update_constraints(self, data, index):
        data["root_y_pos"].append(torch.tensor(self.root_y, dtype=torch.float32))
        index["root_y_pos"].append(self.frame_indices)


class HandGoal:
    """Sparse hand POSITION goal; no invented wrist orientation or frozen pelvis."""

    def __init__(self, indices, hand_index, target, root_index, root):
        self.frame_indices = torch.tensor(indices, dtype=torch.long)
        self.hand_index, self.target = (
            hand_index,
            torch.as_tensor(target, dtype=torch.float32),
        )
        self.root_index, self.root = (
            root_index,
            torch.as_tensor(root, dtype=torch.float32),
        )

    def update_constraints(self, data, index):
        # ARDY converts world hand goals into root-relative position features.
        # The root row supplies that reference; it does NOT constrain pelvis Y.
        count = len(self.frame_indices)
        data["global_joints_positions"].append(
            torch.stack((self.root, self.target)).repeat(count, 1)
        )
        index["global_joints_positions"].append(
            torch.stack(
                (
                    self.frame_indices.repeat_interleave(2),
                    torch.tensor([self.root_index, self.hand_index]).repeat(count),
                ),
                dim=1,
            )
        )
        data["root_2d"].append(self.root[[0, 2]][None].repeat(count, 1))
        index["root_2d"].append(self.frame_indices)


class SpatialPlan:
    def __init__(self, engine, action, origin, *, scale=1):
        self.engine, self.action, self.scale = engine, action, scale
        self.origin = np.asarray(origin, dtype=np.float32) / scale
        self.target = (
            np.array(
                [action["position"][axis] for axis in ("x", "y", "z")], dtype=np.float32
            )
            / scale
            if action.get("position")
            else self.origin.copy()
        )
        self.kind = action["kind"]
        delta = self.target[[0, 2]] - self.origin[[0, 2]]
        distance = float(np.linalg.norm(delta))
        self.duration = action.get("duration_seconds") or (
            min(30, max(2.4, distance / 0.65 + 1.6)) if self.kind == "move_to" else 4.8
        )
        if self.kind == "reach":
            self.duration = max(2.4, self.duration)
        self.frames = (
            math.ceil(self.duration * engine.fps / engine.horizon - 1e-9)
            * engine.horizon
        )
        self.prompt = (
            action.get("description")
            or {
                "move_to": "A person walks naturally toward a destination, then slows down and stands relaxed.",
                "reach": "A person gently reaches forward with their right hand to touch an object.",
                "sit": "A person bends their knees and sits down naturally on a chair.",
                "stand": "A person stands up from a chair and stands relaxed.",
                "perform": action.get("description") or "A person stands relaxed.",
            }[self.kind]
        )

    def constraints(self, generated, history):
        history_frames = history.shape[1]
        skel = self.engine.model.skeleton
        remaining = self.frames - generated
        horizon = min(remaining, 200 - history_frames)
        index = list(range(history_frames + 3, history_frames + horizon, 4))
        if self.kind == "move_to":
            # Native root constraints guide leg motion. Never slide the rendered
            # actor on a separate engine translation clock.
            total = max(1, self.frames - 20)
            progress = np.clip((np.arange(3, horizon, 4) + generated) / total, 0, 1)
            # Ease departure/arrival without restarting at each inference window.
            u = progress * progress * (3 - 2 * progress)
            path = self.origin[None] + (self.target - self.origin)[None] * u[:, None]
            return [
                Root2DConstraintSet(
                    skel,
                    torch.tensor(index),
                    torch.tensor(path[:, [0, 2]], dtype=torch.float32),
                ),
            ]
        if self.kind == "reach":
            # Leave the approach unconstrained. Far-future sparse goals let the
            # native model coordinate balance, elbow, shoulder and torso itself.
            contact_at = max(7, self.frames - 9)
            indices = [
                history_frames + frame - generated
                for frame in (contact_at, self.frames - 1)
                if generated <= frame < generated + horizon
            ]
            return (
                [
                    HandGoal(
                        indices,
                        skel.bone_index["RightHand"],
                        self.target,
                        skel.root_idx,
                        self.origin,
                    )
                ]
                if indices
                else []
            )
        if self.kind == "sit":
            at = history_frames + min(remaining, 48) - 1
            return [
                Root2DConstraintSet(
                    skel, torch.tensor([at]), torch.tensor(self.target[[0, 2]])[None]
                ),
                PointConstraints([at], root_y=[float(self.target[1] + 0.1)]),
            ]
        return []
