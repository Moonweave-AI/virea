---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-12
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 90
summary: Edit and render the VIREA English launch film in the browser.
canonical: productions/virea-launch/workbench/README.md
related: []
supersedes: []
superseded_by: []
---

# VIREA film workbench

An editable timeline for **Bring your avatars to life**: 10 chapters, 33 English captions, narration, music and transition effects. The film runs for 3,795 frames at 30 FPS. This workbench adapts [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft); its Apache 2.0 license is retained in `LICENSE.upstream`.

## Open the film

Download and extract the editable project from the [film release](https://github.com/Moonweave-AI/virea/releases/tag/launch-film-2026-10). It includes the media files used by the adjacent `edit` project.

```sh
cd source/edit
npm ci
cd ../workbench
npm ci
npm start
```

Open **http://127.0.0.1:5198/** and choose **Import film**. The interface opens in English with a muted preview. Select a clip to edit its properties, drag its edges to change timing, and use **Export JSON** to save your changes. **Export video** renders a 3840 × 2160 MP4 to `exports/`.

The Git checkout contains the source. Copy the release's `source/edit/public` directory into `../edit/public` before opening it here. Media and render output stay outside Git.

## Keep source and timeline in sync

```sh
npm run save-project
npm run parity -- --resolution 4k --frames 0,100,350,700,1030,1200,1600,1960,2270,2460,2700,3040,3270,3630,3794
```

The saved project is generated from `edit/src/workbench.ts`. Parity compares the direct composition with the imported timeline at the selected 4K frames; all 15 matched for this release. Set `VIREA_PARITY_PYTHON` to a Python environment with Pillow when the repository's `.venv` is unavailable.

Both previews and export use the same pinned Remotion 4.0.535 / React 19.2.3 components. The server binds to localhost. Asset links, generated indexes, installed dependencies and export caches are created locally and ignored by Git.

See [render instructions](../edit/README.md) for the direct Remotion workflow and [delivery notes](../DELIVERY.md) for the three finished editions.
