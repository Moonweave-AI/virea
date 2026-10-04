"""Revise only the future of a committed phase after its required input expires."""

from pydantic import Field

from ..contracts import Contract
from ..executors import available_executors
from .routing import structured_completion


class PhaseAllocation(Contract):
    executor: str
    reason: str = Field(min_length=1, max_length=200)
    continuation: str = Field(min_length=1, max_length=320, pattern="^[ -~]+$")


async def reallocate_phase(
    config, client, *, program, phase, remaining, body, speech_usable, failure
):
    engines = {
        name: spec
        for name, spec in available_executors(config).items()
        if not spec.requires_speech or speech_usable
    }
    if not engines:
        raise ValueError(
            "No executor can realize the remaining activity with current inputs"
        )
    schema = PhaseAllocation.model_json_schema()
    schema["properties"]["executor"] = {"enum": list(engines)}
    context = dict(
        overall_body_goal=program.get("goal"),
        current_phase=program["actions"][phase],
        remaining_seconds=remaining,
        body=body.model_dump(exclude={"history"}),
        input_failure=failure,
        available_executors={name: spec.model_dump() for name, spec in engines.items()},
    )
    for attempt in range(2):
        value = await structured_completion(
            config,
            client,
            [{"role": "user", "content": failure}],
            context,
            "根据当前可执行能力与实际身体状态，重新分配尚未完成的身体阶段并描述其延续。已执行进度和对话内容属于既成事实。",
            schema,
            tokens=config.language_max_tokens,
            thinking=config.llm_thinking,
        )
        try:
            result = PhaseAllocation.model_validate(value)
            if result.executor not in engines:
                raise ValueError("Reallocation selected an unavailable executor")
            return result
        except ValueError as error:
            if attempt:
                raise
            context.update(invalid_plan=value, validation_error=str(error))
