"""Rolling reservations, realization and receipts for exclusive body ownership."""

import json
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from virea.character.behavior import (
    AllocationUnavailable,
    BehaviorRequest,
    WindowChoice,
    choose_window,
    motion_forecast,
    remaining_actions,
)
from virea.character.contracts import BodyState, Contract
from virea.character.coordination import (
    anchor_reached,
    observe_program,
    phase_anchor,
    unavailable_anchor,
)
from virea.character.executors import available_executors
from virea.character.motion_timing import planned_duration
from virea.character.providers.reallocation import reallocate_phase
from virea.character.providers.recovery import plan_recovery
from virea.character.settlement import terminal_measurement

router = APIRouter()


def current_session(request, session_id):
    try:
        return request.app.state.characters.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, "character session not found") from exc


def slot_for(current, slot_id):
    slot = current.behavior_slots.get(slot_id)
    program_id = (current.body_program or {}).get("id")
    released = bool((current.body_program or {}).get("finish_requested"))
    if (
        not slot
        or (
            slot["program_id"] != program_id
            and slot["status"] not in {"playing", "completed"}
        )
        or current.status == "closed"
        or (
            released
            and slot
            and slot["program_id"] == program_id
            and not slot.get("settling")
            and slot["status"] not in {"playing", "completed"}
        )
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
        observe_program(program, body.speech)
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
                and (not (program or {}).get("finish_requested") or s.get("settling"))
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
        missing = unavailable_anchor(
            program, elapsed, body.speech, epoch, current.status == "error"
        )
        if (
            missing
            and program
            and program.get("status") not in {"completed", "failed", "interrupted"}
        ):
            program["status"] = "failed"
            current.record("body_error", program_id=program_id, message=missing)
            if getattr(current, "timing", None):
                current.timing.fail(missing)
        settling = bool(
            program
            and (
                program.get("ending")
                or program.get("recovery_required")
                or (
                    previous
                    and previous["program_id"] == program_id
                    and previous.get("support", {}).get("settled") is False
                )
            )
            and (
                program.get("finish_requested")
                or not remaining_actions(program, elapsed)
            )
            and program.get("status") not in {"completed", "failed", "interrupted"}
        )
        settled_seconds = (
            previous.get("settled_seconds", 0)
            if previous and previous["program_id"] == program_id
            else (program or {}).get("settled_seconds", 0)
        )
        if settling:
            policy = current.config.settlement
            if settled_seconds >= policy.max_seconds:
                program["status"] = "failed"
                current.record("body_error", message="收势未达到支撑和速度要求")
                if getattr(current, "timing", None):
                    current.timing.fail("Recovery ended without stable support")
                raise HTTPException(422, "收势尚未达到支撑和速度要求，请重新规划动作")
            ending_executor = program.get("ending_executor")
            seconds = program.get("ending_seconds")
            caption = program.get("ending")
            reason = program.get("ending_reason") or "执行 LLM 规划的最终恢复"
            # Recovery is one adopted activity spanning native windows. Its
            # measured completion decides when to stop, not another semantic
            # rewrite between every pair of windows.
            if not caption:
                recovery = await plan_recovery(
                    current.config,
                    request.app.state.characters.client,
                    program=program,
                    previous=previous,
                    body=body.body,
                    budget=policy.max_seconds - settled_seconds,
                )
                ending_executor, seconds, caption, reason = (
                    recovery.executor,
                    recovery.seconds,
                    recovery.goal,
                    recovery.reason,
                )
                if current.body_program is not program or current.epoch != epoch:
                    raise HTTPException(409, "behavior intent changed while planning")
                program.update(
                    ending_executor=ending_executor,
                    ending_seconds=seconds,
                    ending=caption,
                    ending_reason=reason,
                )
            spec = available_executors(current.config).get(ending_executor)
            if not spec or spec.requires_speech or seconds is None:
                raise HTTPException(422, "最终恢复缺少可执行的模型分配")
            seconds = min(seconds, policy.max_seconds - settled_seconds)
            actions = [
                dict(
                    kind="perform",
                    description=caption,
                    label="自然收势",
                    duration_seconds=seconds,
                )
            ]
            choice = WindowChoice(
                owner=spec.source,
                executor=ending_executor,
                seconds=seconds,
                reason=reason,
            )
        else:
            try:
                for attempt in range(2):
                    try:
                        choice, actions = await choose_window(
                            current.config,
                            request.app.state.characters.client,
                            program=program,
                            elapsed=elapsed,
                            body=body.body,
                            speech=body.speech,
                            previous=previous["owner"] if previous else None,
                            expression_executor=(
                                getattr(current, "route", None) or {}
                            ).get("expression_executor"),
                        )
                        break
                    except AllocationUnavailable as error:
                        if attempt:
                            raise
                        remaining = remaining_actions(program, elapsed)
                        phase = len(program["actions"]) - len(remaining)
                        revision = await reallocate_phase(
                            current.config,
                            request.app.state.characters.client,
                            program=program,
                            phase=phase,
                            remaining=remaining[0]["duration_seconds"],
                            body=body.body,
                            speech_usable=body.speech.available
                            and body.speech.epoch == program.get("origin_epoch"),
                            failure=str(error),
                        )
                        if (
                            current.epoch != epoch
                            or current.body_program is not program
                        ):
                            raise HTTPException(
                                409, "intent changed during reallocation"
                            )
                        program["executors"][phase] = revision.executor
                        program["actions"][phase].update(
                            description=revision.continuation,
                            continuation_description=revision.continuation,
                        )
                        current.record(
                            "body_replanned",
                            program_id=program_id,
                            phase=phase,
                            elapsed=elapsed,
                            allocation=revision.model_dump(),
                        )

            except ValueError as error:
                if program:
                    program["status"] = "failed"
                current.record("body_error", program_id=program_id, message=str(error))
                if getattr(current, "timing", None):
                    current.timing.fail(str(error))
                raise HTTPException(422, str(error)) from error

        # A semantic pause cannot freeze an airborne predecessor. Continue its
        # own motion until handoff is supported, without consuming the next cue.
        handoff = bool(
            previous
            and previous["owner"] == "ardy"
            and previous.get("support", {}).get("supported") is False
            and choice.owner != "ardy"
        )
        handoff_seconds = previous.get("handoff_seconds", 0) if handoff else 0
        if handoff:
            policy = current.config.settlement
            if handoff_seconds >= policy.max_seconds:
                if program:
                    program["status"] = "failed"
                current.record("body_error", message="身体交接未能恢复支撑")
                if getattr(current, "timing", None):
                    current.timing.fail("Body handoff ended without stable support")
                raise HTTPException(422, "身体交接未能恢复支撑")
            recovery = await plan_recovery(
                current.config,
                request.app.state.characters.client,
                program=program,
                previous=previous,
                body=body.body,
                budget=policy.max_seconds - handoff_seconds,
                purpose="handoff_to_next_phase",
            )
            seconds = recovery.seconds
            actions = [
                dict(
                    kind="perform", description=recovery.goal, duration_seconds=seconds
                )
            ]
            choice = WindowChoice(
                owner=available_executors(current.config)[recovery.executor].source,
                executor=recovery.executor,
                seconds=seconds,
                reason=recovery.reason,
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
            executor=choice.executor,
            advances_activity=choice.advances_activity,
            seconds=choice.seconds,
            reason=choice.reason,
            speech_available=body.speech.available,
            speech_active=body.speech.active,
            speech_clock=body.speech.clock_seconds,
            speech_epoch=body.speech.epoch,
            observed_marks=body.speech.marks,
            start_anchor=phase_anchor(program, elapsed).model_dump(),
            waiting_for=phase_anchor(program, elapsed).model_dump()
            if remaining_actions(program, elapsed)
            and not anchor_reached(phase_anchor(program, elapsed), program, body.speech)
            and not settling
            else None,
            speech_packet_id=body.speech.packet_id,
            speech_stream_id=body.speech.stream_id,
            phase_index=len((program or {}).get("actions", []))
            - len(remaining_actions(program, elapsed)),
            activity_start=elapsed,
            activity_end=elapsed
            + (
                choice.seconds
                if choice.advances_activity and not settling and not handoff
                else 0
            ),
            handoff=handoff,
            handoff_seconds=handoff_seconds + (choice.seconds if handoff else 0),
            settling=settling,
            settled_seconds=settled_seconds + (choice.seconds if settling else 0),
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
        return {
            "windows": slot["windows"],
            "seconds": slot["seconds"],
            "slot": reservation_view(slot),
        }
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
        slot["support"] = terminal_measurement(
            windows, initial.position.y, current.config.settlement
        )
        slot["terminal"] = bool(slot.get("settling") and slot["support"]["settled"])
        slot["status"] = "ready"
        slot["windows"] = windows
        slot["generation_seconds"] = monotonic() - started
        current.record(
            "behavior_ready",
            slot_id=slot_id,
            owner=slot["owner"],
            generation_seconds=slot["generation_seconds"],
            support=slot["support"],
            terminal=slot["terminal"],
            prompts=list(dict.fromkeys(w.get("prompt", "") for w in windows)),
        )
        return {
            "windows": windows,
            "seconds": slot["seconds"],
            "slot": reservation_view(slot),
        }
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
            timing = getattr(current, "timing", None)
            if timing and timing.epoch == current.epoch:
                timing.fail("Body generation failed before playback")
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
        and (slot.get("advances_activity") or slot.get("settling"))
        and current.body_program["status"] != "failed"
    ):
        current.body_program["elapsed"] = slot["activity_end"]
        current.body_program["settled_seconds"] = slot.get("settled_seconds", 0)
        duration = sum(planned_duration(a) for a in current.body_program["actions"])
        ended = slot["activity_end"] >= duration - 1e-5 or current.body_program.get(
            "finish_requested", False
        )
        current.body_program["recovery_required"] = bool(
            ended and slot.get("support", {}).get("settled") is False
        )
        current.body_program["status"] = (
            "completed"
            if slot.get("terminal")
            or (
                ended
                and not current.body_program.get("ending")
                and not current.body_program["recovery_required"]
            )
            else "settling"
            if ended
            else "playing"
        )
    current.record(
        "behavior_feedback", slot_id=slot_id, owner=slot["owner"], status=body.status
    )
    timing = getattr(current, "timing", None)
    if timing and timing.epoch == current.epoch:
        timing.receipt(current.body_program, slot, body.status)
    return {"accepted": True}
