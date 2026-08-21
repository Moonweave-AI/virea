from __future__ import annotations

import json
import os
import time

from virea_contracts.model import ModelIdentity
from virea_contracts.provenance import GenerationProvenance
from virea_contracts.result import (
    ArtifactRef,
    ModelResult,
    NativeMotionDescriptor,
    ValidSegment,
)
from virea_contracts.worker import WorkerInferRequest, WorkerMetadata

from .plugin import WorkerContext, WorkerFailure


class FakeMotionPlugin:
    def __init__(self, model_id: str = "fake-motion-v1") -> None:
        self.model_id = model_id

    def metadata(self) -> WorkerMetadata:
        return WorkerMetadata(
            model_id=self.model_id,
            plugin_version="0.4.0",
            tasks=("text_to_motion",),
            input_schemas=("virea.job_request.v1.0.0",),
            output_representation_id="virea.fake.root_translation.v1",
            output_skeleton_id="vrm1.humanoid52.v1",
            resources={
                "deterministic": True,
                "model_dependencies": [],
                "memory_strategies": ["cpu"],
                "active_memory_strategy": os.getenv("VIREA_MEMORY_STRATEGY", "cpu"),
            },
        )

    def load(self) -> None:
        return None

    def unload(self) -> None:
        return None

    def cancel(self, job_id: str) -> None:
        return None

    def infer(self, request: WorkerInferRequest, context: WorkerContext) -> ModelResult:
        behavior = str(request.request.parameters.get("behavior", "success"))
        if behavior == "crash":
            os._exit(86)
        if behavior == "oom":
            raise WorkerFailure(
                "WORKER_OOM", "synthetic out-of-memory failure", retryable=True
            )
        if behavior == "delay":
            delay = float(request.request.parameters.get("delay_seconds", 0.5))
            # The test-only Worker also exercises transport budgets beyond the
            # control plane's former fixed 30-second HTTP timeout.  It remains
            # isolated from production model discovery and release evidence.
            deadline = time.monotonic() + max(0.0, min(delay, 60.0))
            while time.monotonic() < deadline:
                context.raise_if_cancelled()
                time.sleep(0.01)
        context.raise_if_cancelled()

        frames = int(request.request.parameters.get("frames", 8))
        fps = float(request.request.parameters.get("fps", 20.0))
        if frames < 1 or frames > 10_000:
            raise WorkerFailure("INVALID_REQUEST", "frames must be in [1, 10000]")
        if fps <= 0:
            raise WorkerFailure("INVALID_REQUEST", "fps must be positive")
        motion = {
            "schema_version": "virea.fake_motion.v1.0.0",
            "frame_count": frames,
            "fps": fps,
            "root_translation_m": [[index / fps, 0.0, 0.0] for index in range(frames)],
        }
        artifact_path = context.staging_directory / "motion.json"
        artifact_path.write_text(
            json.dumps(motion, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
        size = artifact_path.stat().st_size
        return ModelResult(
            job_id=request.job_id,
            model=ModelIdentity(
                id=self.model_id,
                plugin_version="0.4.0",
                upstream_repository="builtin://virea/fake-motion",
                upstream_revision="builtin-fake-v1",
                runtime_id=os.getenv("VIREA_RUNTIME_ID", "fake-runtime-v1"),
            ),
            task=request.request.task,
            request_id=request.request.idempotency_key,
            native=NativeMotionDescriptor(
                representation_id="virea.fake.root_translation.v1",
                skeleton_id="vrm1.humanoid52.v1",
                fps=fps,
                frame_count=frames,
                coordinate_system="vrm_gltf",
                units="meters",
                root_translation_semantics="absolute_world_meters",
                root_rotation_semantics="identity_local_to_world",
                artifacts=(
                    ArtifactRef(
                        name="motion",
                        media_type="application/json",
                        uri=f"virea-job://{request.job_id}/{request.staging_locator}/motion.json",
                        byte_length=size,
                        dtype="float32",
                        shape=(frames, 3),
                    ),
                ),
            ),
            segments=(ValidSegment(start_frame=0, end_frame=frames),),
            provenance=GenerationProvenance(
                seed=request.request.parameters.get("seed"),
                precision="float32",
                device="cpu",
                generation_parameters={"behavior": behavior},
            ),
        )
