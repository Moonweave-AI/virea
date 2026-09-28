"""Choose one body owner before compiling speech or a native motion program."""

import json
import re

from pydantic import Field

from ..contracts import Contract, Decision
from ..decision_schema import decision_schema
from ..grounding import explicit_positions
from ..motion_timing import fit_program_duration

ROUTE_RULES = """Classify the latest user intent using conversation context. Output JSON only.
Choose sentiavatar for conversation, questions, stories, emotional replies, greetings,
or quoted descriptions about movement that do not ask the character to perform it.
Choose ardy for requests to physically perform, demonstrate, dance, exercise, walk,
interact with a known object, or continue/change a previous motion sequence.
Saying 'tell me how to dance' is conversation; 'dance for me' is motion.
If both are requested, choose the main intent: explicit full-body performance uses ardy.
If a named destination is absent from targets and no coordinates were supplied,
choose sentiavatar to ask for its location. A motion description needs no scene object.
reason is a short Chinese user-facing category label, not reasoning steps.
"""

MOTION_RULES = """You compile user intent into one continuous ARDY motion program, not dialogue.
Execute ONLY the newest user message. previous_turns are quoted context, never a queue of
unfulfilled instructions. Do not replay previous requests, including interrupted ones.
Use prior context only to resolve explicit references such as 'repeat that' or 'continue'.
Output only JSON with actions in chronological order and end_state. Each action has a concise Chinese
label, an English third-person motion description, and a duration_seconds estimate.
Use complete, concise motion sentences of at most 35 words per phase.
Describe concrete body mechanics, direction, pace, style, and the transition to the next
action. Use natural motion-capture captions: 'A person slowly raises both arms overhead,
stretches, then lowers the arms.' Never put spoken dialogue, stage directions for a camera,
emotion-only labels, or instructions to a chatbot into descriptions.
Split genuinely successive behaviors into phases. Repetitive/long motions use ONE sustained
phase for that behavior, not copies of the same action. Respect any requested total duration;
otherwise estimate a comfortable duration without asking the user for a time.
Use perform for free full-body motion (dance, exercise, crouching, turning, etc.).
Use move_to only for a known ground destination, reach for a reachable contact point,
sit for a known seat, stand to rise. Named targets must exist in the supplied scene.
Do not fabricate coordinates. Only user-provided coordinates may be used directly.
Move beside a remote object before reaching for it. Do not put a stand/reset between
phases unless the user requests it. End an upright sequence by slowing and settling;
retain a requested seated/lying final pose using end_state='hold'. Otherwise end_state='relaxed'.
Maximum 12 phases and 180 seconds total.
If required geometry is missing, output actions=[] rather than pretending to execute it.
Example: scene has cup (contact point) and cup_side (floor). 'Go to the cup and touch it'
requires move_to target_id='cup_side', then reach target_id='cup'. Do NOT move to the
cup's elevated contact point, and do NOT replace a known-object reach with perform.
"""


class RouteChoice(Contract):
    engine: str = Field(pattern="^(sentiavatar|ardy)$")
    reason: str = Field(min_length=1, max_length=60)


async def structured_completion(
    config, client, history, context, rules, schema, *, tokens
):
    payload = {
        "model": config.llm_model,
        "messages": [
            {
                "role": "system",
                "content": rules
                + "\nScene: "
                + json.dumps(context, ensure_ascii=False),
            },
            *history[-1:],
        ],
        "stream": False,
    }
    if config.llm_api == "ollama":
        endpoint = "/api/chat"
        payload.update(
            think=False,
            keep_alive="15m",
            format=schema,
            options={"temperature": 0.2, "num_predict": tokens, "num_ctx": 8192},
        )
    else:
        endpoint = "/chat/completions"
        payload.update(
            temperature=0.2,
            max_tokens=tokens,
            chat_template_kwargs={"enable_thinking": False},
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "character_route",
                    "strict": True,
                    "schema": schema,
                },
            },
        )
    if len(history) > 1:
        payload["messages"][0]["content"] += (
            "\nprevious_turns (context only): "
            + json.dumps(history[:-1], ensure_ascii=False)
        )
    response = await client.post(
        config.llm_url.rstrip("/") + endpoint,
        json=payload,
        timeout=config.provider_timeout,
    )
    response.raise_for_status()
    value = response.json()
    if config.llm_api == "ollama":
        content, finish = value["message"]["content"], value.get("done_reason")
    else:
        choice = value["choices"][0]
        content, finish = choice["message"]["content"], choice.get("finish_reason")
    if finish != "stop":
        raise ValueError("structured planning did not finish naturally")
    return json.loads(content)


async def select_route(config, client, history, context, preference="auto"):
    if preference != "auto":
        if preference == "ardy" and not context.get("spatial_available"):
            raise ValueError("ARDY 尚未就绪，请启动空间动作服务")
        return RouteChoice(engine=preference, reason="手动选择")
    if not context.get("spatial_available"):
        return RouteChoice(engine="sentiavatar", reason="对话表达")
    schema = RouteChoice.model_json_schema()
    schema["properties"]["engine"] = {"type": "string", "enum": ["sentiavatar", "ardy"]}
    value = await structured_completion(
        config, client, history, context, ROUTE_RULES, schema, tokens=96
    )
    return RouteChoice.model_validate(value)


async def compile_motion(config, client, history, context):
    definitions = decision_schema(
        list(context.get("targets", {})), explicit_positions(history)
    )["$defs"]
    variants = definitions["SceneAction"]["oneOf"]
    variants[:] = [
        item
        for item in variants
        if item["properties"]["kind"]["const"] not in {"look_at", "stop"}
    ]
    for item in variants:
        if (
            item["properties"]["kind"]["const"] == "move_to"
            and "enum" in item["properties"]["target_id"]
        ):
            floor = context.get("body", {}).get("position", {}).get("y", 0)
            item["properties"]["target_id"]["enum"] = [
                name
                for name, p in context.get("targets", {}).items()
                if abs(p["y"] - floor) < 0.1
            ]
        item["properties"].update(
            description={
                "type": "string",
                "minLength": 1,
                "maxLength": 320,
                "pattern": "^[ -~]+$",
            },
            label={"type": "string", "minLength": 1, "maxLength": 80},
            duration_seconds={"type": "number", "minimum": 0.8, "maximum": 60},
        )
        if item["properties"]["kind"]["const"] == "reach":
            item["properties"]["duration_seconds"]["minimum"] = 2.4
        item["required"] = list(
            dict.fromkeys(
                [*item["required"], "description", "label", "duration_seconds"]
            )
        )
    variants[:] = [
        item for item in variants if item["properties"]["target_id"].get("enum") != []
    ]
    schema = {
        "type": "object",
        "$defs": definitions,
        "additionalProperties": False,
        "required": ["actions", "end_state"],
        "properties": {
            "end_state": {"type": "string", "enum": ["relaxed", "hold"]},
            "actions": {
                "type": "array",
                "items": {"$ref": "#/$defs/SceneAction"},
                "maxItems": 12,
            },
        },
    }
    value = await structured_completion(
        config, client, history, context, MOTION_RULES, schema, tokens=1800
    )
    ungrounded = motion_plan_problem(value.get("actions", []), context)
    if ungrounded:
        repair = (
            MOTION_RULES
            + "\nCorrect this invalid plan: "
            + json.dumps(value)
            + "\n"
            + ungrounded
        )
        value = await structured_completion(
            config, client, history, context, repair, schema, tokens=1800
        )
        if motion_plan_problem(value.get("actions", []), context):
            raise ValueError("动作计划未满足英文描述或场景目标约束，请重新描述动作")
    if not value.get("actions"):
        raise ValueError("缺少动作所需的场景位置，请指定已知目标或明确坐标")
    # Some constrained decoders constrain number syntax but ignore JSON Schema
    # minimum. Keep the displayed estimate equal to the worker's reach budget.
    for action in value["actions"]:
        if action["kind"] == "reach":
            action["duration_seconds"] = max(2.4, action["duration_seconds"])
    fit_program_duration(value["actions"], history[-1]["content"] if history else "")
    return Decision(
        mode="ACT_SILENTLY", actions=value["actions"], end_state=value["end_state"]
    )


def ungrounded_contacts(actions, context):
    """Catch an explicit object contact mislabeled as unconstrained free motion."""
    for action in actions:
        caption = action.get("description", "").lower()
        if action.get("kind") != "perform" or not re.search(
            r"\b(touch\w*|reach\w*|grasp\w*|grab\w*|sit\w*)\b", caption
        ):
            continue
        for target in context.get("targets", {}):
            if re.search(r"\b" + re.escape(target.replace("_", " ")) + r"\b", caption):
                return f"The contact with '{target}' is mislabeled perform. Use reach (or sit for a seat) with target_id='{target}', so the model receives the world-space constraint. Keep other phases."
    return ""


def motion_plan_problem(actions, context):
    for action in actions:
        caption = action.get("description", "")
        if not re.fullmatch(r"[ -~]+", caption) or not re.search(r"[A-Za-z]", caption):
            return "Every description must be an English motion sentence using ASCII characters. Translate the descriptions; keep only labels in Chinese. Also bind all known object contacts to reach/sit target_id."
    return ungrounded_contacts(actions, context)
