"""Official MotionCraft T2M and S2G task graphs on one independent timeline.

T2M owns explicit actions. Conversational upper-body gestures use S2G with its
own statistics. This composition is a VIREA extension, not an all-task checkpoint.
"""

from pathlib import Path

import numpy as np

from virea.character.performance_contracts import FPS

from .conditioning import beat_audio_features, conditions
from .motioncraft_timeline import (
    blend_gestures,
    connect_native_clip,
    speech_gesture_weights,
)
from .provenance import verify_source


class MotionCraftEngine:
    backend = "motioncraft"
    representation = "motionx322"
    source_revision = "a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9"
    window_frames = 64
    history_frames = 16

    def __init__(self, settings):
        from virea_model_sdk.upstream_runtime import InstalledArtifactRoots
        from virea_motioncraft.backend import _TASKS, MotionCraftBackend

        roots = InstalledArtifactRoots(
            {
                key: Path(value).resolve(strict=True)
                for key, value in settings["artifacts"].items()
            }
        )
        source = Path(settings["artifacts"]["motioncraft-source"]) / "source"
        verify_source(source, self.source_revision)
        weights = Path(settings["artifacts"]["motioncraft-task-checkpoints"])
        self.statistics = {}
        for task in ("text_to_motion", "speech_to_gesture"):
            spec = _TASKS[task]
            (weights / spec.checkpoint).resolve(strict=True)
            mean, std = (
                np.load(source / name, allow_pickle=False).reshape(-1)
                for name in (spec.mean, spec.std)
            )
            if (
                mean.shape != (322,)
                or std.shape != (322,)
                or not np.isfinite(mean).all()
                or not np.isfinite(std).all()
                or np.any(std < 0)
            ):
                raise ValueError("invalid MotionCraft task normalization")
            self.statistics[task] = mean, std
        self.native = MotionCraftBackend(roots)
        self.native.load()
        self.torch, self.device = self.native._torch, self.native._device
        self.facts = {
            **self.native.device_facts,
            "task_checkpoints": {
                task: _TASKS[task].checkpoint_id for task in self.statistics
            },
            "physical_action_owner": "T2M",
            "speech_control": "S2G_upper_body_in_conversational_segments",
            "composition": "task_specific_statistics_native_prefix_inpainting",
        }

    def _sample(self, task, prompt, frames, history, seed, audio=None):
        """Official per-step noisy-prefix replacement, not only final x0 clamping."""
        self.native._load_task(task)
        self.native._seed(seed % 2147483647)
        torch, device = self.torch, self.device
        model = self.native._model
        mean, std = self.statistics[task]
        prefix = min(self.history_frames, len(history)) if history is not None else 0
        with torch.inference_mode():
            text = model.model.get_precompute_condition(device=device, text=[prompt])
            common = dict(
                motion_mask=torch.ones((1, frames), device=device),
                motion_length=torch.tensor([frames], device=device),
                num_intervals=1,
            )
            control = (
                torch.as_tensor(beat_audio_features(audio), device=device)[None]
                if audio is not None
                else None
            )

            def denoise(x, timesteps, **kwargs):
                arguments = dict(common, **text)
                if task == "speech_to_gesture":
                    arguments["c"] = control
                return model.model(x, timesteps, **arguments)

            options = {}
            if prefix:
                known = np.zeros((frames, 322), dtype=np.float32)
                known[:prefix] = np.divide(
                    history[-prefix:] - mean,
                    std,
                    out=np.zeros((prefix, 322), dtype=np.float32),
                    where=std > 1e-8,
                )
                mask = torch.zeros((1, frames, 322), dtype=torch.bool, device=device)
                mask[:, :prefix] = True
                options = dict(
                    gt=torch.as_tensor(known, device=device)[None],
                    outpainting_mask=mask,
                )
            result = model.diffusion_test.ddim_sample_loop(
                denoise,
                (1, frames, 322),
                device=device,
                clip_denoised=False,
                progress=False,
                model_kwargs={"y": options},
                eta=0,
            )
        return result[0].float().cpu().numpy() * std + mean

    def _extend_text(self, request, state, required):
        values = state["text"]
        planned = max(
            (
                round((s.start_seconds + s.duration_seconds) * FPS)
                for s in request.motions
            ),
            default=0,
        )
        capacity = self.window_frames - self.history_frames
        target = max(required, (planned + capacity - 1) // capacity * capacity)
        if required > planned:
            target = max(target, required + 196 - self.history_frames)
        while len(values) < target:
            cursor = len(values)
            segment = next(
                (
                    s
                    for s in request.motions
                    if round(s.start_seconds * FPS)
                    <= cursor
                    < round((s.start_seconds + s.duration_seconds) * FPS)
                ),
                None,
            )
            if segment:
                end = round((segment.start_seconds + segment.duration_seconds) * FPS)
                prompt = segment.prompt
            else:
                end = min(
                    (
                        round(s.start_seconds * FPS)
                        for s in request.motions
                        if round(s.start_seconds * FPS) > cursor
                    ),
                    default=target,
                )
                prompt = request.idle_prompt
            prefix = min(self.history_frames, len(values))
            count = min(end - cursor, 196 - prefix)
            history = values[-prefix:].copy() if prefix else None
            origin = np.zeros(3, dtype=np.float32)
            if prefix:
                origin[[0, 2]] = history[-1, [309, 311]]
                history[:, 309:312] -= origin
            clip = self._sample(
                "text_to_motion",
                prompt,
                max(30, prefix + count),
                history,
                request.seed + state["text_clips"],
            )
            new = clip[prefix : prefix + count].copy()
            new[:, 309:312] += origin
            if prefix:
                new = connect_native_clip(values[-prefix:], new)
            values = np.concatenate((values, new))
            state["text_clips"] += 1
        state["text"] = values

    def generate(self, request, state):
        waveform, mask, _ = conditions(request, self.window_frames)
        prefix = request.start_frame - request.audio_start_frame
        if prefix != (self.history_frames if state else 0):
            raise ValueError("MotionCraft native prefix is not contiguous")
        if state is None:
            state = {
                "text": np.empty((0, 322), dtype=np.float32),
                "text_clips": 0,
                "speech": None,
            }
        end = request.start_frame + request.frames
        self._extend_text(request, state, end)
        output = state["text"][request.start_frame : end].copy()
        weights = speech_gesture_weights(request, self.window_frames) * mask
        if weights[prefix : prefix + request.frames].any():
            history = state["speech"]
            speech = self._sample(
                "speech_to_gesture",
                "A person is giving a speech.",
                self.window_frames,
                history,
                request.seed + request.sequence,
                audio=waveform,
            )
            state["speech"] = speech[
                prefix + request.frames - self.history_frames : prefix + request.frames
            ].copy()
            output = blend_gestures(
                output,
                speech[prefix : prefix + request.frames],
                weights[prefix : prefix + request.frames],
            )
        else:
            state["speech"] = None
        return output, state
