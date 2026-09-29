"""Semantic verification before a generated interaction becomes executable."""

from pydantic import Field

from ..contracts import Contract
from ..coordination import SpeechAnchor
from ..turn_timing import BodyAnchor
from .routing import structured_completion


class ReviewedSpeech(Contract):
    source: int = Field(description="候选 utterances 的原始索引，从 0 开始。")
    start: BodyAnchor = Field(default_factory=BodyAnchor)


class PlanReview(Contract):
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
    problems: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="选出实际发言后仍存在的实质问题；没有问题时为空数组。非发声条目已经通过 spoken_units 排除，不再重复列为问题。",
    )


async def review_interaction(config, client, history, context, appraisal):
    schema = PlanReview.model_json_schema()
    schema["$defs"]["SpeechAnchor"]["description"] = (
        "immediate 没有额外语音等待；utterance_start 在指定句话开始发声时；"
        "utterance_end 在指定句话完全说完后；reply_start 在整轮第一句话开始时；"
        "reply_end 在整轮所有话语完全结束后。开始和结束是不同的实际事件。"
    )
    schema["$defs"]["BodyAnchor"]["description"] = (
        "immediate 没有额外身体等待；objective_start/end 在指定目标实际开始/完成后；"
        "body_start/end 在整项身体活动实际开始/完成后。"
    )
    schema["required"] = list(schema["properties"])
    schema["$defs"]["ReviewedSpeech"]["properties"]["source"] = dict(
        type="integer", enum=list(range(len(appraisal.reply.utterances)))
    )
    schema["$defs"]["ReviewedSpeech"]["required"] = ["source", "start"]
    schema["properties"]["spoken_units"] = dict(
        type="array",
        minItems=1,
        maxItems=len(appraisal.reply.utterances),
        items={"$ref": "#/$defs/ReviewedSpeech"},
        description=schema["properties"]["spoken_units"]["description"],
    )
    schema["properties"]["activity_starts"] = dict(
        type="array",
        items={"$ref": "#/$defs/SpeechAnchor"},
        minItems=len(appraisal.embodiment.activities),
        maxItems=len(appraisal.embodiment.activities),
        description=schema["properties"]["activity_starts"]["description"],
    )
    result = await structured_completion(
        config,
        client,
        history,
        {
            "candidate_interaction": dict(
                reply=appraisal.reply.model_dump(),
                embodiment=appraisal.embodiment.model_dump(),
                expression_executor=appraisal.expression_executor,
            ),
            "scene": {
                k: context[k]
                for k in ("body", "body_program", "targets")
                if k in context
            },
        },
        "你负责把候选内容组织成可执行的交流时序。根据当前用户对话选择实际发言 spoken_units，并联合规划这些话与身体目标的开始条件 spoken_units.start / activity_starts。这些条件取代候选中的 start；它们表达实际播放的先后或并行关系，不是模型计算顺序。utterances.text 会逐字朗读，舞台说明不入选。embodiment.activities 才会启动独立身体任务，keep 只保留现场已有任务，motion_intent 仅随发言提供表达条件，说明文字不创建执行步骤。execution_summary 概述落实用户意图的执行顺序。problems 只报告内容遗漏或场景矛盾等无法通过本次时序规划解决的问题；没有时为空。动作质量和计算耗时由下层实测，本层不预测。",
        schema,
        tokens=config.language_max_tokens,
        thinking=config.llm_thinking,
        include_history=True,
    )
    return PlanReview.model_validate(result)


def adopt_spoken_units(appraisal, review):
    """Bind the reviewing LLM's selection; never classify text with keywords."""
    if review.spoken_units is None:
        return
    selected = [u.source for u in review.spoken_units]
    utterances = appraisal.reply.utterances
    if (
        not selected
        or selected != sorted(set(selected))
        or selected[-1] >= len(utterances)
        or selected[0] < 0
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
    if review.activity_starts is None and any(
        a.utterance is not None and a.utterance not in indices for a in anchors
    ):
        raise ValueError(
            "Body depends on an unspoken stage direction; revise that dependency in the joint plan"
        )
    if review.activity_starts is None:
        for anchor in anchors:
            if anchor.utterance is not None:
                anchor.utterance = indices[anchor.utterance]
    else:
        for activity, start in zip(activities, review.activity_starts):
            activity.start = start
    appraisal.reply.utterances = [utterances[i] for i in selected]
    for utterance, reviewed in zip(appraisal.reply.utterances, review.spoken_units):
        utterance.start = reviewed.start
