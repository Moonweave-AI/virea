"""Native performance playback: speech placement never sets motion duration."""

import asyncio
import time

from .audio import PlaybackClock
from .desktop import DesktopTimeline
from .mapping import chat_chunks, facial_messages, hand_messages, tracker_messages
from .osc import message
from .timeline import MotionTimeline, movement


class PerformancePlayer:
    def __init__(
        self,
        config,
        transport,
        windows,
        performance,
        audio=None,
        clock_factory=PlaybackClock,
    ):
        self.config = config
        self.transport = transport
        self.timeline = MotionTimeline(windows, performance["duration_seconds"])
        self.desktop = DesktopTimeline(performance)
        self.emotes_sent = {}
        self.emotes_observed = set()
        self.speech = performance.get("speech", [])
        for clip in self.speech:
            start, duration = clip["start_seconds"], clip["duration_seconds"]
            if (
                start < 0
                or duration < 0
                or start + duration > self.timeline.duration + 0.001
            ):
                raise ValueError("speech clip is outside the motion timeline")
        self.clock_factory = clock_factory
        self.audio = audio
        self.clock = None
        self.paused = False
        self.elapsed = 0.0
        self.frames = 0
        self.chat_dropped = 0
        self._captions = []
        for clip in self.speech:
            chunks = chat_chunks(clip["text"])
            for i, chunk in enumerate(chunks):
                # Long captions are distributed within their own speech interval.
                self._captions.append(
                    (
                        clip["start_seconds"]
                        + i * clip["duration_seconds"] / len(chunks),
                        clip["start_seconds"] + clip["duration_seconds"],
                        chunk,
                    )
                )
        self._captions.sort()

    def set_paused(self, paused):
        self.paused = paused
        if self.clock:
            self.clock.pause() if paused else self.clock.resume()
        if paused:
            self.transport.release()

    async def run(self):
        use_emotes = self.config.mode == "desktop" and self.config.desktop_emotes
        if use_emotes and any(c["emote"] for c in self.desktop.clips):
            if "VRCEmote" not in self.transport.protocol.query_status.get(
                "writable_parameters", []
            ):
                raise ValueError(
                    "This avatar does not advertise a writable VRCEmote parameter; disable SDK emotes or use the prepared VIREA avatar"
                )
        clock = self.clock_factory(
            self.timeline.duration,
            self.audio,
            self.config.audio_device if self.config.audio_enabled else None,
        )
        self.clock = clock
        last_chat = -100.0
        last_progress = time.monotonic()
        next_frame = last_progress
        avatar = self.transport.protocol.values.get("avatar_id", (None,))[0]
        try:
            if not self.paused:
                clock.resume()
            while self.elapsed < self.timeline.duration:
                ready, reason = self.transport.ready()
                if not ready:
                    raise RuntimeError(reason)
                if self.paused:
                    last_progress = time.monotonic()
                    next_frame = last_progress
                    await asyncio.sleep(0.03)
                    continue
                if (
                    self.transport.protocol.values.get("avatar_id", (None,))[0]
                    != avatar
                ):
                    raise RuntimeError(
                        "avatar changed during playback; submit a new task after checking its parameters"
                    )
                if clock.error:
                    raise RuntimeError(f"audio output stopped: {clock.error}")
                current = clock.position
                if current > self.elapsed:
                    last_progress = time.monotonic()
                elif time.monotonic() - last_progress > 2:
                    raise RuntimeError(
                        "playback clock stopped advancing; check the audio endpoint"
                    )
                self.elapsed = current
                pose = self.timeline.sample(self.elapsed)
                outgoing = []
                emote, face = self.desktop.sample(self.elapsed)
                if use_emotes:
                    # Action owns the body while an emote is active. Do not mix a
                    # generated root displacement into an unrelated preset clip.
                    outgoing.append(message("/avatar/parameters/VRCEmote", emote))
                    if emote:
                        self.emotes_sent.setdefault(emote, time.monotonic())
                    observed, when = self.transport.protocol.values.get(
                        "VRCEmote", (None, 0)
                    )
                    if (
                        observed in self.emotes_sent
                        and when >= self.emotes_sent[observed]
                    ):
                        self.emotes_observed.add(observed)
                if self.config.locomotion:
                    right, forward, turn = movement(
                        self.timeline,
                        self.elapsed,
                        self.config,
                        self.transport.protocol.fresh(),
                    )
                    if use_emotes and emote:
                        right = forward = turn = 0.0
                    outgoing += [
                        message("/input/Horizontal", right),
                        message("/input/Vertical", forward),
                        message("/input/LookHorizontal", turn),
                    ]
                if self.config.mode == "vr_trackers":
                    # In locomotion mode root travel is already sent via input axes.
                    anchor = (
                        pose.root
                        if self.config.locomotion
                        else self.timeline.sample(0).root
                    )
                    outgoing += tracker_messages(
                        pose.root, pose.rotations, self.config, anchor
                    )
                if self.config.expressions:
                    outgoing.append(message("/avatar/parameters/AI_Active", True))
                    outgoing += hand_messages(pose.rotations)
                    outgoing += facial_messages(face)
                speaking = any(
                    c["start_seconds"]
                    <= self.elapsed
                    < c["start_seconds"] + c["duration_seconds"]
                    for c in self.speech
                )
                if self.config.microphone == "hold":
                    outgoing.append(message("/input/Voice", speaking))
                if self.config.chatbox and time.monotonic() - last_chat >= 2:
                    while self._captions and self._captions[0][1] < self.elapsed:
                        self._captions.pop(0)
                        self.chat_dropped += 1
                    if self._captions and self._captions[0][0] <= self.elapsed:
                        outgoing.append(
                            message(
                                "/chatbox/input", self._captions.pop(0)[2], True, False
                            )
                        )
                        last_chat = time.monotonic()
                # Empty bundles still feed the isolated sender's watchdog.
                self.transport.send(outgoing)
                self.frames += 1
                next_frame = max(next_frame + 1 / self.config.fps, time.monotonic())
                await asyncio.sleep(max(0, next_frame - time.monotonic()))
            return {
                "motion_seconds": self.elapsed,
                "audio_seconds": min(
                    self.elapsed,
                    max(
                        (
                            c["start_seconds"] + c["duration_seconds"]
                            for c in self.speech
                        ),
                        default=0,
                    ),
                )
                if self.config.audio_enabled
                else 0,
                "frames": self.frames,
                "chat_dropped": self.chat_dropped,
                "execution": self.output_status(),
            }
        finally:
            try:
                clock.close()
            finally:
                self.transport.release()
                self.clock = None

    def output_status(self):
        return {
            "mode": self.config.mode,
            "generated_body_transmitted": self.config.mode == "vr_trackers",
            "body_representation": "configured_body_trackers"
            if self.config.mode == "vr_trackers"
            else "SDK avatar presets"
            if self.config.desktop_emotes
            else "none",
            "segments": self.desktop.summary(self.config.desktop_emotes)
            if self.config.mode == "desktop"
            else [],
            "emotes_sent": sorted(self.emotes_sent),
            "emotes_observed": sorted(self.emotes_observed),
            "rendered_pose_verified": False,
        }

    def expression(self, weights, pitch=0.0, yaw=0.0, blink=0.0):
        outgoing = facial_messages(weights) if self.config.expressions else []
        if self.config.eyes:
            outgoing += [
                message("/tracking/eye/CenterPitchYaw", float(pitch), float(yaw)),
                message("/tracking/eye/EyesClosedAmount", float(blink)),
            ]
        self.transport.send(outgoing)
