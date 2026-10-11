<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](character-studio.zh-CN.md)
<!-- END DOC NAV -->

# Character Studio

<!-- WORKSPACE ROUTE -->
> 🎭 **Prepare → generate → observe → export** · [Watch the demos](../demos/README.en.md)

[中文](character-studio.zh-CN.md) · [Set up first](../getting-started/automatic-setup.en.md)

Import a VRM and combine dialogue with generated movement in the browser.

1. Open `/app/character.html`, import your avatar, and start a session.
2. Choose the verified language, speech and motion connections. MotionCraft is the default independent-track method; SynTalker and the existing SentiAvatar + ARDY route are selectable.
3. Describe the interaction in ordinary language. For explicit choreography, use short English captions for each meaningful action stage.
4. Follow planning and generation progress. The timeline shows speech and motion separately; the execution label shows the turn and latest acknowledgement.
5. Pause, interrupt or submit another request. The next turn supersedes unfinished generation and keeps the character's acknowledged pose.
6. Export motion or a recorded video from the playback tools.

For example: perform a four-second wave, then walk for six seconds; speak an introduction beginning two seconds into the wave. The speech length comes from synthesis and may cross the stage boundary.

![Character Studio performance](../assets/unified-motion-demos/motioncraft-01-introduction.jpg)

[Eight examples per motion family](../character/unified-motion.en.md) · [Voice cloning](../character/audio8-tts.zh-CN.md) · [Timing model](../architecture/execution.en.md)

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Use the character-studio workspace.
canonical: doc/workflows/character-studio.en.md
related: []
supersedes: []
superseded_by: []
-->
