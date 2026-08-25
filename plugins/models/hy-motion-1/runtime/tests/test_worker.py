from __future__ import annotations

from pathlib import Path
from threading import Event

import numpy as np
from virea_contracts.job import JobRequest
from virea_contracts.worker import WorkerInferRequest
from virea_hy_motion.backend import HyMotionGeneration
from virea_hy_motion.worker import HyMotionPlugin
from virea_model_sdk import WorkerContext


class FakeBackend:
    loaded = True
    device_facts = {"device": "cpu", "implicit_network_access": False}

    def load(self) -> None: ...

    def unload(self) -> None: ...

    def generate(self, prompt: str, **kwargs) -> HyMotionGeneration:
        assert prompt
        assert kwargs["duration_seconds"] == 2.0
        frames = 60
        return HyMotionGeneration(
            translation_m=np.zeros((frames, 3), dtype=np.float32),
            rotations_6d=np.tile(
                np.asarray([1, 0, 0, 1, 0, 0], dtype=np.float32),
                (frames, 22, 1),
            ),
            latent_denorm=np.zeros((frames, 201), dtype=np.float32),
            keypoints3d=np.zeros((frames, 22, 3), dtype=np.float32),
        )


def test_metadata_reports_strategy_specific_capacity(monkeypatch) -> None:
    plugin = HyMotionPlugin(backend=FakeBackend())

    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cpu")
    cpu_resources = plugin.metadata().resources
    assert cpu_resources["min_ram_gib"] == 40.0
    assert cpu_resources["min_vram_gib"] is None

    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cuda_full")
    cuda_resources = plugin.metadata().resources
    assert cuda_resources["min_ram_gib"] == 24.0
    assert cuda_resources["min_vram_gib"] == 26.0


def test_worker_publishes_adapter_ready_native_arrays(tmp_path: Path) -> None:
    plugin = HyMotionPlugin(backend=FakeBackend())
    request = WorkerInferRequest(
        job_id="job-hy",
        request=JobRequest(
            model_id="hy-motion-1",
            task="text_to_motion",
            input={"prompt": "A person waves.", "duration_seconds": 2.0},
            parameters={"seed": 7},
        ),
        staging_locator="jobs/job-hy/staging",
    )
    context = WorkerContext(
        job_id="job-hy", staging_directory=tmp_path, cancel_event=Event()
    )

    result = plugin.infer(request, context)

    assert result.native.frame_count == 60
    assert result.native.representation_id == "hy_motion.body22.rot6d_translation.v1"
    assert np.load(
        tmp_path / "source_hy_translation_m.npy", allow_pickle=False
    ).shape == (60, 3)
    assert np.load(
        tmp_path / "source_hy_rotations_6d.npy", allow_pickle=False
    ).shape == (60, 22, 6)
