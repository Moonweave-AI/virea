---
type: model-card
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: PRISM TP2M 1.4B 的真实 WSL 部署、外部资产、组件内存策略、表示和许可边界。
canonical: doc/models/prism.zh-CN.md
related:
  - prism.en.md
  - README.zh-CN.md
  - ../platforms/wsl2.zh-CN.md
  - ../research/runtime-resource-requirements-audit-2026-08-23.zh-CN.md
  - ../research/prism-official-integration-audit-2026-08-21.zh-CN.md
supersedes: []
superseded_by: []
---

# PRISM TP2M 1.4B

> [中文](prism.zh-CN.md) · [English](prism.en.md)

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

当前 Runtime ID 是 `prism-tp2m-1-4b-cu128-component-split`，声明 `win-64`、`linux-64`、Python 3.11
和 CUDA 12.8。CUDA lock 已在 Windows 原生解析成功，共享 loader 没有 Linux-only 依赖或路径合同，因此
64 GiB RAM + 16 GiB VRAM 的 Windows 设备可以直接选择该 CUDA Runtime；不必退回 96 GiB CPU profile，
也不必仅为 PRISM 强制使用 WSL。Windows 真实 checkpoint acceptance 尚未重采集，不能把“可构建”写成
“已在 Windows 完成 production E2E”。

安装下载前必须同时满足当前 profile 的独立下限：

| 资源 | 当前准入值 | 解释 |
|---|---:|---|
| total VRAM capacity | 12 GiB | Transformer/VAE 的 CUDA placement；标称容量的小幅固件保留使用有界容差 |
| total physical RAM capacity | 28 GiB | UMT5 CPU placement；不能与 VRAM 相加 |
| free swap | 0 GiB | 不把 swap 当作物理内存最低值 |
| free storage | 40 GiB | 外部资产、Runtime 和事务 staging 的声明下限 |

28 GiB 是依据 25.075 GiB UMT5 权重文件与此前 31.063 GiB WSL 成功部署校准的安装容量下限。当前
managed E2E 已记录：加载前 available RAM 为 32,463,986,688 bytes；加载后 available RAM 为
20,110,942,208 bytes、进程 RSS 为 12,612,476,928 bytes；推理后 available RAM 为 19,152,322,560 bytes、
进程 RSS 为 13,683,249,152 bytes；进程 VmHWM 为 31,703,216,128 bytes。VmHWM 是进程 RAM 高水位，不能
写成 GPU 峰值；本次证据没有记录 GPU allocation peak。Worker 以实测 RSS 加 2 GiB 余量为依据，要求加载前
当前可用 RAM 至少 15 GiB，并在加载和推理后至少保留 2 GiB。这项动态安全检查不再冒充安装总容量门槛。

WSL 只报告约 20 GiB 总 RAM 时，若 Windows 主机拥有 64 GiB，原因是 WSL2 配额而不是整机硬件不足。
向导会显示 `configuration-required`，建议在 `%UserProfile%\.wslconfig` 的 `[wsl2]` 下设置 `memory=32GB`，
保存 WSL 工作后执行 `wsl --shutdown`，再运行 `uv run virea`。调整配额不会删除或重新下载模型资产。

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
本文不预填。即使新记录通过，它也只覆盖实际执行的域、GPU 与 component-split profile；历史记录仍只覆盖
Windows 宿主中的 WSL Ubuntu 24.04 + RTX 5090 Laptop GPU。新加入的 Windows-native 声明当前只有 lock
解析与 wrapper contract 证据，不是原生 Windows 真实推理、原生 Linux、macOS、其他 GPU、`supported`
或公开 GA 证据。

## dtype 安全加载与既有部署更新

Runtime `0.1.4` 改为通过 Diffusers `from_pretrained(..., torch_dtype=...)` 加载 PRISM Transformer 和 VAE，
在权重加载阶段就确定推理精度；VIREA 不再先用 float32 构造完整组件、装载权重，再对整套模型执行
`.to(dtype=...)`。加载仍保持仅本地文件、仅 Safetensors、低内存模式，并继续对 missing、unexpected、
mismatched 与其他权重加载错误实行失败关闭。

此前的 `There are modules ... should be kept in float32` 两行本身是 Diffusers 警告，不是 Python exception；
它能证明旧代码走了不安全的整体 dtype 转换路径，但不能单独证明生成最终失败的原因。Runtime `0.1.4` 已移除
该路径。若更新后仍失败，应以 VIREA 展示的结构化终止原因定位，不要把更早出现的普通警告误当作最终异常。

已有 clone 不需要删除部署；更新代码后让向导只修复过期 Runtime：

```powershell
# 将当前 clone 快进到远端最新 main；这条命令不会删除数据根目录。
git pull --ff-only origin main

# 按锁文件同步项目开发环境；--locked 禁止静默改写依赖版本。
uv sync --locked

# 启动交互向导；它会识别 Runtime 0.1.3 已过期并构建 Runtime 0.1.4。
uv run virea
```

```bash
# 将当前 clone 快进到远端最新 main；这条命令不会删除数据根目录。
git pull --ff-only origin main

# 按锁文件同步项目开发环境；--locked 禁止静默改写依赖版本。
uv sync --locked

# 启动交互向导；它会识别 Runtime 0.1.3 已过期并构建 Runtime 0.1.4。
uv run virea
```

四项固定 artifact revision 均未改变。已经校验的 PRISM 源码、约 32.7 GB 模型快照、tokenizer 和 statistics
仍保留在最初配置的数据根目录中并直接复用；不要删除，也不需要重新下载。只需重建隔离的 PRISM Runtime；
用户确认既有执行域与资源 profile 后，向导会完成该迁移。
