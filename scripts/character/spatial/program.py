"""One native history and one frame counter for a sequence of changing prompts."""

import asyncio

from .plan import SpatialPlan


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
    async with lock:
        height = body.get("pelvis_height")
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
        # Embedding compilation is cached; it happens once per phase, never once
        # per frame. Read-ahead playback hides later prompt encoding latency.
        for generated in range(0, frames, engine.horizon):
            if await request.is_disconnected():
                return
            async with lock:
                constraints = plan.constraints(generated, history)
                history, packet = await asyncio.to_thread(
                    engine.step,
                    history,
                    plan.prompt,
                    constraints,
                    steps=steps,
                    guidance=guidance,
                    history_frames=history_frames,
                    foot_correction=False,
                    output_frames=min(engine.horizon, frames - generated),
                )
            frame = offset + generated
            packet.update(
                sequence=sequence,
                offset=frame / engine.fps,
                total_seconds=total_frames / engine.fps,
                phase_index=phase_index,
                phase_label=action.get("label") or action["kind"],
                phase_kind=action["kind"],
                phase_seconds=frames / engine.fps,
                phase_offset=offset / engine.fps,
                prompt=plan.prompt,
                target=action.get("position"),
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
