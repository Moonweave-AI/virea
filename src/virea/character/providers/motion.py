"""Reuse VIREA's resource admission, worker cancellation, retargeting and export."""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
from pathlib import Path
from urllib.parse import quote

from virea_contracts.job import JobRequest

from ..contracts import CharacterConfig
from ..utterances import planner_action

CAPABILITIES = {
    "body_and_face": True,
    "native_history": True,
    "native_history_mode": "within_continuous_expression",
    "model_native_history": True,
    "planner_history": True,
    "executed_pose_conditioning": False,
    "online_worker_streaming": False,
    "pipeline_streaming": "bounded_audio_windows_with_planner_and_rvq_history",
    "generative_fingers": False,
    "silent_generative_motion": False,
    "playback_continuity": "continuous_windows_then_relaxed_idle",
    "scene_actions": ["look_at", "move_to", "reach", "sit", "stand", "perform", "stop"],
    "spatial_model": "ARDY-Core-RP-20FPS-Horizon8 (optional resident worker)",
    "spatial_physics": False,
    "body_routing": "stationary: SentiAvatar; locomotion: ARDY + upper-body speech; interaction: ARDY + speech face",
}


class MotionProvider:
    def __init__(self, control, config: CharacterConfig):
        self.control = control
        self.config = config

    async def generate(
        self,
        audio: bytes,
        text: str,
        intent: str,
        avatar_id: str | None,
        *,
        motion_prefix: list | None = None,
        planner_history: list | None = None,
    ) -> dict:
        request = JobRequest(
            model_id="sentiavatar-susu",
            task="audio_text_to_avatar_motion",
            input={
                "audio": "data:audio/wav;base64,"
                + base64.b64encode(audio).decode("ascii"),
                "dialogue_text": text,
                "action_and_expression_tags": planner_action(intent),
            },
            parameters={
                "generate_face": True,
                "motion_prefix": motion_prefix,
                "planner_history": planner_history,
                "planner_action_only": True,
                "planner_url": self.config.motion_planner_url,
                "seed": secrets.randbelow(2_147_483_583),
                "temperature": 0.5,
                "top_p": 0.7,
            },
            avatar_id=avatar_id,
            execution_target=self.config.execution_target,
        )
        # submit is a short durable enqueue. Keep it atomic with ownership of job_id.
        job = self.control.submit(
            request,
            inference_timeout=self.config.motion_timeout,
            keep_worker_alive=True,
        )
        job_id = job["id"]
        try:
            return await asyncio.wait_for(
                self._result(job_id), self.config.motion_timeout + 10
            )
        except asyncio.CancelledError:
            await asyncio.to_thread(self.control.discard, job_id)
            raise
        except BaseException:
            await asyncio.to_thread(self.control.cancel, job_id)
            raise

    async def _result(self, job_id: str) -> dict:
        while True:
            job = await asyncio.to_thread(self.control.store.get_job, job_id)
            if job is None:
                raise RuntimeError("motion job disappeared")
            if job["state"] == "SUCCEEDED":
                row = await asyncio.to_thread(self.control.store.result_for_job, job_id)
                result = json.loads(row["payload_json"])
                export = next(
                    item
                    for item in result["exports"]
                    if item["format"].lower() == "vrma"
                )
                result_id = result["result_id"]
                metadata = await asyncio.to_thread(
                    (
                        self.control.paths.result_directory(result_id)
                        / "model-result.json"
                    ).read_text,
                    encoding="utf-8",
                )
                generation = json.loads(metadata)["provenance"]["generation_parameters"]
                return {
                    "job_id": job_id,
                    "result_id": result_id,
                    "vrma_url": f"/api/v1/results/{quote(result_id, safe='')}/artifacts/{quote(Path(export['locator']).name, safe='')}",
                    "native_history_applied": generation.get(
                        "native_history_applied", False
                    ),
                    "motion_tail": generation.get("motion_tail", []),
                    "planner_history": generation.get("planner_history", []),
                    "planner_history_applied": generation.get(
                        "planner_history_applied", False
                    ),
                    "executed_pose_conditioning": False,
                    "planner_backend": generation.get("planner_backend", "transformers"),
                }
            if job["state"] in {"FAILED", "REJECTED", "TIMED_OUT", "CANCELLED"}:
                raise RuntimeError(f"motion job {job_id}: {job['state']}")
            await asyncio.sleep(0.2)
