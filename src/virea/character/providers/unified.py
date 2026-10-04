"""One resident model family for the entire performance; no fallback routing."""

import base64
import copy
import math
from uuid import uuid4

import numpy as np
from pydantic import ValidationError

from ..performance_audio import slice_audio
from ..performance_contracts import (
    FPS,
    MAX_SECONDS,
    SAMPLE_RATE,
    PerformancePlan,
    sample_at,
)
from ..performance_planning import requested_motion_duration
from .routing import structured_completion

RULES = """Plan one character performance with two INDEPENDENT tracks on a shared clock.
motions: ordered nonoverlapping segments with absolute start_seconds, duration_seconds,
English physical motion prompt, and a short user-language label. Multiple actions may
last longer than speech. Speech can start anywhere, cross action boundaries, or be absent.
speech: final spoken text, absolute start_seconds OR after_clip (earlier speech ID) plus
gap_seconds. Never guess speech duration: TTS determines it. Prefer after_clip when words
must follow previous words. Never truncate or stretch motion to the speech length.
Use idle_prompt (English) for gaps and any speech tail beyond planned actions.
If a return to rest is requested, explicitly add it as the last motion segment.
This backend supports free motion captions, not guaranteed object contact or path constraints.
Preserve the user's durations, sequence and silence requests. Do not allocate SentiAvatar
or ARDY, and do not create needless speech. At most 180 seconds in total.
Always emit both motions and speech arrays. They may individually be empty, but never
both. For absolute speech placement set after_clip=null and gap_seconds=0; for relative
placement set start_seconds=null. Use concise English, physical third-person captions
for each motion (not dialogue, stage directions, or multi-stage stories in one caption).
Prefer simple, complete motion intentions in short English captions (usually 3-12 words).
Use the subject 'A person', never a character name, emotional narrative or camera cue.
Natural small combinations are allowed: 'A person raises both arms and lowers them.'
Do not mechanically split preparation, holding and settling into separate segments.
Split only overly complex choreography, distinct action goals, or actions whose timing
the user explicitly controls. Preserve the requested timing and give actions enough time.
Set speech_gestures=true only for conversational gesturing, presenting or explaining.
Keep it false for explicit physical actions such as walking, squatting, dancing or boxing;
speech still plays at its own scheduled time during those actions.
Continuity comes from compatible adjacent poses and native history, not verbose prompts.
"""


class UnifiedMotionProvider:
    def __init__(self, config, client):
        self.config, self.client = config, client
        self.backend = config.motion_backend
        self.url = getattr(config, f"{self.backend}_url")

    async def health(self):
        response = await self.client.get(self.url.rstrip("/") + "/health", timeout=5)
        response.raise_for_status()
        value = response.json()
        if (
            value.get("backend") != self.backend
            or value.get("schema") != "virea.performance_worker.v1"
        ):
            raise ValueError("motion worker identity/protocol mismatch")
        if (
            not value.get("ready")
            or not value.get("native_history")
            or not value.get("temporal_conditioning")
        ):
            raise ValueError(
                f"{self.backend} worker is not ready for independent tracks"
            )
        return value

    async def plan(self, history, context):
        requested_duration = requested_motion_duration(history)
        schema = PerformancePlan.model_json_schema()
        # Optional API defaults are not optional output fields for a constrained LLM.
        # Otherwise some grammar decoders choose the empty/default-only object.
        schema["required"] = list(schema["properties"])
        for definition in schema["$defs"].values():
            definition["required"] = list(definition["properties"])
        # The API validator's XOR must also constrain grammar-based decoding.
        # Merely describing it lets the LLM emit both an absolute time and an ID.
        absolute = copy.deepcopy(schema["$defs"]["SpeechClip"])
        relative = copy.deepcopy(absolute)
        absolute["properties"].update(
            start_seconds={
                "type": "number",
                "minimum": 0,
                "exclusiveMaximum": MAX_SECONDS,
            },
            after_clip={"type": "null"},
            gap_seconds={"const": 0},
        )
        relative["properties"].update(
            start_seconds={"type": "null"},
            after_clip={"type": "string", "minLength": 1, "maxLength": 80},
        )
        schema["$defs"]["SpeechClip"] = {"oneOf": [absolute, relative]}
        for attempt in range(3):
            value = await structured_completion(
                self.config,
                self.client,
                history,
                context,
                self.config.persona + "\n" + RULES,
                schema,
                tokens=self.config.language_max_tokens,
                thinking=self.config.llm_thinking,
                include_history=True,
            )
            try:
                plan = PerformancePlan.model_validate(value)
                if (
                    requested_duration is not None
                    and abs(plan.motion_end - requested_duration) > 1 / FPS
                ):
                    raise ValueError(
                        f"The user requested {requested_duration:g} seconds of motion, but the last action ends at {plan.motion_end:g}. "
                        "Replan the action durations to cover the requested total, keeping speech independently placed."
                    )
                return plan
            except (ValidationError, ValueError) as exc:
                if attempt == 2:
                    raise
                context = {
                    **context,
                    "invalid_plan": value,
                    "validation_feedback": str(exc),
                    "repair_instruction": "Repair the invalid plan while preserving the original user's complete request.",
                }

    async def generate(self, plan, resolve_before, resolve_all, record):
        health = await self.health()
        capacity = int(health["window_frames"]) - int(health["history_frames"])
        overlap = int(health["history_frames"])
        if not 1 <= capacity <= 180 or not 0 <= overlap <= 32:
            raise ValueError("invalid native window geometry")
        stream_id, cursor, sequence = uuid4().hex, 0, 0
        outputs, clips = [], []
        total_frames = math.ceil(plan.motion_end * FPS)
        try:
            while True:
                if cursor >= total_frames:
                    clips = await resolve_all()
                    total_frames = max(
                        total_frames,
                        math.ceil(
                            max((c.end_sample for c in clips), default=0)
                            * FPS
                            / SAMPLE_RATE
                        ),
                    )
                    if cursor >= total_frames:
                        break
                # Keep native seeds on their complete latent lattice. Only trim the
                # final delivered performance; never shorten an intermediate seed.
                count = capacity
                context_start = max(0, cursor - overlap)
                context_end = context_start + int(health["window_frames"])
                # Native lookahead may cross a speech boundary even if emitted frames don't.
                clips = await resolve_before(context_end / FPS)
                pcm = slice_audio(
                    clips, sample_at(context_start), sample_at(context_end)
                )
                response = await self.client.post(
                    self.url.rstrip("/") + "/windows",
                    json={
                        "stream_id": stream_id,
                        "backend": self.backend,
                        "sequence": sequence,
                        "start_frame": cursor,
                        "frames": count,
                        "seed": plan.seed,
                        "motions": [s.model_dump() for s in plan.motions],
                        "idle_prompt": plan.idle_prompt,
                        "audio_pcm": base64.b64encode(pcm.tobytes()).decode(),
                        "audio_start_frame": context_start,
                        "speech_ranges": [
                            (c.start_sample / SAMPLE_RATE, c.end_sample / SAMPLE_RATE)
                            for c in clips
                        ],
                    },
                    timeout=self.config.motion_timeout,
                )
                response.raise_for_status()
                value = response.json()
                width = 322 if self.backend == "motioncraft" else 623
                expected = "motionx322" if self.backend == "motioncraft" else "h3d623"
                array = np.asarray(value.get("values"), dtype=np.float32)
                if (
                    value.get("sequence") != sequence
                    or value.get("start_frame") != cursor
                    or value.get("representation") != expected
                    or value.get("normalized") is not False
                    or array.shape != (count, width)
                    or not np.isfinite(array).all()
                ):
                    raise ValueError("motion worker returned invalid native frames")
                outputs.append(array)
                cursor += count
                sequence += 1
                record(
                    "motion_window_generated",
                    backend=self.backend,
                    frames=count,
                    end_seconds=cursor / FPS,
                )
                if total_frames > MAX_SECONDS * FPS:
                    raise ValueError("performance exceeds duration limit")
            complete = np.concatenate(outputs)
            if health.get("finalize_required"):
                response = await self.client.post(
                    self.url.rstrip("/") + f"/streams/{stream_id}/finalize",
                    timeout=self.config.motion_timeout,
                )
                response.raise_for_status()
                value = response.json()
                complete = np.asarray(value.get("values"), dtype=np.float32)
                if (
                    value.get("frames") != cursor
                    or value.get("representation") != expected
                    or value.get("normalized") is not False
                    or complete.shape != (cursor, width)
                    or not np.isfinite(complete).all()
                ):
                    raise ValueError("motion worker returned invalid complete decoding")
                record("motion_sequence_decoded", backend=self.backend, frames=cursor)
            return complete[:total_frames], clips, health
        finally:
            # Closing HTTP generation alone does not release resident native history.
            try:
                await self.client.delete(
                    self.url.rstrip("/") + f"/streams/{stream_id}", timeout=5
                )
            except Exception:
                pass  # Worker leases are the fallback for a lost connection.
