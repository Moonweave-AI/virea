---
type: model-card
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 14
summary: PRISM TP2M 1.4B 的真实 WSL 部署、外部资产、组件内存策略、表示和许可边界。
canonical: doc/models/prism.zh-CN.md
related:
  - README.zh-CN.md
  - ../platforms/wsl2.zh-CN.md
  - ../research/prism-official-integration-audit-2026-08-21.zh-CN.md
supersedes: []
superseded_by: []
---

# PRISM TP2M 1.4B

PRISM 在 VIREA 中是可部署的技术路径，不再把 tokenizer/statistics/SMPL 资产问题合并为“模型不可运行”。
技术集成、外部资产许可与公开再分发是三个独立维度。

## 已核实的部署事实

- 官方代码 revision：`3c58bc5d946f0827171a3712ed36314f4b1a5186`。
- 官方模型 revision：`825daaa27f4f3845eb0978674c3acb378a12cda6`。
- 文本 tokenizer 来源：`google/umt5-xxl` 的固定 revision。
- 归一化 statistics 来源：`ZeyuLing/MotionHub` 的固定文件。
- 现有 WSL 部署包含约 32.7 GB 权重，并留下三组真实 PRISM 生成产物。
- 实际 placement 为 UMT5/text encoder 在 CPU，Transformer/VAE 在 CUDA，资源策略名为
  `cuda_component_split`。

## Runtime 与资源准入

当前 Runtime ID 是 `prism-tp2m-1-4b-cu128-component-split`，声明 `linux-64`、Python 3.11 和 CUDA 12.8。
在 Windows 宿主上应选择独立 `wsl:<distribution>` execution domain；`linux-64` 声明不能被解释为 Windows
Python 可以直接加载该 Runtime，也不能被外推为原生 Linux 已完成 production E2E。

安装下载前必须同时满足当前 profile 的独立下限：

| 资源 | 当前准入值 | 解释 |
|---|---:|---|
| free VRAM | 12 GiB | Transformer/VAE 的 CUDA placement |
| free physical RAM | 28 GiB | UMT5 CPU placement；不能与 VRAM 相加 |
| free swap | 0 GiB | 不把 swap 当作物理内存最低值 |
| free storage | 40 GiB | 外部资产、Runtime 和事务 staging 的声明下限 |

28 GiB 是依据 25.075 GiB UMT5 权重文件与此前 31.063 GiB WSL 成功部署校准的 preflight 下限。当前
managed E2E 已记录：加载前 available RAM 为 32,463,986,688 bytes；加载后 available RAM 为
20,110,942,208 bytes、进程 RSS 为 12,612,476,928 bytes；推理后 available RAM 为 19,152,322,560 bytes、
进程 RSS 为 13,683,249,152 bytes；进程 VmHWM 为 31,703,216,128 bytes。VmHWM 是进程 RAM 高水位，不能
写成 GPU 峰值；本次证据没有记录 GPU allocation peak。准入仍要求加载和推理后至少保留 2 GiB 可用 RAM。

## 原生表示

PRISM 的公共控制面载荷固定为 `prism.smplh_body22.axis_angle69.v1`、`smplh.body22.v1`、30 FPS：

- `[0:3]`：米制绝对根位移；
- `[3:6]`：根关节 local-to-world 轴角；
- `[6:69]`：21 个非根 body joint 的局部轴角。

网络内部 138D tensor 是可追溯 side artifact，不是对外 native representation，也不得覆盖上述 69D
result identity。Worker 同时保留进入 Motion IR 前的原始 public carrier 与上游原生 NPZ。

空的 SMPL-X 模型目录不是有效资产。当前 model-free processor/body22 FK fallback 可以用于 Motion IR 和
VRMA，但不能宣称完成 SMPL-X mesh 重建。

## 资产与许可

模型、tokenizer 和 statistics 由用户在各自条款下取得，VIREA 只保存固定来源、expected files 与外部
定位，不把大权重复制进仓库或发行 wheel。当前生成路径不需要人体模型几何；它不能据此宣称具备 SMPL-X
mesh 重建能力。技术状态与发行状态独立：当前技术状态为 `integrated_experimental`，同时保持
`distribution_status: external_assets_only` 与 `license_status: license_review_required`。这次本地运行的
显式许可接受只记录操作者决定，不为公开复制、商业使用或再分发补足权利。

复用既有资产时，四个 `--artifact-root ID=PATH` 必须与 manifest 完全一致：`prism-source`、
`prism-tp2m-1-4b-official-hf`、`prism-umt5-xxl-tokenizer`、`prism-motionhub-smplh-stats`；每个 root 还要用
同 ID 的 `--artifact-revision` 明确确认固定 revision。安装只建立外部目录引用，不复制约 32.7 GB 资产；
`--accepted-license` 只记录用户接受，不能代替权利人授权或允许 VIREA 再分发。

## 验收结果与当前重采集

PRISM 此前已在 `wsl:Ubuntu-24.04` 执行域内完成 doctor、安装、离线加载、真实推理、native artifact、
Motion IR、Canonical211、VRMA validator 和 fresh Web job 浏览器播放；验收请求由 manifest 固定为 129 帧、
30 FPS、50 inference steps、guidance 5、seed 42。该历史 validated evidence / validator `v1.0.0` 现已失效；
下列 ID 只用于追溯旧轮次，不是当前 `passed`：
`e2e-browser-prism-tp2m-1-4b-20260821085331248-39264`，fresh result 为
`01M0HREAR9ZH5219NPK930XVT0`，VRMA 为 127,768 bytes。Registry runner 的浏览器记录使用 headless
Chromium/WebGL2，并将 renderer 记录为 SwiftShader；根任务随后在独立应用内 Browser 中打开同一结果，确认
Avatar 完整可见、AnimationMixer 推进、硬件 WebGL2 RTX renderer 与 0 个错误。后者是独立视觉复核，不能
覆盖 registry 中 runner 的 renderer 字段。

PRISM manifest 保留此前有界 `integrated_experimental`，但当前 `v1.1.0` record 必须重新执行 doctor、当前
version/epoch installation acceptance、fresh Web generation 与后端绑定后，才能从 registry 读取实际 ID；
本文不预填。即使新记录通过，它也只覆盖实际运行的本机 Windows 宿主 WSL Ubuntu 24.04、RTX 5090 Laptop
GPU 与 component-split profile；不是原生 Linux、Windows native、macOS、其他 GPU、`supported` 或公开
GA 证据。
