"""Package actual Studio recordings and their evidence; never generate mock media."""

import argparse
import hashlib
import html
import json
import re
import struct
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TITLES = [
    "Welcome and introduction",
    "Warm-up coach",
    "Garden story",
    "Dance lesson",
    "Fashion presentation",
    "From tension to celebration",
    "Walking guide",
    "Boxing practice",
]


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def avatar_metadata(path):
    with path.open("rb") as stream:
        magic, version, _ = struct.unpack("<III", stream.read(12))
        assert magic == 0x46546C67 and version == 2, "expected a GLB avatar"
        length, kind = struct.unpack("<II", stream.read(8))
        assert kind == 0x4E4F534A
        extensions = json.loads(stream.read(length))["extensions"]
    meta = extensions.get("VRMC_vrm", extensions.get("VRM", {}))["meta"]
    return dict(
        name=meta.get("name", meta.get("title")),
        authors=meta.get("authors", [meta.get("author", "")]),
        source_filename=path.name,
        license_url=meta.get("licenseUrl", meta.get("otherLicenseUrl", "")),
        sha256=digest(path),
    )


def motion_metrics(path, capacity):
    windows = json.loads(path.read_text(encoding="utf-8"))["windows"]
    root = np.concatenate([np.asarray(w["root"][:-1]) for w in windows])
    steps = np.linalg.norm(np.diff(root, axis=0), axis=-1)
    maxima, percentiles = {}, {}
    for name in windows[0]["rotations"]:
        q = np.concatenate([np.asarray(w["rotations"][name][:-1]) for w in windows])
        assert np.isfinite(q).all()
        assert np.max(np.abs(np.linalg.norm(q, axis=-1) - 1)) < 1e-4
        angles = np.rad2deg(
            2 * np.arccos(np.clip(np.abs(np.sum(q[1:] * q[:-1], axis=-1)), 0, 1))
        )
        maxima[name], percentiles[name] = (
            float(angles.max()),
            float(np.percentile(angles, 95)),
        )
    assert np.isfinite(root).all()
    return dict(
        frames=len(root),
        fps=30,
        root_step_max=float(steps.max()),
        root_step_p95=float(np.percentile(steps, 95)),
        root_extent_xyz=np.ptp(root, axis=0).tolist(),
        native_boundary_root_steps=[
            float(steps[i - 1]) for i in range(capacity, len(root), capacity)
        ],
        joint_step_max_degrees=maxima,
        joint_step_p95_degrees=percentiles,
        note="VRM retarget output after smoothing. Finite samples and bounded steps do not establish task fidelity or foot contact.",
    )


def transcode(ffmpeg, source, destination, extra):
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            *extra,
            str(destination),
        ],
        check=True,
    )


def table(entries, chinese):
    published_path = ROOT / "doc/assets/unified-motion-demos/github-videos.json"
    published = (
        json.loads(published_path.read_text(encoding="utf-8"))
        if published_path.exists()
        else {}
    )
    rows = ["<table>"]
    for offset in range(0, len(entries), 2):
        rows.append("<tr>")
        for entry in entries[offset : offset + 2]:
            stem = entry["id"]
            title = entry["title"] if chinese else entry["title_en"]
            detail = f"{entry['duration_seconds']:g}s · {len(entry['motions'])} {'段动作' if chinese else 'actions'} · {len(entry['speech'])} {'段语音' if chinese else 'speech clips'}"
            raw_url = f"https://github.com/Moonweave-AI/virea/raw/refs/heads/main/doc/assets/unified-motion-demos/{stem}.mp4"
            attachment = published.get(stem, {})
            # Re-recorded clips must never silently keep an older hosted video.
            if (
                entry.get("hashes", {}).get("mp4")
                and attachment.get("sha256") == entry["hashes"]["mp4"]
                and re.fullmatch(
                    r"https://github\.com/user-attachments/assets/[0-9a-f-]{36}",
                    attachment.get("url", ""),
                )
            ):
                media = f'<video src="{attachment["url"]}" controls muted preload="metadata" width="100%"></video>'
            else:
                media = f'<a href="{raw_url}"><img src="../assets/unified-motion-demos/{stem}.jpg" alt="{html.escape(title)}" width="100%"></a>'
            rows.append(
                f'<td width="50%" valign="top"><strong>{html.escape(title)}</strong><br>'
                f"{media}<br><sub>{detail} · {entry['backend']} + Audio8-TTS</sub><br>"
                f'<sub><a href="../assets/unified-motion-demos/{stem}.mp4">MP4</a> · <a href="../assets/unified-motion-demos/{stem}.jpg">{"封面" if chinese else "Poster"}</a></sub></td>'
            )
        rows.append("</tr>")
    rows.append("</table>")
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--avatar", type=Path, required=True)
    parser.add_argument(
        "--require-render",
        action="store_true",
        help="Require verified replays with current avatar grounding",
    )
    parser.add_argument(
        "--receipts", type=Path, help="Directory with voice and worker asset receipts"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "doc/assets/unified-motion-demos"
    )
    args = parser.parse_args()
    tasks = json.loads(
        (ROOT / "configs/character/demo-tasks.json").read_text(encoding="utf-8")
    )
    args.output.mkdir(parents=True, exist_ok=True)
    avatar = avatar_metadata(args.avatar)
    credit = f"Avatar: {avatar['name']} — {', '.join(avatar['authors'])}"
    receipts = args.receipts or args.input.parent
    voice = json.loads((receipts / "voice-receipt.json").read_text(encoding="utf-8"))
    entries = []
    for backend in ("motioncraft", "syntalker"):
        asset_receipt = json.loads(
            (receipts / backend / "asset-receipt.json").read_text(encoding="utf-8")
        )
        for index, task in enumerate(tasks):
            stem = f"{backend}-{task['id']}"
            report = json.loads(
                (args.input / f"{stem}.json").read_text(encoding="utf-8")
            )
            assert report["outcome"] == "passed", (
                f"{stem}: actual browser acceptance must pass first"
            )
            assert report["task"] == task["task"], (
                f"{stem}: regenerate after changing a task"
            )
            state, plan = report["completed"], report["packet"]["performance"]
            assert state["voice"] == voice["voice"]["id"]
            assert len(plan["motions"]) >= 5 and len(plan["speech"]) >= 2
            assert abs(plan["duration_seconds"] - task["expected_seconds"]) <= 1, (
                f"{stem}: requested duration was not met"
            )
            silent_tail = plan["duration_seconds"] - max(
                s["start_seconds"] + s["duration_seconds"] for s in plan["speech"]
            )
            assert silent_tail >= task["minimum_silent_tail_seconds"], (
                f"{stem}: requested silent tail is missing"
            )
            trace = args.input / f"{stem}-trace.json"
            assert trace.is_file()
            video, motion, audio = [
                args.input / f"{stem}{suffix}"
                for suffix in (".webm", "-motion.json", ".wav")
            ]
            original_video = video
            render_path = args.input / f"{stem}-render.json"
            render = None
            if render_path.exists():
                render = json.loads(render_path.read_text(encoding="utf-8"))
                video = args.input / f"{stem}-render.webm"
                assert render["outcome"] == "passed"
                assert render["avatar_sha256"] == avatar["sha256"]
                assert render["source_motion_sha256"] == digest(motion)
                assert render["source_audio_sha256"] == digest(audio)
                assert render["video_sha256"] == digest(video)
            elif args.require_render:
                raise ValueError(f"{stem}: current avatar replay is missing")
            output = args.output / f"{stem}.mp4"
            if not output.exists() or output.stat().st_mtime < video.stat().st_mtime:
                transcode(
                    args.ffmpeg,
                    video,
                    output,
                    [
                        "-vf",
                        "scale=960:-2,fps=30",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "medium",
                        "-crf",
                        "23",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "128k",
                        "-movflags",
                        "+faststart",
                        "-metadata",
                        f"comment={credit}",
                    ],
                )
                transcode(
                    args.ffmpeg,
                    output,
                    args.output / f"{stem}.jpg",
                    [
                        "-ss",
                        str(plan["duration_seconds"] * 0.4),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=480:-2",
                    ],
                )
                transcode(
                    args.ffmpeg,
                    output,
                    args.input / f"{stem}-contact.jpg",
                    [
                        "-vf",
                        f"fps=8/{plan['duration_seconds']},scale=320:-2,tile=4x2",
                        "-frames:v",
                        "1",
                    ],
                )
            entry = dict(
                id=stem,
                backend=backend,
                title=task["title"],
                title_en=TITLES[index],
                task=task["task"],
                started_at=report["started_at"],
                duration_seconds=plan["duration_seconds"],
                motions=plan["motions"],
                speech=plan["speech"],
                source_revision=plan["model_revision"],
                generation_metrics=state["metrics"],
                browser_acceptance="passed",
                native_history=plan["native_history"],
                numerical_metrics=motion_metrics(
                    motion, 48 if backend == "motioncraft" else 112
                ),
                perceptual_acceptance="not_certified; inspect the complete recording",
                face="audio_envelope_preview_only",
                hashes={
                    "source_webm": digest(video),
                    "original_capture_webm": digest(original_video),
                    "mp4": digest(output),
                    "mixed_wav": digest(audio),
                    "retarget_motion": digest(motion),
                    "browser_trace": digest(trace),
                },
                asset_receipt=asset_receipt,
                avatar_replay=render,
            )
            entries.append(entry)
    manifest = dict(
        schema="virea.unified_motion_showcase.v1",
        voice=dict(
            name=voice["voice"]["name"],
            reference_seconds=voice["voice"]["seconds"],
            audio_sha256=voice["source_sha256"].lower(),
            transcript_sha256=voice["transcript_sha256"].lower(),
        ),
        capture="Actual CharacterStage playback of generated motion and cloned speech at normal speed; H.264/AAC transcode without cuts or speed changes. Per-demo avatar_replay records any later avatar grounding replay.",
        avatar=avatar,
        environment=dict(
            motioncraft="RTX 5090 Laptop / torch 2.11.0+cu128",
            syntalker="CPU / torch 2.14.1+cpu",
            language="qwen3.5:9b",
            speech="audio8/tts-0.6b",
        ),
        demos=entries,
    )
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    cards = []
    for backend in ("motioncraft", "syntalker"):
        cards.append(f"<h2>{backend}</h2><section>")
        for entry in [e for e in entries if e["backend"] == backend]:
            stem = entry["id"]
            cards.append(
                f'<article><h3>{html.escape(entry["title"])}</h3><video controls preload="none" poster="{stem}.jpg" src="{stem}.mp4"></video><p>{html.escape(entry["task"])}</p>'
                f"<p>{entry['duration_seconds']}s · preparation {entry['generation_metrics']['generation_seconds']:.1f}s · {entry['backend']}</p></article>"
            )
        cards.append("</section>")
    (args.output / "index.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>VIREA · independent performance tracks</title><style>body{max-width:1120px;margin:40px auto;padding:0 20px;font:16px/1.6 system-ui;background:#f4f6fa;color:#1c2738}section{display:grid;grid-template-columns:1fr 1fr;gap:24px}article{padding:20px;background:white;border-radius:16px}video{width:100%}p{font-size:14px}@media(max-width:700px){section{grid-template-columns:1fr}}</style><h1>MotionCraft × 8 · SynTalker × 8</h1><p>真实 LLM、克隆语音和官方动作权重。完整录制，正常速度；生成等待不在录像内。模型动作语义和接触质量仍属实验性，数值测试通过不等于自然度认证。</p><a href="manifest.json">任务、时间轴与执行证据</a>'
        + "\n".join(cards)
        + f"<footer>{html.escape(credit)}</footer>"
        + "</html>",
        encoding="utf-8",
        newline="\n",
    )
    for chinese, filename in (
        (False, "doc/demos/recordings.en.md"),
        (True, "doc/demos/recordings.zh-CN.md"),
    ):
        heading = (
            "## 单模型路线：16 个复杂任务 Demo"
            if chinese
            else "## Single-family routes: 16 complex task demos"
        )
        intro = (
            "MotionCraft、SynTalker 各 8 段，分别按 **2 列 × 4 行** 排列。点击封面查看完整 MP4；音频来自用户提供的 `audio_reference_chu2.mp3` 与 `chu2.txt`，由 Audio8-TTS 克隆生成。录像为真实页面按正常速度回放，不包含准备等待。"
            if chinese
            else "**Eight recordings per family, each in two columns × four rows.** Click a cover for the complete MP4. Audio8-TTS uses the supplied `audio_reference_chu2.mp3` and `chu2.txt` voice reference. These are actual Studio replays at normal speed; preparation latency is separate."
        )
        limits = (
            "对照录像查看动作节奏、脚部接触和手部细节。任务配置、时间轴与实测生成耗时见[技术说明](../character/unified-motion.zh-CN.md)。"
            if chinese
            else "Compare action timing, foot contact and hand detail in the recordings. See the [technical synopsis](../character/unified-motion.en.md) for task configuration, timelines and measured generation latency."
        )
        section = (
            f"<!-- BEGIN UNIFIED_MOTION_DEMOS -->\n{heading}\n\n{intro}\n\n{limits}\n\n"
        )
        for backend in ("motioncraft", "syntalker"):
            section += (
                f"### {'MotionCraft' if backend == 'motioncraft' else 'SynTalker'}\n\n"
                + table([e for e in entries if e["backend"] == backend], chinese)
                + "\n\n"
            )
        section += "[Local video gallery](../assets/unified-motion-demos/index.html) · [Execution manifest](../assets/unified-motion-demos/manifest.json)\n<!-- END UNIFIED_MOTION_DEMOS -->"
        section = section.replace(
            "<!-- END UNIFIED_MOTION_DEMOS -->",
            f"\n{credit}. Source: `{avatar['source_filename']}`.\n<!-- END UNIFIED_MOTION_DEMOS -->",
        )
        path = ROOT / filename
        content = path.read_text(encoding="utf-8")
        if "<!-- BEGIN UNIFIED_MOTION_DEMOS -->" in content:
            content = re.sub(
                r"<!-- BEGIN UNIFIED_MOTION_DEMOS -->.*?<!-- END UNIFIED_MOTION_DEMOS -->",
                lambda _: section,
                content,
                flags=re.S,
            )
        else:
            raise ValueError(f"Missing UNIFIED_MOTION_DEMOS section in {filename}")
        path.write_text(content, encoding="utf-8", newline="\n")
    print(f"Packaged {len(entries)} actual recordings into {args.output}")


if __name__ == "__main__":
    main()
