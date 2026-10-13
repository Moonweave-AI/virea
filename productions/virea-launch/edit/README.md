---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-12
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 90
summary: Edit and render the film
canonical: productions/virea-launch/edit/README.md
related: []
supersedes: []
superseded_by: []
---

# Edit and render the film

Use Node.js and npm. Download the editable package from the [media release](https://github.com/Moonweave-AI/virea/releases/tag/launch-film-2026-10) to obtain the matching `public/` media. From this directory:

```sh
npm ci
npx tsc --noEmit
npm run dev
```

Choose **VIREA-English-4K** for the 3840 × 2160 master or **VIREA-English** for the 1080p preview. Both use 3,795 frames at 30 FPS. Mute the player before previewing when sound is unwanted.

```sh
npx remotion render src/index.ts VIREA-English-4K out/VIREA-English-4K-v2.mp4 --codec=h264 --crf=18 --concurrency=4 --gl=angle
```

The composition props are `withMusic`, `withNarration`, `withSfx` and `captions`. Disable `withMusic` to export narration and effects without the music bed. Disable all three audio props for silent rendering. Source product videos are always muted.

Change English copy in `src/timeline.ts`, regenerate narration and captions with the included preparation scripts, and render again. The phoneme override is in `prepare_english_voice.py`. The `src/workbench.ts` manifest imports the same scenes, timing and audio into the editable workbench.

The renderer uses ANGLE on Windows. Use a supported Chromium GL backend on other hosts. FFmpeg is required for the optional audio-mastering and validation scripts.
