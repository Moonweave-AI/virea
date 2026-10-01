"""Native full-body conditions for a transition to an already generated model."""

import torch
from ardy.constraints import FullBodyConstraintSet
from ardy.postprocess import post_process_motion


def boundary_constraints(engine, samples, frame_indices, scale):
    history = engine.observed_history(samples, scale)
    data = engine.model.motion_rep.inverse(
        history[:, -len(samples) :], is_normalized=True
    )
    positions = data["posed_joints"][0].clone()
    # SentiAvatar playback aligns its feet to the current floor. Express the same
    # target on the native skeleton; retaining an ARDY airborne pelvis would make
    # an impossible airborne "standing" target at a model handoff.
    floor = torch.tensor(
        [s["position"]["y"] / scale for s in samples], device=positions.device
    )
    lift = floor - positions[:, :, 1].amin(dim=1)
    positions[:, :, 1] += lift[:, None]
    return FullBodyConstraintSet(
        engine.model.skeleton,
        torch.tensor(frame_indices, dtype=torch.long),
        positions,
        data["global_rot_mats"][0],
    )


def correct_boundary(model, history, generated, constraints):
    """Use the official rotation-aware solver on new frames and a frozen prefix.

    Predicted foot contacts are not activated here: this operation resolves known
    model handoff keyframes. It must not add unrelated foot locks to the activity.
    """
    start, end = history.shape[1], history.shape[1] + generated.shape[1]
    full = [
        c
        for c in constraints
        if isinstance(c, FullBodyConstraintSet)
        and bool(((c.frame_indices >= start) & (c.frame_indices < end)).any())
    ]
    if not full:
        return generated
    prefix = min(model.num_frames_per_token, start)
    data = model.motion_rep.inverse(
        torch.cat((history[:, -prefix:], generated), dim=1), is_normalized=True
    )
    goals = [c.crop_move(start - prefix, end) for c in full]
    goals.append(
        FullBodyConstraintSet(
            model.skeleton,
            torch.arange(prefix),
            data["posed_joints"][0, :prefix],
            data["global_rot_mats"][0, :prefix],
        )
    )
    corrected = post_process_motion(
        data["local_rot_mats"],
        data["root_positions"],
        torch.zeros_like(data["foot_contacts"]),
        model.skeleton,
        constraint_lst=goals,
    )
    return model.motion_rep(
        corrected["local_rot_mats"][:, prefix:],
        corrected["root_positions"][:, prefix:],
        to_normalize=True,
    )
