---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-20
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: 2025–2026 motion generation 首批适配候选的官方制品、许可证、运行时、输出表示与真实支持状态。
canonical: doc/model-catalog/first-wave-2026-08-20.zh-CN.md
related:
  - ../../registries/models/motion-model-registry.v1.0.0.yaml
  - ../../registries/models/first-wave.v1.yaml
  - motion-generation-registry-2026-08-20.zh-CN.md
  - ../refactor/WP00_WP15_IMPLEMENTATION_MAP.md
supersedes: []
superseded_by: []
audience:
  - VIREA maintainers
  - model adapter authors
visibility: public
---

# Motion Generation 首批适配清单

## 结论

2026-08-20 的研究优先矩阵建议覆盖九个模型族，并分为三类：

1. 优先建立真实推理与 Motion IR 适配：MARDM、InterMask、MotionCraft、DART、DisCoRD。
2. 以显式许可证选择启用：HY-Motion 1.0、SentiAvatar、ReMoMask。
3. 作为高复杂度物理桥接：InterMimic。

这是一份适配优先级与上游可用性参考，不是统一 SOTA 排名。HumanML3D、InterHuman、音乐、共语手势和物理 HOI 的指标、数据分布与输出空间不可直接横向排序。

本页同时记录 2026-08-21 的工程状态：FloodDiffusionTiny、MoMADiff、MARDM、ACMDM、CMDM 与 PRISM
`prism-tp2m-1-4b` 此前分别完成过固定正式制品、仓库外安装、独立 Worker、真实推理、Motion IR/Canonical211、
VRMA validator 和 fresh Web 浏览器播放，因此 manifest 保留受限 `integrated_experimental`。但旧 validated
evidence / validator `v1.0.0` 已失效；当前 `v1.1.0` 六模型重采集尚未写入，有效 `passed = 0`。目标范围仍是
前五条 Windows native / RTX 5090 Laptop GPU 与 PRISM `wsl:Ubuntu-24.04` component-split，但不能把目标或
历史 ID 当作当前证据。当前没有真实模型达到 `supported`；单机事实不能外推到原生 Linux、macOS、其他
GPU、CPU profile、公开再分发或 GA。

## 状态语义

| 状态 | 语义 |
|---|---|
| registered | 只登记研究工作、目标能力和来源；不声明代码、权重、许可证或推理可用 |
| runnable_upstream | 作者上游存在官方代码、官方权重或必要 checkpoint，以及至少一条有文档的推理路径；VIREA 尚未完成要求的 production E2E，期间可以已有部分 managed Runtime/Worker |
| integrated_experimental | VIREA 已有 worker、运行时描述和 Motion IR 解码，并跑通真实安装、真实 checkpoint 推理与受限 production acceptance，但覆盖、许可证或端到端回归仍不完整 |
| supported | 已有经过测试的 VIREA worker、runtime manifest、解码器、端到端 VRM 回归和明确许可证声明 |

登记不是实现；上游可运行也不是 VIREA 支持。状态只能按证据向前推进，不能因论文发表、仓库存在或文件下载成功直接提升。

## 历史 v1.0 真实接入快照（2026-08-21，仅追溯）

下表保留旧轮次定位信息用于排错与审计，所有 evidence/result/VRMA 字段均不再代表当前 `passed`。新 v1.1
record 必须由当前六条完整链生成后从 registry 读取，不能在下表上替换 schema 版本或复用旧 result。

| 模型 | 固定上游 | 已验证边界 | 状态与未外推项 |
|---|---|---|---|
| FloodDiffusionTiny | [AlayaLab/FloodDiffusionTiny](https://huggingface.co/AlayaLab/FloodDiffusionTiny) `e86746efa2f16b94a1bb08550e3d8d4a32163f14`；[google/umt5-base](https://huggingface.co/google/umt5-base) `0de9394d54f8975e71838d309de1cb496c894ab9` | fresh evidence `e2e-browser-flood-diffusion-tiny-20260821084140103-3292`；result `01M0HQR3JEBFNAZR7Z9BQEN1BH`；真实 `[T,263]`→Motion IR/Canonical211→83,668-byte VRMA→fresh browser | `integrated_experimental`；只证明 Windows native / RTX 5090 Laptop GPU，不是 `supported`、质量基准或公开 GA |
| MoMADiff | [代码](https://github.com/zzysteve/MoMADiff/tree/6dd9bea254bbca6cf19756ac3ee037cbf4f6021c)、[权重](https://huggingface.co/SteveZh/momadiff_models/tree/daf83c1441fbb9e8bacd377e28f557b54080c2a1)、[CLIP](https://github.com/openai/CLIP/tree/d05afc436d78f1c48dc0dbf8e5980a9d471f35f6) | fresh evidence `e2e-browser-momadiff-humanml3d-20260821084325940-15364`；result `01M0HQV6R49BFJAYKYETD0PXQ9`；真实 `[T,263]`→Motion IR/Canonical211→86,212-byte VRMA→fresh browser | `integrated_experimental`；只证明 Windows native / RTX 5090 Laptop GPU；官方模型卡与 HumanML3D/AMASS 条款仍分别适用 |
| MARDM | [代码](https://github.com/neu-vi/MARDM/tree/5e32b69723376028f38125ccee33011549cd341d)、[SiT-XL](https://huggingface.co/cr8br0ze/MARDM_SiT_XL/tree/6b9a9d6ea5456995e9883bda317e45ef111ecad3)及固定 AE/长度估计器/CLIP | fresh evidence `e2e-browser-mardm-humanml3d-20260821080913573-55864`；result `01M0HNWZNAHQHZCJTWANBJTWDM`；真实 80×67→Motion IR/Canonical211→86,192-byte VRMA→fresh browser | `integrated_experimental`；仅 `cuda_full`，只证明 Windows native / RTX 5090 Laptop GPU |
| ACMDM | [代码](https://github.com/neu-vi/ACMDM/tree/25ed4ba22fb54d9c3e99361609ee344e7c940303)、[权重](https://huggingface.co/cr8br0ze/ACMDM_Flow_S_PatchSize22/tree/f7b77ecb16968afb0329a4a706978780843a1fc9)、固定 AE/CLIP | fresh evidence `e2e-browser-acmdm-humanml3d-20260821081301384-48528`；result `01M0HP3EKMYZZPP3C2C9A3NHZP`；真实 `[T,22,3]`→Motion IR/Canonical211→86,208-byte VRMA→fresh browser | `integrated_experimental`；仅 `cuda_full`，只证明 Windows native / RTX 5090 Laptop GPU |
| CMDM | [代码](https://github.com/lycorp-jp/CMDM/tree/7fac27ecd78365115db5c29937f20889c318d79d)、[权重](https://huggingface.co/ly-corporation/CMDM/tree/be818de05ee83018d25dfeb9fbcd3fadddf4ccd8)、固定 DistilBERT/HumanML3D stats | fresh evidence `e2e-browser-cmdm-humanml3d-20260821081557740-44044`；result `01M0HP8V88QN9VZ1F31143D39B`；真实 `[T,263]`→Motion IR/Canonical211→86,196-byte VRMA→fresh browser | `integrated_experimental`；只证明 Windows native / RTX 5090 Laptop GPU；权重模型卡许可链接缺文件仍需发布复核 |
| PRISM `prism-tp2m-1-4b` | [代码](https://github.com/ZeyuLing/PRISM/tree/3c58bc5d946f0827171a3712ed36314f4b1a5186)、[权重](https://huggingface.co/ZeyuLing/PRISM-TP2M-1.4B/tree/825daaa27f4f3845eb0978674c3acb378a12cda6) | fresh evidence `e2e-browser-prism-tp2m-1-4b-20260821085331248-39264`；result `01M0HREAR9ZH5219NPK930XVT0`；129-frame `[T,69]`→Motion IR/Canonical211→127,768-byte VRMA→fresh browser | `integrated_experimental`；只证明 `wsl:Ubuntu-24.04` / RTX 5090 Laptop GPU；外部资产与许可不允许自动再分发；无 GPU peak 记录 |

独立于上表失效的 v1.0 browser record，ACMDM 当前 Runtime `0.1.3` / core epoch
`virea-runtime-core-20260821.2` 已用 80 帧 acceptance 和 196 帧 manifest 上限真实推理校准资源。观测 maxima
为 2,552,532,992 B process RSS、1,540,747,264 B system available RAM drop、673,024,512 B CUDA allocated、
687,865,856 B CUDA reserved、759,169,024 B CUDA free drop；公式推导 5 GiB RAM / 3 GiB VRAM，下限仍保守
保留为 8 GiB / 6 GiB。该校准不外推其他 GPU/平台，也不是 v1.1 browser evidence。

Flood 的官方 VAE decode 已应用其固定 mean/std；VIREA 通过显式 `upstream_vae_decoded` contract 接收
263D，不再做第二次反归一化。CLI validator 验证 installation/job/result/native/Motion IR/Canonical211/VRMA，
但把 `web_playback` 留给独立真实浏览器证据；两类证据不能互相替代。

## 当前 pinned-upstream contract adapter 层（2026-08-21）

当前 adapter family 均按固定上游 revision 的公开布局、单位和 provenance 契约验收。其确定性
pinned-upstream contract fixture 不是 checkpoint 输出或模型效果证据；真实 checkpoint/Worker/E2E 证据
只按模型单独记录：

| Adapter family | 当前引用模型 | 契约覆盖 | 未覆盖 |
|---|---|---|---|
| `dart-smplx-primitives` | DART | 保留 betas、primitive half-open boundaries、text segments、rollout provenance 与 native SMPL-X arrays；要求 rollout/overlap 前置声明 | continuity 仅为 caller upstream attestation；无 VIREA rollout/checkpoint golden，legacy preview 不应用 betas、仍 shape-agnostic |
| `humanml3d-motion263-body22` | FloodDiffusionTiny、MoMADiff、CMDM、DisCoRD、MoMask、ReMoMask | 精确 `(T,263)`、20 FPS、finite；normalized producer 要求 checkpoint identity/mean/std，已反归一化 producer 禁止二次 denormalize；source/stats 逐值保留 | Flood、MoMADiff、CMDM 已有逐模型真实 Worker/E2E；fixture 本身不替代该证据 |
| `hy-motion-body22` | HY-Motion 1 | pre-postprocess `[T,201]` 是 `hy_motion.latent201.v1` side artifact（`135:201` opaque）；registered decoded profile 是 `hy_motion.body22.rot6d_translation.v1` `[T,135]`，包含 translation3 + 22×6D，按上游 `view(3, 2)` 解码并要求 smoothing/ground flags | 官方 checkpoint decode、GPU/runtime 与 Avatar golden；其他 smoothing/ground mode 需要独立 profile；冗余 root rotation matrix 不声明为 preserved artifact |
| `intermask-interhuman-two-actor` | InterMask | Worker/native 是两个 `interhuman.motion262.v1` `[T,262]`；adapter output 是两个 `interhuman.two_actor_smpl22.pos3_rot6d.v1` `[T,22,9]`；`132:258` non-root 6D pass-through、root zero sentinel→identity，并保留 262D/shared transform/source artifact | 真实 262D checkpoint/export golden、multi-actor VRM 产品路径；不能无损转 single-actor canonical211；不声称 runtime BVH/IK |
| `mardm-ric67-body22` | MARDM | 精确 67D、20 FPS、finite、checkpoint identity/mean/std、RIC67 recovery 与 normalized/denormalized/stat 逐值保留 | 已有固定官方 checkpoint Worker/E2E；fixture 不等于该 checkpoint 证据 |
| `joint-positions-body22` | ACMDM | 精确 `[T,22,3]` absolute positions、20 FPS、finite；不虚构上游未输出的 rotation | 已有固定官方 checkpoint Worker/E2E；位置到目标旋转仍由显式下游适配完成 |
| `prism-smplh-body22-axis-angle69` | PRISM | 公开 `[T,69]`、30 FPS、finite；absolute translation + global axis-angle + 21 local body axis-angle；内部 138D 只作为可追溯 side artifact | managed Runtime 已完成 WSL fresh production E2E；许可仍限制分发，原生 Linux/macOS 未实测 |
| `motioncraft-smplx322` | MotionCraft | 精确 322D native carrier、30 FPS、finite、checkpoint identity/mean/std 与 source profile；body output 是 `virea.canonical211.v3` `[T,211]`；`159:209` expression50 同时保留为 native artifact 并作为 `smplx.expression50.v1` 标准 Motion IR face track，face-shape/betas 等其余 322D slices 只属 native artifacts | 三任务真实 checkpoint、hands/face 数值 golden |
| `sentiavatar-susu-mta63` | SentiAvatar | body 精确 153D、左右手各 120D、20 FPS 与 finite；仅 body 使用 153D checkpoint mean/std，hands 必须显式标记为已反归一化；root cm delta+cumsum 直接换算米而不重复 legacy scale；MTA63/BVH/cm 仅 native/intermediate provenance，output 为 `virea.canonical211.v3` `[T,211]`、`vrm1.humanoid52.v1`、meters、`quaternion_xyzw`；ARKit51/body/hands/stat arrays 逐值保留 | 音频/标签 Worker、真实流式输出、许可验收与 VRM 表情 golden |

这里的 pinned-upstream contract fixture 只证明按固定上游格式做 fail-closed 验证并保留 native artifacts；
逐值 fixture 不是上游 checkpoint golden，也不证明模型效果。六个 integrated model 的历史真实独立
runtime/Worker/E2E 与当前待采集的 v1.1 record 是另一组证据，其中目标范围为五个 Windows native 与一条
PRISM WSL；在新 record 落盘前不得宣称当前 evidence 已关闭。全部真实模型的 `supported = 0`。

本页的 2026-08-20 研究优先矩阵仍把 InterMimic 作为高复杂度物理桥接候选；历史 0.3 plugin slice 曾
注册了共享 HumanML3D adapter 的 MoMask。两者都不能据此称为已集成。当前工程状态以
[WP00-WP15 实现映射](../refactor/WP00_WP15_IMPLEMENTATION_MAP.md)为准。

## 首批优先矩阵

| 顺序 | 模型与发布日期 | 官方代码与权重 | 输入与原生输出 | 许可证 | 官方运行时边界 | 当前状态 / 难度 |
|---:|---|---|---|---|---|---|
| 1 | MARDM；CVPR 2025，arXiv v1 2024-11-25 | [官方仓库](https://github.com/neu-vi/MARDM)、[论文](https://arxiv.org/abs/2411.16575)；仓库脚本从作者 Hugging Face 下载 SiT/DDPM、AE、长度估计器与 evaluator | 文本 + 可选长度；HumanML3D 原生 67D / KIT 64D，官方 sample 可恢复为 (T,22,3) / (T,21,3) joint XYZ | MIT | Python 3.10.13、PyTorch 2.2.0、CUDA 12.1；纯生成不要求训练集 | `integrated_experimental`；已完成固定 SiT-XL 路径的 Win64/RTX 5090 真实验收，仍非 `supported` |
| 2 | InterMask；ICLR 2025，arXiv v1 2024-10-13 | [官方仓库](https://github.com/gohar-malik/intermask)、[论文](https://arxiv.org/abs/2410.10010)；官方脚本下载 InterHuman/Inter-X 的 VQ-VAE 和 Inter-M Transformer | 文本，或参考演员 + 文本；Worker/native 为两个演员各 `(T,262)`、30 FPS；adapter output 为 position3 + rotation6d 的两个 `(T,22,9)` track | MIT；InterHuman、Inter-X、SMPL-X 另有条款 | Python 3.7.7、PyTorch 1.13.1；Inter-X 需要 SMPL-X | runnable_upstream；P0，中等难度。需共享 world/time 的 multi-actor IR |
| 3 | MotionCraft；AAAI 2025，arXiv v1 2024-07-30 | [官方仓库](https://github.com/cure-lab/MotionCraft)、[论文](https://arxiv.org/abs/2407.21136)；官方提供 T2M、Speech-to-Gesture、Music-to-Dance 三个 checkpoint | 文本 / 语音 / 音乐；MC-Bench 的 Worker/native carrier 使用 SMPL-X 322D；adapter body output 为 Canonical211，expression50 为标准 Motion IR face track | Apache-2.0；训练数据另行授权 | Python 3.9、PyTorch 1.12.1、CUDA 11.3、mmcv-full、Tutel、PyTorch3D | runnable_upstream；P0，高难度。是同一代码族的三套任务 checkpoint，不是单权重全模态 |
| 4 | DART / DartControl；ICLR 2025 Spotlight，arXiv v1 2024-10-07 | [官方仓库](https://github.com/zkf1997/DART)、[论文](https://arxiv.org/abs/2410.05260)；作者 Google Drive 提供 checkpoint 与必要数据 | 历史/seed + 连续文本，可附 keyframe、trajectory、waypoint、goal 或 scene SDF；输出自回归 SMPL-X motion primitives、PKL/NPZ；BABEL 30 FPS，HML3D/SMPL-H 20 FPS | Apache-2.0；SMPL-X/H、AMASS、BABEL 各自授权 | 官方测试 Ubuntu 22.04、RTX 4090；需 SMPL-X/H；场景模式需要 mesh/SDF，policy 模式含 RL | runnable_upstream；P0/P1，高难度。应拆成 text_stream、inbetween、trajectory、scene、policy 能力 |
| 5 | HY-Motion 1.0 / Lite；官方发布 2025-12-30 | [官方仓库](https://github.com/Tencent-Hunyuan/HY-Motion-1.0)、[官方权重](https://huggingface.co/tencent/HY-Motion-1.0)、[论文](https://arxiv.org/abs/2512.23464)、[许可证](https://github.com/Tencent-Hunyuan/HY-Motion-1.0/blob/master/License.txt) | 英文文本 + 可选时长/提示重写；201D 是 pre-postprocess model tensor/side artifact，公开 decoded body profile 为 135D（translation3 + 22×6D）；应包装官方 skeleton 解码和动画导出链 | Tencent HY-MOTION 1.0 Community License；不适用于 EU、英国、韩国；月活超过一百万需另行授权；不得用输出改进其他 AI 模型 | 1.0B 最低 26GB VRAM，Lite 0.46B 最低 24GB VRAM；官方称 Windows、macOS、Linux；依赖 PyTorch、Qwen/CLIP、SMPL/H、PyTorch3D、FBX SDK 等 | runnable_upstream；许可证门控 P0，中高难度，不得默认启用 |
| 6 | SentiAvatar；arXiv 2026-04-03 | [官方仓库](https://github.com/SentiAvatar/SentiAvatar)、[官方权重](https://huggingface.co/Chuhaojin/SentiAvatar)、[论文](https://arxiv.org/abs/2604.02908)、[许可证](https://github.com/SentiAvatar/SentiAvatar/blob/main/LICENSE) | 16 kHz 普通话音频 + 中文动作标签；20 FPS；body (T,153)=root 3+25×6D，左右手各 (T,120)=20×6D，另有 ARKit 51 表情；导出 BVH、UE JSON、WAV | SentiPulse Non-Commercial Source License v1.0；禁止商业、SaaS 与商业组织内部生产使用 | Python 3.10、Qwen2-0.5B、Chinese HuBERT、vLLM、RVQ-VAE、Mask Transformer | runnable_upstream；非商业隔离 P0/P1，中高难度 |
| 7 | DisCoRD；ICCV 2025 Highlight；官方推理 2025-01-01、训练代码 2025-09-27 | [官方仓库](https://github.com/whwjdqls/DisCoRD)、[论文](https://arxiv.org/abs/2411.19527)；作者提供基于 MoMask 的 checkpoint | 文本 + 长度；MoMask/HumanML3D 离散 token 经 rectified-flow 连续解码器得到运动 | MIT | Python 3.8.5、CUDA 11.8；依赖 MoMask checkpoint 和 HumanML/KIT 工具链 | runnable_upstream；P1，低至中等难度。更适合 continuous_decoder/refiner adapter family |
| 8 | ReMoMask；arXiv 2025-08-04，ECCV 2026 | [官方仓库](https://github.com/AIGeeksGroup/ReMoMask)、[官方权重](https://huggingface.co/AIGeeksGroup/ReMoMask)、[论文](https://arxiv.org/abs/2508.02605) | 文本 + 可选长度 + retrieval database；HumanML3D 路线的 22-joint / SMPL 可视化输出 | CC BY-NC-SA 4.0；非商业且 ShareAlike；CLIP、SMPL 与数据集条款叠加 | Python 3.10、PyTorch 2.1、CUDA 11.8；官方 Hugging Face 当前约 8.87GB，包含 Part-TMR、TMR、VQ 与生成模型 | runnable_upstream；非商业隔离 P1，中高难度。官方仓库 README 的 coming soon 已落后于 HF 文件状态 |
| 9 | InterMimic；CVPR 2025 Highlight，arXiv 2025-02-27 | [官方仓库](https://github.com/Sirui-Xu/InterMimic)、[论文](https://arxiv.org/abs/2502.20390)；作者提供 teacher/student 示例 checkpoint，但 teacher 覆盖并非完整 17 类 | SMPL-X/InterAct 等参考 HOI 轨迹 + 物体几何/状态；输出模拟中的 SMPL-X 或 Unitree G1 状态、物体 6-DoF、接触和 rollout | MIT；Isaac、PHC、数据、机器人和物体资产各有条款 | Isaac Gym 路线为 Python 3.8、PyTorch/CUDA 11.6；另支持 Isaac Sim 5.1 + IsaacLab 2.3.1 | runnable_upstream；P1/P2，极高难度。只能先覆盖已发布情景，不能宣称 universal HOI 全支持 |

### 输出表示注意事项

- MARDM 与 DisCoRD 应复用 HumanML/KIT 解码与 root trajectory 归一化，不应各自复制数学实现。
- InterMask 必须产生两个独立 actor track，并保存共享时间轴、坐标系和交互 provenance。官方 naive foot IK 可能失败，不构成质量保证。
- MotionCraft 需要 SMPL-X 322D native carrier 的显式字段映射；body output 是 canonical211，expression50
  是标准 Motion IR face track，face-shape/betas 等其余切片只作 native artifact，不得靠维度猜测。
- DART 应保留 motion primitive、历史窗口、控制约束与 scene/object 证据；不能只展平为单段关节序列。
- HY-Motion 的 201D 是 pre-postprocess side artifact，decoded135 才是登记 body profile；`135:201` 保持
  opaque，冗余 root rotation matrix 不声明为 preserved artifact。
- SentiAvatar 上游 README 把 joint count 写成 63，但其声明的 25 + 20 + 20 等于 65。适配时必须以实际张量、named-joint map 和模板为准，不能信任汇总数字。
- InterMimic 是 physics-policy bridge，不是普通 text-to-motion worker；需要 actor、object、contact 与 simulator provenance。

## 只能登记，不能称支持

| 模型 | 官方事实 | 当前裁决 |
|---|---|---|
| OpenDanceNet / CVPR 2026 | [官方项目页](https://open-dance.github.io/)明确标注 Code coming soon | registered；无官方代码和权重 |
| OpenT2M / MonoFrill / CVPR 2026 | [官方项目页](https://research.beingbeyond.com/opent2m)有论文、数据与模型说明，没有代码或权重入口 | registered |
| LiveGesture / CVPR 2026 | 有[CVPR 官方论文](https://openaccess.thecvf.com/content/CVPR2026/html/Saleem_LiveGesture_Streamable_Co-Speech_Gesture_Generation_Model_CVPR_2026_paper.html)，未找到官方代码和权重 | registered |
| DyaDiT / CVPR 2026 | [官方仓库](https://github.com/puckikk1202/dyadit)有独立推理源码，但要求外部 checkpoint；无官方权重下载且无许可证 | registered |
| Being-M0 | [官方仓库](https://github.com/BeingBeyond/Being-M0)仍写将来发布代码与部分数据 | registered |
| Being-M0.5 | [官方仓库](https://github.com/BeingBeyond/Being-M0.5)仍写将来发布代码与部分数据 | registered |
| OmniMotion-X | [官方仓库](https://github.com/GuoweiXu368/OmniMotion-X)声明代码、评测与 checkpoint 等待数据集首阶段发布 | registered |
| MotionStreamer | [官方仓库](https://github.com/zju3dv/MotionStreamer)和 [HF](https://huggingface.co/lxxiao/MotionStreamer/tree/main)有 272D 表示、Causal TAE、evaluator 与普通 T2M checkpoint，但没有 motionstreamer_model checkpoint 或 streaming inference demo | registered；可另行研究 base T2M，不能宣称流式能力 |
| MotionLab | [官方仓库](https://github.com/Diouo/MotionLab)有代码和 checkpoint，但没有 LICENSE；作者还提示 2025-09 修 bug 后建议重训，论文复现需旧代码 | registered，等待许可证与版本化 checkpoint |
| UniMuMo | [官方仓库](https://github.com/hanyangclarence/UniMuMo)有代码与权重说明，运动格式为 (T,263)，但仓库无 LICENSE | registered，不能进入可分发 provider |

## 提升状态所需证据

从 runnable_upstream 提升为 integrated_experimental，至少需要：

- 独立、可禁用的 VIREA model provider；
- 明确的 runtime manifest 与可复现依赖；
- 输入验证和官方权重定位；
- 原生输出到 Motion IR 的字段级映射；
- 至少一条使用固定官方 checkpoint 的真实推理与 production acceptance 路径；
- 许可证与第三方数据/人体模型依赖说明。

从 integrated_experimental 提升为 supported，还需要：

- 针对真实官方 checkpoint 的确定性契约测试；
- 输出 shape、FPS、joint map、坐标、rotation space 与 root 语义验证；
- 端到端 Motion IR → retarget → VRM 回归；
- 失败模式、资源边界和可选能力声明；
- Owner 人工复核并更新本页和 overlay。

## Review 清单

| Action | Owner | Due / Review | Canonical Link |
|---|---|---|---|
| 复核研究矩阵及当前 plugin manifest 的官方仓库、权重与状态 | VIREA maintainers | 2026-09-19 或上游发布变化时 | [first-wave overlay](../../registries/models/first-wave.v1.yaml) |
| 为许可证受限 provider 记录显式启用边界 | VIREA maintainers | 实现前 | 各模型官方许可证 |
| 每完成一个真实适配后更新状态与证据 | adapter owner | 同一变更内 | 本页与 overlay |

本文由一手论文、作者仓库、作者模型仓库和官方文档整理；正式提升状态前必须由 Owner 人工核验。
