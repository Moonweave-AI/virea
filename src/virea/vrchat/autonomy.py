"""Advance an explicit goal using output history, without inventing perception."""

from pydantic import Field

from virea.character.providers.routing import structured_completion

from .contracts import StrictModel


class NextStep(StrictModel):
    continue_goal: bool
    instruction: str = Field(max_length=1900)


async def next_step(session, client, completed, feedback):
    value = await structured_completion(
        session.config,
        client,
        [
            {
                "role": "user",
                "content": "现在已完成 completed_outputs 中的输出。请核对 original_goal，只安排尚未完成的下一阶段；若所有阶段都已完成，则结束。之前的‘现在只规划第一轮’仅约束初始规划，不取消任务中明确要求的后续阶段。",
            }
        ],
        {
            "original_goal": next(
                (
                    turn["content"]
                    for turn in reversed(session.history)
                    if turn["role"] == "user"
                ),
                "",
            ),
            "conversation": list(session.history),
            "completed_outputs": completed,
            "osc_feedback": feedback,
        },
        "Decide whether the latest user's explicit goal still has an unfinished step. "
        "completed_outputs contains already played timelines, not observations of the world. "
        "Do not repeat them. Return continue_goal=false with an empty instruction if the goal "
        "is finished or requires unavailable perception, external input or new permission. "
        "Do not add greetings or new goals. Otherwise return just the NEXT unfinished step as "
        "a self-contained instruction with its original duration, action and exact speech. "
        "A request to plan only the first round applied to the initial plan; when its output "
        "is complete, advance to the explicitly requested next round. No world objects, "
        "positions, collisions or other players are observed.",
        NextStep.model_json_schema(),
        tokens=1024,
        include_history=True,
    )
    result = NextStep.model_validate(value)
    if result.continue_goal and not result.instruction.strip():
        raise ValueError("autonomous continuation requires an explicit next step")
    return result
