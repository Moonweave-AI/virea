"""A typed interaction score: semantic activities, not inference windows.

Sequence waits for observed completion; parallel releases disjoint channels.
The compiler emits the existing speech/body event contracts without asking a
second model to reinterpret timing or regenerate the adopted words.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .audio import text_chunks
from .contracts import Contract, SceneAction
from .coordination import SpeechAnchor
from .turn_timing import BodyAnchor
from .utterances import SpeechBeat


class Say(Contract):
    kind: Literal["say"]
    motion_intent: str = Field(
        min_length=1,
        max_length=100,
        description="说话者当下交流情绪的中文面部、视线和手势条件，不发声。故事人物和被评价对象的身体动作属于谈论内容；独立活动由 act 承载。",
    )
    text: str = Field(
        min_length=1,
        max_length=4000,
        description="听众实际听到的完整词句，TTS 会逐字朗读此字段；舞台说明与非发声信息属于 motion_intent。长内容会无损切为语音窗口。",
    )


class Act(Contract):
    kind: Literal["act"]
    goal: str = Field(
        min_length=1,
        max_length=320,
        description="角色采纳的独立身体活动。普通说话的情绪手势属于 say；有意保持姿态也可以是任务。",
    )
    completion: str = Field(min_length=1, max_length=320)
    executor: str
    action: SceneAction


class Group(Contract):
    kind: Literal["sequence", "parallel"]
    children: list[Node] = Field(max_length=64)


Node = Annotated[Say | Act | Group, Field(discriminator="kind")]
Group.model_rebuild()


class ProgramTracks:
    """Lower a resource-exclusive tree to two ordered tracks and cross edges."""

    def __init__(self, program: Group):
        self.speech: list[SpeechBeat] = []
        self.activities: list[Act] = []
        self.anchors: list[SpeechAnchor] = []
        self.sources: list[dict] = []
        self._visited = 0
        self._visit(program, (-1, -1), "program", 0)

    def _visit(self, node: Node, before, path, depth):
        self._visited += 1
        if depth > 8 or self._visited > 200:
            raise ValueError("Interaction program exceeds its structural budget")
        speech, body = before
        if isinstance(node, Say):
            first = len(self.speech)
            anchor = (
                BodyAnchor(event="objective_end", objective=body)
                if body >= 0
                else BodyAnchor()
            )
            # Split for the transport contract, never by rewriting the text.
            self.speech.extend(
                SpeechBeat(text=text, motion_intent=node.motion_intent, start=anchor)
                for text in text_chunks(node.text, limit=120)
            )
            if len(self.speech) > 64:
                raise ValueError("Interaction contains more than 64 speech units")
            self.sources.append(
                dict(
                    path=path, channel="speech", first=first, last=len(self.speech) - 1
                )
            )
            return len(self.speech) - 1, body
        if isinstance(node, Act):
            if len(self.activities) >= 12:
                raise ValueError("Interaction contains more than 12 body activities")
            self.activities.append(node)
            self.anchors.append(
                SpeechAnchor(event="utterance_end", utterance=speech)
                if speech >= 0
                else SpeechAnchor()
            )
            self.sources.append(
                dict(path=path, channel="body", objective=len(self.activities) - 1)
            )
            return speech, len(self.activities) - 1
        if node.kind == "sequence":
            for i, child in enumerate(node.children):
                before = self._visit(child, before, f"{path}.children[{i}]", depth + 1)
            return before
        # Concurrent branches must not compete for either exclusive channel.
        ends, occupied = [], set()
        first_speech, first_body = len(self.speech), len(self.activities)
        for i, child in enumerate(node.children):
            end = self._visit(child, before, f"{path}.children[{i}]", depth + 1)
            channels = {axis for axis in (0, 1) if end[axis] > before[axis]}
            if occupied & channels:
                raise ValueError(
                    f"Parallel branches compete for the same channel at {path}"
                )
            occupied.update(channels)
            ends.append(end)
        if occupied == {0, 1}:
            # Actual audio onset releases the first body phase. Preparation can
            # run ahead, but a fast motion worker cannot outrun pending TTS.
            self.anchors[first_body] = SpeechAnchor(
                event="utterance_start", utterance=first_speech
            )
        return tuple(
            max([before[axis], *(end[axis] for end in ends)]) for axis in (0, 1)
        )
