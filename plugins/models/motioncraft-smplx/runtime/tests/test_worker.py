from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from virea_contracts.job import JobRequest
from virea_contracts.worker import WorkerInferRequest
from virea_model_sdk import WorkerContext
from virea_motioncraft.backend import MotionCraftGeneration
from virea_motioncraft.worker import MotionCraftPlugin


class FakeBackend:
    device_facts = {"device": "cpu", "offline": True}

    def load(self) -> None: ...

    def unload(self) -> None: ...

    @staticmethod
    def _output(task: str, frames: int) -> MotionCraftGeneration:
        return MotionCraftGeneration(
            normalized_motion322=np.zeros((frames, 322), dtype=np.float32),
            mean322=np.zeros(322, dtype=np.float32),
            std322=np.ones(322, dtype=np.float32),
            checkpoint_id=f"official-{task}",
            source_profile="motionx.metric_y_up",
            task=task,
            conditioning_frames=None if task == "text_to_motion" else frames,
        )

    def generate_text(
        self, prompt: str, *, frames: int, seed: int
    ) -> MotionCraftGeneration:
        assert prompt and seed == 7
        return self._output("text_to_motion", frames)

    def generate_speech(
        self, audio_path: Path, *, transcript: str, seed: int
    ) -> MotionCraftGeneration:
        assert audio_path.is_file() and transcript == "hello" and seed == 7
        return self._output("speech_to_gesture", 60)

    def generate_music(
        self, audio_path: Path, *, style_prompt: str, seed: int
    ) -> MotionCraftGeneration:
        assert audio_path.is_file() and style_prompt == "jazz" and seed == 7
        return self._output("music_to_dance", 90)


@pytest.mark.parametrize(
    ("task", "request_input", "frames"),
    (
        (
            "text_to_motion",
            {"prompt": "A person waves.", "motion_length_frames": 60},
            60,
        ),
        ("speech_to_gesture", {"audio": "{audio}", "transcript": "hello"}, 60),
        ("music_to_dance", {"audio": "{audio}", "style_prompt": "jazz"}, 90),
    ),
)
def test_worker_publishes_exact_adapter_contract(
    tmp_path: Path,
    task: str,
    request_input: dict[str, object],
    frames: int,
) -> None:
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"RIFF-test")
    resolved_input = {
        key: str(audio) if value == "{audio}" else value
        for key, value in request_input.items()
    }
    plugin = MotionCraftPlugin(backend=FakeBackend())
    request = WorkerInferRequest(
        job_id=f"job-{task}",
        request=JobRequest(
            model_id="motioncraft-smplx",
            task=task,
            input=resolved_input,
            parameters={"seed": 7},
        ),
        staging_locator=f"jobs/job-{task}/staging",
    )
    context = WorkerContext(
        job_id=request.job_id,
        staging_directory=tmp_path,
        cancel_event=Event(),
    )

    result = plugin.infer(request, context)

    assert result.native.frame_count == frames
    assert result.native.representation_id == "motionx.smplx322.v1"
    assert np.load(
        tmp_path / "source_motioncraft_motionx322_normalized.npy",
        allow_pickle=False,
    ).shape == (frames, 322)
    assert np.load(
        tmp_path / "source_motioncraft_motionx_mean322.npy",
        allow_pickle=False,
    ).shape == (322,)
    metadata = json.loads((tmp_path / "generation_metadata.json").read_text("utf-8"))
    assert metadata["checkpoint_id"] == f"official-{task}"
    assert metadata["source_profile"] == "motionx.metric_y_up"


def test_metadata_declares_all_three_official_tasks() -> None:
    metadata = MotionCraftPlugin(backend=FakeBackend()).metadata()
    assert metadata.tasks == (
        "text_to_motion",
        "speech_to_gesture",
        "music_to_dance",
    )


def test_worker_materializes_browser_audio_data_uri(tmp_path: Path) -> None:
    plugin = MotionCraftPlugin(backend=FakeBackend())
    request = WorkerInferRequest(
        job_id="job-browser-audio",
        request=JobRequest(
            model_id="motioncraft-smplx",
            task="speech_to_gesture",
            input={
                "audio": "data:audio/wav;base64,UklGRi10ZXN0",
                "transcript": "hello",
            },
            parameters={"seed": 7},
        ),
        staging_locator="jobs/job-browser-audio/staging",
    )

    result = plugin.infer(
        request,
        WorkerContext(
            job_id=request.job_id,
            staging_directory=tmp_path,
            cancel_event=Event(),
        ),
    )

    assert result.native.frame_count == 60
    assert (tmp_path / "browser_audio.wav").read_bytes() == b"RIFF-test"
