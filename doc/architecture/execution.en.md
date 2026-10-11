<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](execution.zh-CN.md)
<!-- END DOC NAV -->

# Timing, cancellation and execution evidence

[中文](execution.zh-CN.md) · [Overview](overview.en.md)

Speech and body movement are separate tracks. Place speech at an absolute offset or after a previous clip. The scheduler measures PCM samples, resolves dependencies and publishes final intervals before playback. Generated plans shift overlapping speech forward; explicitly authored plans preserve strict timing and report conflicts.

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#302b3a","primaryTextColor":"#f2edf1","primaryBorderColor":"#bdb8d1","secondaryColor":"#352c33","secondaryTextColor":"#f2edf1","secondaryBorderColor":"#c9adb8","tertiaryColor":"#23222b","tertiaryTextColor":"#f2edf1","tertiaryBorderColor":"#a49baa","lineColor":"#a89eb3","textColor":"#716878","edgeLabelBackground":"#eee9ee","clusterBkg":"#23222b","clusterBorder":"#a49baa","titleColor":"#f2edf1","noteBkgColor":"#eee9ee","noteTextColor":"#302b3a","noteBorderColor":"#a49baa"}}}%%
sequenceDiagram
    participant User
    participant Session
    participant Compiler
    participant Speech
    participant Motion
    participant Target
    User->>Session: New input
    Session->>Session: Advance epoch, cancel older work
    Session->>Compiler: Timed plan
    par Independent preparation
        Compiler->>Speech: Synthesize words
        Compiler->>Motion: Generate text-conditioned windows
    end
    Speech-->>Compiler: Actual PCM and duration
    Compiler->>Motion: Resolve required speech conditions
    Motion-->>Compiler: Native samples and provenance
    Compiler->>Compiler: Retarget, validate, hash artifacts
    Compiler-->>Session: Executable performance
    Session->>Target: Identity-bound execution command
    Target-->>Session: Playback receipt
```

MotionCraft text-only windows can run while speech is being synthesized. Speech-conditioned MotionCraft windows and SynTalker windows wait for the relevant audio. Native history, latent window geometry and sequence finalization remain model-specific. Prepared playback begins once the full performance is available.

The session epoch increases on interruption or replacement. Old acknowledgements and late publications are rejected. Only one command owns the body channel. Interruption preserves the last acknowledged body state; it does not invent a new rest pose.

Execution commands include the expected state revision, expiration, authorized capabilities and a payload digest. The session retains its latest 128 accepted commands and their terminal receipts: retries join an active execution or return its receipt, even after a later command completes. Command IDs and idempotency keys remain paired. An `accepted` acknowledgement advances to the terminal playback result. Artifact integrity is checked again when the target loads it.

A terminal acknowledgement releases body ownership and removes the pending delivery in one synchronous update. The producer subsequently updates history and removes temporary files. Playback consumers can continue immediately without a timed cleanup delay or rereading the finished motion.

| Evidence | What it establishes |
|---|---|
| planned | A validated intent exists |
| generated | The model produced a result |
| validated | The result passed its contract and quality checks |
| sent | Output was transmitted |
| device_ack | The playback target acknowledged it |
| observed_rendered | A referenced observation records the rendered result |
| semantically_satisfied | Referenced evidence supports the requested outcome |

Character Studio and VRChat Studio display the current turn and receipt. The immutable native, audio and playback artifacts live in `characters/artifacts/` under the configured VIREA data root. The session's temporary HTTP playback files are released after acknowledgement. Content-addressed audit artifacts remain for inspection; apply the project's [data retention policy](../operations/runtime-data-and-retention.en.md) when clearing a workspace.

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: explanation
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Unified runtime execution.
canonical: doc/architecture/execution.en.md
related: []
supersedes: []
superseded_by: []
-->
