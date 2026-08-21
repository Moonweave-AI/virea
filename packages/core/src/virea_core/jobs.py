from __future__ import annotations

from virea_contracts.job import TERMINAL_JOB_STATES, JobState


class InvalidJobTransition(ValueError):
    pass


_FORWARD: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset(
        {JobState.ADMITTED, JobState.CANCELLING, JobState.REJECTED, JobState.FAILED}
    ),
    JobState.ADMITTED: frozenset(
        {
            JobState.STARTING_WORKER,
            JobState.CANCELLING,
            JobState.FAILED,
            JobState.TIMED_OUT,
        }
    ),
    JobState.STARTING_WORKER: frozenset(
        {
            JobState.LOADING_MODEL,
            JobState.CANCELLING,
            JobState.FAILED,
            JobState.TIMED_OUT,
        }
    ),
    JobState.LOADING_MODEL: frozenset(
        {
            JobState.RUNNING,
            JobState.CANCELLING,
            JobState.FAILED,
            JobState.TIMED_OUT,
        }
    ),
    JobState.RUNNING: frozenset(
        {
            JobState.DECODING,
            JobState.CANCELLING,
            JobState.FAILED,
            JobState.TIMED_OUT,
        }
    ),
    JobState.DECODING: frozenset(
        {
            JobState.NORMALIZING,
            JobState.CANCELLING,
            JobState.FAILED,
            JobState.TIMED_OUT,
        }
    ),
    JobState.NORMALIZING: frozenset(
        {
            JobState.RETARGETING,
            JobState.VALIDATING,
            JobState.CANCELLING,
            JobState.FAILED,
            JobState.TIMED_OUT,
        }
    ),
    JobState.RETARGETING: frozenset(
        {
            JobState.VALIDATING,
            JobState.CANCELLING,
            JobState.FAILED,
            JobState.TIMED_OUT,
        }
    ),
    JobState.VALIDATING: frozenset(
        {
            JobState.EXPORTING,
            JobState.SUCCEEDED,
            JobState.CANCELLING,
            JobState.FAILED,
            JobState.TIMED_OUT,
        }
    ),
    JobState.EXPORTING: frozenset(
        {
            JobState.SUCCEEDED,
            JobState.CANCELLING,
            JobState.FAILED,
            JobState.TIMED_OUT,
        }
    ),
    JobState.CANCELLING: frozenset(
        {JobState.CANCELLED, JobState.FAILED, JobState.TIMED_OUT}
    ),
    **{state: frozenset() for state in TERMINAL_JOB_STATES},
}


def next_job_states(state: JobState | str) -> frozenset[JobState]:
    return _FORWARD[JobState(state)]


def validate_job_transition(current: JobState | str, target: JobState | str) -> None:
    before = JobState(current)
    after = JobState(target)
    if after not in next_job_states(before):
        raise InvalidJobTransition(
            f"job state cannot move from {before.value} to {after.value}"
        )
