"""Optional recorder regressions; no game, audio stream or encoder is opened."""

from collections import deque
from types import SimpleNamespace

import pytest

pytest.importorskip("PIL")
pytest.importorskip("imageio_ffmpeg")

from scripts.vrchat import record_demo


class ImmediateStop:
    stopped = False

    def wait(self, _):
        return self.stopped

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True


@pytest.mark.parametrize("session_error", [False, True])
def test_recorder_completes_when_result_history_is_full_or_stops_on_error(
    monkeypatch, session_error
):
    # The bridge retains only 20 results. Finishing a new task must still be
    # detected when its arrival evicts an older result and the length stays 20.
    results = deque(({"packet_id": f"old-{i}"} for i in range(20)), maxlen=20)
    submitted = []

    def api(path="", body=None):
        if path == "/messages":
            submitted.append(body["text"])
            results.append(
                {
                    "packet_id": f"new-{len(submitted)}",
                    "status": "completed",
                    "chat_dropped": 0,
                }
            )
        return {
            "config": {"audio_enabled": False},
            "session": {
                "epoch": len(submitted),
                "status": "error" if session_error and submitted else "waiting",
                "events": [{"kind": "error", "message": "speech overlap"}],
            },
            "recent_performances": list(results),
            "execution": None,
        }

    ticks = iter(range(0, 100000, 100))
    monkeypatch.setattr(
        record_demo, "time", SimpleNamespace(monotonic=lambda: next(ticks))
    )
    monkeypatch.setattr(record_demo, "muted_render_endpoints", lambda: 5)
    recorder = object.__new__(record_demo.DemoRecorder)
    recorder.scenario = {"turns": [{"text": f"Turn {i}"} for i in range(4)]}
    recorder.api = api
    recorder.start = 0
    recorder.stop = ImmediateStop()
    recorder.events, recorder.completed = [], []
    recorder.interact()
    if session_error:
        assert len(submitted) == 1
        assert not recorder.completed
        assert recorder.events[-1]["kind"] == "recording_failed"
        assert recorder.status == "speech overlap"
    else:
        assert len(submitted) == 4
        assert len(recorder.completed) == 4
        assert recorder.events[-1]["kind"] == "recording_completed"
        assert recorder.status == "completed"
