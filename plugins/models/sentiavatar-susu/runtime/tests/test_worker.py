from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from virea_contracts.job import JobRequest
from virea_contracts.worker import WorkerInferRequest
from virea_model_sdk import WorkerContext
from virea_sentiavatar.backend import SentiAvatarGeneration
from virea_sentiavatar.worker import SentiAvatarPlugin


class FakeBackend:
    loaded = True
    device_facts = {"device": "cpu", "implicit_network_access": False}

    def __init__(self) -> None:
        self.calls: list[
            tuple[tuple[str, ...], tuple[str, ...], dict[str, object]]
        ] = []

    def load(self) -> None: ...

    def unload(self) -> None: ...

    def generate(self, audios, actions, **parameters) -> SentiAvatarGeneration:
        self.calls.append((tuple(audios), tuple(actions), parameters))
        frames = 40 * len(audios)
        return SentiAvatarGeneration(
            body153_normalized=np.zeros((frames, 153), dtype=np.float32),
            left_hand120_denormalized=np.zeros((frames, 120), dtype=np.float32),
            right_hand120_denormalized=np.zeros((frames, 120), dtype=np.float32),
            body_mean153=np.zeros((153,), dtype=np.float32),
            body_std153=np.ones((153,), dtype=np.float32),
            face_arkit51=np.zeros((frames, 51), dtype=np.float32),
            chunk_count=len(audios),
        )


def _context(tmp_path: Path, job_id: str) -> WorkerContext:
    return WorkerContext(
        job_id=job_id, staging_directory=tmp_path, cancel_event=Event()
    )


def test_audio_text_worker_publishes_exact_adapter_contract(tmp_path: Path) -> None:
    backend = FakeBackend()
    request = WorkerInferRequest(
        job_id="job-senti",
        request=JobRequest(
            model_id="sentiavatar-susu",
            task="audio_text_to_avatar_motion",
            input={
                "audio": "artifact://sentiavatar-source/source/examples/demo.wav",
                "dialogue_text": "你好。",
                "action_and_expression_tags": "动作：挥手",
            },
            parameters={"seed": 7, "generate_face": True},
        ),
        staging_locator="jobs/job-senti/staging",
    )

    result = SentiAvatarPlugin(backend=backend).infer(
        request, _context(tmp_path, "job-senti")
    )

    assert result.native.frame_count == 40
    assert result.native.representation_id == "susu.body25_hands40.cont6d_root_delta.v1"
    expected = {
        "source_sentiavatar_body153_normalized": (40, 153),
        "source_sentiavatar_left_hand120_denormalized": (40, 120),
        "source_sentiavatar_right_hand120_denormalized": (40, 120),
        "source_sentiavatar_body_mean153": (153,),
        "source_sentiavatar_body_std153": (153,),
        "source_sentiavatar_face_arkit51": (40, 51),
    }
    for name, shape in expected.items():
        assert np.load(tmp_path / f"{name}.npy", allow_pickle=False).shape == shape
    metadata = json.loads((tmp_path / "generation_metadata.json").read_text())
    assert metadata["hands_are_denormalized"] is True
    assert metadata["checkpoint_id"].endswith(
        "242b2031a913dd1b25f43fe1f3e112611864c9cc"
    )
    assert backend.calls[0][1] == ("动作：挥手你好。",)


def test_streaming_task_accepts_json_arrays_and_concatenates_chunks(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    request = WorkerInferRequest(
        job_id="job-stream",
        request=JobRequest(
            model_id="sentiavatar-susu",
            task="streaming_dialogue_avatar_motion",
            input={
                "audio_chunks": json.dumps(["first.wav", "second.wav"]),
                "dialogue_turns": ["第一句", "第二句"],
            },
        ),
        staging_locator="jobs/job-stream/staging",
    )

    result = SentiAvatarPlugin(backend=backend).infer(
        request, _context(tmp_path, "job-stream")
    )

    assert result.native.frame_count == 80
    assert backend.calls[0][0] == ("first.wav", "second.wav")
    assert backend.calls[0][1] == ("动作：说话第一句", "动作：说话第二句")


def test_streaming_task_rejects_misaligned_turns(tmp_path: Path) -> None:
    request = WorkerInferRequest(
        job_id="job-invalid",
        request=JobRequest(
            model_id="sentiavatar-susu",
            task="streaming_dialogue_avatar_motion",
            input={
                "audio_chunks": ["one.wav", "two.wav"],
                "dialogue_turns": ["one", "two", "three"],
            },
        ),
        staging_locator="jobs/job-invalid/staging",
    )

    with pytest.raises(Exception, match="equal length"):
        SentiAvatarPlugin(backend=FakeBackend()).infer(
            request, _context(tmp_path, "job-invalid")
        )
