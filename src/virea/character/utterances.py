"""A single LLM response containing ordered, individually conditioned speech beats."""

import json
import re

from pydantic import Field

from .contracts import Contract, Decision
from .decision_schema import decision_schema
from .turn_timing import BodyAnchor


class SpeechBeat(Contract):
    start: BodyAnchor = Field(
        default_factory=BodyAnchor,
        description="When this utterance may be spoken: immediately, during an adopted activity, or after its observed completion. The objective index refers to body_commitment.activities, not model windows.",
    )
    motion_intent: str = Field(
        min_length=1,
        max_length=100,
        description="随当前话语表达情绪和意义的中文交际手势描述。独立的 body_commitment 按其同步条件由行为层执行。",
    )
    text: str = Field(
        min_length=1,
        max_length=120,
        description="一个完整话语单元的可朗读正文；动作说明属于 motion_intent 或 body_commitment。",
    )


def utterance_schema(
    targets=None,
    positions=None,
    *,
    speech_only=False,
    max_beats=64,
    committed_speech=False,
    body_objectives=None,
):
    schema = decision_schema(targets, positions)
    beat = SpeechBeat.model_json_schema()
    schema["$defs"].update(beat.pop("$defs", {}))
    schema["$defs"]["SpeechBeat"] = beat
    events = ["immediate"] + (
        ["body_start", "body_end"] if body_objectives is not None else []
    )
    anchors = [
        dict(
            type="object",
            additionalProperties=False,
            properties=dict(event=dict(enum=events), objective=dict(type="null")),
            required=["event", "objective"],
        )
    ]
    if body_objectives:
        anchors.append(
            dict(
                type="object",
                additionalProperties=False,
                properties=dict(
                    event=dict(enum=["objective_start", "objective_end"]),
                    objective=dict(type="integer", enum=list(range(body_objectives))),
                ),
                required=["event", "objective"],
            )
        )
    schema["$defs"]["BodyAnchor"] = {"oneOf": anchors}
    beat["required"] = ["start", *beat["required"]]
    for variant in schema["oneOf"]:
        props = variant["properties"]
        mode = props["mode"]["const"]
        variant["properties"] = {
            "mode": props["mode"],
            "actions": props["actions"],
            "beats": {
                "type": "array",
                "items": {"$ref": "#/$defs/SpeechBeat"},
                "minItems": 1 if mode == "SPEAK" else 0,
                "maxItems": max_beats if mode == "SPEAK" else 0,
            },
        }
        variant["required"] = ["mode", "actions", "beats"]
        if speech_only:
            variant["properties"]["actions"]["maxItems"] = 0
    if speech_only:
        schema["oneOf"] = [
            v
            for v in schema["oneOf"]
            if v["properties"]["mode"]["const"] != "ACT_SILENTLY"
        ]
    if committed_speech:
        schema["oneOf"] = [
            v for v in schema["oneOf"] if v["properties"]["mode"]["const"] == "SPEAK"
        ]
    return schema


def decode_beats(source: str):
    """Release only complete beat objects; braces/escapes inside text are JSON data.

    The mode and action list must be complete before any speech is released.
    Incomplete tails stay buffered, so a partial escape is never pronounced.
    """
    match = re.search(r',\s*"beats"\s*:\s*\[', source)
    if match is None:
        return None
    control = json.loads(source[: match.start()] + "}")
    if set(control) != {"mode", "actions"}:
        raise ValueError("speech controls must precede beats")
    decoder, beats, cursor = json.JSONDecoder(), [], match.end()
    while cursor < len(source):
        while cursor < len(source) and source[cursor] in " \n\r\t,":
            cursor += 1
        if cursor == len(source) or source[cursor] == "]":
            break
        try:
            value, consumed = decoder.raw_decode(source[cursor:])
        except json.JSONDecodeError:
            break
        beats.append(SpeechBeat.model_validate(value))
        cursor += consumed
    return control, beats


def beat_decision(control, beats):
    return Decision(
        **control,
        text="".join(beat.text for beat in beats),
        motion_intent=beats[-1].motion_intent if beats else "",
    )


def planner_action(intent: str) -> str:
    """Match upstream extract_description, accepting both public/demo delimiters."""
    tags = re.findall(r"[【〖]([^】〗]+)[】〗]", intent)
    if tags:
        return tags[-1]
    return intent.strip()
