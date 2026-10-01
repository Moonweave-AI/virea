"""One native history and one frame counter for a sequence of changing prompts."""

import asyncio

import numpy as np

from .boundary import boundary_constraints
from .plan import SpatialPlan
from .trajectory import waypoint_velocity


async def generate_program(
    engine,
    lock,
    request,
    *,
    actions,
    body,
    hip_height,
    steps,
    guidance,
    end_state,
    history_frames=40,
    max_seconds=None,
    end_pose_samples=None,
):
    origin = [body["position"][axis] for axis in ("x", "y", "z")]
    scale = hip_height / engine.hip_height
    # Estimate phase durations once, then reuse them when each phase starts from
    # its ACTUAL predecessor endpoint. No resets, HTTP gaps or per-phase recovery.
    planned_origin = origin
    phases = []
    for action in actions:
        plan = SpatialPlan(engine, action, planned_origin, scale=scale)
        phases.append((action, plan.frames))
        if action["kind"] == "move_to":
            planned_origin = [action["position"][axis] for axis in ("x", "y", "z")]
    total_frames = sum(frames for _, frames in phases)
    output_frames = (
        min(total_frames, round(max_seconds * engine.fps))
        if max_seconds
        else total_frames
    )
    async with lock:
        height = body.get("pelvis_height")
        if body.get("history"):
            history = await asyncio.to_thread(
                engine.observed_history, body["history"], scale
            )
        else:
            history = await asyncio.to_thread(
                engine.initial_history,
                body["pose"],
                [v / scale for v in origin],
                body.get("yaw", 0),
                height / scale if height is not None else None,
            )
        history = history[:, -history_frames:]
    offset = 0
    sequence = 0
    for phase_index, (action, frames) in enumerate(phases):
        if await request.is_disconnected():
            return
        root = (
            engine.model.motion_rep.inverse(history[:, -1:], is_normalized=True)[
                "root_positions"
            ][0, 0]
            .cpu()
            .tolist()
        )
        phase_origin = [root[0] * scale, origin[1], root[2] * scale]
        plan = SpatialPlan(engine, action, phase_origin, scale=scale)
        plan.frames = frames
        roots = (
            engine.model.motion_rep.inverse(history[:, -4:], is_normalized=True)[
                "root_positions"
            ][0]
            .cpu()
            .numpy()
        )
        if len(roots) > 1:
            plan.entry_velocity = (roots[-1] - roots[0]) * engine.fps / (len(roots) - 1)
            plan.entry_velocity[1] = 0
        if action["kind"] == "move_to" and phase_index + 1 < len(phases):
            following, following_frames = phases[phase_index + 1]
            if following["kind"] == "move_to":
                destination = (
                    np.array([following["position"][axis] for axis in ("x", "y", "z")])
                    / scale
                )
                plan.exit_velocity = waypoint_velocity(
                    plan.origin,
                    plan.target,
                    destination,
                    frames / engine.fps,
                    following_frames / engine.fps,
                )
        # Embedding compilation is cached; it happens once per phase, never once
        # per frame. Read-ahead playback hides later prompt encoding latency.
        for generated in range(0, frames, engine.horizon):
            if offset + generated >= output_frames:
                return
            if await request.is_disconnected():
                return
            async with lock:
                constraints = plan.constraints(generated, history)
                if end_pose_samples:
                    first = output_frames - len(end_pose_samples)
                    if first < 0:
                        raise ValueError("Boundary samples exceed the generated window")
                    indices = [
                        history.shape[1] + first + i - offset - generated
                        for i in range(len(end_pose_samples))
                    ]
                    if indices[-1] >= history.shape[1]:
                        constraints.append(
                            boundary_constraints(
                                engine, end_pose_samples, indices, scale
                            )
                        )
                prompt = (
                    (
                        action.get("transition_description")
                        if phase_index + 1 < len(phases)
                        and generated + engine.horizon >= frames
                        else None
                    )
                    or (action.get("continuation_description") if generated else None)
                    or plan.prompt
                )
                history, packet = await asyncio.to_thread(
                    engine.step,
                    history,
                    prompt,
                    constraints,
                    steps=steps,
                    guidance=guidance,
                    history_frames=history_frames,
                    foot_correction=False,
                    output_frames=min(
                        engine.horizon,
                        frames - generated,
                        output_frames - offset - generated,
                    ),
                )
            frame = offset + generated
            packet.update(
                sequence=sequence,
                offset=frame / engine.fps,
                total_seconds=output_frames / engine.fps,
                phase_index=phase_index,
                phase_label=action.get("label") or action["kind"],
                phase_kind=action["kind"],
                phase_seconds=frames / engine.fps,
                phase_offset=offset / engine.fps,
                prompt=prompt,
                target=action.get("position"),
                boundary_conditioned=bool(end_pose_samples),
                continues=frame + round(packet["seconds"] * engine.fps) < total_frames,
            )
            packet["root"] = [[v * scale for v in row] for row in packet["root"]]
            packet["joints"] = {
                name: [[v * scale for v in row] for row in rows]
                for name, rows in packet["joints"].items()
            }
            packet["hip_height"] *= scale
            yield packet
            sequence += 1
        offset += frames
