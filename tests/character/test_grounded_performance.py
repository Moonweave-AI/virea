import asyncio
import io
import wave

import pytest
from native_plans import native_plan

from virea.character.audio_stream import PCMWindows
from virea.character.contracts import CharacterConfig
from virea.character.providers import performance


def test_audio_window_captions_partition_text_without_repeating_whole_clauses():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x01\x00" * (24000 * 9))
    text = "这是一整句话，音频会跨越多个播放窗口，但文字不应该被重复。"
    windows = PCMWindows()
    output = windows.push(dict(audio=buffer.getvalue(), text=text, caption=text))
    output.extend(windows.take(final=True))
    assert len(output) > 1
    assert "".join(window["caption"] for window in output) == text
    assert all(window["caption"] != text for window in output)


@pytest.mark.parametrize("target,allowed", [("user", False), ("floor", True)])
def test_sitting_requires_a_scene_support_affordance(monkeypatch, target, allowed):
    async def completion(config, client, history, context, rules, schema, **kwargs):
        sitting = [
            v
            for v in schema["$defs"]["SceneAction"]["oneOf"]
            if v["properties"]["kind"]["const"] == "sit"
        ]
        assert len(sitting) == 1
        assert sitting[0]["properties"]["target_id"]["enum"] == ["floor"]
        return native_plan(
            **(
                {
                    "operation": "replace",
                    "ending": "Sitting comfortably on the floor.",
                    "ending_executor": "ardy",
                    "ending_seconds": 2,
                    "executors": ["ardy"],
                    "objective_groups": [[0]],
                    "starts": [{"event": "immediate"}],
                    "actions": [
                        {
                            "kind": "sit",
                            "target_id": target,
                            "description": "Sitting down on the floor.",
                            "duration_seconds": 4,
                        }
                    ],
                }
            )
        )

    monkeypatch.setattr(performance, "structured_completion", completion)
    appraisal = performance.DialogueAppraisal(
        understanding="接受坐下的邀请",
        speech="silent",
        reply=None,
        embodiment={"operation": "replace", "goal": "在地面坐下"},
    )

    def run():
        return asyncio.run(
            performance.compile_performance(
                CharacterConfig(spatial_url="http://worker"),
                None,
                [{"role": "user", "content": "坐下休息一会吧"}],
                {
                    "spatial_available": True,
                    "targets": {
                        "user": {"x": 0, "y": 1.5, "z": 3},
                        "floor": {"x": 0, "y": 0, "z": 0},
                    },
                    "affordances": {"user": ["look_at"], "floor": ["sit", "move_to"]},
                },
                appraisal,
            )
        )

    if allowed:
        assert run().body.actions[0].target_id == "floor"
    else:
        with pytest.raises(ValueError, match="不支持 sit"):
            run()


def test_dialogue_appraisal_does_not_prime_a_compulsory_ending(monkeypatch):
    async def completion(config, client, history, context, rules, schema, **kwargs):
        assert "resting" not in schema["properties"]
        return {
            "understanding": "闲聊",
            "speech": "speak",
            "reply": {"goal": "分享趣事", "outline": ["叙述"]},
            "embodiment": {"operation": "keep", "goal": None},
        }

    monkeypatch.setattr(performance, "structured_completion", completion)
    appraisal = asyncio.run(
        performance.appraise_dialogue(CharacterConfig(), None, [], {})
    )
    assert appraisal.resting is None


def test_decoder_numeric_bound_failure_gets_one_repair_before_execution(monkeypatch):
    calls = []

    async def completion(config, client, history, context, rules, schema, **kwargs):
        calls.append(context)
        assert len(schema["$defs"]["EmbodiedCommitment"]["oneOf"]) == 2
        return {
            "understanding": "问候",
            "speech": "speak",
            "reply": {"goal": "问好", "outline": ["问候"]},
            "embodiment": {
                "operation": "keep",
                "goal": None,
                "duration_seconds": 0 if len(calls) == 1 else None,
                "duration_evidence": None,
            },
        }

    monkeypatch.setattr(performance, "structured_completion", completion)
    result = asyncio.run(performance.appraise_dialogue(CharacterConfig(), None, [], {}))
    assert result.embodiment.duration_seconds is None
    assert len(calls) == 2
    assert "validation_error" in calls[1]


def test_structured_full_history_is_present_exactly_once():
    import httpx

    from virea.character.providers.routing import structured_completion

    async def run():
        def respond(request):
            import json

            body = json.loads(request.content)
            assert body["messages"][1:] == history
            assert "previous_turns" not in body["messages"][0]["content"]
            return httpx.Response(
                200,
                json={
                    "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]
                },
            )

        history = [
            {"role": "user", "content": "先前的问题"},
            {"role": "assistant", "content": "先前的回答"},
            {"role": "user", "content": "新的问题"},
        ]
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await structured_completion(
                CharacterConfig(llm_api="openai"),
                client,
                history,
                {},
                "role",
                {"type": "object"},
                tokens=30,
                include_history=True,
            )

    asyncio.run(run())
