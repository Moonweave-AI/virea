"""Loopback OSC feedback and an isolated sender with a dead-man timeout."""

import asyncio
import contextlib
import math
import multiprocessing
import socket
import time

from .contracts import FACE_PARAMETERS, HAND_PARAMETERS, valid_avatar_id
from .osc import bundle, decode, message, release_messages


def reset_packet(config):
    messages = release_messages(config.microphone == "hold")
    if config.mode == "generated_vr":
        messages.append(message("/input/MoveHoldFB", 0.0))
        messages += [
            message(f"/input/{button}", 0)
            for button in (
                "QuickMenuToggleLeft",
                "QuickMenuToggleRight",
                "GrabLeft",
                "GrabRight",
                "DropLeft",
                "DropRight",
                "ComfortLeft",
                "ComfortRight",
            )
        ]
    if config.mode == "desktop":
        # Included even before opt-in so a live settings change is also covered
        # by the child process's existing dead-man reset packet.
        messages.append(message("/avatar/parameters/VRCEmote", 0))
    if config.eyes:
        messages += [
            message("/tracking/eye/EyesClosedAmount", 0.0),
            message("/tracking/eye/CenterPitchYaw", 0.0, 0.0),
        ]
    if config.expressions:
        messages.append(message("/avatar/parameters/AI_Active", False))
        messages += [
            message(f"/avatar/parameters/{name}", 0.0) for name in FACE_PARAMETERS
        ]
        messages += [
            message(f"/avatar/parameters/{name}", 0) for name in HAND_PARAMETERS
        ]
    return bundle(messages)


def sender_process(pipe, destination, reset, timeout=0.75, ready=None):
    """Own the output socket so parent death/blocked event loop releases inputs."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    deadline = time.monotonic() + timeout
    armed = False
    try:
        if ready is not None:
            ready.set()
        while True:
            try:
                available = pipe.poll(0.05)
                packet = pipe.recv_bytes(65507) if available else None
            except (EOFError, OSError):
                # Windows may report a closed parent pipe from poll(), before recv().
                break
            if available:
                if not packet:
                    break
                sock.sendto(packet, destination)
                deadline = time.monotonic() + timeout
                armed = packet != reset
            elif armed and time.monotonic() >= deadline:
                for _ in range(3):
                    sock.sendto(reset, destination)
                armed = False
    finally:
        with contextlib.suppress(OSError):
            for _ in range(3):
                sock.sendto(reset, destination)
        sock.close()
        pipe.close()


class FeedbackProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.values = {}
        self.last_received = None
        self.invalid_packets = 0
        self.closed = asyncio.Event()
        self.query_status = {"state": "searching"}
        self.query_checked = None

    def connection_lost(self, exc):
        self.closed.set()

    def datagram_received(self, data, address):
        if address[0] != "127.0.0.1":
            return
        try:
            decoded = decode(data)
        except ValueError:
            self.invalid_packets += 1
            return
        now = time.monotonic()
        for path, args in decoded:
            if path == "/avatar/change":
                # An unknown/loading avatar must never leave the old identity armed.
                self.values.clear()
                if len(args) == 1 and valid_avatar_id(args[0]):
                    self.values["avatar_id"] = (args[0], now)
                self.last_received = now
            elif path.startswith("/avatar/parameters/") and len(args) == 1:
                name = path.rsplit("/", 1)[-1]
                if (
                    name
                    in {
                        "VelocityX",
                        "VelocityZ",
                        "AngularY",
                        "VRMode",
                        "TrackingType",
                        "MuteSelf",
                        "Grounded",
                        "InStation",
                        "AI_Active",
                        "VRCEmote",
                        *FACE_PARAMETERS,
                        *HAND_PARAMETERS,
                    }
                    and isinstance(args[0], (bool, int, float))
                    and math.isfinite(args[0])
                ):
                    self.values[name] = (args[0], now)
                    self.last_received = now

    def fresh(self):
        now = time.monotonic()
        return {
            key: value for key, (value, when) in self.values.items() if now - when < 1.0
        }

    def snapshot(self):
        return {
            "values": {k: v[0] for k, v in self.values.items()},
            "fresh": self.fresh(),
            "last_received_seconds_ago": None
            if self.last_received is None
            else round(time.monotonic() - self.last_received, 3),
            "invalid_packets": self.invalid_packets,
            "query": {
                **self.query_status,
                "last_checked_seconds_ago": None
                if self.query_checked is None
                else round(time.monotonic() - self.query_checked, 3),
            },
        }


class OSCTransport:
    def __init__(self, config):
        self.config = config
        self.protocol = FeedbackProtocol()
        self.receiver = None
        self.process = None
        self.pipe = None
        self.query = None
        self.monitor = None
        self.monitor_task = None
        self.frames_sent = 0
        self.reset = reset_packet(config)

    async def open(self):
        loop = asyncio.get_running_loop()
        try:
            self.receiver, _ = await loop.create_datagram_endpoint(
                lambda: self.protocol,
                local_addr=("127.0.0.1", self.config.receive_port),
            )
            ctx = multiprocessing.get_context("spawn")
            read, self.pipe = ctx.Pipe(duplex=False)
            started = ctx.Event()
            self.process = ctx.Process(
                target=sender_process,
                args=(
                    read,
                    (self.config.host, self.config.send_port),
                    self.reset,
                    0.75,
                    started,
                ),
                name="virea-osc-watchdog",
                daemon=True,
            )
            self.process.start()
            read.close()
            if not await asyncio.to_thread(started.wait, 30):
                raise RuntimeError("OSC sender did not become ready within 30 seconds")
            from .client_query import ClientQuery

            self.monitor = ClientQuery(self.config, self.protocol)
            self.monitor_task = asyncio.create_task(self.monitor.run())
            if self.config.oscquery:
                from .discovery import OSCQuery

                self.query = OSCQuery(self.config.receive_port)
                await asyncio.to_thread(self.query.open)
        except BaseException:
            await self.close()
            raise

    def send(self, messages):
        if not self.process or not self.process.is_alive():
            raise RuntimeError("OSC sender stopped; reconnect the bridge")
        self.pipe.send_bytes(bundle(messages))
        self.frames_sent += 1

    def release(self):
        if self.pipe and self.process and self.process.is_alive():
            with contextlib.suppress(OSError):
                self.pipe.send_bytes(self.reset)

    def ready(self, *, require_full_body=True):
        values = self.protocol.values
        if (
            self.monitor
            and self.monitor.verified
            and (
                self.protocol.query_checked is None
                or time.monotonic() - self.protocol.query_checked > 3
            )
        ):
            return False, "AI client feedback lost; reconnecting automatically"
        if not self.config.avatar_id:
            return False, "bind the independent AI avatar_id before enabling output"
        if "avatar_id" not in values:
            return (
                False,
                "waiting for /avatar/change from VRChat; enable OSC and reload the avatar",
            )
        if self.config.avatar_id:
            if values.get("avatar_id", (None,))[0] != self.config.avatar_id:
                return False, "waiting for the configured avatar_id from VRChat OSC"
        if (
            self.config.mode in {"vr_trackers", "generated_vr"}
            and values.get("VRMode", (None,))[0] != 1
        ):
            return False, "VR tracker output requires VRMode=1 feedback from VRChat"
        if (
            require_full_body
            and self.config.mode == "generated_vr"
            and values.get("TrackingType", (None,))[0] != 6
        ):
            return False, "Calibrate FBT in the AI client; waiting for TrackingType=6"
        return True, None

    async def close(self):
        if self.monitor_task:
            self.monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.monitor_task
            self.monitor_task = None
        self.release()
        if self.pipe:
            with contextlib.suppress(OSError):
                self.pipe.send_bytes(b"")
            self.pipe.close()
            self.pipe = None
        stop_error = None
        if self.process:
            await asyncio.to_thread(self.process.join, 2)
            if self.process.is_alive():
                self.process.terminate()
                await asyncio.to_thread(self.process.join, 5)
            if self.process.is_alive():
                # Retain the handle so a later close can retry. Never close a
                # running process, or skip receiver cleanup because it is slow.
                stop_error = RuntimeError("OSC sender did not stop after termination")
            else:
                self.process.close()
                self.process = None
        if self.receiver:
            self.receiver.close()
            await asyncio.wait_for(self.protocol.closed.wait(), 2)
            self.receiver = None
        if self.query:
            await asyncio.to_thread(self.query.close)
            self.query = None
        if stop_error:
            raise stop_error
