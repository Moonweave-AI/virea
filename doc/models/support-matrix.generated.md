<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md)
<!-- END DOC NAV -->

# 模型支持矩阵

> 此文件由 `python scripts/generate_docs.py` 生成。不要直接编辑。

当前登记真实模型 **14** 个；`integrated_experimental` **14** 个；`supported` **0** 个。
状态定义见 [状态语义](../reference/status-semantics.zh-CN.md)。

| Model | Status | Tasks | Native skeleton / representation | Declared Runtime capability | Known deployment blockers | Observed evidence coverage | Distribution |
|---|---|---|---|---|---|---|---|
| **ACMDM-S-PS22 HumanML3D Absolute XYZ**<br><code>acmdm-humanml3d</code><br>arXiv 2025 | Integrated · experimental | <code>text_to_motion</code> | <code>humanml3d.body22.v1</code><br><code>humanml3d.body22.positions.v1</code> · 20.0 FPS | <code>acmdm-humanml3d-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 6 GiB, RAM 8 GiB)<br><code>acmdm-humanml3d-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 12 GiB) | No structured blocker recorded | No model-scoped observation recorded | Redistributable under declared terms |
| **CMDM HumanML3D**<br><code>cmdm-humanml3d</code><br>CVPR 2026 | Integrated · experimental | <code>text_to_motion</code> | <code>humanml3d.body22.v1</code><br><code>humanml3d.vector263.v1</code> · 20.0 FPS | <code>cmdm-humanml3d-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 6 GiB, RAM 8 GiB)<br><code>cmdm-humanml3d-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 12 GiB) | No structured blocker recorded | No model-scoped observation recorded | Redistributable under declared terms |
| **DART BABEL SMPL-X Motion Primitives**<br><code>dart-smplx</code><br>ICLR 2025 Spotlight | Integrated · experimental | <code>streaming_text_to_motion</code> | <code>smplx.body22.v1</code><br><code>dart.smplx.body22.axis_angle_primitives.v1</code> · 30.0 FPS | <code>dart-smplx-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 10 GiB, RAM 16 GiB)<br><code>dart-smplx-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 24 GiB, swap 8 GiB) | No structured blocker recorded | No model-scoped observation recorded | External assets / acceptance required |
| **DisCoRD MoMask HumanML3D**<br><code>discord-humanml3d</code><br>ICCV 2025 Highlight | Integrated · experimental | <code>text_to_motion</code> | <code>humanml3d.body22.v1</code><br><code>humanml3d.vector263.v1</code> · 20.0 FPS | <code>discord-humanml3d-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 8 GiB, RAM 10 GiB)<br><code>discord-humanml3d-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 14 GiB) | No structured blocker recorded | No model-scoped observation recorded | License review required |
| **FloodDiffusion Tiny**<br><code>flood-diffusion-tiny</code><br>arXiv 2025; pinned Hugging Face snapshot | Integrated · experimental | <code>text_to_motion</code> | <code>humanml3d.body22.v1</code><br><code>humanml3d.vector263.v1</code> · 20.0 FPS | <code>flood-diffusion-tiny-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 16 GiB, RAM 16 GiB)<br><code>flood-diffusion-tiny-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 16 GiB) | No structured blocker recorded | No model-scoped observation recorded | Redistributable under declared terms |
| **InterMask InterHuman**<br><code>intermask-interhuman</code><br>ICLR 2025 | Integrated · experimental | <code>text_to_two_person_interaction</code><br><code>interaction_reaction_generation</code> | <code>interhuman.two_actor_smpl22.v1</code><br><code>interhuman.motion262.v1</code> · 30.0 FPS | <code>intermask-interhuman-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 8 GiB, RAM 12 GiB)<br><code>intermask-interhuman-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 16 GiB) | No structured blocker recorded | No model-scoped observation recorded | License review required |
| **MARDM SiT-XL HumanML3D**<br><code>mardm-humanml3d</code><br>CVPR 2025 | Integrated · experimental | <code>text_to_motion</code> | <code>humanml3d.body22.v1</code><br><code>mardm.humanml3d.ric67.v1</code> · 20.0 FPS | <code>mardm-humanml3d-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 12 GiB, RAM 16 GiB)<br><code>mardm-humanml3d-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 24 GiB) | No structured blocker recorded | No model-scoped observation recorded | Redistributable under declared terms |
| **MoMADiff HumanML3D**<br><code>momadiff-humanml3d</code><br>ACM Multimedia 2025 | Integrated · experimental | <code>text_to_motion</code> | <code>humanml3d.body22.v1</code><br><code>humanml3d.vector263.v1</code> · 20.0 FPS | <code>momadiff-humanml3d-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 6 GiB, RAM 8 GiB)<br><code>momadiff-humanml3d-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 12 GiB) | No structured blocker recorded | No model-scoped observation recorded | Redistributable under declared terms |
| **MoMask HumanML3D**<br><code>momask-humanml3d</code><br>CVPR 2024 | Integrated · experimental | <code>text_to_motion</code> | <code>humanml3d.body22.v1</code><br><code>humanml3d.vector263.v1</code> · 20.0 FPS | <code>momask-humanml3d-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 6 GiB, RAM 8 GiB)<br><code>momask-humanml3d-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 10 GiB) | No structured blocker recorded | No model-scoped observation recorded | License review required |
| **MotionCraft MC-Bench SMPL-X 322D**<br><code>motioncraft-smplx</code><br>AAAI 2025 | Integrated · experimental | <code>text_to_motion</code><br><code>speech_to_gesture</code><br><code>music_to_dance</code> | <code>motionx.smplx53.v1</code><br><code>motionx.smplx322.v1</code> · 30.0 FPS | <code>motioncraft-smplx-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 12 GiB, RAM 24 GiB)<br><code>motioncraft-smplx-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 24 GiB, swap 8 GiB) | No structured blocker recorded | No model-scoped observation recorded | External assets / acceptance required |
| **PRISM TP2M 1.4B**<br><code>prism-tp2m-1-4b</code><br>arXiv 2603.08590 v3 and official public checkpoint snapshot | Integrated · experimental | <code>text_to_motion</code> | <code>smplh.body22.v1</code><br><code>prism.smplh_body22.axis_angle69.v1</code> · 30.0 FPS | <code>prism-tp2m-1-4b-cu128-component-split</code> · Windows x86_64, Linux x86_64 · cuda_component_split (VRAM 12 GiB, RAM 28 GiB)<br><code>prism-tp2m-1-4b-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 96 GiB) | No structured blocker recorded | No model-scoped observation recorded | external_assets_only |
| **ReMoMask HumanML3D**<br><code>remomask-humanml3d</code><br>ECCV 2026; arXiv v1 2025-08-04 | Integrated · experimental | <code>text_to_motion</code><br><code>retrieval_augmented_text_to_motion</code> | <code>humanml3d.body22.v1</code><br><code>humanml3d.vector263.v1</code> · 20.0 FPS | <code>remomask-humanml3d-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 12 GiB, RAM 12 GiB)<br><code>remomask-humanml3d-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 16 GiB) | No structured blocker recorded | No model-scoped observation recorded | Redistributable under declared terms |
| **SentiAvatar SuSu**<br><code>sentiavatar-susu</code><br>arXiv v1 2026-04-03; public code and weights 2026 | Integrated · experimental | <code>audio_text_to_avatar_motion</code><br><code>streaming_dialogue_avatar_motion</code> | <code>susu.body25_hands40.v1</code><br><code>susu.body25_hands40.cont6d_root_delta.v1</code> · 20.0 FPS | <code>sentiavatar-susu-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 8 GiB, RAM 12 GiB)<br><code>sentiavatar-susu-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 16 GiB, swap 4 GiB) | No structured blocker recorded | No model-scoped observation recorded | Redistributable under declared terms |
| **Tencent HY-Motion 1.0**<br><code>hy-motion-1</code><br>2025-12-30 | Integrated · experimental | <code>text_to_motion</code> | <code>hy_motion.wooden_body22.v1</code><br><code>hy_motion.body22.rot6d_translation.v1</code> · 30.0 FPS | <code>hy-motion-1-cu128</code> · Windows x86_64, Linux x86_64 · cuda_full (VRAM 26 GiB, RAM 24 GiB)<br><code>hy-motion-1-cpu</code> · Windows x86_64, Linux x86_64, macOS arm64, macOS x86_64 · cpu (RAM 40 GiB, swap 16 GiB) | No structured blocker recorded | No model-scoped observation recorded | External assets / acceptance required |

## 🧭 字段怎么读

| 字段 | 信息来源与含义 |
|:--|:--|
| Declared Runtime capability | RuntimeSpec 中的平台 ABI 与已实现的资源配置。 |
| Known deployment blockers | Manifest 登记的模型／平台安装条件；空列表表示没有已登记条件。 |
| Observed evidence coverage | 执行目标 registry 中明确点名该模型的实测范围。 |
| Resource profile | Worker 可执行的内存与设备配置；RAM、VRAM、swap 分别计算。 |
| Distribution | 模型资产的获取与发行条款，包含需要单独获取的资源。 |

当前验证记录、validator policy 和 record ID 见 production evidence registry。缺少记录的组合可以继续
通过实际生成检验。对照[平台矩阵](../platforms/support-matrix.generated.md)，选择检测到的 execution domain；
控制面会复用模型资产，并按需构建对应环境。

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: reference
status: Generated
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-22
last_reviewed: 2026-08-22
review_cycle_days: 14
summary: 从模型 manifest 与 RuntimeSpec 生成的模型、任务、原生骨骼/表示、资源和发行状态矩阵。
canonical: doc/models/support-matrix.generated.md
related:
  - README.zh-CN.md
  - ../platforms/support-matrix.generated.md
  - ../reference/status-semantics.zh-CN.md
supersedes: []
superseded_by: []
-->
