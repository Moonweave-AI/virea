<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](overview.zh-CN.md)
<!-- END DOC NAV -->

# Architecture: one foundation, three workspaces

[中文](overview.zh-CN.md) · [Documentation](../README.en.md) · [Design decision](../rfcs/0004-unified-embodied-runtime.md)

VIREA is a Verifiable Interaction Runtime for Embodied Agents. Motion Lab, Character Studio and VRChat Studio are workflows over shared capabilities. A browser VRM and an independent VRChat character are execution targets.

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#302b3a","primaryTextColor":"#f2edf1","primaryBorderColor":"#bdb8d1","secondaryColor":"#352c33","secondaryTextColor":"#f2edf1","secondaryBorderColor":"#c9adb8","tertiaryColor":"#23222b","tertiaryTextColor":"#f2edf1","tertiaryBorderColor":"#a49baa","lineColor":"#a89eb3","textColor":"#716878","edgeLabelBackground":"#eee9ee","clusterBkg":"#23222b","clusterBorder":"#a49baa","titleColor":"#f2edf1","noteBkgColor":"#eee9ee","noteTextColor":"#302b3a","noteBorderColor":"#a49baa"}}}%%
flowchart TB
    subgraph Workspaces["Three workspaces"]
        Lab["Motion Lab"]
        Studio["Character Studio"]
        VRC["VRChat Studio"]
    end
    subgraph Capabilities["Pluggable capabilities"]
        LLM["LLM · intent and planning"]
        Audio["TTS · measured speech"]
        Motion["Motion generators · native outputs"]
    end
    Lab --> Motion
    Studio --> LLM
    VRC --> LLM
    LLM --> Plan["Performance compiler · independent tracks"]
    Plan --> Audio
    Plan --> Motion
    Motion --> Source["Source adapters · Motion IR v2"]
    Source --> Rig["Shared skeletal retargeting<br/>Frames · FK · rotations · hands · contacts"]
    Audio --> Performance["Executable performance"]
    Rig --> Performance
    Performance --> Executor["Session + executor<br/>Timing · ownership · cancellation · receipts"]
    Rig --> Export["Motion Lab · inspect / export"]
    Executor --> Browser["Browser VRM"]
    Executor --> Bridge["OpenVR / OSC → VRChat Humanoid"]
    Browser -. acknowledgements .-> Executor
    Bridge -. acknowledgements .-> Executor
    classDef workspace fill:#23222b,stroke:#b1aabd,color:#f2edf1
    classDef core fill:#302b3a,stroke:#bbb0ca,color:#f2edf1
    classDef target fill:#352c33,stroke:#c7adb7,color:#f5eef0
    class Lab,Studio,VRC workspace
    class Plan,Source,Rig,Performance,Executor core
    class Browser,Bridge,Export target
```

## Responsibility map

| Location | Responsibility |
|---|---|
| `packages/contracts/src/virea_contracts/performance.py` | Intent, artifacts, executable performances, commands and receipts |
| `packages/contracts/src/virea_contracts/timeline.py` | Independent speech and motion track validation |
| `src/virea/ports/` | Language, audio, motion, source conversion and embodiment interfaces |
| `src/virea/adapters/` | Typed language plans, measured audio artifacts and native motion adapters |
| `src/virea/application/` | Request routing, preparation, sample timing, immutable artifacts, epochs and delivery |
| `src/virea/motion/` | Existing skeleton, quaternion, hand and kinematic mathematics |
| `packages/retarget/` | Public `retarget_motion_ir` entry point, actors and auxiliary tracks |
| `src/virea/character/` | Character context, provider adapters, browser delivery and legacy orchestration |
| `src/virea/vrchat/` | AI identity, calibration, native pose transport, input, room and capture adapters |
| `apps/api/`, `apps/web/` | HTTP routes, model management and the three workspaces |
| `plugins/models/`, `registries/` | Isolated workers, assets, runtime profiles and model facts |

## Motion foundation

Motion Lab normalizes native outputs to Motion IR v2 and calls the public retarget package. The interactive MotionCraft and SynTalker paths use that same retarget boundary. The numerical implementation lives in `src/virea/motion`; the previous character import paths are compatibility facades.

MotionCraft supplies local rotations; explicit source rest geometry binds them to target axes without discarding observed twist. Its raw artifact and unfiltered normalized rotations are retained separately from conditioned playback. SynTalker supplies recovered joint positions; its palm, twist observability and hand constraints remain in effect. Source profiles describe model output and target profiles describe the avatar. Offline and live poses use one rigid FK kernel. See [skeletal mathematics and evidence](../research/skeletal-retargeting-2026-10-11.md).

Motion IR retains multiple actors and face, gaze, contact and object tracks. The prepared humanoid playback adapter currently consumes one body's windows and speech; its native artifact is retained alongside the playback payload. New track consumers can use the existing IR rather than adding another motion tensor format.

## Preparation and execution

`PerformanceCompiler` owns speech task cleanup, actual-duration scheduling and one native generation per request. `SessionCoordinator` owns the active turn, epoch and body owner. `PerformanceExecutor` validates target identity, revision, expiry, capabilities and payload hashes. `load_delivery` rechecks artifacts immediately before a target loads them.

Browser and VRChat playback keep their target-specific clocks and device code. Each performance uses one target playback clock for motion, speech and subtitles. The server's pause-aware acknowledgement deadline measures waiting time, not a second animation timeline.

SentiAvatar + ARDY retains its semantic body-program planner and streaming behavior path. `IntentPlan` names that semantic plan; `TimedPerformancePlan` names the independent timed tracks. Existing `PerformancePlan` imports remain compatible. Shared state and timing utilities are extracted incrementally without rewriting those algorithms.

The model control plane continues to own installation, resource admission, worker processes and result export. These are runtime infrastructure, separate from conversational session orchestration.

See [contracts](contracts.en.md), [execution](execution.en.md), and [migration evidence](../quality/unified-runtime.md).

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
summary: Unified runtime overview.
canonical: doc/architecture/overview.en.md
related: []
supersedes: []
superseded_by: []
-->
