"""LLM-authored spoken intentions and their dependencies, before realization."""

from pydantic import Field

from .contracts import Contract
from .turn_timing import TurnTiming
from .utterances import SpeechBeat


class CommunicationPlan(Contract):
    goal: str = Field(min_length=1, max_length=300)
    utterances: list[SpeechBeat] = Field(
        min_length=1,
        max_length=64,
        description="本轮实际朗读的完整正文，按发言顺序排列；各项 start 与 embodiment.activities 共同构成一份时序计划。静默通过依赖与无声身体活动表达，不是一个待朗读的条目。",
    )

    @property
    def outline(self):
        return [part.text for part in self.utterances]


def check_communication(program, reply, speech_executors=()):
    timing = TurnTiming(0, lambda *a, **k: None, speech_executors)
    timing.set_body(program)
    for index, part in enumerate(getattr(reply, "utterances", [])):
        timing.add_speech(index, part.start)
    timing.finish_speech()


def check_appraisal(appraisal, current_body=None):
    """Validate the joint semantic plan before either channel has side effects."""
    commitment, reply = appraisal.embodiment, appraisal.reply
    if (appraisal.speech == "speak") != bool(reply):
        raise ValueError("Spoken reply and speech mode disagree")
    if reply and not isinstance(reply, CommunicationPlan):
        return  # old stored plans retain their original contract
    program = current_body
    if commitment.operation == "replace":
        anchors = [a.start for a in commitment.activities] or [commitment.start]
        program = dict(
            id="intent",
            status="planned",
            actions=[dict(duration_seconds=1) for _ in anchors],
            objective_groups=[[i] for i in range(len(anchors))],
            cues=[dict(phase=i, start=a.model_dump()) for i, a in enumerate(anchors)],
        )
    check_communication(program, reply)
