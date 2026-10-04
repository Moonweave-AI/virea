import asyncio

from fastapi.testclient import TestClient
from virea_api.app import create_app

from virea.character.contracts import Decision
from virea.character.providers.speech import SpeechProvider


def test_voice_catalogue_and_preferences_are_isolated_between_sessions(
    tmp_path, monkeypatch
):
    async def voices(_):
        return [dict(id=name, name=name, language="z") for name in ("zf_001", "zm_010")]

    class QuietLanguage:
        async def decide(self, history, context):
            return Decision(mode="WAIT")

    monkeypatch.setattr(SpeechProvider, "voices", voices)
    application = create_app(virea_home=tmp_path, include_legacy_preview=False)
    with TestClient(application) as client:
        manager = application.state.characters
        manager.language = QuietLanguage()
        defaults = client.get("/api/v1/characters/preferences").json()
        assert len(defaults["voices"]) == 2
        first = client.post(
            "/api/v1/characters", json={"voice": "zm_010", "persona": "冷静的研究伙伴"}
        ).json()
        second = client.post("/api/v1/characters", json={}).json()
        assert first["voice"] == "zm_010" and first["persona"] == "冷静的研究伙伴"
        assert (
            second["voice"] == defaults["voice"]
            and second["persona"] == defaults["persona"]
        )
        response = client.post(
            f"/api/v1/characters/{first['id']}/messages",
            json={"text": "先等等", "voice": "zf_001", "persona": "幽默的伙伴"},
        )
        assert response.status_code == 202
        assert response.json()["voice"] == "zf_001"
        assert manager.config.persona == defaults["persona"]
        assert manager.get(second["id"]).config.persona == defaults["persona"]
        invalid = client.post(
            f"/api/v1/characters/{first['id']}/messages",
            json={"text": "不会进入历史", "voice": "missing"},
        )
        assert invalid.status_code == 422
        assert all(
            item["content"] != "不会进入历史"
            for item in manager.get(first["id"]).history
        )
        assert (
            client.post(
                "/api/v1/characters/voice-preview",
                json={"text": "你好", "voice": "missing"},
            ).status_code
            == 422
        )


def test_synthesis_uses_the_selected_voice_in_each_request():
    import httpx

    from virea.character.contracts import CharacterConfig

    sent = []

    async def run():
        import io
        import json
        import wave

        payload = io.BytesIO()
        with wave.open(payload, "wb") as stream:
            stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            stream.writeframes(bytes(48000))

        def handler(request):
            sent.append(json.loads(request.content)["voice"])
            return httpx.Response(200, content=payload.getvalue())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            config = CharacterConfig(tts_voice="zm_010")
            provider = SpeechProvider(config, client)
            await provider.synthesize("你好")
            config.tts_voice = "zf_001"
            await provider.synthesize("你好")

    asyncio.run(run())
    assert sent == ["zm_010", "zf_001"]
