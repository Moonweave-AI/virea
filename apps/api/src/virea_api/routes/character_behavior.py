"""Rolling reservations, realization and receipts for exclusive body ownership."""

import json
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from virea.character.behavior import BehaviorRequest, choose_window, motion_forecast
from virea.character.contracts import BodyState, Contract

router = APIRouter()


def current_session(request, session_id):
    try:
        return request.app.state.characters.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, "character session not found") from exc


def slot_for(current, slot_id):
    slot = current.behavior_slots.get(slot_id)
    program_id = (current.body_program or {}).get("id")
    if (
        not slot
        or (
            slot["program_id"] != program_id
            and slot["status"] not in {"playing", "completed"}
        )
        or current.status == "closed"
        or (
            slot["epoch"] != current.epoch
            and slot["status"] not in {"playing", "completed"}
        )
    ):
        raise HTTPException(409, "behavior reservation is stale")
    return slot


def reservation_view(slot):
    return {
        k: v for k, v in slot.items() if k not in {"actions", "forecast", "windows"}
    }


@router.post("/{session_id}/behavior/plan")
async def plan_behavior(session_id: str, body: BehaviorRequest, request: Request):
    current = current_session(request, session_id)
    async with current.behavior_lock:
        program = current.body_program
        epoch = current.epoch
        program_id = (program or {}).get("id")
        previous = slot_for(current, body.after) if body.after else None
        active = next(
            (s for s in current.behavior_slots.values() if s["status"] == "playing"),
            None,
        )
        if active and body.after != active["id"]:
            raise HTTPException(409, "a successor must follow the active body owner")
        # A successor can be prepared while its immediate predecessor executes.
        if previous and previous["status"] not in {"playing", "completed"}:
            raise HTTPException(409, "predecessor has not started")
        existing = next(
            (
                s
                for s in current.behavior_slots.values()
                if s["after"] == body.after
                and s["program_id"] == program_id
                and s["status"] in {"planned", "generating", "ready"}
                and s["epoch"] == current.epoch
            ),
            None,
        )
        if existing:
            return reservation_view(existing)
        elapsed = (
            previous["activity_end"]
            if previous and previous["program_id"] == program_id
            else (program or {}).get("elapsed", 0)
        )
        choice, actions = await choose_window(
            current.config,
            request.app.state.characters.client,
            program=program,
            elapsed=elapsed,
            body=body.body,
            speech=body.speech,
            previous=previous["owner"] if previous else None,
        )
        if (
            current.body_program is not program
            or current.epoch != epoch
            or current.status == "closed"
        ):
            raise HTTPException(409, "behavior intent changed while planning")
        slot = dict(
            id=uuid4().hex,
            after=body.after,
            program_id=program_id,
            epoch=current.epoch,
            owner=choice.owner,
            seconds=choice.seconds,
            reason=choice.reason,
            speech_available=body.speech.available,
            phase_index=len((program or {}).get("actions", [])) - len(actions),
            activity_start=elapsed,
            activity_end=elapsed + (choice.seconds if choice.owner == "ardy" else 0),
            actions=actions,
            status="planned",
        )
        current.behavior_slots[slot["id"]] = slot
        # Keep the current and immediate future, plus a bounded diagnostic tail.
        for key in list(current.behavior_slots)[:-16]:
            del current.behavior_slots[key]
        current.record(
            "behavior_planned", **{k: v for k, v in slot.items() if k != "actions"}
        )
        return reservation_view(slot)


class RealizationRequest(Contract):
    body: BodyState
    hip_height: float = Field(gt=0.2, lt=3)


@router.post("/{session_id}/behavior/{slot_id}/motion")
async def realize_behavior(
    session_id: str, slot_id: str, body: RealizationRequest, request: Request
):
    current = current_session(request, session_id)
    slot = slot_for(current, slot_id)
    if slot["status"] == "ready" and slot.get("windows"):
        return {"windows": slot["windows"], "seconds": slot["seconds"]}
    if slot["status"] != "planned" or slot["owner"] != "ardy":
        raise HTTPException(409, "slot is not an unclaimed ARDY reservation")
    slot["status"] = "generating"
    previous = current.behavior_slots.get(slot["after"])
    # Consecutive ARDY windows use the exact committed predecessor forecast.
    initial = (
        BodyState.model_validate(previous["forecast"])
        if previous and previous.get("forecast")
        else body.body
    )
    manager = request.app.state.characters
    windows = []
    started = monotonic()
    try:
        async with manager.client.stream(
            "POST",
            current.config.spatial_url.rstrip("/") + "/generate",
            json={
                "actions": slot["actions"],
                "body": initial.model_dump(),
                "hip_height": body.hip_height,
                "end_state": "hold",
                "max_seconds": slot["seconds"],
                "history_frames": current.config.spatial_history_frames,
            },
            timeout=current.config.provider_timeout,
        ) as response:
            response.raise_for_status()
            done = False
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("error"):
                    raise ValueError(item["error"])
                if item.get("done"):
                    done = True
                else:
                    item["phase_index"] = slot["phase_index"] + item.get(
                        "phase_index", 0
                    )
                    windows.append(item)
            if not done:
                raise ValueError("ARDY stream ended without completion")
        slot_for(current, slot_id)
        slot["forecast"] = motion_forecast(windows, initial).model_dump()
        slot["status"] = "ready"
        slot["windows"] = windows
        slot["generation_seconds"] = monotonic() - started
        return {"windows": windows, "seconds": slot["seconds"]}
    except HTTPException:
        slot["status"] = "interrupted"
        raise
    except Exception:
        slot["status"] = "failed"
        if (
            current.body_program
            and slot["program_id"] == current.body_program["id"]
            and slot["epoch"] == current.epoch
        ):
            current.body_program["status"] = "failed"
        raise


class SlotReceipt(Contract):
    status: str = Field(pattern="^(playing|completed|interrupted|failed)$")
    body: BodyState


@router.post("/{session_id}/behavior/{slot_id}/feedback")
async def behavior_feedback(
    session_id: str, slot_id: str, body: SlotReceipt, request: Request
):
    current = current_session(request, session_id)
    slot = slot_for(current, slot_id)
    allowed = {
        "playing": {"ready", "planned"},
        "completed": {"playing"},
        "interrupted": {"playing", "ready", "planned"},
        "failed": {"playing", "ready", "planned"},
    }
    if slot["status"] not in allowed[body.status] or (
        body.status == "playing"
        and slot["owner"] == "ardy"
        and slot["status"] != "ready"
    ):
        raise HTTPException(409, "invalid behavior receipt")
    if body.status == "playing":
        if any(s["status"] == "playing" for s in current.behavior_slots.values()):
            raise HTTPException(409, "body already has an active owner")
        previous = current.behavior_slots.get(slot["after"])
        if previous and previous["status"] != "completed":
            raise HTTPException(409, "body is still owned by predecessor")
    was_playing = slot["status"] == "playing"
    slot["status"] = body.status
    current.body = body.body
    if (
        current.body_program
        and slot["program_id"] == current.body_program["id"]
        and body.status in {"failed", "interrupted"}
        and was_playing
    ):
        current.body_program["status"] = body.status
    if (
        current.body_program
        and slot["program_id"] == current.body_program["id"]
        and body.status == "completed"
    ):
        current.body_program["elapsed"] = slot["activity_end"]
        duration = sum(
            a.get("duration_seconds") or 4.8 for a in current.body_program["actions"]
        )
        current.body_program["status"] = (
            "completed" if slot["activity_end"] >= duration - 1e-5 else "playing"
        )
    current.record(
        "behavior_feedback", slot_id=slot_id, owner=slot["owner"], status=body.status
    )
    return {"accepted": True}
