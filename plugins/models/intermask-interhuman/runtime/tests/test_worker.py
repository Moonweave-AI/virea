from __future__ import annotations

from pathlib import Path
from threading import Event

import numpy as np
import pytest
from virea_contracts.job import JobRequest
from virea_contracts.worker import WorkerInferRequest
from virea_intermask.backend import InterMaskGeneration
from virea_intermask.worker import InterMaskPlugin
from virea_model_sdk import WorkerContext, WorkerFailure


class FakeBackend:
    loaded = True
    device_facts = {"device": "cpu", "implicit_network_access": False}

    def load(self) -> None: ...

    def unload(self) -> None: ...

    def generate(self, prompt: str, **kwargs) -> InterMaskGeneration:
        frames = kwargs["frame_count"]
        assert prompt and frames == 60
        return InterMaskGeneration(
            actors_motion262=np.zeros((2, frames, 262), dtype=np.float32),
            shared_frame_transform=np.eye(4, dtype=np.float32),
        )


def test_metadata_reports_strategy_specific_capacity(monkeypatch) -> None:
    plugin = InterMaskPlugin(backend=FakeBackend())

    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cpu")
    cpu_resources = plugin.metadata().resources
    assert cpu_resources["min_ram_gib"] == 16.0
    assert cpu_resources["min_vram_gib"] is None

    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cuda_full")
    cuda_resources = plugin.metadata().resources
    assert cuda_resources["min_ram_gib"] == 12.0
    assert cuda_resources["min_vram_gib"] == 8.0


def test_worker_rejects_duration_that_is_not_a_four_frame_multiple(
    tmp_path: Path,
) -> None:
    plugin = InterMaskPlugin(backend=FakeBackend())
    envelope = WorkerInferRequest(
        job_id="job-invalid-duration",
        request=JobRequest(
            model_id="intermask-interhuman",
            task="text_to_two_person_interaction",
            input={"prompt": "Two people shake hands.", "duration_seconds": 2.1},
            parameters={"seed": 7},
        ),
        staging_locator="jobs/job-invalid-duration/staging",
    )

    with pytest.raises(WorkerFailure, match="multiple of 4 frames"):
        plugin.infer(
            envelope,
            WorkerContext(
                job_id=envelope.job_id,
                staging_directory=tmp_path,
                cancel_event=Event(),
            ),
        )


def test_worker_publishes_two_actor_contract(tmp_path: Path) -> None:
    plugin = InterMaskPlugin(backend=FakeBackend())
    envelope = WorkerInferRequest(
        job_id="job-intermask",
        request=JobRequest(
            model_id="intermask-interhuman",
            task="text_to_two_person_interaction",
            input={"prompt": "Two people shake hands.", "duration_seconds": 2.0},
            parameters={"seed": 7},
        ),
        staging_locator="jobs/job-intermask/staging",
    )
    result = plugin.infer(
        envelope,
        WorkerContext(
            job_id="job-intermask",
            staging_directory=tmp_path,
            cancel_event=Event(),
        ),
    )

    assert result.native.frame_count == 60
    assert np.load(
        tmp_path / "source_intermask_motion262.npy", allow_pickle=False
    ).shape == (2, 60, 262)
    assert len(result.native.artifacts) == 3


def test_worker_executes_reaction_conditioning_branch(tmp_path: Path) -> None:
    class ReactionBackend(FakeBackend):
        def generate(self, prompt: str, **kwargs) -> InterMaskGeneration:
            conditioning = kwargs["conditioning_actor_motion"]
            assert isinstance(conditioning, np.ndarray)
            assert conditioning.shape == (60, 262)
            return super().generate(prompt, **kwargs)

    plugin = InterMaskPlugin(backend=ReactionBackend())
    conditioning = np.zeros((60, 262), dtype=np.float32)
    envelope = WorkerInferRequest(
        job_id="job-intermask-reaction",
        request=JobRequest(
            model_id="intermask-interhuman",
            task="interaction_reaction_generation",
            input={
                "prompt": "The second person responds with a handshake.",
                "conditioning_actor_motion": conditioning.tolist(),
            },
            parameters={"seed": 7},
        ),
        staging_locator="jobs/job-intermask-reaction/staging",
    )

    result = plugin.infer(
        envelope,
        WorkerContext(
            job_id=envelope.job_id,
            staging_directory=tmp_path,
            cancel_event=Event(),
        ),
    )

    assert result.task == "interaction_reaction_generation"
    assert result.native.frame_count == 60
