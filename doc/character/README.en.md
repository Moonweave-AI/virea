<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](README.zh-CN.md)
<!-- END DOC NAV -->

# 🎭 Character Studio

Import a VRM, choose your models, and talk to a character whose speech and movement share a timeline.

## Start

1. Launch VIREA with `Start-VIREA.cmd` on Windows or `sh start-virea.sh` on Linux/macOS.
2. In **Set Up**, connect and verify language, speech and motion capabilities. Existing local services are detected before installation.
3. Open **Character Studio** from the header, or use the address printed by the launcher: `http://127.0.0.1:8000/app/character.html` by default.
4. Load a VRM and open settings when you want to choose an avatar, voice or method. Start a conversation and send a message.

| Capability | Where to configure it | What to inspect |
|---|---|---|
| Language | Set Up → language connections | Generated reply and verification receipt |
| Speech | Set Up → speech connections | Selected voice, waveform and WAV result |
| Motion | Set Up → local deployment / motion model library | Runtime, native skeleton result and generation check |
| Avatar | Character Studio → settings | VRM preview and the generated motion |

## Speech and motion

Speech clips and motion segments have independent start times and lengths. A movement can outlast speech, and speech can start partway through an action sequence. Use short, concrete English motion descriptions; a simple action does not need to be split into every joint movement.

MotionCraft, SynTalker and SentiAvatar + ARDY use the same capability and execution contracts. Choose the available method in the studio. See [motion backends](unified-motion.en.md) for the native outputs and [execution](../architecture/execution.en.md) for channel ownership, interruption and playback receipts.

Speech verification never plays automatically. Use explicit playback controls when sound is wanted. Reference audio and its matching transcript can be imported for [Audio8 voice cloning](audio8-tts.zh-CN.md); Kokoro provides pretrained voices.

## Inspect and extend

Use [Motion Lab](../workflows/motion-lab.en.md) to compare the source skeleton with VRM playback. Native rotations, source coordinate frames and target rest frames are described in the [retargeting reference](../math-retarget/README.zh-CN.md).

| Layer | Source |
|---|---|
| Session, plans and providers | `src/virea/character/` |
| Shared execution and motion | `src/virea/application/`, `src/virea/motion/` |
| HTTP/WebSocket | `apps/api/src/virea_api/routes/` |
| Browser | `apps/web/src/character/` |

[Complete setup](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [VRChat operation](vrchat-operations.en.md)

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-09-26
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: Character Studio setup and workflow through the shared capability system.
canonical: doc/character/README.en.md
related:
  - README.zh-CN.md
  - ../getting-started.en.md
supersedes: []
superseded_by: []
-->
