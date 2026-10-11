<!-- BEGIN DOC NAV -->
[✦ VIREA](../README.md) · [Documentation](README.en.md) · [Set Up](getting-started/automatic-setup.en.md) · [Demos](demos/README.en.md) · [简体中文](comparison.zh-CN.md)
<!-- END DOC NAV -->

# 🧭 Comparing embodied character projects

This comparison describes public implementations reviewed on **October 11, 2026**. It groups capabilities by the job a reader wants to do, rather than assigning an overall score. The README contains the compact matrix.

## What the columns mean

| Column | A check means |
|:--|:--|
| LLM + speech | A conversational language model and spoken response are connected to the character workflow, including speech-to-speech services. |
| Generated motion | A prompt can produce new skeletal motion through a generative engine or LLM keyframes. A clip library or video pose reconstruction is a different capability. |
| Native skeleton → VRM | The implementation converts a generator's or capture model's native joint representation into VRM/VRMA bone motion. Playing an already-built VRMA does not by itself perform this conversion. |
| Browser avatar | A browser renders the animated 3D character. A control dashboard or game-window capture is distinct. |
| VRChat execution | The implementation drives an avatar in a VRChat client. WebXR support targets another environment. |
| Independent tracks | A performance can explicitly schedule multiple motion segments and speech clips with separate start times and lengths. Concurrent live audio alone does not establish this scheduling contract. |
| Motion / execution contracts | Versioned normalized motion artifacts and target execution commands/receipts form a shared boundary across providers and targets. A model's network endpoint alone covers only part of this column. |

✅ denotes an implemented capability in this scope; ❌ denotes a capability outside the reviewed implementation. Optional integrations are included and identified below.

## Sources and scope

| Project / pinned revision | What the implementation provides | Sources |
|:--|:--|:--|
| **Project Gabriel**, `motion-server` · `ab5883b` | A VRChat companion with Gemini Live or a local conversation backend. DART and ARDY share a motion-server protocol; a retargeter streams body parameters into a custom DesktopFBT avatar rig over OSC. The web dashboard manages the agent. | [README](https://github.com/HoppouAI/ProjectGabriel-Remastered/blob/ab5883be0cb12c3e75ff803609d6daec211cac4a/README.md) · [Motion server and protocol](https://github.com/HoppouAI/ProjectGabriel-Remastered/blob/ab5883be0cb12c3e75ff803609d6daec211cac4a/motion_server/README.md) |
| **rexclaw**, `main` · `481011b` | A browser/desktop VRM companion with multiple language and voice providers, VRMA playback and WebXR. Its optional gesture tool calls the separate Text-To-VRMA application and receives a finished VRMA file. That external application's native skeletal conversion is counted in its own row. | [README](https://github.com/Codemarchant/rexclaw/blob/481011b2df4ad30fb15d09c2936b8f4435ebf7d8/README.md) · [Text-To-VRMA integration](https://github.com/Codemarchant/rexclaw/blob/481011b2df4ad30fb15d09c2936b8f4435ebf7d8/server/text_to_vrma.py) |
| **text-to-vrma**, `master` · `b808187` | Animation authoring with LLM keyframes or local ARDY, VRM preview, expressions and VRMA export. ARDY Core skeleton rotations are retargeted to VRM bones. Its LLM motion planner is separate from a spoken character conversation. | [README](https://github.com/Kirakun0328/text-to-vrma/blob/b8081875916c8621c7ec226b4adcb2c70e7b13b7/README.md) · [ARDY retargeter](https://github.com/Kirakun0328/text-to-vrma/blob/b8081875916c8621c7ec226b4adcb2c70e7b13b7/tools/ardy-engine/retarget.py) |
| **MotionMind**, `main` · `ab5d0ef` | Video-to-SMPL reconstruction, VRM retargeting, clip search/composition and a voice coach using Gemini Live or a fallback speech pipeline. The motion input is captured movement rather than newly sampled text-to-motion. | [README](https://github.com/rohitacharyams/MotionMind/blob/ab5d0efc904d856f65c69de7f4e4eabd22e6ec49/README.md) · [Architecture](https://github.com/rohitacharyams/MotionMind/blob/ab5d0efc904d856f65c69de7f4e4eabd22e6ec49/ARCHITECTURE.md) |
| **ChatVRM**, archived `main` · `b542aa0` | A browser conversation demo using ChatGPT, Koemotion/Koeiromap, speech recognition and three-vrm. The project was archived in July 2024. | [README and feature list](https://github.com/pixiv/ChatVRM/blob/b542aa00e19dccf9fc48ba340cf7eee011d2329a/README.md) |
| **VIREA**, main after PR #11 · `65f6b59` | Model capability ports, native source conversion and Motion IR, shared skeletal retargeting, independent speech/motion scheduling, browser and VRChat targets, and versioned execution receipts. | [Contracts](architecture/contracts.en.md) · [Execution](architecture/execution.en.md) · [Motion foundation](architecture/overview.en.md) · [Schemas](../packages/contracts/schemas/v1/) |

## Maintaining the comparison

When a project gains a capability, update its pinned revision, inspect the implementation and adjust both READMEs together. Model quality, generation latency and hardware requirements need controlled experiments; this feature table does not rank those dimensions.

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](catalog.en.md) · [🛠️ Troubleshooting](operations/troubleshooting.en.md) · [🤝 Contributing](../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Capability comparison with pinned primary-source references.
canonical: doc/comparison.en.md
related: []
supersedes: []
superseded_by: []
-->
