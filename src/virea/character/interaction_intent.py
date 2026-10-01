"""Conversation commitments before persona-driven performance realization."""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import Contract


class SpeechIntent(Contract):
    kind: Literal["say"]
    goal: str = Field(
        min_length=1, max_length=400, description="此处实际要说出的内容目标。"
    )


class BodyIntent(Contract):
    kind: Literal["act"]
    goal: str = Field(
        min_length=1, max_length=320, description="角色采纳的独立身体活动。"
    )
    completion: str = Field(
        min_length=1, max_length=320, description="本项活动完成时可观察的结果。"
    )


class Composition(Contract):
    kind: Literal["sequence", "parallel"]
    children: list[Intent] = Field(max_length=64)


Intent = Annotated[SpeechIntent | BodyIntent | Composition, Field(discriminator="kind")]
Composition.model_rebuild()


def intent_leaves(node, depth=0):
    if depth > 8:
        raise ValueError("Interaction intent exceeds its nesting budget")
    if isinstance(node, Composition):
        return [
            leaf for child in node.children for leaf in intent_leaves(child, depth + 1)
        ]
    return [node]


def intent_channels(node):
    if not isinstance(node, Composition):
        return {node.kind}
    occupied = set()
    for child in node.children:
        channels = intent_channels(child)
        if node.kind == "parallel" and occupied & channels:
            raise ValueError("Parallel intent branches compete for the same channel")
        occupied.update(channels)
    return occupied


class InteractionIntent(Contract):
    understanding: str = Field(min_length=1, max_length=300)
    body_operation: Literal["keep", "replace", "stop"]
    body_scope: Literal["response", "activity"]
    requested_seconds: float | None = Field(gt=0, le=180)
    duration_evidence: str | None = Field(
        description="最新用户消息中明确指定动作时长的逐字原文片段，与 requested_seconds 成对；未指定为 null。"
    )
    program: Composition

    @model_validator(mode="after")
    def coherent(self):
        leaves = intent_leaves(self.program)
        intent_channels(self.program)
        activities = [leaf for leaf in leaves if isinstance(leaf, BodyIntent)]
        if len(leaves) > 76 or len(activities) > 12:
            raise ValueError("Interaction intent exceeds its task budget")
        if (self.body_operation == "replace") != bool(activities):
            raise ValueError("Only a replacement intent adopts new body activities")
        if (self.requested_seconds is None) != (self.duration_evidence is None):
            raise ValueError(
                "Requested duration and exact user quotation must occur together"
            )
        if not activities and self.requested_seconds is not None:
            raise ValueError("Only a new activity receives a new duration budget")
        return self


INTENT_RULES = """分析对话与已发生的执行事实，生成本轮采纳的交互任务结构。你处理交互意图，不演绎角色的表情、姿势或台词。
say.goal 是角色需要回应或讲述的内容任务，由下一层生成实际台词；act 是具有独立目的的身体活动，其完成结果本身是此次交互的目标。
任务表示采纳的承诺；执行时的背景姿态、交流表情和伴随手势属于表达实现层，描述这些状态不会增加独立任务。
sequence 表示前项实际完成后再做后项；parallel 表示并行，分支分别占语音或身体通道。
身体任务 operation 为 keep 时现有活动自动继续并保留进度，这个操作本身已表达延续；replace 时采纳新活动，stop 时结束当前任务。
对话中提及动作、描写他人和请求角色执行的语义有所不同。
requested_seconds 与 duration_evidence 仅记录用户明确给出的时长，未指定则为 null。
"""


def intent_schema(native_available=True):
    """A continuation can speak while the old program runs, but cannot replace it."""
    schema = InteractionIntent.model_json_schema()
    continuation = deepcopy(schema["$defs"]["Composition"])
    continuation["properties"]["kind"] = {"const": "sequence"}
    children = continuation["properties"]["children"]["items"]
    children.pop("discriminator", None)
    children["oneOf"] = [
        {"$ref": "#/$defs/SpeechIntent"},
        {"$ref": "#/$defs/ContinuationComposition"},
    ]
    schema["$defs"]["ContinuationComposition"] = continuation
    fields = schema.pop("properties")
    required = schema.pop("required")
    base = dict(
        type="object", additionalProperties=False, properties=fields, required=required
    )
    keep, replace = deepcopy(base), deepcopy(base)
    keep["properties"].update(
        body_operation={"enum": ["keep", "stop"]},
        requested_seconds={"type": "null"},
        duration_evidence={"type": "null"},
        program={"$ref": "#/$defs/ContinuationComposition"},
    )
    replace["properties"]["body_operation"] = {"const": "replace"}
    schema.pop("additionalProperties", None)
    schema["oneOf"] = [keep, replace] if native_available else [keep]
    return schema
