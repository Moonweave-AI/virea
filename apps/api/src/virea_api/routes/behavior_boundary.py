"""Prepare one native constrained handoff to future, already available speech."""

import asyncio
from math import ceil

from virea.character.behavior import WindowChoice
from virea.character.contracts import BodyState
from virea.character.expression_boundary import expression_boundary


async def native_window(current, client):
    response = await client.get(current.config.spatial_url.rstrip("/") + "/health")
    response.raise_for_status()
    return response.json()


async def plan_expression_handoff(current, client, previous, observation, choice):
    if not (
        previous
        and previous["owner"] == "ardy"
        and choice.owner == "sentiavatar"
        and previous.get("transition_to") != choice.owner
        and getattr(current, "motion", None)
    ):
        return None
    native = await native_window(current, client)
    if not native.get("full_body_boundary_constraints"):
        raise ValueError("Spatial worker needs the full-body boundary adapter")
    quantum = native["window_frames"] / native["fps"]
    measured = max(
        (
            s.get("generation_seconds", 0)
            for s in current.behavior_slots.values()
            if s.get("transition_to")
        ),
        default=0,
    )
    seconds = max(quantum, ceil((measured + 1 / native["fps"]) / quantum) * quantum)
    remaining = (
        max(
            0,
            previous.get("playback_start_clock", observation.speech.clock_seconds)
            + previous["seconds"]
            - observation.speech.clock_seconds,
        )
        if previous["status"] == "playing"
        else 0
    )
    # A completed predecessor provides no generation buffer. Reserve computation
    # time as well as motion time; the player waits for this scheduled start.
    compute_lead = (measured or quantum) + 1 / native["fps"]
    lead = seconds + max(remaining, compute_lead)
    initial = BodyState.model_validate(previous["forecast"])
    boundary = await asyncio.to_thread(
        expression_boundary,
        current.motion.control,
        list(current.ready.values()),
        observation.speech,
        lead,
        initial,
        fps=native["fps"],
    )
    if not boundary:
        return None
    action = dict(previous["actions"][-1], duration_seconds=seconds)
    return dict(
        choice=WindowChoice(
            owner="ardy",
            executor=previous["executor"],
            seconds=seconds,
            reason="ARDY 以即将播放的 SentiAvatar 身体轨迹为末端运动学约束",
        ),
        actions=[action],
        transition_to="sentiavatar",
        boundary=boundary,
        boundary_clock=observation.speech.clock_seconds + lead,
        boundary_frame_seconds=1 / native["fps"],
    )
