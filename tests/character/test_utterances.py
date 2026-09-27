import asyncio
import json

import httpx
import pytest

from virea.character.contracts import CharacterConfig
from virea.character.providers.language import LanguageProvider
from virea.character.utterances import decode_beats, planner_action


def test_one_request_releases_distinct_beats_before_response_end():
    beats = [dict(motion_intent="动作：摊开双手", text='他说："你好"。'),
             dict(motion_intent="动作：摇头叹气", text="可是事情并没有结束。")]
    source = json.dumps(dict(mode="SPEAK", actions=[], beats=beats), ensure_ascii=True)
    released = []
    for i in range(len(source)):
        parsed = decode_beats(source[:i])
        if parsed and parsed[1]:
            released.append((i, len(parsed[1])))
    assert released[0][0] < len(source) - 20
    assert released[-1][1] == 2

    async def run():
        calls = []
        def reply(request):
            calls.append(request)
            events = [dict(choices=[dict(delta=dict(content=char), finish_reason=None)]) for char in source]
            events.append(dict(choices=[dict(delta={}, finish_reason="stop")]))
            return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events))
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            updates = [u async for u in LanguageProvider(CharacterConfig(), client).stream([], {})]
        assert len(calls) == 1
        assert [u.beat.text for u in updates if u.beat] == [b["text"] for b in beats]
        assert [u.beat.motion_intent for u in updates if u.beat] == [b["motion_intent"] for b in beats]
        assert updates[-1].final
        assert updates[-1].decision.text == "".join(b["text"] for b in beats)
    asyncio.run(run())


@pytest.mark.parametrize("value,expected", [
    ("【表情：欣喜】【动作：张开双手】", "动作：张开双手"),
    ("〖表情：担忧〗〖动作：无动作〗", "动作：担忧"),
    ("双手交叠", "动作：双手交叠"),
])
def test_planner_receives_the_upstream_action_description(value, expected):
    assert planner_action(value) == expected
