"""Interpret dialogue before compiling a character's adopted body intentions."""

from typing import Literal

from pydantic import Field, model_validator

from ..communication import CommunicationPlan, check_communication
from ..contracts import Contract, SceneAction
from ..coordination import PhaseCue, SpeechAnchor
from ..decision_schema import decision_schema
from ..executors import available_executors, executable_seconds, executor_context
from ..grounding import explicit_positions
from ..motion_timing import fit_program_duration, planned_duration
from .recovery import RecoveryPlan
from .routing import ReplyPlan, motion_plan_problem, structured_completion


class BodyPlan(Contract):
    completion_mode: Literal["duration", "observed"] = "duration"
    completions: list[str] = Field(default_factory=list, max_length=12)
    operation: Literal["keep", "replace", "stop"] = Field(
        description="keep preserves the ongoing body activity while conversing; replace starts a new requested activity; stop ends it."
    )
    actions: list[SceneAction] = Field(default_factory=list, max_length=12)
    executors: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Model executor selected for each adopted objective, in action order, using the advertised capabilities.",
    )
    objective_groups: list[list[int]] = Field(default_factory=list, max_length=12)
    total_duration_seconds: float | None = Field(default=None, gt=0, le=180)
    start_with_reply: bool = False
    cues: list[PhaseCue] = Field(
        default_factory=list,
        max_length=12,
        description="Optional speech synchronization for each action phase. Other phases follow their predecessor directly. Cue indices refer to actions, not inference windows.",
    )
    scope: Literal["response", "activity"] = "response"
    ending: str | None = Field(
        default=None,
        max_length=320,
        description="English motion caption for completing this whole activity and settling into its appropriate supported resting posture. Preserve a meaningful seated, kneeling or lying destination; finish airborne motion by landing. This is a separate terminal behavior, never an intermediate keyframe.",
    )
    end_state: Literal["hold", "relaxed"] = Field(
        default="hold",
        description="Final pose contract: hold preserves the activity's own final posture; relaxed requires a planned recovery to the intended comfortable posture. This applies once after the whole activity.",
    )
    ending_executor: str | None = None
    ending_seconds: float | None = Field(default=None, ge=0.8, le=12)
    ending_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def coherent(self):
        if (self.operation == "replace") != bool(self.actions):
            raise ValueError("Only a replacement body program has actions")
        if len(self.executors) != len(self.actions):
            raise ValueError("Each action requires an explicit model allocation")
        if bool(self.ending) != bool(
            self.ending_executor
            and (self.completion_mode == "observed" or self.ending_seconds)
        ):
            raise ValueError("An ending requires its model and duration allocation")
        if (
            self.operation == "replace"
            and self.end_state == "relaxed"
            and not self.ending
        ):
            raise ValueError(
                "A relaxed end state requires a recovery allocation; hold explicitly preserves the activity's own terminal pose"
            )
        if self.completion_mode == "observed":
            if len(self.completions) != len(self.actions) or any(
                a.duration_seconds is not None for a in self.actions
            ):
                raise ValueError(
                    "Observed activities need completion goals and no preallocated durations"
                )
        elif sum(planned_duration(a.model_dump()) for a in self.actions) > 180:
            raise ValueError("Body program exceeds 180 seconds")
        phases = [cue.phase for cue in self.cues]
        if len(set(phases)) != len(phases) or any(
            i >= len(self.actions) for i in phases
        ):
            raise ValueError(
                "Each phase cue must reference one distinct existing action"
            )
        return self


class RealizationPhase(Contract):
    objectives: list[int] = Field(min_length=1, max_length=12)
    start: SpeechAnchor
    executor: str
    action: SceneAction


class RealizationPlan(Contract):
    phases: list[RealizationPhase] = Field(min_length=1, max_length=12)
    recovery: RecoveryPlan | None
    end_state: Literal["hold", "relaxed"]


class PerformancePlan(Contract):
    intent: str = Field(min_length=1, max_length=300)
    spoken_content: str | None = Field(
        description="Requested verbal content, independently planned while the body program runs."
    )
    body: BodyPlan
    reply_plan: CommunicationPlan | ReplyPlan | None = None


class ActivityIntent(Contract):
    completion: str = Field(
        default="",
        max_length=320,
        description="本项任务完成时可观察到的身体结果。描述实际完成了什么活动，而非愿意尝试、表达期待或准备开始。",
    )
    start: SpeechAnchor = Field(default_factory=SpeechAnchor)
    target_ids: list[str] = Field(
        default_factory=list,
        description="本目标实际涉及的现场实体 ID；由已采纳的行动语义决定。未涉及现场实体时为空，实体仅仅在场不代表要与其交互。",
    )
    goal: str = Field(
        min_length=1,
        max_length=320,
        description="为达成 completion 持续执行的身体活动。以完整活动为单位，发言伴随的表情手势属于 reply.motion_intent，起始姿态来自现场，最终恢复由实现层处理。",
    )


class EmbodiedCommitment(Contract):
    scope: Literal["response", "activity"] = Field(
        default="response",
        description="response 是随本次口头回应结束的表达；activity 是有独立完成目标的任务，例如走到目的地或完成指定表演。一般说话姿态属于 response。",
    )
    duration_seconds: float | None = Field(
        default=None,
        gt=0,
        le=180,
        description="只有用户明确要求时长时填写总秒数；未指定为 null。",
    )
    duration_evidence: str | None = Field(
        default=None,
        max_length=160,
        description="指定时长的用户原文片段；与 duration_seconds 成对，无明确时长时为 null。",
    )
    operation: Literal["keep", "replace", "stop"] = Field(
        description="keep 保留现有身体任务；replace 采纳新的身体任务；stop 终止正在执行的身体任务。发言结束不等于身体任务停止。",
    )
    coordination: Literal["independent", "with_reply"] = Field(
        default="independent",
        description="身体目标与口头回应的时间关系。with_reply 表示共同表演、同时开始；independent 表示行动可以独立开始，口头确认不构成等待条件。",
    )
    start: SpeechAnchor = Field(
        default_factory=SpeechAnchor,
        description="身体任务的起始条件：immediate 可立即开始；reply_start 随口头回应开始；reply_end 等完整回应说完；utterance_start/end 对应从 0 开始计数的话语单元。此条件限制身体，不延迟说话。",
    )
    goal: str | None = Field(
        max_length=500,
        description="角色实际采纳的身体任务，解析清楚动作主体和指代。发言内容属于 reply，时序由各目标的 start 表达；没有采纳新身体任务时为 null。",
    )
    activities: list[ActivityIntent] = Field(
        default_factory=list,
        max_length=12,
        description="Ordered adopted physical objectives with speech dependencies. Empty for keep/stop. This is the semantic activity sequence, independent of native generation windows.",
    )

    @model_validator(mode="after")
    def coherent(self):
        if self.operation == "replace" and not self.goal:
            raise ValueError("A new embodied commitment requires an adopted goal")
        if self.operation != "replace" and self.activities:
            raise ValueError("Only a replacement commitment adopts new activities")
        return self


class DialogueAppraisal(Contract):
    interaction_program: dict | None = None
    compiled_body: BodyPlan | None = None
    objective_review: dict | None = None
    timing_rationale: str | None = None
    expression_executor: str | None = Field(
        default=None,
        description="Executor selected for accompanying this reply outside committed activity intervals; null leaves the body unchanged. Choose from available capabilities, independently of whether speech is produced.",
    )
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
    reply: CommunicationPlan | ReplyPlan | None = Field(
        description="实际要说给对方听的完整正文及开始条件；不记录内部计划或非发声条目。无口头内容时为 null。",
    )
    embodiment: EmbodiedCommitment


PERFORMANCE_RULES = """你是身体实现规划层。结合已采纳目标、对话理解、实际身体状态和可用能力，自主组织阶段、时间关系、执行器及其运动输入。
每个 phase 将目标来源 objectives、起始依赖 start、执行器 executor 和动作输入 action 绑定为一个整体。目标可以跨阶段延续，也可以合并为连续阶段。
objective_start_conditions 和 requested_communication 是已采纳的联合时序；本层在这些依赖内组织运动阶段。
executor 来自现场能力目录，action 提供选定执行器的英文运动描述、阶段时长及必要的场景目标。
description 是本阶段持续使用的简短运动描述，用一句话表达当前任务必要的身体运动细节，如实际步法、重心或肢体变化。选择哪些细节由你判断，无需罗列全身；风格和情绪用于修饰运动，不能独自代替运动内容。模型从实际身体历史自然进入该运动，推理窗口和音频分片不产生新的行为目标。阶段划分对应运动条件的改变，准备发言和发言后的等待不占运动阶段。
objective_outcomes 是活动完成的验收条件；phase 描述达成它的运动过程，recovery 描述有需要的最终恢复。完成后的状态不是整段运动的条件。
recovery 描述整项活动结束时适合当下的恢复分配；任务本身已经到达所需终态时可保持其终态。
语音内容在独立对话通道实现。输出契约表达计划与能力，不提供特定请求的预设动作或模型映射。
"""


async def appraise_dialogue(config, client, history, context):
    from .program_planner import plan_interaction

    return await plan_interaction(config, client, history, context)


async def plan_performance(config, client, history, context):
    appraisal = await appraise_dialogue(config, client, history, context)
    return await compile_performance(config, client, history, context, appraisal)


async def compile_performance(config, client, history, context, appraisal):
    if appraisal.compiled_body is not None:
        body = appraisal.compiled_body.model_copy(deep=True)
        reply = appraisal.reply if appraisal.speech == "speak" else None
        check_communication(
            body.model_dump() if body.actions else context.get("body_program"), reply
        )
        return PerformancePlan(
            intent=appraisal.understanding,
            spoken_content=reply.goal if reply else None,
            body=body,
            reply_plan=reply,
        )
    operation = appraisal.embodiment.operation
    if operation == "stop" and (context.get("body_program") or {}).get(
        "status"
    ) not in {"ready", "playing", "settling"}:
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
    schema = RealizationPlan.model_json_schema()
    goals = [a.goal for a in appraisal.embodiment.activities] or [
        appraisal.embodiment.goal
    ]
    anchors = [a.start for a in appraisal.embodiment.activities] or [
        appraisal.embodiment.start
    ]
    reviewed_objectives = appraisal.objective_review is not None
    inherit_timing = isinstance(reply, CommunicationPlan) or reviewed_objectives
    explicit_seconds = appraisal.embodiment.duration_seconds
    evidence = appraisal.embodiment.duration_evidence
    user_text = next(
        (m["content"] for m in reversed(history) if m["role"] == "user"), ""
    )
    if explicit_seconds is not None and (not evidence or evidence not in user_text):
        raise ValueError("动作时长缺少对应的用户原文依据")
    selected_targets = {
        target
        for activity in appraisal.embodiment.activities
        for target in activity.target_ids
    }
    targets = {
        key: value
        for key, value in context.get("targets", {}).items()
        if key in selected_targets
    }
    definitions = decision_schema(list(targets), explicit_positions(history))["$defs"]
    properties = schema["$defs"]["SceneAction"]["properties"]
    variants = definitions["SceneAction"]["oneOf"]
    variants[:] = [
        v
        for v in variants
        if v["properties"]["kind"]["const"] not in {"look_at", "stop", "stand"}
    ]
    affordances = context.get("affordances", {})
    for variant in variants:
        props = variant["properties"]
        kind = props["kind"]["const"]
        if props["target_id"].get("type") == "string":
            props["target_id"]["enum"] = [
                target
                for target in props["target_id"].get("enum", [])
                if kind in affordances.get(target, [])
            ]
    variants[:] = [
        v for v in variants if v["properties"]["target_id"].get("enum") != []
    ]
    for variant in variants:
        variant["properties"].update(
            {
                name: properties[name]
                for name in (
                    "description",
                    "label",
                    "duration_seconds",
                )
            }
        )
        for name in ("transition_description", "continuation_description"):
            variant["properties"].pop(name, None)
        variant["properties"]["description"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 320,
            "pattern": "^[ -~]+$",
            "description": "One short English sentence describing the ongoing motion and its most relevant observable body mechanics. Choose the details needed for this activity, rather than enumerating every joint. The same caption conditions every window; preparation, completion and generic style alone do not describe the ongoing motion.",
        }
        variant["properties"]["duration_seconds"] = {
            "type": "number",
            "minimum": 0.8,
            "maximum": explicit_seconds or 180,
            "description": "This phase's finite execution budget; not a persistent mood or personality duration.",
        }
        variant["required"] = list(
            dict.fromkeys(
                [
                    *variant["required"],
                    "description",
                    "duration_seconds",
                ]
            )
        )
    schema["$defs"].update(definitions)
    # The motion compiler owns physical realization only. Intent operation,
    # dialogue lifetime and global timing are supplied by the appraisal layer.
    engines = available_executors(config, context)
    phase_schema = schema["$defs"]["RealizationPhase"]["properties"]
    if inherit_timing:
        phase_schema.pop("start")
        schema["$defs"]["RealizationPhase"]["required"].remove("start")
    phase_schema["executor"] = {"enum": list(engines)}
    phase_schema["objectives"]["items"] = {
        "type": "integer",
        "enum": list(range(len(goals))),
    }
    phase_schema["objectives"]["description"] = (
        "Zero-based adopted objective indices realized by this phase. Objectives can continue across phases or be combined; cover every adopted objective."
    )
    if reviewed_objectives:
        # Intent review owns the semantic timeline. Realization translates its
        # activities; it cannot insert a second preparation/recovery timeline.
        schema["properties"]["phases"].update(minItems=len(goals), maxItems=len(goals))
        phase_schema["objectives"].update(minItems=1, maxItems=1)
        phase_schema["objectives"]["description"] = (
            "The single reviewed activity index being realized, in original execution order. Each activity is one persistent motion condition; final recovery is separate."
        )
    # Each phase is atomic: its dependency, executor and input cannot have
    # different list lengths. The same principle applies to terminal recovery.
    recovery_engines = [
        name for name, spec in engines.items() if not spec.requires_speech
    ]
    if recovery_engines:
        schema["$defs"]["RecoveryPlan"]["properties"]["executor"] = {
            "enum": recovery_engines
        }
    else:
        schema["properties"]["recovery"] = {"type": "null"}
    motion_context = {
        **{k: context[k] for k in ("body", "environment") if k in context},
        "adopted_objectives": goals,
        "objective_outcomes": [a.completion for a in appraisal.embodiment.activities],
        "objective_targets": [a.target_ids for a in appraisal.embodiment.activities],
        "targets": targets,
        "affordances": {key: affordances[key] for key in targets if key in affordances},
        "objective_start_conditions": [a.model_dump() for a in anchors],
        "coordination": appraisal.embodiment.coordination,
        "overall_body_goal": "；".join(goals),
        "requested_communication": {
            "utterances": [dict(start=u.start.model_dump()) for u in reply.utterances]
        }
        if isinstance(reply, CommunicationPlan)
        else None,
        "activity_seconds": explicit_seconds,
        "available_executors": executor_context(config, context),
        "speech_planned": bool(reply),
    }
    for attempt in range(2):
        value = await structured_completion(
            config,
            client,
            [{"role": "user", "content": "\n".join(goals)}],
            motion_context,
            PERFORMANCE_RULES,
            schema,
            tokens=config.language_max_tokens,
            thinking=config.llm_thinking,
        )
        try:
            if inherit_timing:
                for phase in value["phases"]:
                    phase["start"] = SpeechAnchor().model_dump()
            realization = RealizationPlan.model_validate(value)
            # One semantic phase has one persistent text condition. A transport
            # window boundary does not introduce a second, often terminal goal.
            for phase in realization.phases:
                phase.action.continuation_description = phase.action.description
                phase.action.transition_description = None
            ending = realization.recovery
            body_plan = BodyPlan(
                operation=operation,
                actions=[phase.action for phase in realization.phases],
                executors=[phase.executor for phase in realization.phases],
                objective_groups=[phase.objectives for phase in realization.phases],
                ending=ending.goal if ending else None,
                ending_executor=ending.executor if ending else None,
                ending_seconds=ending.seconds if ending else None,
                ending_reason=ending.reason if ending else None,
                end_state=realization.end_state,
            )
            groups = body_plan.objective_groups
            if reviewed_objectives and groups != [[i] for i in range(len(goals))]:
                raise ValueError(
                    "Realization must translate each reviewed activity once, in order"
                )
            covered = [i for group in groups for i in group]
            if sorted(set(covered)) != list(range(len(goals))):
                raise ValueError(
                    f"The motion compiler changed the adopted objective count: groups={groups}; cover {list(range(len(goals)))}"
                )
            phase_anchors, started_objectives = [], set()
            for phase in realization.phases:
                allowed_targets = {
                    target
                    for i in phase.objectives
                    for target in (
                        appraisal.embodiment.activities[i].target_ids
                        if appraisal.embodiment.activities
                        else []
                    )
                }
                if (
                    phase.action.target_id
                    and phase.action.target_id not in allowed_targets
                ):
                    raise ValueError(
                        "Motion phase used a scene entity outside its adopted objectives"
                    )
                if not inherit_timing:
                    phase_anchors.append(phase.start)
                    continue
                new_goals = set(phase.objectives) - started_objectives
                dependencies = {
                    anchors[i].model_dump_json()
                    for i in new_goals
                    if anchors[i].event != "immediate"
                }
                if len(dependencies) > 1:
                    raise ValueError(
                        "Objectives with different speech dependencies need distinct phases"
                    )
                phase_anchors.append(
                    SpeechAnchor.model_validate_json(next(iter(dependencies)))
                    if dependencies
                    else SpeechAnchor()
                )
                started_objectives.update(phase.objectives)
            for name in [
                *body_plan.executors,
                *([body_plan.ending_executor] if body_plan.ending else []),
            ]:
                if name not in engines:
                    raise ValueError(f"Unavailable model executor: {name}")
                if engines[name].requires_speech and not reply:
                    raise ValueError(f"Executor {name} requires speech input")
            if body_plan.ending and engines[body_plan.ending_executor].requires_speech:
                raise ValueError("An ending must remain executable after speech ends")
            for name, anchor in zip(body_plan.executors, phase_anchors):
                if engines[name].requires_speech and (anchor.event == "reply_end"):
                    raise ValueError(
                        "A speech-conditioned executor cannot start after reply end"
                    )
            if isinstance(reply, CommunicationPlan):
                check_communication(
                    {
                        **body_plan.model_dump(),
                        "id": "compiled",
                        "status": "planned",
                        "cues": [
                            dict(phase=i, start=a.model_dump())
                            for i, a in enumerate(phase_anchors)
                        ],
                    },
                    reply,
                    [name for name, spec in engines.items() if spec.requires_speech],
                )
            break
        except ValueError as error:
            if attempt:
                raise
            motion_context = {
                **motion_context,
                "invalid_plan": value,
                "validation_error": str(error),
            }
    plan = PerformancePlan(
        intent=appraisal.understanding,
        spoken_content=spoken_content,
        body=body_plan,
        reply_plan=reply,
    )
    plan.body.cues = [
        PhaseCue(phase=i, start=anchor) for i, anchor in enumerate(phase_anchors)
    ]
    plan.body.start_with_reply = bool(reply) and phase_anchors[0].event == "reply_start"
    if not reply and any(c.start.event != "immediate" for c in plan.body.cues):
        raise ValueError("A silent activity cannot wait for speech")
    plan.body.scope = appraisal.embodiment.scope if reply else "activity"
    if any(c.start.event == "reply_end" for c in plan.body.cues):
        plan.body.scope = "activity"
    plan.body.total_duration_seconds = explicit_seconds
    if plan.body.ending:
        plan.body.ending_seconds = executable_seconds(
            engines[plan.body.ending_executor], plan.body.ending_seconds
        )
    actions = [a.model_dump() for a in plan.body.actions]
    problem = motion_plan_problem(actions, context)
    if problem:
        raise ValueError(problem)
    for action in actions:
        target = action.get("target_id")
        if target and action["kind"] not in affordances.get(target, []):
            raise ValueError(f"场景目标 {target} 不支持 {action['kind']}")
    fit_program_duration(actions, plan.body.total_duration_seconds)
    plan.body.actions = [SceneAction.model_validate(a) for a in actions]
    return plan
