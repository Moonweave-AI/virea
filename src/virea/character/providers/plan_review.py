"""Semantic verification before a generated interaction becomes executable."""

from typing import Literal

from pydantic import Field

from ..communication import check_appraisal
from ..contracts import Contract
from ..coordination import SpeechAnchor
from ..turn_timing import BodyAnchor
from .routing import structured_completion


class ReviewedSpeech(Contract):
    source: int = Field(description="候选 utterances 的原始索引，从 0 开始。")
    start: BodyAnchor = Field(default_factory=BodyAnchor)


class ReviewedObjective(Contract):
    role: Literal["activity"] = "activity"
    source: int = Field(description="候选 activities 的原始索引。")
    goal: str = Field(
        min_length=1,
        max_length=320,
        description="保留的原始身体目标；审查只选择任务和安排时机，不改写运动内容。",
    )
    start: SpeechAnchor = Field(default_factory=SpeechAnchor)


class OmittedObjective(Contract):
    role: Literal["expression", "state", "recovery", "covered"] = "covered"
    source: int
    reason: str = Field(
        min_length=1,
        max_length=300,
        description="为何该候选不是额外身体任务，以及由哪项保留任务、随声表达、现有状态或整项活动的终态负责。",
    )
    replacement: BodyAnchor | None = Field(
        default=None,
        description="若发言仍引用这个省略目标，指定由哪个实际事件满足该引用；可指向保留目标或整项活动终点。没有引用时可为空。",
    )


class PlanReview(Contract):
    requested_outcome: str = Field(
        default="",
        max_length=500,
        description="用户本轮希望实际得到的交流或运动结果，以及如何从保留任务完成后的可观察结果判断是否达成。",
    )
    execution_summary: str = Field(
        default="",
        max_length=1200,
        description="仅根据可执行字段，概述实际会发生的发言、身体活动和先后关系，并与用户意图比较。不要把计划的说明文字当作已落实的步骤。",
    )
    spoken_units: list[ReviewedSpeech] | None = Field(
        default=None,
        description="按原顺序选出实际发言，每项绑定原始索引 source 与开始条件 start。正常口头内容全部保留，非发声条目不入选。身体目标索引对应 embodiment.activities。",
    )
    activity_starts: list[SpeechAnchor] | None = Field(
        default=None,
        description="为 embodiment.activities 中每个身体目标规划开始条件。utterance 索引对应 spoken_units 筛选后的发言序号，从 0 开始。",
    )
    body_objectives: list[ReviewedObjective] | None = Field(
        default=None,
        description="按执行顺序选出独立身体任务。所有 start 引用候选列表的原始索引，与 source 一致；运行时统一重绑定。",
    )
    omitted_objectives: list[OmittedObjective] | None = Field(
        default=None,
        description="逐项说明未入选的候选身体目标。与 body_objectives 合起来覆盖所有原始 activities，索引不重复。",
    )
    problems: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="本次整理仍不能满足的实质问题，包括采纳的任务未完成用户所需结果。表达期待、准备动作、承诺以后完成与实际完成任务不同。没有问题时为空数组。",
    )


async def review_interaction(config, client, history, context, appraisal):
    schema = PlanReview.model_json_schema()
    utterances = getattr(appraisal.reply, "utterances", [])
    activities = appraisal.embodiment.activities
    # New plans select objectives and their anchors atomically. The old parallel
    # anchor array remains readable for stored plans, but cannot constrain review.
    schema["properties"].pop("activity_starts")
    schema["$defs"]["SpeechAnchor"]["description"] = (
        "immediate 没有额外语音等待；utterance_start 在指定句话开始发声时；"
        "utterance_end 在指定句话完全说完后；reply_start 在整轮第一句话开始时；"
        "reply_end 在整轮所有话语完全结束后。开始和结束是不同的实际事件。"
    )
    schema["$defs"]["BodyAnchor"]["description"] = (
        "immediate 没有额外身体等待；objective_start/end 在指定目标实际开始/完成后；"
        "body_start/end 在整项身体活动实际开始/完成后。"
    )
    for model, candidates in (
        ("ReviewedSpeech", utterances),
        ("ReviewedObjective", activities),
        ("OmittedObjective", activities),
    ):
        schema["$defs"][model]["properties"]["source"] = dict(
            type="integer",
            **({"enum": list(range(len(candidates)))} if candidates else {}),
        )
    schema["$defs"]["ReviewedSpeech"]["required"] = ["source", "start"]
    schema["properties"]["spoken_units"] = dict(
        type="array",
        minItems=0,
        maxItems=len(utterances),
        items={"$ref": "#/$defs/ReviewedSpeech"},
        description=schema["properties"]["spoken_units"]["description"],
    )
    # A required decision for each candidate prevents omissions and duplicate
    # source indices at generation time, rather than retrying the whole reply.
    kept = schema["$defs"]["ReviewedObjective"]
    decision = dict(
        oneOf=[
            dict(
                type="object",
                properties={
                    k: v
                    for k, v in kept["properties"].items()
                    if k not in {"source", "goal"}
                },
                required=["role", "start"],
                additionalProperties=False,
            ),
            dict(
                type="object",
                properties={
                    k: v
                    for k, v in schema["$defs"]["OmittedObjective"][
                        "properties"
                    ].items()
                    if k != "source"
                },
                required=["role", "reason", "replacement"],
                additionalProperties=False,
            ),
        ]
    )
    schema["properties"].pop("body_objectives")
    schema["properties"].pop("omitted_objectives")
    schema["$defs"].pop("ReviewedObjective")
    schema["$defs"].pop("OmittedObjective")
    schema["properties"] = {
        "requested_outcome": schema["properties"].pop("requested_outcome"),
        "objective_decisions": dict(
            type="object",
            properties={str(i): decision for i in range(len(activities))},
            required=[str(i) for i in range(len(activities))],
            additionalProperties=False,
            description="逐项判断角色：activity 是独立目的的运动或有意静态表演；expression 是随声情绪手势；state 是背景或当前状态；recovery 是最终收势；covered 是其他活动已包含的部分。activity 才编译成额外身体时段。引用使用原始索引。",
        ),
        **schema["properties"],
    }
    schema["required"] = list(schema["properties"])
    result = await structured_completion(
        config,
        client,
        history,
        {
            "candidate_interaction": dict(
                understanding=appraisal.understanding,
                reply=appraisal.reply.model_dump() if appraisal.reply else None,
                embodiment=appraisal.embodiment.model_dump(),
                expression_executor=appraisal.expression_executor,
            ),
            "scene": {
                k: context[k]
                for k in ("body", "body_program", "targets", "available_executors")
                if k in context
            },
            **{
                k: context[k]
                for k in ("invalid_review", "review_validation_error")
                if k in context
            },
        },
        REVIEW_RULES,
        schema,
        tokens=config.language_max_tokens,
        thinking=config.llm_thinking,
        include_history=True,
    )
    decisions = result.pop("objective_decisions")
    if set(decisions) != {str(i) for i in range(len(activities))}:
        raise ValueError("Objective review keys do not match candidate objectives")
    result["body_objectives"], result["omitted_objectives"] = [], []
    for index in range(len(activities)):
        item = decisions[str(index)]
        destination = (
            "body_objectives" if item["role"] == "activity" else "omitted_objectives"
        )
        result[destination].append(
            {
                **item,
                "source": index,
                **(
                    dict(goal=activities[index].goal)
                    if destination == "body_objectives"
                    else {}
                ),
            }
        )
    return PlanReview.model_validate(result)


REVIEW_RULES = """你负责把候选内容组织为角色实际要执行的交流计划。
requested_outcome 根据用户本轮意图和现场能力判断实际要达成的结果。对照候选的可执行内容检验是否达成，而不是只复述候选的意图声明。无法完成或缺少必要动作时，problems 给出差异以便上层修订。
如果提供 invalid_review 与 review_validation_error，它们是上次未执行的审查结果和精确校验反馈；在同一候选内容上修正冲突引用。
先根据用户意图和现场逐项判断 objective_decisions.role。activity 有独立的任务完成标准，保留原始 goal 和 completion 并分配 start；expression 是台词伴随的情绪和手势，由已分配的表达通道承担；state 是背景状态；recovery 是整项活动收势；covered 已包含在其他活动中。这些归属由语义和现场判断，不依据特定动作名称。本层只选择和编排已有目标，不重新撰写身体内容。
角色已有的姿态、发言背景、随声表达和整项活动的最终收势，与额外身体任务是不同概念。活动实现层负责一次最终恢复；同一活动的开始、持续和结束不因此成为三个独立目标。用户要求的静态表演或真实姿态改变仍然是任务。
spoken_units 选出实际朗读的正文，舞台说明不入选。联合规划发言与保留运动的 start；所有引用使用候选列表的原始索引，与 source 一致，引用的条目也需要入选。这些条件取代候选中的 start，表达实际执行事件的先后或并行关系，不是模型计算顺序。
keep 保留现场已有任务；motion_intent 随发言提供表达条件；说明文字不创建执行步骤。每项候选身体目标必须有明确归属，保留任务的具体运动和意图不能在整理中丢失。
execution_summary 概述实际执行顺序。problems 报告本次整理无法解决的内容遗漏或场景矛盾，没有时为空。动作质量和计算耗时由下层实测。
"""


async def reviewed_appraisal(config, client, history, context, appraisal, *, reviewer):
    """Repair event references locally; do not regenerate valid dialogue text."""
    for attempt in range(2):
        review = await reviewer(config, client, history, context, appraisal)
        if review.problems:
            raise ValueError("Interaction review: " + "; ".join(review.problems))
        candidate = appraisal.model_copy(deep=True)
        try:
            adopt_spoken_units(candidate, review)
            check_appraisal(candidate, context.get("body_program"))
        except ValueError as error:
            if attempt:
                raise
            context = {
                **context,
                "invalid_review": review.model_dump(),
                "review_validation_error": str(error),
            }
            continue
        candidate.timing_rationale = review.execution_summary
        candidate.objective_review = dict(
            requested_outcome=review.requested_outcome,
            retained=[a.model_dump() for a in review.body_objectives or []],
            omitted=[a.model_dump() for a in review.omitted_objectives or []],
        )
        return type(candidate).model_validate(candidate.model_dump())


def bind_body_anchor(anchor, indices, replacements, visited=()):
    """Resolve only explicitly authored event aliases, never infer their meaning."""
    source = anchor.objective
    if source is None:
        return anchor
    if source in indices:
        return anchor.model_copy(update=dict(objective=indices[source]))
    if source in visited:
        raise ValueError("Circular omitted-objective event aliases")
    replacement = replacements.get(source)
    if replacement is None:
        raise ValueError(
            "Retained speech depends on omitted body objective without an event replacement"
        )
    return bind_body_anchor(replacement, indices, replacements, (*visited, source))


def adopt_body_objectives(appraisal, review):
    """Apply explicit semantic selections, without recognizing action words."""
    if review.body_objectives is None:
        return
    original = appraisal.embodiment.activities
    selected = [a.source for a in review.body_objectives]
    omitted = [a.source for a in review.omitted_objectives or []]
    if sorted(selected + omitted) != list(range(len(original))):
        raise ValueError("Body review must account for every candidate exactly once")
    if selected != sorted(selected):
        raise ValueError("Body review must preserve adopted objective order")
    speech_indices = {u.source: i for i, u in enumerate(review.spoken_units or [])}
    if any(
        a.start.utterance is not None and a.start.utterance not in speech_indices
        for a in review.body_objectives
    ):
        raise ValueError("Retained body objective depends on omitted speech")
    body_indices = {source: i for i, source in enumerate(selected)}
    replacements = {a.source: a.replacement for a in review.omitted_objectives or []}
    for unit in review.spoken_units or []:
        bind_body_anchor(unit.start, body_indices, replacements)
    commitment = appraisal.embodiment
    commitment.activities = [
        original[a.source].model_copy(
            update=dict(
                start=a.start.model_copy(
                    update=dict(utterance=speech_indices[a.start.utterance])
                )
                if a.start.utterance is not None
                else a.start,
            )
        )
        for a in review.body_objectives
    ]
    if commitment.operation == "replace":
        commitment.goal = "；".join(a.goal for a in commitment.activities) or None
        if not commitment.activities:
            commitment.operation = "keep"
            commitment.duration_seconds = commitment.duration_evidence = None


def adopt_spoken_units(appraisal, review):
    """Bind the reviewing LLM's selection; never classify text with keywords."""
    if review.spoken_units is None:
        return
    selected = [u.source for u in review.spoken_units]
    utterances = getattr(appraisal.reply, "utterances", [])
    if (
        (not selected and bool(utterances) and review.body_objectives is None)
        or selected != sorted(set(selected))
        or (selected and (selected[-1] >= len(utterances) or selected[0] < 0))
    ):
        raise ValueError(
            "Speech review must select distinct existing utterances in order"
        )
    indices = {source: target for target, source in enumerate(selected)}
    activities = appraisal.embodiment.activities
    if review.activity_starts is not None and len(review.activity_starts) != len(
        activities
    ):
        raise ValueError("Timing plan needs one start condition per body objective")
    anchors = [
        appraisal.embodiment.start,
        *(a.start for a in activities),
    ]
    if (
        review.body_objectives is None
        and review.activity_starts is None
        and any(a.utterance is not None and a.utterance not in indices for a in anchors)
    ):
        raise ValueError(
            "Body depends on an unspoken stage direction; revise that dependency in the joint plan"
        )
    if review.body_objectives is not None:
        adopt_body_objectives(appraisal, review)
    elif review.activity_starts is None:
        for anchor in anchors:
            if anchor.utterance is not None:
                anchor.utterance = indices[anchor.utterance]
    else:
        for activity, start in zip(activities, review.activity_starts):
            activity.start = start
    if appraisal.reply:
        appraisal.reply.utterances = [utterances[i] for i in selected]
        body_indices = {a.source: i for i, a in enumerate(review.body_objectives or [])}
        replacements = {
            a.source: a.replacement for a in review.omitted_objectives or []
        }
        for utterance, reviewed in zip(appraisal.reply.utterances, review.spoken_units):
            utterance.start = (
                bind_body_anchor(reviewed.start, body_indices, replacements)
                if review.body_objectives is not None
                and reviewed.start.objective is not None
                else reviewed.start
            )
        if not selected:
            appraisal.reply, appraisal.speech = None, "silent"
