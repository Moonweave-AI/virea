---
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
---

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

## 解释边界

- “Declared Runtime capability”只来自 RuntimeSpec 的平台 ABI 与已实现资源 profile；manifest 中的
  `availability` 文本不会被渲染为能力或支持结论。
- “Known deployment blockers”只来自模型 manifest 的结构化 model/platform blocker；空列表表示当前没有
  已登记 blocker，不等于真实推理或该平台验收通过。
- “Observed evidence coverage”只展示 execution-target registry 中明确点名该模型的观测范围；target-level
  状态不会扩散到同一平台行的其他模型，也不会改变可选执行域。
- 观测范围不等于当前 promotion。record 是否有效、采用哪个 validator policy 与 record ID，必须以
  production evidence registry 为准。
- 资源 profile 只有 Worker 真实实现时才可选择；RAM、VRAM 与 swap 不相加。
- `external_assets` 或许可复核只限制获取/发行，不自动等于技术不可运行。
- 缺少观测记录表示该组合仍待实测，不表示模型或操作系统被主动判为不支持。
- 每个平台的 declared capability 与 observed coverage 见
  [平台矩阵](../platforms/support-matrix.generated.md)；启动时先检测可选执行域，再由用户为同一模型资产选择
  execution domain，控制面随后解析并按需懒构建或复用对应 Runtime 与域内路径，不重复下载模型资产。
