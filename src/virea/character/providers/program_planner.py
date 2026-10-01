"""LLM intent -> constrained realization -> deterministic event compilation."""

from typing import Literal

from pydantic import Field, model_validator

from ..communication import CommunicationPlan, check_appraisal, check_communication
from ..contracts import Contract, SceneAction
from ..coordination import PhaseCue
from ..decision_schema import decision_schema
from ..executors import available_executors, executable_seconds, executor_context
from ..grounding import explicit_positions
from ..interaction_intent import (
    INTENT_RULES,
    BodyIntent,
    Composition,
    InteractionIntent,
    SpeechIntent,
    intent_leaves,
    intent_schema,
)
from ..interaction_program import Group, ProgramTracks
from ..motion_timing import fit_program_duration
from .performance import ActivityIntent, BodyPlan, DialogueAppraisal, EmbodiedCommitment
from .recovery import RecoveryPlan
from .routing import motion_plan_problem, structured_completion


class InteractionScore(Contract):
    understanding: str = Field(min_length=1, max_length=300)
    speech: Literal["speak", "silent"]
    body_operation: Literal["keep", "replace", "stop"]
    body_scope: Literal["response", "activity"]
    expression_executor: str | None
    requested_seconds: float | None = Field(gt=0, le=180)
    duration_evidence: str | None
    program: Group
    end_state: Literal["hold", "relaxed"]
    recovery: RecoveryPlan | None

    @model_validator(mode="after")
    def coherent(self):
        if (self.requested_seconds is None) != (self.duration_evidence is None):
            raise ValueError(
                "Requested duration and user quotation must occur together"
            )
        if (
            self.end_state == "relaxed"
            and self.body_operation == "replace"
            and not self.recovery
        ):
            raise ValueError("A relaxed activity ending requires an allocated recovery")
        if self.body_operation != "replace" and (
            self.recovery or self.requested_seconds
        ):
            raise ValueError("Only a new activity has a duration and terminal recovery")
        return self


PROGRAM_RULES = """你是 scene.persona 所描述的角色，面向对话中的用户实现 adopted_intent 中已采纳的交互任务。
每个 node 对应 node_intents 中同名任务。say 的 goal 是待完成的交流任务，text 才是你实际说给对方听的完整正文；角色设定塑造叙述的口吻，不替换该任务的内容。叙述的情节和结局属于正文。
motion_intent 表示说话者当前交流情绪的中文面部、视线和手势条件，不发声；谈论的人物及其动作是内容，角色采纳的独立身体活动由 act 承载。
为身体活动分配执行器、英文运动输入和时长。没有空间目标的运动使用自由文本条件；有目标的运动使用该场景提供的约束。
节点关系已由意图层决定。action.description 描述本活动持续发生的身体运动，completion 是验收结果，整项活动的最终恢复属于 recovery；它们用途不同。
身体初态来自实际运动历史。expression_executor 结合语音实现伴随表达；独立身体任务在它自己的时段占用身体通道。选择能力来自 available_executors。
"""


def program_schema(config, context, history, intent):
    schema = InteractionScore.model_json_schema()
    engines = available_executors(config, context)
    native = [name for name, spec in engines.items() if not spec.requires_speech]
    expression = [name for name, spec in engines.items() if spec.requires_speech]
    leaves = intent_leaves(intent.program)
    if not native and any(isinstance(leaf, BodyIntent) for leaf in leaves):
        raise ValueError("No available executor can realize the adopted body activity")
    schema["properties"]["expression_executor"] = {"enum": [None, *expression]}
    schema["$defs"]["Act"]["properties"]["executor"] = {"enum": native}
    schema["$defs"]["RecoveryPlan"]["properties"]["executor"] = {"enum": native}
    if not native:
        # Grammar excludes unsupported actions, rather than silently rerouting.
        schema["$defs"].pop("Act")
        children = schema["$defs"]["Group"]["properties"]["children"]["items"]
        children.pop("discriminator", None)
        children["oneOf"] = [
            item for item in children["oneOf"] if item.get("$ref") != "#/$defs/Act"
        ]
        schema["properties"]["recovery"] = {"type": "null"}
        schema["$defs"].pop("RecoveryPlan")
    definitions = decision_schema(
        list(context.get("targets", {})), explicit_positions(history)
    )["$defs"]
    variants = definitions["SceneAction"]["oneOf"]
    affordances = context.get("affordances", {})
    variants[:] = [
        v
        for v in variants
        # `stand` has the same unconstrained native implementation as `perform`;
        # retain one representation, with intentional stillness in the caption.
        if v["properties"]["kind"]["const"] not in {"stop", "look_at", "stand"}
    ]
    for variant in variants:
        props = variant["properties"]
        target = props["target_id"]
        if target.get("type") == "string":
            target["enum"] = [
                name
                for name in target.get("enum", [])
                if props["kind"]["const"] in affordances.get(name, [])
            ]
        for name in ("transition_description", "continuation_description"):
            props.pop(name, None)
        props.update(
            description=dict(
                type="string",
                minLength=1,
                maxLength=320,
                pattern="^[ -~]+$",
                description="One short English caption of the ongoing physical movement and relevant body mechanics, reused across continuous inference windows. Completion state and recovery have separate fields.",
            ),
            duration_seconds=dict(type="number", minimum=0.8, maximum=180),
        )
        variant["required"] = list(
            dict.fromkeys([*variant["required"], "description", "duration_seconds"])
        )
    variants[:] = [
        v for v in variants if v["properties"]["target_id"].get("enum") != []
    ]
    schema["$defs"].update(definitions)
    nodes = {}
    for i, leaf in enumerate(leaves):
        name = "Say" if isinstance(leaf, SpeechIntent) else "Act"
        node = schema["$defs"][name]
        fields = ("text", "motion_intent") if name == "Say" else ("executor", "action")
        nodes[f"node_{i}"] = dict(
            type="object",
            additionalProperties=False,
            properties={key: node["properties"][key] for key in fields},
            required=list(fields),
            description=leaf.goal,
        )
    schema["properties"] = {
        "nodes": dict(
            type="object",
            additionalProperties=False,
            properties=nodes,
            required=list(nodes),
        ),
        **{
            key: schema["properties"][key]
            for key in ("expression_executor", "end_state", "recovery")
        },
    }
    schema["required"] = list(schema["properties"])
    if not any(isinstance(leaf, BodyIntent) for leaf in leaves):
        schema["properties"].update(
            end_state={"const": "hold"}, recovery={"type": "null"}
        )
    if not any(isinstance(leaf, SpeechIntent) for leaf in leaves):
        schema["properties"]["expression_executor"] = {"type": "null"}
    # Unused recursive definitions can bloat both model context and grammar.
    for name in ("Act", "Say", "Group"):
        schema["$defs"].pop(name, None)
    if any(isinstance(leaf, BodyIntent) for leaf in leaves):
        from copy import deepcopy

        fields = schema.pop("properties")
        required = schema.pop("required")
        base = dict(
            type="object",
            additionalProperties=False,
            properties=fields,
            required=required,
        )
        hold, recover = deepcopy(base), deepcopy(base)
        hold["properties"].update(
            end_state={"const": "hold"}, recovery={"type": "null"}
        )
        recover["properties"].update(
            end_state={"const": "relaxed"}, recovery={"$ref": "#/$defs/RecoveryPlan"}
        )
        schema.pop("additionalProperties", None)
        schema["oneOf"] = [hold, recover]
    return schema


def compile_score(score, config, history, context):
    tracks = ProgramTracks(score.program)
    engines = available_executors(config, context)
    if (score.body_operation == "replace") != bool(tracks.activities):
        raise ValueError("Only replace adopts independent body activities")
    if (score.speech == "speak") != bool(tracks.speech):
        raise ValueError("Speech mode and actual say nodes disagree")
    if len(tracks.speech) > config.max_speech_beats:
        raise ValueError("Speech program exceeds the configured utterance budget")
    if score.expression_executor is not None and (
        score.expression_executor not in engines
        or not engines[score.expression_executor].requires_speech
    ):
        raise ValueError("Expression allocation cannot consume this speech input")
    for activity in tracks.activities:
        if (
            activity.executor not in engines
            or engines[activity.executor].requires_speech
        ):
            raise ValueError(
                "Activity allocation cannot execute caption-conditioned motion"
            )
    ending = score.recovery
    if ending and (
        ending.executor not in engines or engines[ending.executor].requires_speech
    ):
        raise ValueError("Recovery allocation requires an independent body executor")
    user_text = next(
        (m["content"] for m in reversed(history) if m["role"] == "user"), ""
    )
    if score.requested_seconds is not None and (
        not score.duration_evidence or score.duration_evidence not in user_text
    ):
        raise ValueError(
            "Requested duration requires a quotation from the current user message"
        )
    actions = [activity.action.model_dump() for activity in tracks.activities]
    problem = motion_plan_problem(actions, context)
    if problem:
        raise ValueError(problem)
    for action in actions:
        target = action.get("target_id")
        if target and action["kind"] not in context.get("affordances", {}).get(
            target, []
        ):
            raise ValueError(f"Scene target {target} does not support {action['kind']}")
        if action.get("position") is not None and action[
            "position"
        ] not in explicit_positions(history):
            raise ValueError(
                "Explicit motion coordinates must come from the conversation"
            )
        action["continuation_description"] = action["description"]
        action["transition_description"] = None
    fit_program_duration(actions, score.requested_seconds)
    for action, activity in zip(actions, tracks.activities):
        action["duration_seconds"] = executable_seconds(
            engines[activity.executor], action["duration_seconds"]
        )
    body = BodyPlan(
        operation=score.body_operation,
        actions=[SceneAction.model_validate(a) for a in actions],
        executors=[a.executor for a in tracks.activities],
        objective_groups=[[i] for i in range(len(actions))],
        cues=[
            PhaseCue(phase=i, start=anchor) for i, anchor in enumerate(tracks.anchors)
        ],
        scope=score.body_scope,
        total_duration_seconds=score.requested_seconds,
        end_state=score.end_state,
        ending=ending.goal if ending else None,
        ending_executor=ending.executor if ending else None,
        ending_seconds=executable_seconds(engines[ending.executor], ending.seconds)
        if ending
        else None,
        ending_reason=ending.reason if ending else None,
    )
    reply = (
        CommunicationPlan(goal=score.understanding, utterances=tracks.speech)
        if tracks.speech
        else None
    )
    # An explicit motion budget survives a shorter concurrent utterance. The
    # transport's response lifecycle cannot erase an adopted user duration.
    if (
        score.requested_seconds is not None
        or not reply
        or any(
            c.start.event == "utterance_end"
            and c.start.utterance == len(tracks.speech) - 1
            for c in body.cues
        )
    ):
        body.scope = "activity"
    commitment = EmbodiedCommitment(
        operation=score.body_operation,
        scope=body.scope,
        goal=score.understanding if tracks.activities else None,
        duration_seconds=score.requested_seconds,
        duration_evidence=score.duration_evidence,
        activities=[
            ActivityIntent(
                goal=a.goal,
                completion=a.completion,
                start=anchor,
                target_ids=[a.action.target_id] if a.action.target_id else [],
            )
            for a, anchor in zip(tracks.activities, tracks.anchors)
        ],
    )
    appraisal = DialogueAppraisal(
        understanding=score.understanding,
        speech=score.speech,
        reply=reply,
        embodiment=commitment,
        expression_executor=score.expression_executor,
        compiled_body=body,
        interaction_program=dict(score=score.model_dump(), sources=tracks.sources),
    )
    check_appraisal(appraisal, context.get("body_program"))
    check_communication(
        body.model_dump() if actions else context.get("body_program"), reply
    )
    return appraisal


def realize_intent(intent, value):
    if (
        not isinstance(value, dict)
        or set(value) != {"nodes", "expression_executor", "end_state", "recovery"}
        or not isinstance(value.get("nodes"), dict)
    ):
        raise ValueError("Realization needs exactly the declared program fields")
    leaves = intent_leaves(intent.program)
    if set(value["nodes"]) != {f"node_{i}" for i in range(len(leaves))}:
        raise ValueError("Realization must fill every adopted node exactly once")
    nodes = iter(value["nodes"][f"node_{i}"] for i in range(len(leaves)))

    def fill(node):
        if isinstance(node, Composition):
            return dict(
                kind=node.kind, children=[fill(child) for child in node.children]
            )
        payload = next(nodes)
        fields = (
            {"text", "motion_intent"}
            if isinstance(node, SpeechIntent)
            else {"executor", "action"}
        )
        if not isinstance(payload, dict) or set(payload) != fields:
            raise ValueError(
                "Realization cannot change the adopted node's kind or goal"
            )
        return (
            dict(kind="say", **payload)
            if isinstance(node, SpeechIntent)
            else dict(kind="act", goal=node.goal, completion=node.completion, **payload)
        )

    return InteractionScore(
        **intent.model_dump(exclude={"program"}),
        speech="speak"
        if any(isinstance(leaf, SpeechIntent) for leaf in leaves)
        else "silent",
        program=fill(intent.program),
        **{key: value[key] for key in ("expression_executor", "end_state", "recovery")},
    )


def quoted_duration(intent, history):
    """Bind a model-supplied quotation to source text, allowing whitespace only."""
    if intent.requested_seconds is None:
        return
    text = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    positions = [i for i, char in enumerate(text) if not char.isspace()]
    normalized = "".join(text[i] for i in positions)
    quote = "".join((intent.duration_evidence or "").split())
    start = normalized.find(quote) if quote else -1
    if start < 0:
        raise ValueError("Duration evidence must quote the current user message")
    intent.duration_evidence = text[
        positions[start] : positions[start + len(quote) - 1] + 1
    ]


async def plan_interaction(config, client, history, context):
    # Interpretation sees executed facts and dialogue, not persona performance
    # directions or generated poses from an earlier, possibly completed turn.
    intent_scene = {
        key: context[key]
        for key in (
            "body",
            "body_program",
            "environment",
            "targets",
            "affordances",
            "trigger",
        )
        if key in context
    }
    for attempt in range(2):
        value = await structured_completion(
            config,
            client,
            history,
            intent_scene,
            INTENT_RULES,
            intent_schema(
                any(
                    not spec.requires_speech
                    for spec in available_executors(config, context).values()
                )
            ),
            tokens=config.language_max_tokens,
            thinking=config.llm_thinking,
            include_history=True,
        )
        try:
            intent = InteractionIntent.model_validate(value)
            quoted_duration(intent, history)
            break
        except ValueError as error:
            if attempt:
                raise
            intent_scene = {
                **intent_scene,
                "unexecuted_intent": value,
                "compiler_error": str(error),
            }
    schema = program_schema(config, context, history, intent)
    scene = {
        **context,
        "available_executors": executor_context(config, context),
        "adopted_intent": intent.model_dump(),
        "node_intents": {
            f"node_{i}": leaf.model_dump()
            for i, leaf in enumerate(intent_leaves(intent.program))
        },
    }
    for attempt in range(2):
        value = await structured_completion(
            config,
            client,
            history,
            scene,
            PROGRAM_RULES,
            schema,
            tokens=config.language_max_tokens,
            thinking=config.llm_thinking,
            include_history=True,
        )
        try:
            appraisal = compile_score(
                realize_intent(intent, value), config, history, context
            )
            appraisal.interaction_program["intent"] = intent.model_dump()
            return appraisal
        except ValueError as error:
            if attempt:
                raise
            scene = {**scene, "unexecuted_program": value, "compiler_error": str(error)}
