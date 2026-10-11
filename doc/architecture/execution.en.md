---
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
---

# Timing, cancellation and execution evidence

[中文](execution.zh-CN.md) · [Overview](overview.en.md)

Speech and body movement are separate tracks. Place speech at an absolute offset or after a previous clip. The scheduler measures PCM samples, resolves dependencies and publishes final intervals before playback. Generated plans shift overlapping speech forward; explicitly authored plans preserve strict timing and report conflicts.

```mermaid
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

Execution commands include the expected state revision, expiration, authorized capabilities and a payload digest. Identical replay does not start another execution. Reusing an idempotency key with another command is rejected. Artifact integrity is checked again when the target loads it.

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
