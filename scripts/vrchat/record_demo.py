"""Record continuous, silent VRChat window feeds and actual conversation events.

Usage: uv run --with pillow --with imageio-ffmpeg --with pycaw python
       scripts/vrchat/record_demo.py scenario.json --output OUTPUT_DIRECTORY

Requires the local bridge, two connected game clients, and muted Windows render
endpoints. Never records microphones or opens an audio playback stream.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageOps


def muted_render_endpoints():
    import comtypes
    from pycaw.pycaw import AudioUtilities

    comtypes.CoInitialize()
    try:
        devices = [
            d
            for d in AudioUtilities.GetAllDevices()
            if d.id.startswith("{0.0.0.") and d.state.value == 1
        ]
        if not devices or any(not d.EndpointVolume.GetMute() for d in devices):
            raise RuntimeError("All active Windows render endpoints must be muted")
        return len(devices)
    finally:
        comtypes.CoUninitialize()


def wrapped(draw, text, font, width):
    lines, line = [], ""
    for char in text:
        if char == "\n" or draw.textlength(line + char, font=font) > width:
            lines.append(line)
            line = "" if char == "\n" else char
        else:
            line += char
    return lines + ([line] if line else [])


class DemoRecorder:
    def __init__(self, scenario, output, base_url):
        self.scenario, self.output = scenario, output
        self.client = httpx.Client(base_url=base_url, trust_env=False, timeout=90)
        self.output.mkdir(parents=True, exist_ok=True)
        self.path = self.output / (scenario["id"] + ".mp4")
        if self.path.exists():
            raise FileExistsError(self.path)
        self.frames, self.sequences, self.capture_counts = {}, {}, {}
        self.state, self.step, self.user_text = {}, 0, ""
        self.status, self.capture_errors = "准备", []
        self.stop = threading.Event()
        self.events, self.completed = [], []
        self.start = 0.0
        self.fonts = {
            n: ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", n)
            for n in [20, 23, 27, 32]
        }

    def api(self, path="", body=None):
        r = (
            self.client.get("/api/v1/vrchat" + path)
            if body is None
            else self.client.post("/api/v1/vrchat" + path, json=body)
        )
        r.raise_for_status()
        return r.json()

    def event(self, kind, **data):
        item = {
            "at_seconds": round(time.monotonic() - self.start, 3),
            "kind": kind,
            **data,
        }
        self.events.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    def capture(self, role):
        with httpx.Client(
            base_url=str(self.client.base_url), trust_env=False, timeout=5
        ) as c:
            while not self.stop.is_set():
                try:
                    r = c.get(
                        "/api/v1/vrchat/views/" + role + "/frame",
                        headers={"X-Virea-Capture": "1"},
                    )
                    r.raise_for_status()
                    frame = Image.open(io.BytesIO(r.content)).convert("RGB")
                    seq = int(r.headers["X-Capture-Sequence"])
                    self.frames[role] = (frame, time.monotonic())
                    if self.sequences.get(role) != seq:
                        self.capture_counts[role] = self.capture_counts.get(role, 0) + 1
                    self.sequences[role] = seq
                except Exception as exc:
                    self.capture_errors.append(
                        {
                            "role": role,
                            "at_seconds": round(time.monotonic() - self.start, 3),
                            "error": str(exc)[:150],
                        }
                    )
                self.stop.wait(0.065)

    def draw(self, elapsed):
        im = Image.new("RGB", (1600, 960), "#10151e")
        d = ImageDraw.Draw(im)

        def text(x, y, value, size=23, color="#e4ebf5"):
            d.text((x, y), value, font=self.fonts[size], fill=color)

        text(24, 16, self.scenario["title"], 32)
        text(
            1140,
            24,
            f"连续实录  {int(elapsed) // 60:02d}:{int(elapsed) % 60:02d}   静音 / 无音轨",
            20,
            "#63d5ba",
        )
        for role, box, label in [
            ("observer", (24, 102, 1048, 714), "观察者 · 同房间第三人称"),
            ("ai", (1072, 102, 1576, 404), "AI 客户端 · 第一人称"),
        ]:
            text(box[0], 72, label, 20, "#91a7c2")
            frame = self.frames.get(role)
            if frame and time.monotonic() - frame[1] < 2:
                im.paste(
                    ImageOps.pad(
                        frame[0], (box[2] - box[0], box[3] - box[1]), color="#05080d"
                    ),
                    box[:2],
                )
            else:
                text(box[0] + 15, box[1] + 30, "画面暂不可用", 27, "#ffac83")
        state = self.state
        method = (state.get("settings") or {}).get("motion_backend", "")
        session = state.get("session") or {}
        phase = (
            "动作与字幕播放中"
            if state.get("execution")
            else {
                "thinking": "构思回复",
                "generating": "生成动作",
                "waiting": "等待下一轮",
            }.get(session.get("status"), session.get("status", "准备"))
        )
        text(1072, 430, f"{method.upper()}   /   第 {self.step} 轮", 27, "#63d5ba")
        text(1072, 477, phase, 23)
        text(1072, 514, f"动作时间  {state.get('elapsed_seconds', 0):.1f} 秒", 23)
        output = state.get("execution") or {}
        acknowledged = (output.get("pose_driver") or {}).get("acknowledged", 0)
        text(1072, 551, f"虚拟设备已接收 {acknowledged} 帧", 20, "#91a7c2")
        text(1072, 600, "模型姿态 → 头手 / 手指 / 身体追踪", 23)
        text(1072, 637, "VRChat IK 呈现 · 以观察者画面为准", 20, "#91a7c2")
        text(24, 736, "用户", 23, "#91a7c2")
        for i, line in enumerate(wrapped(d, self.user_text, self.fonts[23], 1440)[:2]):
            text(98, 734 + i * 31, line, 23)
        text(24, 815, "Virea", 23, "#63d5ba")
        reply = ""
        latest = session.get("latest_expression") or {}
        if state.get("execution"):
            clips = (latest.get("performance") or {}).get("speech", [])
            active = [
                c["text"]
                for c in clips
                if c["start_seconds"]
                <= state.get("elapsed_seconds", 0)
                < c["start_seconds"] + c["duration_seconds"]
            ]
            reply = " ".join(active)
        if not reply:
            history = session.get("history", [])
            if history and history[-1]["role"] == "assistant":
                reply = history[-1]["content"]
            elif latest.get("text") and latest.get("epoch") == session.get("epoch"):
                reply = latest["text"]
        for i, line in enumerate(
            wrapped(d, reply or "正在准备本轮回复……", self.fonts[27], 1435)[:3]
        ):
            text(98, 811 + i * 35, line, 27)
        text(
            24,
            936,
            "真实窗口同步合成 · 原速连续 · 字幕来自实际回复 · Avatar: Unnamed Character 6 — Reira",
            20,
            "#7c8fa8",
        )
        return im

    def run(self):
        muted = muted_render_endpoints()
        self.state = self.api()
        if (
            not self.state["ready"]
            or self.state["config"]["audio_enabled"]
            or not self.state["config"]["chatbox"]
            or not self.state["config"].get("observer_chatbox")
            or self.state["config"]["mode"] != "generated_vr"
            or self.state["config"]["desktop_emotes"]
            or self.state["feedback"]["values"].get("VRMode") != 1
        ):
            raise RuntimeError(
                "Ready generated_vr bridge, both chatboxes, VRMode=1, no audio or presets required"
            )
        settings = self.state["settings"].copy()
        settings.update(
            json.loads(
                (Path(__file__).parent / "demos/session.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        self.state = self.api("/settings", settings)
        self.start = time.monotonic()
        self.event(
            "recording_started",
            muted_render_endpoints=muted,
            scenario=self.scenario,
            settings={k: v for k, v in settings.items() if k != "voice"},
            observer_chat=self.state.get("observer_chat"),
        )
        threads = [
            threading.Thread(target=self.capture, args=(role,), daemon=True)
            for role in ["observer", "ai"]
        ]
        for t in threads:
            t.start()
        log = self.path.with_suffix(".encoder.log").open("wb")
        encoder = subprocess.Popen(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-loglevel",
                "warning",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                "1600x960",
                "-r",
                "15",
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "25",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(self.path),
            ],
            stdin=subprocess.PIPE,
            stderr=log,
        )
        worker = threading.Thread(target=self.interact, daemon=True)
        worker.start()
        count = 0
        try:
            while not self.stop.is_set():
                elapsed = time.monotonic() - self.start
                # Preserve wall time even if an encoding tick is delayed.
                if count > elapsed * 15:
                    time.sleep(min(0.02, count / 15 - elapsed))
                    continue
                encoder.stdin.write(self.draw(count / 15).tobytes())
                count += 1
                if count % 450 == 0:
                    print(f"recorded {count / 15:.0f}s", flush=True)
        finally:
            self.stop.set()
            for t in threads:
                t.join(timeout=6)
            worker.join(timeout=5)
            encoder.stdin.close()
            encoder.wait(timeout=60)
            log.close()
            manifest = {
                "id": self.scenario["id"],
                "title": self.scenario["title"],
                "recorded_on": datetime.now().astimezone().date().isoformat(),
                "continuous": True,
                "speed": 1,
                "audio_tracks": 0,
                "fps": 15,
                "frames": count,
                "duration_seconds": count / 15,
                "wall_seconds": round(time.monotonic() - self.start, 3),
                "capture_frames": self.capture_counts,
                "capture_errors": self.capture_errors,
                "events": self.events,
                "performances": self.completed,
                "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                "bytes": self.path.stat().st_size,
                "encoder_exit": encoder.returncode,
            }
            self.path.with_suffix(".json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if encoder.returncode or self.status != "completed":
            raise RuntimeError(f"Incomplete recording: {self.status}")

    def interact(self):
        try:
            self.stop.wait(2)
            for i, turn in enumerate(self.scenario["turns"], 1):
                if self.stop.is_set():
                    return
                muted_render_endpoints()
                self.step, self.user_text = i, turn["text"]
                if turn.get("method"):
                    before_switch = self.api()
                    settings = before_switch["settings"].copy()
                    settings.update(
                        motion_backend=turn["method"], autonomous_decisions=0
                    )
                    after_switch = self.api("/settings", settings)
                    preserved = (
                        before_switch["session"]["id"] == after_switch["session"]["id"]
                        and before_switch["session"]["history"]
                        == after_switch["session"]["history"]
                    )
                    if not preserved:
                        raise RuntimeError("Method switch lost the conversation")
                    self.event(
                        "method_changed",
                        method=turn["method"],
                        conversation_preserved=preserved,
                        history_turns=len(after_switch["session"]["history"]),
                    )
                prior_results = self.api()["recent_performances"]
                previous_packet = (
                    prior_results[-1]["packet_id"] if prior_results else None
                )
                self.api("/messages", {"text": turn["text"]})
                self.event("user_message", step=i, text=turn["text"])
                deadline = time.monotonic() + 360
                last_reply = None
                while time.monotonic() < deadline and not self.stop.is_set():
                    self.state = self.api()
                    if self.state.get("error"):
                        raise RuntimeError(self.state["error"])
                    if (self.state.get("session") or {}).get("status") == "error":
                        errors = [
                            e
                            for e in self.state["session"].get("events", [])
                            if e["kind"] == "error"
                        ]
                        raise RuntimeError(
                            errors[-1].get("message", "Session error")
                            if errors
                            else "Session error"
                        )
                    if self.state["config"]["audio_enabled"]:
                        raise RuntimeError("Audio was enabled during recording")
                    latest = (self.state.get("session") or {}).get(
                        "latest_expression"
                    ) or {}
                    if (
                        latest.get("text")
                        and latest.get("epoch") == self.state["session"]["epoch"]
                        and latest.get("id") != last_reply
                    ):
                        last_reply = latest["id"]
                        self.event(
                            "assistant_reply",
                            text=latest["text"],
                            performance=latest.get("performance"),
                        )
                    results = self.state["recent_performances"]
                    if (
                        results
                        and results[-1]["packet_id"] != previous_packet
                        and not self.state.get("execution")
                    ):
                        result = results[-1]
                        if result["status"] != "completed" or result.get(
                            "chat_dropped", 0
                        ):
                            raise RuntimeError(
                                "Performance incomplete or captions dropped"
                            )
                        self.completed.append(result)
                        self.event(
                            "turn_completed",
                            step=i,
                            result=result,
                            observer_chat=self.state.get("observer_chat"),
                        )
                        break
                    self.stop.wait(0.3)
                else:
                    raise RuntimeError("Performance timeout")
                self.stop.wait(4)
            self.status = "completed"
            self.event("recording_completed", turns=len(self.completed))
        except Exception as exc:
            self.status = str(exc)
            self.event("recording_failed", error=str(exc))
        finally:
            self.stop.wait(2)
            self.stop.set()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:18001")
    args = parser.parse_args()
    DemoRecorder(
        json.loads(args.scenario.read_text(encoding="utf-8")),
        args.output,
        args.base_url,
    ).run()
