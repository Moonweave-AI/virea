from __future__ import annotations

import asyncio
import json

import httpx
import numpy as np
import pytest

from virea.character.contracts import CharacterConfig, Decision
from virea.character.face import vrm_face_track
from virea.character.providers.language import LanguageProvider
from virea.character.providers.motion import MotionProvider


def test_language_preserves_input_roles_and_disables_thinking():
    def respond(request):
        payload = json.loads(request.content)
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        assert payload["messages"][1] == {"role": "user", "content": "你好"}
        assert payload["messages"][-1]["role"] == "system"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": Decision(mode="WAIT").model_dump_json()},
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await LanguageProvider(CharacterConfig(), client).decide(
                [{"role": "user", "content": "你好"}], {"trigger": "context"}
            )
            assert result.mode == "WAIT"

    asyncio.run(run())


def test_language_rejects_truncated_response():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {"finish_reason": "length", "message": {"content": "{}"}}
                        ]
                    },
                )
            )
        ) as client:
            with pytest.raises(ValueError, match="naturally"):
                await LanguageProvider(CharacterConfig(), client).decide([], {})

    asyncio.run(run())


def test_motion_cancellation_reaches_control_plane():
    class Control:
        cancelled = []

        def submit(self, request, **kwargs):
            assert request.parameters["generate_face"]
            assert "duration" not in request.parameters
            return {"id": "motion-job"}

        def cancel(self, job_id):
            self.cancelled.append(job_id)

        @property
        def store(self):
            return self

        def get_job(self, _):
            return {"state": "RUNNING"}

    async def run():
        control = Control()
        provider = MotionProvider(control, CharacterConfig())
        task = asyncio.create_task(provider.generate(b"wav", "你好", "挥手", None))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert control.cancelled == ["motion-job"]

    asyncio.run(run())


def test_face_mapping_binds_verified_upstream_indices():
    values = np.zeros((2, 51), dtype=np.float32)
    values[0, 24] = 0.8
    values[0, 26] = 0.5
    values[0, 8] = 1
    values[0, 43:45] = 0.7
    result = vrm_face_track(values, 20)
    mapped = dict(zip(result["names"], result["values"][0]))
    assert mapped["aa"] == pytest.approx(0.4)
    assert mapped["blinkLeft"] == 1
    assert mapped["happy"] == pytest.approx(0.7)
    assert result["lossy"]


def test_nonfinite_face_is_rejected():
    with pytest.raises(ValueError):
        vrm_face_track(np.full((3, 51), np.nan), 20)


def test_ollama_uses_native_thinking_switch_and_json_schema():
    def respond(request):
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["think"] is False
        variants = payload["format"]["oneOf"]
        assert [value["properties"]["mode"]["const"] for value in variants] == [
            "SPEAK",
            "ACT_SILENTLY",
            "WAIT",
        ]
        assert variants[2]["properties"]["actions"]["maxItems"] == 0
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "message": {"content": '{"mode":"WAIT"}'},
            },
        )

    async def run():
        config = CharacterConfig(llm_api="ollama", llm_url="http://127.0.0.1:11434")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert (
                await LanguageProvider(config, client).decide([], {})
            ).mode == "WAIT"

    asyncio.run(run())
