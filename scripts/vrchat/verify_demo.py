"""Validate a completed continuous silent recording and its execution journal."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg


def verify(path):
    evidence = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]
    assert path.stat().st_size == evidence["bytes"]
    assert evidence["encoder_exit"] == 0
    assert not evidence["capture_errors"], evidence["capture_errors"]
    assert evidence["duration_seconds"] >= 120
    assert evidence["continuous"] and evidence["speed"] == 1
    for role in ("observer", "ai"):
        assert evidence["capture_frames"][role] >= evidence["duration_seconds"] * 3
    events = evidence["events"]
    assert events[-1]["kind"] == "recording_completed"
    assert sum(e["kind"] == "user_message" for e in events) == 4
    assert len(evidence["performances"]) == 4
    for performance in evidence["performances"]:
        assert performance["status"] == "completed"
        assert performance["audio_seconds"] == 0
        assert performance["chat_dropped"] == 0
        assert performance["performance"]["speech"]
        execution = performance["execution"]
        assert execution["mode"] == "generated_vr"
        assert execution["generated_body_transmitted"]
        assert not execution["emotes_sent"], (
            "SDK presets invalidate model-pose evidence"
        )
        driver = execution["pose_driver"]
        assert driver["acknowledged"] > 0
        assert driver["active_devices"] == 7 and driver["skeleton_devices"] == 6
    previous_sent = events[0]["observer_chat"]["sent_chunks"]
    for event in (e for e in events if e["kind"] == "turn_completed"):
        relay = event["observer_chat"]
        assert relay["sent_chunks"] > previous_sent and relay["pending"] == 0
        assert not relay["error"] and relay["notification_sound"] is False
        previous_sent = relay["sent_chunks"]
    # Driver acknowledgements cannot establish the remote avatar's rendered pose.
    # A separate review must be written only after watching this exact video.
    review = json.loads(path.with_suffix(".review.json").read_text(encoding="utf-8"))
    assert review["sha256"] == evidence["sha256"]
    assert review["reviewer"] and review["same_instance_verified"]
    assert review["generated_motion_visible"] and review["both_chatboxes_visible"]
    assert len(review["turns"]) == 4 and all(t["observations"] for t in review["turns"])
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True
    )
    assert "Video: h264" in probe.stderr and "yuv420p" in probe.stderr
    assert "Audio:" not in probe.stderr, "Unexpected audio stream"
    duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", probe.stderr)
    assert duration
    hours, minutes, seconds = map(float, duration.groups())
    encoded_seconds = hours * 3600 + minutes * 60 + seconds
    assert abs(encoded_seconds - evidence["duration_seconds"]) < 0.15
    assert abs(evidence["duration_seconds"] - events[-1]["at_seconds"] - 2) < 0.3
    decode = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    assert decode.returncode == 0 and not decode.stderr, decode.stderr
    return {
        "file": path.name,
        "seconds": encoded_seconds,
        "bytes": path.stat().st_size,
        "turns": 4,
        "audio_streams": 0,
        "full_decode": "passed",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", nargs="+", type=Path)
    args = parser.parse_args()
    for video in args.videos:
        print(json.dumps(verify(video), ensure_ascii=False))
