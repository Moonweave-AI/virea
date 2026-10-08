"""One owned VIREA session and player, independent of the browser lifecycle."""

import asyncio
import contextlib
import json
import time
from collections import deque

from virea.character.contracts import EnvironmentEvent, PlaybackFeedback, SessionRequest
from virea.character.providers.language import LanguageProvider
from virea.character.providers.speech import SpeechProvider
from virea.character.providers.unified import UnifiedMotionProvider

from .autonomy import next_step
from .player import PerformancePlayer
from .transport import OSCTransport


class VRChatService:
    def __init__(self, characters):
        self.characters = characters
        self.session = None
        self.transport = None
        self.config = None
        self.player = None
        self.playing = None
        self.pump = None
        self.paused = False
        self.error = None
        self.results = deque(maxlen=20)
        self.lock = asyncio.Lock()
        self.packet = None
        self.goal_active = False
        self.next_decision = 0
        self.decision = None
        self.completed_goal_outputs = []

    async def connect(self, request):
        async with self.lock:
            if self.session:
                raise ValueError("disconnect the current bridge before reconnecting")
            if request.voice:
                await self.characters.speech.validate_voice(request.voice)
            self.config = request.config
            if self.config.audio_enabled:
                from .audio import PlaybackClock

                try:
                    probe = await asyncio.to_thread(
                        PlaybackClock, 0.05, None, self.config.audio_device
                    )
                    probe.close()
                except Exception as exc:
                    raise ValueError(f"audio endpoint unavailable: {exc}") from exc
            self.error = None
            self.paused = False
            self.results.clear()
            self.transport = OSCTransport(self.config)
            try:
                await self.transport.open()
                self.session = self.characters.create(
                    SessionRequest(
                        motion_backend=request.motion_backend,
                        voice=request.voice,
                        persona=request.persona,
                        playback_mode="synchronized",
                    )
                )
                self.session.config.max_autonomous_decisions = (
                    request.autonomous_decisions
                )
                if request.history:
                    self.session.history.extend(
                        turn.model_dump() for turn in request.history
                    )
                # Feed capability restrictions to the planner without changing model adapters.
                await self.session.environment_event(
                    EnvironmentEvent(
                        kind="context",
                        summary=self.execution_context(),
                    )
                )
                self.pump = asyncio.create_task(
                    self._run(), name="virea-vrchat-session"
                )
            except BaseException:
                if self.session:
                    await self.characters.remove(self.session.id)
                    self.session = None
                await self.transport.close()
                self.transport = None
                raise
            return self.snapshot()

    def snapshot(self):
        ready, reason = (
            self.transport.ready() if self.transport else (False, "disconnected")
        )
        return {
            "connected": self.session is not None,
            "paused": self.paused,
            "ready": ready,
            "waiting_for": reason,
            "error": self.error,
            "config": self.config.model_dump() if self.config else None,
            "capabilities": self.config.capabilities() if self.config else None,
            "session": self.session.snapshot() if self.session else None,
            "feedback": self.transport.protocol.snapshot() if self.transport else None,
            "frames_sent": self.transport.frames_sent if self.transport else 0,
            "elapsed_seconds": self.player.elapsed if self.player else 0,
            "recent_performances": list(self.results),
            "execution": self.player.output_status() if self.player else None,
            "settings": {
                "motion_backend": self.session.config.motion_backend,
                "voice": self.session.config.tts_voice,
                "persona": self.session.config.persona,
                "autonomous_decisions": self.session.config.max_autonomous_decisions,
                "desktop_emotes": self.config.desktop_emotes,
            }
            if self.session and hasattr(self.session.config, "motion_backend")
            else None,
            "autonomy": {
                "active": self.goal_active,
                "remaining": max(
                    0,
                    self.session.config.max_autonomous_decisions
                    - self.session._autonomous,
                )
                if self.session
                else 0,
            },
        }

    def execution_context(self):
        desktop = (
            "Desktop body output uses the avatar's SDK emote presets: wave, clap, point, cheer, dance. "
            "These are preset animations, not generated joint playback. Prefer these simple actions for greetings. "
            if self.config.mode == "desktop" and self.config.desktop_emotes
            else "Desktop has no full-body animation output; only custom finger poses are available. "
        )
        return (
            "Execution endpoint: VRChat. No world positions, objects, collisions or other players are observed. "
            + (
                desktop
                if self.config.mode == "desktop"
                else "VR trackers need external head/hand devices. "
            )
            + "Facial cues support smile, sad, angry and surprised when the avatar has those bindings. "
            "Use short English action prompts and independent speech timing. "
            "Match spoken language to the user. Do not claim to have seen or reached objects."
        )

    async def configure(self, request):
        # Preflight without holding the player lock: stop/pause remain responsive.
        async with self.lock:
            if not self.session or self.pump is None or self.pump.done():
                raise ValueError("connect a running bridge first")
            session, epoch = self.session, self.session.epoch
            config = session.config.model_copy(
                update={
                    "motion_backend": request.motion_backend,
                    "tts_voice": request.voice or self.characters.config.tts_voice,
                    "persona": request.persona
                    if request.persona is not None
                    else self.characters.config.persona,
                    "max_autonomous_decisions": request.autonomous_decisions,
                }
            )
        if not getattr(config, f"{request.motion_backend}_url"):
            raise ValueError(f"{request.motion_backend} is not configured")
        unified = UnifiedMotionProvider(config, self.characters.client)
        await unified.health()
        speech = SpeechProvider(config, self.characters.client)
        if config.tts_voice:
            await speech.validate_voice(config.tts_voice)
        async with self.lock:
            if self.session is not session or session.epoch != epoch:
                raise ValueError("conversation changed while checking settings; retry")
            await self._stop_player()
            await session.interrupt(session.body)
            session.config = config
            session.unified = unified
            session.speech = speech
            session.language = LanguageProvider(config, self.characters.client)
            session.draft_text = ""
            session.latest_expression = None
            session.motion_plan = []
            session.route = None
            session._autonomous = 0
            self.config.desktop_emotes = request.desktop_emotes
            self.goal_active = False
            self.error = None
            self.completed_goal_outputs.clear()
            await session.environment_event(
                EnvironmentEvent(kind="context", summary=self.execution_context())
            )
            session.playback_clock.set_paused(self.paused)
            session.record("settings_updated", motion_backend=request.motion_backend)
            return self.snapshot()

    async def _stop_player(self):
        if self.decision:
            self.decision.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.decision
            self.decision = None
        if self.playing:
            self.playing.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.playing
        self.playing = self.player = self.packet = None
        if self.transport:
            self.transport.release()

    async def message(self, text):
        async with self.lock:
            if not self.session:
                raise ValueError("connect the bridge first")
            if self.pump is None or self.pump.done():
                raise ValueError("bridge task stopped; disconnect and reconnect")
            await self._stop_player()
            self.error = None
            self.completed_goal_outputs.clear()
            await self.session.message(text)
            self.session.playback_clock.set_paused(self.paused)
            self.goal_active = True
            return self.snapshot()

    async def environment(self, event):
        async with self.lock:
            if not self.session:
                raise ValueError("connect the bridge first")
            # The caller must identify its external perception source in summary.
            await self.session.environment_event(event)
            return self.snapshot()

    async def bind_avatar(self, avatar_id):
        async with self.lock:
            if not self.transport or not self.session:
                raise ValueError("connect the AI receiver first")
            observed = self.transport.protocol.values.get("avatar_id", (None,))[0]
            if observed != avatar_id:
                raise ValueError(
                    "avatar_id must match feedback on the dedicated AI port"
                )
            if self.playing or self.goal_active:
                raise ValueError("stop the current task before binding an avatar")
            self.config.avatar_id = avatar_id
            return self.snapshot()

    async def performance(self, plan):
        async with self.lock:
            if not self.session or self.pump is None or self.pump.done():
                raise ValueError("connect a running bridge first")
            await self._stop_player()
            self.goal_active = False
            self.error = None
            await self.session.submit_performance(plan)
            self.session.playback_clock.set_paused(self.paused)
            return self.snapshot()

    async def control(self, action):
        if action == "disconnect":
            await self.close()
            return self.snapshot()
        async with self.lock:
            if not self.session:
                raise ValueError("connect the bridge first")
            if action == "interrupt":
                self.goal_active = False
                await self._stop_player()
                await self.session.interrupt(self.session.body)
            else:
                self.paused = action == "pause"
                self.session.playback_clock.set_paused(self.paused)
                if self.player:
                    self.player.set_paused(self.paused)
                if self.paused:
                    self.transport.release()
            return self.snapshot()

    async def _run(self):
        try:
            while self.session:
                async with self.lock:
                    if self.session:
                        await self._tick()
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            async with self.lock:
                self.error = str(exc)
                self.goal_active = False
                await self._stop_player()
                if self.session:
                    await self.session.interrupt(self.session.body)

    async def _tick(self):
        self.characters.get(self.session.id)  # native player owns the lease
        ready, _ = self.transport.ready()
        self.session.playback_clock.set_paused(self.paused or not ready)
        if self.playing and self.playing.done():
            result, status, detail = (
                {},
                "completed",
                "OSC output completed; avatar/world pose is unobserved.",
            )
            try:
                result = self.playing.result()
                if result.get("execution", {}).get("mode") == "desktop":
                    detail = "Desktop preset/finger output completed; generated full-body motion was not transmitted. Avatar/world pose is unobserved."
            except Exception as exc:
                status, detail = "failed", str(exc)
                self.error = detail
                self.goal_active = False
            packet = self.packet
            if status == "completed":
                self.completed_goal_outputs.append(packet.get("performance", {}))
            self.results.append(
                {
                    "packet_id": packet["id"],
                    "status": status,
                    **result,
                    "detail": detail,
                    "performance": packet.get("performance"),
                }
            )
            self.session.acknowledge(
                PlaybackFeedback(
                    packet_id=packet["id"],
                    epoch=packet["epoch"],
                    status=status,
                    body=self.session.body,
                    message=detail[:500],
                    audio_seconds=result.get("audio_seconds", 0),
                    motion_seconds=result.get("motion_seconds", 0),
                )
            )
            self.playing = self.player = self.packet = None
            self.next_decision = time.monotonic() + 5
            await asyncio.sleep(0.05)  # let acknowledgement release the packet
        pending = self.session.pending
        if pending and not self.playing and not self.paused:
            ready, _ = self.transport.ready()
            if ready:
                performance = pending.get("performance")
                if not performance:
                    raise ValueError(
                        "live VRChat playback requires an independent-track motion backend"
                    )
                path = self.session.directory / f"{pending['id']}.json"
                asset = json.loads(path.read_text(encoding="utf-8"))
                wav = self.session.directory / f"{pending['id']}.wav"
                audio = wav.read_bytes() if pending.get("audio_url") else None
                self.player = PerformancePlayer(
                    self.config,
                    self.transport,
                    asset["windows"],
                    performance,
                    audio,
                )
                self.packet = pending.copy()
                self.playing = asyncio.create_task(self.player.run())
        if self.session.status == "error":
            self.goal_active = False
        if (
            self.goal_active
            and ready
            and not self.paused
            and not self.playing
            and self.session.status == "waiting"
            and time.monotonic() >= self.next_decision
        ):
            if self.session._autonomous < self.session.config.max_autonomous_decisions:
                if self.decision is None:
                    self.decision = asyncio.create_task(
                        next_step(
                            self.session,
                            self.characters.client,
                            list(self.completed_goal_outputs),
                            self.transport.protocol.fresh(),
                        )
                    )
                elif self.decision.done():
                    decision = self.decision.result()
                    self.decision = None
                    if decision.continue_goal:
                        await self.session.environment_event(
                            EnvironmentEvent(
                                kind="context",
                                silent=False,
                                summary="VIREA_AUTONOMOUS_STEP\n"
                                + decision.instruction,
                            )
                        )
                        self.next_decision = time.monotonic() + 5
                    else:
                        self.goal_active = False
            else:
                self.goal_active = False

    async def close(self):
        async with self.lock:
            self.goal_active = False
            if self.pump:
                self.pump.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.pump
                self.pump = None
            await self._stop_player()
            if self.session:
                if self.session.id in self.characters.sessions:
                    await self.characters.remove(self.session.id)
                self.session = None
            if self.transport:
                await self.transport.close()
                self.transport = None
