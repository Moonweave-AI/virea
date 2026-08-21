# ACMDM 官方接入审计（2026-08-21）

## 结论

接入对象固定为 2025 年论文 *Absolute Coordinates Make Motion Generation Easy*
的官方 joint-level `ACMDM-Flow-S-PatchSize22`。代码、两份权重、内部 checkpoint
路径、许可证和推理数学均已核实。独立 Worker 曾在正式权重上完成安装验收、manifest-exact 推理、
Motion IR、Canonical211、VRMA validator 与真实浏览器播放；当前 Runtime `0.1.3` / core epoch
`virea-runtime-core-20260821.2` 又完成 80 帧 acceptance 与 196 帧 manifest 上限的真实显存/内存校准。
模型保留仅覆盖 Windows win64/RTX 5090 路径的 `integrated_experimental`，仍不等于跨平台 `supported`；
校准记录不是当前 v1.1 production browser evidence，后者仍须单独重采集。

## 分类与依据

- 风险 / 质量目标：S3 / QA-L4。
- 论文：<https://arxiv.org/abs/2505.19377>，2025-05-26 首次提交。
- 官方代码：<https://github.com/neu-vi/ACMDM>，固定 revision
  `25ed4ba22fb54d9c3e99361609ee344e7c940303`，MIT。
- 官方权重集合：<https://huggingface.co/collections/cr8br0ze/acmdm>。
- 官方 README 明确给出 joint-level S-PS22 的 AE 与 ACMDM 下载链接和评测命令；
  text-to-motion demo 仍写着 `To be implemented`，因此不能把 README demo 当作验收证据。

## 固定制品

| Component | Revision | Released file | Bytes | Required member |
|---|---|---:|---:|---|
| ACMDM-S-PS22 | `f7b77ecb16968afb0329a4a706978780843a1fc9` | `ACMDM_Flow_S_PatchSize22.zip` | 290,192,456 | `ACMDM_Flow_S_PatchSize22/model/latest.tar` |
| Causal-AE | `78bbd7fc5ec129a6c74812d542892939261a984f` | `AE_2D_Causal.zip` | 187,332,448 | `AE_2D_Causal/model/latest.tar` |
| AE latent stats | same as Causal-AE | same archive | 144 + 144 | `AE_2D_Causal_Post_Mean.npy`, `AE_2D_Causal_Post_Std.npy` |
| OpenAI CLIP | code `d05afc436d78f1c48dc0dbf8e5980a9d471f35f6` | `ViT-B-32.pt` | upstream official file | local path passed to `clip.load` |

使用 `hf models info` 与 `hf download --dry-run` 得到完整 Hub revision；随后把两个
zip 下载到 checkout 外的 `VIREA-Data/cache/huggingface` 并只读检查目录。两张 Hub
model card 都声明 `license: mit`。checkpoint 只以 `torch.load(..., weights_only=True,
map_location="cpu")` 检查结构：

- ACMDM 的 `ema_acmdm` 为 125 个 state entries、39,094,184 parameters；
- Causal-AE 的 `ae` 为 66 个 state entries、17,076,743 parameters；
- latent mean/std 均为 float32 `[4]`；官方源码内 absolute XYZ mean/std 均为
  float32 `[3]`。

此外，已在 checkout 外的
`<external-acceptance-root>/acmdm-artifact-contract-20260821`
实际执行 Worker 的 artifact materialization：两个 HF local-dir 的 revision metadata
通过，GitHub source zip 的固定 prefix 与全部必需源文件通过，得到 312,829,822-byte
ACMDM checkpoint、204,997,782-byte AE checkpoint、两份 144-byte latent stats 和两份
140-byte XYZ stats。该结果证明真实制品安装/解包合同可用，但不代表 GPU 推理通过。

未使用 SHA、进程安全码或额外制品门禁；revision metadata、文件存在性、zip member
路径和 checkpoint state contract 是模型真实加载所必需的一致性检查。

## 数学与输出合同

论文定义每帧 `X^i ∈ R^(22×3)` 为全局绝对 XYZ。官方 S-PS22 release 实际执行：

1. 以 Causal-AE 将时间维下采样 4 倍，ACMDM 采样 latent `[B,4,T/4,22]`；
2. `create_transport()` 使用 Linear path、velocity prediction；
3. `Sampler.sample_ode()` 使用默认 Dopri5、50 个保存点、`atol=1e-6`、`rtol=1e-3`；
4. classifier-free guidance 默认 `cfg=3`；
5. 使用发布的 `[4]` latent mean/std 反归一化，再用 Causal-AE decode；
6. 使用发布的 `[3]` absolute-coordinate mean/std 反归一化，输出 float32
   `[T,22,3]`、20 fps。

VIREA `ArtifactRef` 合同固定为：

```text
name: source_acmdm_absolute_positions22
media_type: application/x-npy
dtype: float32
shape: [T, 22, 3]
representation_id: humanml3d.body22.positions.v1
skeleton_id: humanml3d.body22.v1
coordinate_system: humanml3d.right_handed_y_up_z_forward_global
root_translation: joint 0 absolute XYZ per frame
root_rotation: not provided
```

Worker 不捏造旋转，也不先转换成 263D。该原生载荷复用项目已有的
`humanml3d.body22.positions.v1` 表示；主线 `joint-positions-body22` compatibility
adapter 必须从绝对关节位置明确推导目标旋转/根变换并记录算法身份。

## 环境与资源裁决

上游声明的测试环境是 Python 3.10.13 / PyTorch 2.2.0 / CUDA 12.1。VIREA 的
Blackwell runtime 使用 Python 3.11 / PyTorch 2.11.0 / cu128；这是兼容性运行时升级，
不改变采样数学。上游 `load_and_freeze_clip()` 明确 `assert torch.cuda.is_available()`，
且模型、AE、CLIP 都整体 `.to(device)`，因此只实现 `cuda_full`：

- 安装前最少 6 GiB 可用 VRAM、8 GiB 可用物理 RAM、12 GiB 磁盘；
- 不声明 CPU、component offload 或 sequential offload；
- RAM 不与 VRAM 相加；不满足 CUDA profile 时下载前拒绝；
- Runtime project 为 `virea-model-acmdm-humanml3d-runtime==0.1.3`，core epoch 为
  `virea-runtime-core-20260821.2`。

### 真实内存下限校准

Manifest 中的 `virea.runtime_memory_floor_calibration.v1.0.0` 固定到 Windows x64、NVIDIA GeForce RTX
5090 Laptop GPU（设备 UUID 已从公开材料移除）、Python 3.11、PyTorch
2.11.0+cu128 / CUDA 12.8 与 `cuda_full`。同一 doctor report `01M0J26ZC4NXVWD4J3FQPHNF75` 下执行：

| 请求范围 | Job | Result | Frames |
|---|---|---|---:|
| production acceptance | `01M0J2AKYNW53B285ZHJ55NBK1` | `01M0J2BP0W0Z5XSRPQPG443CZ7` | 80 |
| manifest maximum | `01M0J2Q7GXAR4YBH2ZH1670JZS` | `01M0J2QP7TCM2AD7VCD4EAZSRN` | 196 |

两次真实推理的跨请求 maxima 为：

| 指标 | Bytes |
|---|---:|
| process peak RSS | 2,552,532,992 |
| system available RAM 最大下降 | 1,540,747,264 |
| CUDA max allocated | 673,024,512 |
| CUDA max reserved | 687,865,856 |
| CUDA device free 最大下降 | 759,169,024 |

公式分别选择 `max(process peak RSS, available RAM drop)` 与
`max(CUDA allocator peak, CUDA free drop)`，再增加 `max(2 GiB, 20%)` headroom，推导下限为 5 GiB RAM / 3
GiB VRAM。Registry 保留更保守的 8 GiB RAM / 6 GiB VRAM，`floors_not_reduced: true`；没有把校准外推到
CPU profile、其他 GPU 或平台。推理前仍须在同一 authoritative `VIREA_HOME` 的 durable lease 内重测当前
可用资源；不同 home/外部进程不互锁，校准与准入都不是“绝不 OOM”保证。

## 负面结果 / 未验证项

- 上述两次 GPU 校准只证明固定 Runtime/epoch 与 80/196 帧请求的资源观测；它们没有 fresh Web observation，
  不能计为 `virea.production_e2e_evidence.v1.1.0`。
- 官方 text-to-motion demo 未实现；Worker 依据已发布 evaluation path 形成单 prompt
  runner，并没有把不存在的 demo 当作来源。
- 未接入 XL（官方 README 没有对应下载项）、raw、Prefix-AR、NoisyPrefix-AR、
  ControlNet 或 mesh；每个变体需要单独权重与合同。
- 历史 v1.0 轮次的 READY installation 为 `01M0H4S4Y1EZ24K83A9A84T7SQ`，acceptance job/result 为
  `01M0H4V95VTXSBNC09D5A4Y916` / `01M0H4VS58ZAXSWNBA77V28S6Y`。
- 同一历史轮次的 manifest-exact job/result 为 `01M0H48K70MFBG3PMM02ZEVQ9J` /
  `01M0H495Q61VDKGFGD6PKW3ZK5`；strict validator 返回 `ok=true`。
- 原生输出为 finite float32 `[80,22,3]`，Canonical 为 `[80,211]`；VRMA 为 86,208 bytes、
  80 帧、3.95 秒、52 rotation + 1 hips translation、rest hips 1.0。
- 真实浏览器载入 Avatar 与该 VRMA 后完整角色可见，console warning/error 为 0。
- 上述历史 v1.0 ID 与浏览器事实不再是当前晋级证据；新的 current-version/current-epoch doctor→install→
  acceptance→fresh Web→v1.1 validator record 尚待生成，本文不预填其 ID。
- HumanML3D/AMASS 数据谱系仍要求部署方审阅适用数据条款。

## 可复现检查清单

```powershell
git ls-remote https://github.com/neu-vi/ACMDM.git HEAD
hf models info cr8br0ze/ACMDM_Flow_S_PatchSize22 --format json
hf models info cr8br0ze/AE_2D_Causal --format json
hf download cr8br0ze/ACMDM_Flow_S_PatchSize22 --revision f7b77ecb16968afb0329a4a706978780843a1fc9 --dry-run
hf download cr8br0ze/AE_2D_Causal --revision 78bbd7fc5ec129a6c74812d542892939261a984f --dry-run
```

当前 evidence 重新有效前还必须在同一次真实事务链中完成：环境检测、资源准入、artifact install、隔离
runtime build/load、非零全有限 `[T,22,3]` 推理、adapter、MotionIR、retarget、VRMA、
fresh 浏览器播放、acceptance/generation Runtime core identity 绑定、取消/重启，以及 checkout 外 wheel 安装。

## 下一步决策

当前决策为 **`integrated_experimental`**。adapter、catalog、release assets、历史真实 E2E 与当前资源校准已完成；
状态只覆盖上述固定 revision、Windows win64 与 RTX 5090 的历史有界技术事实；当前 v1.1 E2E 仍待收口。
其他 GPU、Linux、质量分布和长期回归仍需分别补证，未满足前不得提升为 `supported`。

<!--
type: research-log
status: Validated
owner: "@Joker-of-Gotham"
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: ACMDM 正式源码、权重、数学、80/196 帧资源校准、历史 E2E 与当前 v1.1 重采集边界审计。
canonical: doc/research/acmdm-official-integration-audit-2026-08-21.zh-CN.md
related:
  - doc/model-catalog/first-wave-2026-08-20.zh-CN.md
  - doc/refactor/RELEASE_ACCEPTANCE_0.4.0.md
supersedes: []
superseded_by: []
-->
