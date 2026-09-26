"""Reuse VIREA's resource admission, worker cancellation, retargeting and export."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from urllib.parse import quote

from virea_contracts.job import JobRequest

from ..contracts import CharacterConfig

CAPABILITIES = {
    "body_and_face": True,
    "native_history": False,
    "executed_pose_conditioning": False,
    "online_worker_streaming": False,
    "generative_fingers": False,
    "silent_generative_motion": False,
    "playback_continuity": "renderer_pose_blend",
    "scene_actions": ["look_at", "move_to", "stop"],
}


class MotionProvider:
    def __init__(self, control, config: CharacterConfig):
        self.control = control
        self.config = config

    async def generate(
        self, audio: bytes, text: str, intent: str, avatar_id: str | None
    ) -> dict:
        request = JobRequest(
            model_id="sentiavatar-susu",
            task="audio_text_to_avatar_motion",
            input={
                "audio": "data:audio/wav;base64,"
                + base64.b64encode(audio).decode("ascii"),
                "dialogue_text": text,
                "action_and_expression_tags": intent,
            },
            parameters={"generate_face": True},
            avatar_id=avatar_id,
            execution_target=self.config.execution_target,
        )
        # submit is a short durable enqueue. Keep it atomic with ownership of job_id.
        job = self.control.submit(request, inference_timeout=self.config.motion_timeout)
        job_id = job["id"]
        try:
            return await asyncio.wait_for(
                self._result(job_id), self.config.motion_timeout + 10
            )
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
                return {
                    "job_id": job_id,
                    "result_id": result_id,
                    "vrma_url": f"/api/v1/results/{quote(result_id, safe='')}/artifacts/{quote(Path(export['locator']).name, safe='')}",
                    "native_history_applied": False,
                    "executed_pose_conditioning": False,
                }
            if job["state"] in {"FAILED", "REJECTED", "TIMED_OUT", "CANCELLED"}:
                raise RuntimeError(f"motion job {job_id}: {job['state']}")
            await asyncio.sleep(0.2)
