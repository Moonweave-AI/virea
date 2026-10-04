"""Build a two-column gallery from actual Studio exports and diagnostics."""

import argparse
import hashlib
import html
import json
import subprocess
from pathlib import Path


def run(ffmpeg, *args):
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("doc/assets/character-demos")
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    tasks = json.loads((args.evidence / "tasks.json").read_text(encoding="utf-8-sig"))
    items = []
    for task in tasks:
        name = task["id"]
        source, trace = args.evidence / f"{name}.webm", args.evidence / f"{name}.json"
        if not source.exists() or not trace.exists():
            continue
        diagnostics = json.loads(trace.read_text(encoding="utf-8"))
        recording = diagnostics["playback"]["recording"]
        drivers = recording["drivers"]
        models = sorted({d["owner"] for d in drivers} & {"ardy", "sentiavatar"})
        if models != ["ardy", "sentiavatar"] or not recording["complete"]:
            raise ValueError(f"{name}: requires a complete recording with both models")
        video = args.output / f"{name}.mp4"
        preview_at = next(d["at"] for d in drivers if d["owner"] == "ardy") + 1
        if not video.exists() or source.stat().st_mtime > video.stat().st_mtime:
            run(
                args.ffmpeg,
                "-i",
                source,
                "-vf",
                "scale=720:-2",
                "-c:v",
                "libx264",
                "-crf",
                "26",
                "-preset",
                "fast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                video,
            )
            run(
                args.ffmpeg,
                "-ss",
                preview_at,
                "-i",
                video,
                "-frames:v",
                "1",
                args.output / f"{name}.jpg",
            )
            run(
                args.ffmpeg,
                "-ss",
                preview_at,
                "-t",
                "5",
                "-i",
                video,
                "-filter_complex",
                "fps=10,scale=360:-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer",
                "-an",
                "-loop",
                "0",
                args.output / f"{name}.gif",
            )
        item = {
            **task,
            "duration_seconds": round(recording["duration_seconds"], 3),
            "audio_seconds": round(recording["audio_seconds"], 3),
            "models": models,
            "driver_sequence": [
                {"at": round(d["at"], 3), "owner": d["owner"]} for d in drivers
            ],
            "first_audio_seconds": diagnostics["metrics"].get("first_audio_seconds"),
            "execution_errors": [
                e for e in diagnostics["events"] if "error" in e["kind"]
            ],
            "preview_start_seconds": round(preview_at, 3),
            "preview_seconds": 5,
            "video": video.name,
            "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        }
        items.append(item)
    (args.output / "manifest.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    cards = []
    for item in items:
        name = item["id"]
        cards.append(f'''<article><header><span>{html.escape(name[:2])} / {item["duration_seconds"]:.1f}s</span>
<h2>{html.escape(item["title"])}</h2></header>
<video controls preload="metadata" playsinline poster="{name}.jpg" src="{name}.mp4" aria-label="{html.escape(item["title"])}"></video>
<details><summary>任务 / Task</summary><p>{html.escape(item["task"])}</p></details>
<p class="models">Qwen → Kokoro · SentiAvatar ↔ ARDY</p></article>''')
    (args.output / "index.html").write_text(
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>VIREA · Motion Studio / 8 performances</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f4f5f7;color:#20232b;font:15px/1.65 system-ui,sans-serif}
main{max-width:1080px;margin:auto;padding:56px 24px}h1{font-size:clamp(32px,5vw,56px);line-height:1.12;letter-spacing:-2px;margin:16px 0}
.eyebrow{letter-spacing:3px;font-size:12px;color:#6158b8}.intro{max-width:700px;color:#677080;margin-bottom:36px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}article{background:white;border:1px solid #e0e3eb;border-radius:20px;overflow:hidden}
header{padding:20px 22px 8px}header span{font-size:12px;color:#7a8190}h2{font-size:19px;margin:6px 0 10px}video{display:block;width:100%;background:#eef0f3;aspect-ratio:720/794;object-fit:contain}
details{padding:16px 22px 0}summary{cursor:pointer;color:#4e459d}p{margin:8px 0}.models{font-size:12px;color:#7a8190;padding:8px 22px 18px}
footer{margin-top:32px;color:#737b8b;font-size:13px}a{color:#4e459d}@media(max-width:600px){main{padding:30px 14px}.grid{grid-template-columns:1fr}}
</style><main><div class="eyebrow">VIREA / MOTION STUDIO</div><h1>从一次对话，<br>到一段完整表演。</h1>
<p class="intro">Eight real local performances. 对话、声音、身体动作与空间移动，由模型规划并连续执行。视频按实际播放记录回放录制，保留停顿和收势，没有加速或替换动作。实验性结果，任务意图不等于每个细节都已正确完成。</p>
<section class="grid">"""
        + "\n".join(cards)
        + """</section><footer>2026-10-02 · RTX 5090 Laptop · Qwen3.5-9B Q4_K_M · Kokoro · SentiAvatar · ARDY<br>
<a href="manifest.json">执行摘要 / Manifest</a> · 请逐个播放，避免多个音轨同时响起。</footer></main></html>""",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Built {len(items)} recorded demos in {args.output}")


if __name__ == "__main__":
    main()
