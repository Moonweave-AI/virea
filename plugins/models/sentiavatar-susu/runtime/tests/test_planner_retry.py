"""A malformed sampled plan must never become a fabricated pose."""

from types import SimpleNamespace

import numpy as np
import pytest
from virea_model_sdk.plugin import WorkerFailure
from virea_sentiavatar import backend as module
from virea_sentiavatar.backend import SentiAvatarBackend


@pytest.mark.parametrize("recovers", [True, False])
def test_short_plan_retries_once_with_same_context(monkeypatch, recovers):
    backend = SentiAvatarBackend.__new__(SentiAvatarBackend)
    backend.roots = None
    backend._mask_model = None
    backend._seed = lambda _: None
    monkeypatch.setattr(module, "_read_audio", lambda *args: np.zeros(16000))
    backend._audio_features = lambda _: (np.zeros((12, 768)), None)
    backend._audio_tokens = lambda _: list(range(12))
    backend._pipeline = SimpleNamespace(
        construct_llm_prompt=lambda *args, **kwargs: ("same audio prompt", None),
        sparse_to_keyframes=lambda value: value,
        ensure_length=lambda value, _: value,
    )
    calls = []

    def planner(prompt, **kwargs):
        calls.append((prompt, kwargs, backend._generation_seed))
        if len(calls) == 1 or not recovers:
            raise WorkerFailure("PLANNER_OUTPUT_INVALID", "too short", retryable=True)
        return [[1, 2, 3, 4]] * 3

    backend._planner_tokens = planner
    monkeypatch.setattr(module, "interpolate_batched", lambda *args, **kwargs: [[1, 2, 3, 4]] * 12)
    backend._decode_body = lambda _: np.zeros((24, 153))
    kwargs = dict(seed=42, temperature=.5, top_p=.7, generate_steps=6,
                  max_new_tokens=512, generate_face=False)
    if recovers:
        body, face, tail, history = backend._generate_chunk("audio", "intent", **kwargs)
        assert body.shape == (24, 153) and face is None
        assert len(history) == 2 and tail
    else:
        with pytest.raises(WorkerFailure, match="too short"):
            backend._generate_chunk("audio", "intent", **kwargs)
    assert len(calls) == 2
    assert calls[0][0] == calls[1][0]
    assert [call[2] for call in calls] == [42, 43]
    assert calls[1][1]["temperature"] == .2
