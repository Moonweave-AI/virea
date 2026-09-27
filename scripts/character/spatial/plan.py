"""Explicit spatial constraints for a bounded, interruptible action trajectory."""

import math

import numpy as np
import torch
from ardy.constraints import EndEffectorConstraintSet, Root2DConstraintSet


class PointConstraints:
    def __init__(self, indices, *, root_y):
        self.frame_indices = torch.tensor(indices, dtype=torch.long)
        self.root_y = root_y

    def update_constraints(self, data, index):
        data["root_y_pos"].append(torch.tensor(self.root_y, dtype=torch.float32))
        index["root_y_pos"].append(self.frame_indices)


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
        self.reference = None
        delta = self.target[[0, 2]] - self.origin[[0, 2]]
        distance = float(np.linalg.norm(delta))
        self.heading = (
            math.atan2(float(delta[0]), float(delta[1])) if distance > 0.02 else 0
        )
        self.duration = (
            min(30, max(2.4, distance / 0.65 + 1.6)) if self.kind == "move_to" else 4.8
        )
        self.frames = (
            math.ceil(self.duration * engine.fps / engine.horizon) * engine.horizon
        )
        self.prompt = {
            "move_to": "A person walks naturally toward a destination, then slows down and stands relaxed.",
            "reach": "A person gently reaches forward with their right hand to touch an object.",
            "sit": "A person bends their knees and sits down naturally on a chair.",
            "stand": "A person stands up from a chair and stands relaxed.",
            "perform": action.get("description") or "A person stands relaxed.",
        }[self.kind]

    def constraints(self, generated, history):
        history_frames = history.shape[1]
        if self.reference is None:
            self.reference = self.engine.model.motion_rep.inverse(
                history[:, -1:], is_normalized=True
            )
        skel = self.engine.model.skeleton
        remaining = self.frames - generated
        horizon = min(remaining, 48)
        index = list(range(history_frames + 3, history_frames + horizon, 4))
        if self.kind == "move_to":
            # Native root constraints guide leg motion. Never slide the rendered
            # actor on a separate engine translation clock.
            total = max(1, self.frames - 20)
            progress = np.clip((np.arange(3, horizon, 4) + generated) / total, 0, 1)
            # Ease departure/arrival without restarting at each inference window.
            u = progress * progress * (3 - 2 * progress)
            path = self.origin[None] + (self.target - self.origin)[None] * u[:, None]
            arrival = np.clip((progress - 0.6) / 0.4, 0, 1)
            headings = self.heading * (1 - arrival * arrival * (3 - 2 * arrival))
            return [
                Root2DConstraintSet(
                    skel,
                    torch.tensor(index),
                    torch.tensor(path[:, [0, 2]], dtype=torch.float32),
                    global_root_heading=torch.tensor(headings, dtype=torch.float32),
                ),
                PointConstraints(
                    index, root_y=(path[:, 1] + self.engine.hip_height).tolist()
                ),
            ]
        if self.kind == "reach":
            # Keep the planted feet and pelvis; move the hand along one
            # continuous goal trajectory, not a new target for every window.
            positions = self.reference["posed_joints"][0].cpu().repeat(len(index), 1, 1)
            rotations = (
                self.reference["global_rot_mats"][0].cpu().repeat(len(index), 1, 1, 1)
            )
            progress = np.clip(
                (np.arange(3, horizon, 4) + generated) / max(1, self.frames - 24), 0, 1
            )
            u = torch.tensor(
                progress * progress * (3 - 2 * progress), dtype=torch.float32
            )[:, None]
            hand = skel.bone_index["RightHand"]
            delta = (torch.tensor(self.target) - positions[0, hand]) * u
            for name in skel.right_hand_joint_names:
                positions[:, skel.bone_index[name]] += delta
            return [
                EndEffectorConstraintSet(
                    skel,
                    torch.tensor(index),
                    positions,
                    rotations,
                    None,
                    joint_names=["Hips", "LeftFoot", "RightFoot", "RightHand"],
                ),
                Root2DConstraintSet(
                    skel,
                    torch.tensor(index),
                    torch.tensor(self.origin[[0, 2]])[None].repeat(len(index), 1),
                ),
            ]
        if self.kind == "sit":
            at = history_frames + min(remaining, 48) - 1
            return [
                Root2DConstraintSet(
                    skel, torch.tensor([at]), torch.tensor(self.target[[0, 2]])[None]
                ),
                PointConstraints([at], root_y=[float(self.target[1] + 0.1)]),
            ]
        return []
