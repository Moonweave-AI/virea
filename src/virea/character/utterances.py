"""A single LLM response containing ordered, individually conditioned speech beats."""

import json
import re

from pydantic import Field

from .contracts import Contract, Decision
from .decision_schema import decision_schema


class SpeechBeat(Contract):
    motion_intent: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=120)


def utterance_schema(
    targets=None,
    positions=None,
    *,
    speech_only=False,
    max_beats=64,
    committed_speech=False,
):
    schema = decision_schema(targets, positions)
    schema["$defs"]["SpeechBeat"] = SpeechBeat.model_json_schema()
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
        motion_intent=beats[-1].motion_intent if beats else "自然站立",
    )


def planner_action(intent: str) -> str:
    """Match upstream extract_description, accepting both public/demo delimiters."""
    tags = re.findall(r"[【〖]([^】〗]+)[】〗]", intent)
    if tags:
        action = tags[-1]
        if action in {"动作：无动作", "动作:无动作"}:
            emotion = next(
                (
                    tag
                    for tag in tags
                    if tag.startswith("表情：") and tag != "表情：无表情"
                ),
                None,
            )
            if emotion:
                action = "动作：" + emotion.split("：", 1)[1]
        return action
    return (
        intent.strip()
        if intent.startswith("动作：")
        else "动作：" + (intent.strip() or "轻松说话")
    )
