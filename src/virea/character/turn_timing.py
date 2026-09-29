"""Partial-order execution: prepared speech is released by observed body events."""

import asyncio
from collections import defaultdict
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract
from .coordination import SpeechAnchor
from .motion_timing import planned_duration


class BodyAnchor(Contract):
    event: Literal[
        "immediate", "body_start", "body_end", "objective_start", "objective_end"
    ] = "immediate"
    objective: int | None = Field(default=None, ge=0, le=11)

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        for name in ("properties", "required", "additionalProperties"):
            schema.pop(name, None)
        schema["oneOf"] = [
            dict(
                type="object",
                additionalProperties=False,
                properties=dict(event=dict(enum=events), objective=index),
                required=["event", "objective"],
            )
            for events, index in [
                (["immediate", "body_start", "body_end"], dict(type="null")),
                (
                    ["objective_start", "objective_end"],
                    dict(type="integer", minimum=0, maximum=11),
                ),
            ]
        ]
        return schema

    @model_validator(mode="after")
    def coherent(self):
        if self.event.startswith("objective_") != (self.objective is not None):
            raise ValueError("Only an objective event has an objective index")
        return self

    @property
    def key(self):
        channel, _, edge = self.event.partition("_")
        return (
            f"{channel}:{self.objective}:{edge}"
            if self.objective is not None
            else self.event.replace("_", ":")
        )


class TimingConflict(ValueError):
    """Unexecuted dependencies contradict each other or reference missing work."""


class TurnTiming:
    def __init__(self, epoch, record, speech_executors=()):
        self.epoch, self.record = epoch, record
        self.speech_executors = set(speech_executors)
        self.program = None
        self.body_known = False
        self.speech: dict[int, BodyAnchor] = {}
        self.speech_complete = False
        self.facts: set[str] = set()
        self.error = None
        self.changed = asyncio.Event()
        self.waiting: dict[str, str] = {}

    def snapshot(self):
        return dict(
            epoch=self.epoch,
            observed=sorted(self.facts),
            waiting=dict(self.waiting),
            speech_dependencies={
                str(i): a.model_dump() for i, a in self.speech.items()
            },
            error=self.error,
        )

    def set_body(self, program):
        self.program, self.body_known = program, True
        if program:
            status, elapsed = program.get("status"), program.get("elapsed", 0)
            self.facts.update(program.get("observed_body_events", []))
            if status in {"failed", "interrupted"}:
                self.fail(f"Body activity {status}")
            if elapsed > 0 and not program.get("finish_requested"):
                self.facts.add("body:start")
            if status == "completed":
                self.facts.add("body:end")
            # elapsed is advanced only by accepted playback receipts, never by
            # inference forecasts. Adopt those facts when continuing a task.
            for goal, (start, end) in self.objective_bounds().items():
                if program.get("finish_requested"):
                    continue
                if elapsed > start or status == "completed":
                    self.facts.add(f"objective:{goal}:start")
                if elapsed >= end - 1e-5 or status == "completed":
                    self.facts.add(f"objective:{goal}:end")
        self.validate()
        self.changed.set()

    def objective_bounds(self):
        bounds, at = {}, 0.0
        groups = (self.program or {}).get("objective_groups", [])
        for phase, action in enumerate((self.program or {}).get("actions", [])):
            end = at + planned_duration(action)
            for goal in groups[phase] if phase < len(groups) else [phase]:
                bounds[goal] = (bounds.get(goal, (at, end))[0], end)
            at = end
        return bounds

    def add_speech(self, index, anchor):
        self.speech[index] = anchor
        self.validate()
        self.record("speech_timing_planned", utterance=index, start=anchor.model_dump())

    def finish_speech(self):
        self.speech_complete = True
        self.validate()

    def fail(self, message):
        self.error = message
        self.changed.set()

    def validate(self):
        """Detect circular waits, including speech-conditioned body executors."""
        if not self.body_known:
            return
        graph = defaultdict(set)

        def before(a, b):
            # An already observed event cannot be made pending by a later turn.
            if b not in self.facts:
                graph[a].add(b)

        def span(name):
            before(f"{name}:start", f"{name}:end")

        actions = (self.program or {}).get("actions", [])
        groups = (self.program or {}).get("objective_groups", [])
        goals = defaultdict(list)
        for phase, action in enumerate(actions):
            span(f"phase:{phase}")
            if phase:
                before(f"phase:{phase - 1}:end", f"phase:{phase}:start")
            for goal in groups[phase] if phase < len(groups) else [phase]:
                goals[goal].append(phase)
        if actions:
            before("phase:0:start", "body:start")
            before(f"phase:{len(actions) - 1}:end", "body:end")
        for goal, phases in goals.items():
            before(f"phase:{min(phases)}:start", f"objective:{goal}:start")
            before(f"phase:{max(phases)}:end", f"objective:{goal}:end")
        for index, anchor in self.speech.items():
            span(f"utterance:{index}")
            if index:
                before(f"utterance:{index - 1}:end", f"utterance:{index}:start")
            else:
                before("utterance:0:start", "reply:start")
            before(f"utterance:{index}:end", "reply:end")
            if anchor.event != "immediate":
                if (self.program or {}).get(
                    "status"
                ) == "completed" and anchor.key not in self.facts:
                    raise TimingConflict(
                        f"Body finished without observing {anchor.key}"
                    )
                if (
                    not actions
                    or anchor.objective is not None
                    and anchor.objective not in goals
                ):
                    raise TimingConflict(
                        f"Speech references unavailable body event {anchor.key}"
                    )
                before(anchor.key, f"utterance:{index}:start")
        for cue in (self.program or {}).get("cues", []):
            anchor = SpeechAnchor.model_validate(cue["start"])
            if anchor.key in (self.program or {}).get("observed_marks", {}):
                continue
            if (
                self.speech_complete
                and anchor.event != "immediate"
                and (
                    not self.speech
                    or anchor.utterance is not None
                    and anchor.utterance not in self.speech
                )
            ):
                raise TimingConflict(
                    f"Body references missing speech event {anchor.key}"
                )
            if anchor.event != "immediate":
                before(anchor.key, f"phase:{cue['phase']}:start")
        for phase, name in enumerate((self.program or {}).get("executors", [])):
            if name in self.speech_executors:
                before("reply:start", f"phase:{phase}:start")
        visiting, done = [], set()

        def visit(node):
            if node in visiting:
                raise TimingConflict(
                    "Circular speech/body timing dependency: "
                    + " -> ".join(visiting[visiting.index(node) :] + [node])
                    + ". Every event is waiting for another event in this cycle; revise the start dependencies together."
                )
            if node in done:
                return
            visiting.append(node)
            for successor in graph.get(node, ()):
                visit(successor)
            visiting.pop()
            done.add(node)

        for node in list(graph):
            visit(node)

    def receipt(self, program, slot, status):
        if (
            not self.program
            or not program
            or program["id"] != self.program["id"]
            or slot["program_id"] != program["id"]
        ):
            return
        if program["status"] in {"failed", "interrupted"}:
            self.fail(f"Body activity {program['status']}")
            return
        observed = set()
        if slot.get("advances_activity") and status == "playing":
            observed.add("body:start")
            groups = program.get("objective_groups", [])
            phase = slot["phase_index"]
            for goal in groups[phase] if phase < len(groups) else [phase]:
                observed.add(f"objective:{goal}:start")
        if status == "completed":
            if slot.get("advances_activity"):
                observed.update(
                    f"objective:{goal}:end"
                    for goal, (_, end) in self.objective_bounds().items()
                    if slot["activity_end"] >= end - 1e-5
                )
            if program["status"] == "completed":
                observed.add("body:end")
        for event in sorted(observed - self.facts):
            self.record(
                "timing_observed",
                event=event,
                slot_id=slot["id"],
                program_id=program["id"],
            )
        self.facts.update(observed)
        program["observed_body_events"] = sorted(
            set(program.get("observed_body_events", [])) | observed
        )
        self.changed.set()

    async def wait(self, anchor, packet_id):
        if anchor.event == "immediate":
            return
        self.waiting[packet_id] = anchor.key
        self.record("speech_waiting", packet_id=packet_id, event=anchor.key)
        try:
            while anchor.key not in self.facts:
                if self.error:
                    raise TimingConflict(self.error)
                self.validate()
                self.changed.clear()
                await self.changed.wait()
            self.record("speech_released", packet_id=packet_id, event=anchor.key)
        finally:
            self.waiting.pop(packet_id, None)
