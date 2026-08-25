from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import numpy as np
from virea_contracts.job import JobRequest
from virea_contracts.worker import WorkerInferRequest
from virea_dart.backend import DartGeneration
from virea_dart.worker import DartPlugin
from virea_model_sdk import WorkerContext


class FakeBackend:
    device_facts = {"device": "cpu", "implicit_network_access": False}

    def load(self) -> None: ...

    def unload(self) -> None: ...

    def generate(self, segments, **kwargs) -> DartGeneration:
        assert segments[0].text == "walk forward"
        assert segments[0].primitive_count == 2
        assert kwargs["seed"] == 7
        frames = 18
        return DartGeneration(
            transl=np.zeros((frames, 3), dtype=np.float32),
            global_orient=np.zeros((frames, 3), dtype=np.float32),
            body_pose=np.zeros((frames, 63), dtype=np.float32),
            primitive_boundaries=np.asarray(((0, 10), (10, 18)), dtype=np.int64),
            betas=np.zeros(10, dtype=np.float32),
            gender="male",
            text_segments=(
                {
                    "text": "walk forward",
                    "start_frame": 0,
                    "end_frame": 18,
                    "primitive_count": 2,
                },
            ),
            continuity_evidence={"verified": True},
        )


def test_metadata_reports_strategy_specific_capacity(monkeypatch) -> None:
    plugin = DartPlugin(backend=FakeBackend())

    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cpu")
    cpu_resources = plugin.metadata().resources
    assert cpu_resources["min_ram_gib"] == 24.0
    assert cpu_resources["min_vram_gib"] is None

    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cuda_full")
    cuda_resources = plugin.metadata().resources
    assert cuda_resources["min_ram_gib"] == 16.0
    assert cuda_resources["min_vram_gib"] == 10.0


def test_worker_publishes_exact_dart_artifacts(tmp_path: Path) -> None:
    plugin = DartPlugin(backend=FakeBackend())
    request = WorkerInferRequest(
        job_id="job-dart",
        request=JobRequest(
            model_id="dart-smplx",
            task="streaming_text_to_motion",
            input={"text_timeline": [{"text": "walk forward", "primitive_count": 2}]},
            parameters={"seed": 7, "guidance_scale": 5.0},
        ),
        staging_locator="jobs/job-dart/staging",
    )
    result = plugin.infer(
        request,
        WorkerContext(
            job_id="job-dart",
            staging_directory=tmp_path,
            cancel_event=Event(),
        ),
    )

    assert result.native.frame_count == 18
    assert [artifact.name for artifact in result.native.artifacts] == [
        "source_dart_transl",
        "source_dart_global_orient",
        "source_dart_body_pose",
        "source_dart_primitive_boundaries",
        "source_dart_betas",
        "generation_metadata",
    ]
    boundaries = np.load(
        tmp_path / "source_dart_primitive_boundaries.npy", allow_pickle=False
    )
    assert boundaries.dtype == np.int64
    metadata = json.loads(
        (tmp_path / "generation_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["rollout_reconstructed"] is True
    assert metadata["overlap_continuity_verified"] is True
