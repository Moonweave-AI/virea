"""Review a playing predecessor while preparing its successor."""

from time import monotonic

from virea.character.activity_progress import (
    activity_done,
    after_window,
    commit_window,
    is_observed,
)
from virea.character.providers.activity_review import review_activity


async def review_predecessor(current, client, previous, observation):
    program = current.body_program
    if not (
        is_observed(program)
        and previous
        and previous.get("advances_activity")
        and previous["program_id"] == program["id"]
    ):
        return program
    if not previous.get("activity_review"):
        started = monotonic()
        review = await review_activity(
            current.config,
            client,
            program=program,
            slot=previous,
            body=observation.body,
            speech=observation.speech,
        )
        # A cancelled turn cannot publish or apply the old model's decision.
        if current.body_program is not program or previous["epoch"] != current.epoch:
            return program
        previous["activity_review"] = review.model_dump()
        current.record(
            "activity_reviewed",
            program_id=program["id"],
            slot_id=previous["id"],
            phase=previous["phase_index"],
            observation_source=previous["status"],
            review=review.model_dump(),
            review_seconds=monotonic() - started,
        )
    if previous["status"] == "completed":
        commit_window(program, previous)
        if activity_done(program) and program.get("status") not in {
            "failed",
            "interrupted",
            "completed",
        }:
            program["recovery_required"] = (
                previous.get("support", {}).get("settled") is False
            )
            program["status"] = (
                "settling"
                if program.get("ending") or program["recovery_required"]
                else "completed"
            )
        if getattr(current, "timing", None):
            current.timing.receipt(program, previous, "completed")
    return after_window(program, previous)
