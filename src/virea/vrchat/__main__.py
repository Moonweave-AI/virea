"""Local diagnostics and model-independent Motion IR / playback-window replay."""

import argparse
import asyncio
import json
from pathlib import Path

from .audio import devices
from .contracts import BridgeConfig
from .mapping import tracker_messages
from .osc import bundle, decode
from .player import PerformancePlayer
from .timeline import MotionTimeline
from .transport import OSCTransport


def load_input(args):
    if args.motion_ir:
        from virea_motion_ir.storage import load_motion_ir

        timeline = MotionTimeline.from_motion_ir(
            load_motion_ir(args.motion_ir), hip_height=args.hip_height
        )
        windows = [
            {
                "offset": w[0],
                "seconds": w[1],
                "fps": w[2],
                "root": w[3].tolist(),
                "rotations": {n: q.tolist() for n, q in w[4].items()},
            }
            for w in timeline.windows
        ]
    else:
        windows = json.loads(Path(args.windows).read_text(encoding="utf-8"))["windows"]
        duration = max(w["offset"] + w["seconds"] for w in windows)
        timeline = MotionTimeline(windows, duration)
    performance = (
        json.loads(Path(args.performance).read_text(encoding="utf-8"))
        if args.performance
        else {"duration_seconds": timeline.duration, "speech": []}
    )
    config = (
        BridgeConfig.model_validate_json(Path(args.config).read_text(encoding="utf-8"))
        if args.config
        else BridgeConfig()
    )
    return windows, timeline, performance, config


async def replay(windows, performance, config, audio, wait_seconds):
    transport = OSCTransport(config)
    await transport.open()
    try:
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while not transport.ready()[0]:
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError(transport.ready()[1])
            await asyncio.sleep(0.1)
        return await PerformancePlayer(
            config, transport, windows, performance, audio
        ).run()
    finally:
        await transport.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="list output endpoints without opening one")
    for command in ("inspect", "replay"):
        sub = commands.add_parser(command)
        source = sub.add_mutually_exclusive_group(required=True)
        source.add_argument("--windows", help="JSON with VIREA playback windows")
        source.add_argument("--motion-ir", help="canonical Motion IR descriptor")
        sub.add_argument("--hip-height", type=float, default=1.0)
        sub.add_argument(
            "--performance",
            help="resolved performance metadata, including speech times",
        )
        sub.add_argument("--config", help="BridgeConfig JSON")
        sub.add_argument(
            "--audio", help="PCM16 WAV already placed on the full timeline"
        )
        sub.add_argument("--wait-seconds", type=float, default=30)
    args = parser.parse_args()
    try:
        if args.command == "devices":
            result = devices()
        else:
            windows, timeline, performance, config = load_input(args)
            if args.command == "inspect":
                # Exercise FK, handedness, quaternion/Euler conversion and OSC
                # encoding for every output frame; this does not contact VRChat.
                count = 0
                for frame in range(round(timeline.duration * config.fps) + 1):
                    pose = timeline.sample(frame / config.fps)
                    decode(
                        bundle(
                            tracker_messages(
                                pose.root, pose.rotations, config, pose.root
                            )
                        )
                    )
                    count += 1
                result = {
                    "validated_frames": count,
                    "motion_seconds": timeline.duration,
                    "windows": len(windows),
                    "capabilities": config.capabilities(),
                    "vrchat_execution_verified": False,
                }
            else:
                audio = Path(args.audio).read_bytes() if args.audio else None
                result = asyncio.run(
                    replay(windows, performance, config, audio, args.wait_seconds)
                )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"VRChat bridge: {exc}\n")


if __name__ == "__main__":
    main()
