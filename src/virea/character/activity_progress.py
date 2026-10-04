"""Receipt-owned progress for coarse activities, independent of inference windows.

The executor may review a playing window's predicted endpoint to prepare its
successor. Only an accepted completion receipt commits that decision. A native
window has a duration; the semantic activity does not acquire that duration.
"""

from copy import deepcopy

from .kinematic_progress import activity_measurements


def is_observed(program):
    return (program or {}).get("completion_mode") == "observed"


def phase_index(program, elapsed=0):
    if is_observed(program):
        return program.get("phase_index", 0)
    from .motion_timing import planned_duration

    for index, action in enumerate((program or {}).get("actions", [])):
        duration = planned_duration(action)
        if elapsed < duration - 1e-6:
            return index
        elapsed -= duration
    return len((program or {}).get("actions", []))


def activity_done(program):
    return bool(
        program
        and (
            program.get("finish_requested")
            or phase_index(program, program.get("elapsed", 0))
            >= len(program["actions"])
        )
    )


def after_window(program, slot):
    """Project one reservation without mutating any observed facts."""
    value = deepcopy(program)
    if not is_observed(value) or not slot or slot.get("program_id") != value.get("id"):
        return value
    if slot.get("advances_activity"):
        if slot["activity_end"] < value.get("elapsed", 0) - 1e-6:
            return value
        value["elapsed"] = slot["activity_end"]
        phase = slot["phase_index"]
        value.setdefault("motion_progress", {})[str(phase)] = activity_measurements(
            value, slot
        )
        # Idempotent when the predecessor's receipt already committed its review.
        if phase == value.get("phase_index", 0):
            value["phase_elapsed"] = slot.get("phase_elapsed_end", 0)
            review = slot.get("activity_review")
            if review:
                value["last_activity_review"] = review
            budget = value.get("total_duration_seconds")
            final_before_budget = (
                phase == len(value["actions"]) - 1
                and budget is not None
                and value["elapsed"] < budget - 1e-5
            )
            if review and review["decision"] == "complete" and not final_before_budget:
                value["phase_index"] = phase + 1
                value["phase_elapsed"] = 0
            elif review and review.get("continuation"):
                value["actions"][phase]["description"] = review["continuation"]
                value["actions"][phase]["continuation_description"] = review[
                    "continuation"
                ]
        budget = value.get("total_duration_seconds")
        if budget is not None and value["elapsed"] >= budget - 1e-5:
            value["phase_index"] = len(value["actions"])
            value["phase_elapsed"] = 0
    return value


def commit_window(program, slot):
    projected = after_window(program, slot)
    for key in (
        "elapsed",
        "phase_index",
        "phase_elapsed",
        "actions",
        "last_activity_review",
        "motion_progress",
    ):
        if key in projected:
            program[key] = projected[key]
