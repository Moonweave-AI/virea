import asyncio
from types import SimpleNamespace

from test_behavior import setup
from test_streaming import acknowledge, session_fixture, until

from virea.character.motion_timing import fit_program_duration
from virea.character.settlement import SettlementPolicy, terminal_measurement


def test_unspecified_total_still_uses_the_native_time_grid():
    actions = [
        dict(kind="perform", duration_seconds=2.5),
        dict(kind="perform", duration_seconds=3),
    ]
    fit_program_duration(actions, None)
    assert [a["duration_seconds"] for a in actions] == [2.6, 3.0]


def test_speech_receipt_cannot_reopen_an_already_settled_activity(monkeypatch):
    client, current = setup(monkeypatch)
    current.body_program = dict(
        id="program",
        actions=[],
        ending="Resting comfortably.",
        status="completed",
        elapsed=8,
        settled_seconds=4,
    )
    with client:
        slot = client.post("/s/behavior/plan", json={"body": {}}).json()
        for status in ("playing", "completed"):
            assert (
                client.post(
                    f"/s/behavior/{slot['id']}/feedback",
                    json={"body": {}, "status": status},
                ).status_code
                == 200
            )
    assert current.body_program["status"] == "completed"
    assert current.body_program["settled_seconds"] == 4


def test_terminal_acceptance_rejects_airborne_and_moving_but_accepts_seated_support():
    policy = SettlementPolicy()

    def window(height, moving=False):
        return dict(
            fps=20,
            hip_height=1,
            root=[[i / 10 if moving else 0, 0.45, 0] for i in range(21)],
            joints={"hips": [[0, 0.45, 0]] * 21, "leftFoot": [[0, height, 0]] * 21},
        )

    assert not terminal_measurement([window(0.4)], 0, policy)["settled"]
    assert not terminal_measurement([window(0.02, True)], 0, policy)["settled"]
    assert terminal_measurement([window(0.02)], 0, policy)["settled"]


def test_temporal_audio_completes_even_when_motion_never_finishes(tmp_path):
    async def run():
        session = session_fixture(tmp_path)
        entered = asyncio.Event()

        async def blocked(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        session.motion.generate = blocked
        await session.message("开始")
        session.route = {"engine": "temporal"}
        await until(lambda: len(session.ready) == 3)
        assert session.pending["motion"] is None
        assert session.pending["independent_speech"]
        await until(entered.is_set)
        session.language.finish.set()
        while session.status != "waiting":
            if session.pending:
                assert session.acknowledge(acknowledge(session))
            await asyncio.sleep(0.001)
        assert session.history[-1]["content"] == session.language.text
        assert session._task.done()
        await session.close()

    asyncio.run(run())


def test_body_compiler_failure_cannot_cancel_accepted_speech(tmp_path):
    from virea.character.providers.performance import EmbodiedCommitment

    async def run():
        session = session_fixture(tmp_path)
        original = session.language
        release = asyncio.Event()

        async def appraise(*args):
            return SimpleNamespace(
                speech="speak",
                expression_executor="sentiavatar",
                embodiment=EmbodiedCommitment(operation="replace", goal="表演"),
                understanding="交谈并表演",
                reply=SimpleNamespace(
                    goal="讲故事", model_dump=lambda: {"goal": "讲故事", "outline": []}
                ),
            )

        async def compile(*args):
            await release.wait()
            raise RuntimeError("motion compiler unavailable")

        session.language.appraise = appraise
        session.language.compile = compile
        original.finish.set()
        await session.message("边表演边讲故事")
        await until(lambda: session.pending is not None)
        assert not release.is_set()
        release.set()
        while session.status != "waiting":
            if session.pending:
                assert session.acknowledge(acknowledge(session))
            await asyncio.sleep(0.001)
        assert session.history[-1]["content"] == original.text
        assert any(e["kind"] == "body_error" for e in session.events)
        await session.close()

    asyncio.run(run())
