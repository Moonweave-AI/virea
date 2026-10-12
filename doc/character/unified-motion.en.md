<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](unified-motion.zh-CN.md)
<!-- END DOC NAV -->

# 🦴 Motion backends on one timeline

Deploy models in **Set Up**, then choose the ready backend in Character Studio or VRChat Studio. Both studios use the same provider configuration and worker readiness checks.

| Backend | Native route | Role |
|---|---|---|
| MotionCraft | Official task checkpoints, including text motion and speech gestures | Generate stage-specific body motion |
| SynTalker | Text/audio-conditioned motion | Generate body and hand motion from its native representation |
| SentiAvatar + ARDY | Speech gesture generation and action planning | Existing combined capability route |

## Deploy and use

Run the [automatic launcher](../getting-started/automatic-setup.en.md), detect existing assets in Set Up, select CPU or a supported GPU runtime, then deploy and verify. Each deployment reports stages, downloads, logs and a real generation result. The motion-model library manages additional catalog models.

Open `/app/character.html` for a VRM, or `/app/vrchat.html` for the Windows bridge. MotionCraft is the default interaction backend. Workers are connected by the setup service; users do not need to copy a `motioncraft_url` or build a separate stack configuration.

## Timeline and skeleton contracts

Speech and motion tracks have independent offsets and durations. Text prompts describe simple stages; a plan can contain several stages with continuity across boundaries. Timing is resolved against the actual generated audio, including explicit `after_clip` relationships.

The source adapter declares native joint order, parents, units, rotation semantics and coordinate frames. Shared motion code converts this into Motion IR, then maps source rest frames onto the target rig. VRM playback and the VRChat output bridge consume that shared result. VRChat applies its own IK to the transmitted tracking targets.

Read [skeletal mathematics](../math-retarget/README.zh-CN.md) for rotation transport, hand observability and source-pose conventions. Use the same generated sample in Motion Lab when comparing a native skeleton with its target; the comparison keeps input identity intact.

## API and evidence

`GET /api/v1/characters/motion-backends` reports configured backends and live readiness. Sessions use `motion_backend`; interaction settings can update the selected method. `POST /api/v1/characters/{session_id}/performances` accepts a scheduled performance, illustrated in [performance.example.json](../../configs/character/performance.example.json).

[Model contracts](../architecture/contracts.en.md) · [Execution](../architecture/execution.en.md) · [Demos](../demos/README.en.md)

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-04
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: Shared deployment, native motion sources and independent speech/motion timing.
canonical: doc/character/unified-motion.en.md
related: [unified-motion.zh-CN.md, ../../README.md]
supersedes: []
superseded_by: []
-->
