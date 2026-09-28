"""Plan concurrent activities, independently of the models rendering them."""

from typing import Literal

from pydantic import Field, model_validator

from ..contracts import Contract, SceneAction
from ..decision_schema import decision_schema
from ..grounding import explicit_positions
from ..motion_timing import fit_program_duration
from .routing import motion_plan_problem, structured_completion


class BodyPlan(Contract):
    operation: Literal["keep", "replace", "stop"] = Field(
        description="keep preserves the ongoing body activity while conversing; replace starts a new requested activity; stop ends it."
    )
    actions: list[SceneAction] = Field(default_factory=list, max_length=12)
    total_duration_seconds: float | None = Field(default=None, gt=0, le=180)
    end_state: Literal["hold", "relaxed"] = Field(
        default="hold",
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


class BodyChange(Contract):
    request: str = Field(
        min_length=1,
        max_length=500,
        description="本条最新消息明确要求改变的身体活动，已解析指代。",
    )
    operation: Literal["continue", "replace", "stop"] = Field(
        description="continue 延续现有任务且保留执行进度；replace 创建新的身体任务；stop 终止现有任务。"
    )


class ActivityIntent(Contract):
    requested_task: str = Field(
        min_length=1, max_length=300, description="本条最新消息实际要求的结果。"
    )
    channels: list[Literal["spoken_content", "physical_movement"]] = Field(
        max_length=2,
        description="All requested results. Verbal content and physical activity can both be requested in the same message.",
    )
    body_change: BodyChange | None = Field(
        description="本轮对身体活动的新增或改变；继续已有活动或只交流时为 null。"
    )


PERFORMANCE_RULES = """根据最新请求、角色设定、对话和当前执行状态，规划同一角色的并行表达。
speech 是本轮真正需要讲出的内容；body 是独立持续的身体活动。两者可以同时存在。
已有身体活动在交谈期间继续执行；新的身体意图通过 operation 表达。
原生模型根据连续历史完成起步与行为衔接；时间轴的阶段描述请求中的实质活动。
actions 中每项是一个持续行为。description 为正在发生的运动的英文第三人称描述，
供 ARDY 每个原生窗口重复使用。行为改变由阶段时间轴表达；收势是有意行为，不是阶段分隔符。
transition_description 可描述进入下一阶段的运动，只在该阶段最后一个窗口使用。
gesture_weights 表示该阶段各身体区域允许叠加多少语义手势：0 保留任务动作，1 完整语义手势。
脚、骨盆、世界位移始终由身体轨道负责；接触链由几何约束保护。
空间目标来自当前场景或用户明确给出的坐标；自由动作使用 perform。duration_seconds 是阶段时长，
total_duration_seconds 是用户指定的整个任务时长。end_state 只作用于整个任务完成之后。
输出符合契约的 JSON。
"""


async def plan_performance(config, client, history, context):
    program = context.get("body_program") or {}
    intent = ActivityIntent.model_validate(
        await structured_completion(
            config,
            client,
            history[-1:],
            {
                "body_activity_in_progress": program.get("status")
                in {"ready", "playing"}
            },
            "Identify ALL outputs requested by the latest user message. spoken_content is an actual verbal result. physical_movement is executing or changing a body activity. These are independent channels, so a combined request includes both. Acknowledging a physical task verbally does not count as requested spoken content. Existing body activity runs independently of speech. body_change describes only a change or explicit continuation requested by this message, otherwise null.",
            ActivityIntent.model_json_schema(),
            tokens=config.planning_max_tokens,
            thinking=config.llm_thinking,
        )
    )
    operation = {"continue": "keep", "replace": "replace", "stop": "stop"}.get(
        intent.body_change.operation
        if intent.body_change and "physical_movement" in intent.channels
        else None,
        "keep",
    )
    spoken_content = (
        intent.requested_task if "spoken_content" in intent.channels else None
    )
    if operation != "replace":
        return PerformancePlan(
            intent=intent.requested_task,
            spoken_content=spoken_content,
            body=BodyPlan(operation=operation),
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
                    "gesture_weights",
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
                    "gesture_weights",
                    "continuation_description",
                ]
            )
        )
    schema["$defs"].update(definitions)
    schema["properties"]["operation"] = {"const": "replace", "type": "string"}
    schema["properties"]["actions"]["minItems"] = 1
    schema["required"] = list(dict.fromkeys([*schema["required"], "actions"]))
    value = await structured_completion(
        config,
        client,
        [{"role": "user", "content": intent.body_change.request}],
        {
            **{k: v for k, v in context.items() if k not in {"body_program", "route"}},
            "requested_body_change": intent.body_change.request,
        },
        PERFORMANCE_RULES,
        schema,
        tokens=config.language_max_tokens,
    )
    plan = PerformancePlan(
        intent=intent.requested_task,
        spoken_content=spoken_content,
        body=BodyPlan.model_validate(value),
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
