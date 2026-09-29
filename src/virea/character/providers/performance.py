"""Interpret dialogue before compiling a character's adopted body intentions."""

from typing import Literal

from pydantic import Field, model_validator

from ..contracts import Contract, SceneAction
from ..decision_schema import decision_schema
from ..grounding import explicit_positions
from ..motion_timing import fit_program_duration
from .routing import ReplyPlan, motion_plan_problem, structured_completion


class BodyPlan(Contract):
    operation: Literal["keep", "replace", "stop"] = Field(
        description="keep preserves the ongoing body activity while conversing; replace starts a new requested activity; stop ends it."
    )
    actions: list[SceneAction] = Field(default_factory=list, max_length=12)
    total_duration_seconds: float | None = Field(default=None, gt=0, le=180)
    start_with_reply: bool = False
    ending: str | None = Field(
        default=None,
        max_length=320,
        description="English motion caption for completing this whole activity and settling into its appropriate supported resting posture. Preserve a meaningful seated, kneeling or lying destination; finish airborne motion by landing. This is a separate terminal behavior, never an intermediate keyframe.",
    )
    end_state: Literal["hold", "relaxed"] = Field(
        default="relaxed",
        description="Terminal pose policy for the whole program, never for intermediate phases.",
    )

    @model_validator(mode="after")
    def coherent(self):
        if (self.operation == "replace") != bool(self.actions):
            raise ValueError("Only a replacement body program has actions")
        if sum(a.duration_seconds or 4.8 for a in self.actions) > 180:
            raise ValueError("Body program exceeds 180 seconds")
        return self


class PerformancePlan(Contract):
    intent: str = Field(min_length=1, max_length=300)
    spoken_content: str | None = Field(
        description="Requested verbal content, independently planned while the body program runs."
    )
    body: BodyPlan
    reply_plan: ReplyPlan | None = None


class EmbodiedCommitment(Contract):
    operation: Literal["keep", "replace", "stop"] = Field(
        description="keep 保留现有身体任务；replace 采纳新的身体任务；stop 终止正在执行的身体任务。发言结束不等于身体任务停止。",
    )
    goal: str | None = Field(
        max_length=500,
        description="角色自主采纳、已解析指代的具体身体任务目标。它不是用户句子的动作摘录，不是发声或静默等对话控制，也不是一般说话姿态。没有新任务时为 null。",
    )
    coordination: Literal["independent", "with_reply"] = Field(
        default="independent",
        description="身体目标与口头回应的时间关系。with_reply 表示共同表演、同时开始；independent 表示行动可以独立开始，口头确认不构成等待条件。",
    )

    @model_validator(mode="after")
    def coherent(self):
        if self.operation == "replace" and not self.goal:
            raise ValueError("A new embodied commitment requires an adopted goal")
        return self


class DialogueAppraisal(Contract):
    resting: str | None = Field(
        default=None,
        max_length=320,
        description="English caption of how the character comfortably settles after this entire response. Consistent with the current or adopted activity's final posture (including sitting or lying), with relaxed hands and stable support. This is an ending, not a new task or repeated action.",
    )
    understanding: str = Field(
        min_length=1,
        max_length=300,
        description="理解说话者、动作主体、真实意图和话语用途（叙述、提问、引用、想象、表演请求等）。",
    )
    speech: Literal["speak", "silent"] = Field(
        description="本轮是否实际出声。speak 表示口头交流；silent 表示无声回应，包括安静地执行已采纳的行为。",
    )
    reply: ReplyPlan | None = Field(
        description="实际要说给对方听的内容目标和提纲；不记录动作执行状态或内部计划。无口头内容时为 null。",
    )
    embodiment: EmbodiedCommitment


DIALOGUE_RULES = """你是当前角色的对话与意图层。结合人设、历史和现场理解对方，决定自己如何回应。
understanding 表达对话的意义，reply 是自己的口头回应计划，embodiment 是自己采纳的身体目标。
动作的提及不等于让角色执行：叙述者、被描述的人、假设情景和角色自己是不同主体。
表演请求可以被角色采纳并自然回应；普通交流的表情、语气和伴随手势由表达层实现。
发声、静默和等待下一轮交流属于 speech/reply；embodiment 代表具有独立目的的身体任务。
已经在进行的身体目标可以在交谈中继续，keep 保留进度；replace 是新的承诺，stop 结束承诺。
此层描述沟通与行为目的，不选择动作模型，不生成骨骼指令。
"""


PERFORMANCE_RULES = """根据最新请求、角色设定、对话和当前执行状态，规划同一角色的并行表达。
输入是对话层已采纳的身体目标。将目标分解为有意义的行为阶段，执行层会在线决定后续短时段的模型。
原生模型根据连续历史完成起步与行为衔接；时间轴的阶段描述请求中的实质活动。
actions 中每项是一个持续行为。description 为正在发生的运动的英文第三人称描述，
供 ARDY 每个原生窗口重复使用。行为改变由阶段时间轴表达；收势是有意行为，不是阶段分隔符。
transition_description 可描述进入下一阶段的运动，只在该阶段最后一个窗口使用。
空间目标来自当前场景或用户明确给出的坐标；自由动作使用 perform。duration_seconds 是阶段时长，
total_duration_seconds 是用户指定的整个任务时长。end_state 只作用于整个任务完成之后。
输出符合契约的 JSON。
"""


async def appraise_dialogue(config, client, history, context):
    schema = DialogueAppraisal.model_json_schema()
    schema["properties"]["resting"] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 320,
        "pattern": "^[ -~]+$",
        "description": DialogueAppraisal.model_fields["resting"].description,
    }
    schema["required"] = list(dict.fromkeys([*schema["required"], "resting"]))
    return DialogueAppraisal.model_validate(
        await structured_completion(
            config,
            client,
            history,
            context,
            DIALOGUE_RULES,
            schema,
            tokens=config.language_max_tokens,
            thinking=config.llm_thinking,
            include_history=True,
        )
    )


async def plan_performance(config, client, history, context):
    appraisal = await appraise_dialogue(config, client, history, context)
    return await compile_performance(config, client, history, context, appraisal)


async def compile_performance(config, client, history, context, appraisal):
    operation = appraisal.embodiment.operation
    if operation == "stop" and (context.get("body_program") or {}).get(
        "status"
    ) not in {"ready", "playing"}:
        operation = "keep"
    reply = appraisal.reply if appraisal.speech == "speak" else None
    spoken_content = reply.goal if reply else None
    if operation != "replace":
        return PerformancePlan(
            intent=appraisal.understanding,
            spoken_content=spoken_content,
            body=BodyPlan(operation=operation),
            reply_plan=reply,
        )
    schema = BodyPlan.model_json_schema()
    definitions = decision_schema(
        list(context.get("targets", {})), explicit_positions(history)
    )["$defs"]
    properties = schema["$defs"]["SceneAction"]["properties"]
    variants = definitions["SceneAction"]["oneOf"]
    variants[:] = [
        v
        for v in variants
        if v["properties"]["kind"]["const"] not in {"look_at", "stop", "stand"}
    ]
    for variant in variants:
        variant["properties"].update(
            {
                name: properties[name]
                for name in (
                    "description",
                    "label",
                    "duration_seconds",
                    "transition_description",
                    "continuation_description",
                )
            }
        )
        variant["properties"]["description"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 320,
            "pattern": "^[ -~]+$",
            "description": "A time-local English caption of movement already underway, in present progressive. This conditions every window of the phase; it describes the maintained activity, not its entrance or ending.",
        }
        variant["properties"]["continuation_description"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 320,
            "pattern": "^[ -~]+$",
            "description": "The motion maintained after entry has already happened. English present-progressive caption for every subsequent window, separate from the entry and exit.",
        }
        variant["required"] = list(
            dict.fromkeys(
                [
                    *variant["required"],
                    "description",
                    "duration_seconds",
                    "continuation_description",
                ]
            )
        )
    schema["$defs"].update(definitions)
    schema["properties"]["operation"] = {"const": "replace", "type": "string"}
    schema["properties"]["actions"]["minItems"] = 1
    schema["properties"]["ending"] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 320,
        "pattern": "^[ -~]+$",
        "description": BodyPlan.model_fields["ending"].description,
    }
    schema["required"] = list(dict.fromkeys([*schema["required"], "actions", "ending"]))
    value = await structured_completion(
        config,
        client,
        [{"role": "user", "content": appraisal.embodiment.goal}],
        {
            **{k: v for k, v in context.items() if k not in {"body_program", "route"}},
            "adopted_goal": appraisal.embodiment.goal,
        },
        PERFORMANCE_RULES,
        schema,
        tokens=config.language_max_tokens,
    )
    plan = PerformancePlan(
        intent=appraisal.understanding,
        spoken_content=spoken_content,
        body=BodyPlan.model_validate(value),
        reply_plan=reply,
    )
    plan.body.start_with_reply = (
        bool(reply) and appraisal.embodiment.coordination == "with_reply"
    )
    actions = [a.model_dump() for a in plan.body.actions]
    problem = motion_plan_problem(actions, context)
    if problem:
        raise ValueError(problem)
    if actions and not context.get("spatial_available"):
        raise ValueError("身体轨道需要已启动的 ARDY 服务")
    fit_program_duration(actions, plan.body.total_duration_seconds)
    plan.body.actions = [SceneAction.model_validate(a) for a in actions]
    return plan
