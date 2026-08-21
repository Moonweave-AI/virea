# VIREA 0.4 多模型生产化工程简报

> 状态：Implemented（六模型工程切片已落地；当前 v1.1 E2E 重采集 pending；公开 GA 仍 No-Go）
> 日期：2026-08-21
> 风险与质量：S3 / QA-L4
> 范围：目录与资源治理、运行时资源准入、多模型身份、首批真实模型接入、跨平台交付

## 1. 背景与裁决

VIREA 0.4 曾让 FloodDiffusionTiny、MoMADiff、MARDM、ACMDM 与 CMDM 在 Windows native、PRISM 在
`wsl:Ubuntu-24.04`，分别从环境探测、正式权重安装、隔离 Worker 和真实推理贯通 Motion IR、Canonical
211、VRMA 与 fresh 浏览器播放；这些旧 validated evidence / validator v1.0 现已失效，当前 v1.1 六链必须
重采集。开发环境、模型缓存、日志、pytest 临时目录和
fresh-install 证据已与 checkout 分离；RuntimeSpec 也已能用独立的显存、物理内存、交换空间和磁盘预算
选择经过 Worker 实现与实测的资源策略。

本轮采用以下不可变裁决：

1. 仓库只保存源代码、轻量注册表、锁文件、测试和文档；环境、权重、日志、结果、缓存及验收工作区一律写入
   `VIREA_HOME` 或操作系统临时目录。
2. RAM 不能抽象地等价为 VRAM。只有某个 Worker 明确实现并真实验收了 offload 策略，解析器才能用可用 RAM
   补足该策略的显存需求；否则显存不足必须在下载前拒绝。
3. 模型、原生骨架、原生表示、目标骨架和目标表示必须作为不同身份维度保存，不能仅靠展示名称推断。
4. `registered` 不声明可运行；`runnable_upstream` 表示固定上游可执行但尚未完成并登记要求的 VIREA
   production E2E，期间可以已有部分 managed Runtime/Worker。只有真实官方权重完成全链验收才能晋级
   `integrated_experimental`。`supported` 仍需跨机型、跨系统与持续回归证据。
5. 用户所指 PRISM 规范为 2026 年的 *PRISM: Streaming Human Motion Generation with Per-Joint
   Latent Decomposition*。只把论文 v3 指向的 `ZeyuLing/PRISM` 与 `PRISM-TP2M-1.4B` 视为正式来源；
   Motius PRISM-KT 是不同实现，不能冒充论文正式发布。内部网络表示为 138D；控制面公开 69D / SMPL-H
   body-22 / 30 FPS axis-angle carrier。tokenizer 与 stats 使用独立固定正式来源，生成不要求 SMPL geometry；
   许可未声明继续禁止 VIREA 再分发外部源码/权重，但不再被解释成技术不可运行。

## 2. 目标与非目标

### 2.1 目标

- 删除运行时对 checkout 当前目录的隐式依赖，并清理由 VIREA 生成的根目录环境、缓存和日志。
- 将 Flood Worker 的轻量源码迁入 `plugins/models/flood-diffusion-tiny/runtime/`，模型权重与虚拟环境仍放在
  `VIREA_HOME`；删除已退役的根级 Flood 独立包。
- 在安装下载前完成平台、Python、驱动、可用显存、可用内存、交换空间和磁盘准入，并选择一个模型声明的
  可执行内存策略。
- 首批形成六个真实模型闭环；优先 2025–2026，同时保留一个资源要求较低的降级选项。
- 让 CLI、API、Web 和结果制品明确显示 `model + native skeleton/representation -> target
  skeleton/representation`。
- 提供 Windows、Linux/WSL、macOS 的能力分级和可执行修复建议，而不是笼统声称全平台支持。

### 2.2 非目标

- 不通过合成张量、空 Worker、固定输出或客户端自报来证明模型已接入。
- 不为了统一接口而改变上游模型的采样、扩散、流匹配、VAE 或旋转数学。
- 不把未经实现验证的统一内存池、自动量化或任意 CPU fallback 写成能力。
- 不在许可不明时复制 PRISM 等第三方源码或权重到发布 wheel。
- 不把同一模型的 checkpoint variant 重复计算为多个独立模型。

## 3. 领域模型与命名

### 3.1 模型身份

模型选择键保持稳定、机器可读：

```text
model_id              prism-tp2m-1-4b
model_version         0.1
runtime_variant_id    prism-tp2m-1-4b-cu128-component-split
native_skeleton_id    smplh.body22.v1
native_representation prism.smplh_body22.axis_angle69.v1
target_skeleton_id    vrm1.humanoid52.v1
target_representation virea.canonical211.v3
```

展示标签由上述字段生成，例如：

```text
PRISM TP2M 1.4B · SMPL-H Body22 / AxisAngle69 @ 30fps → VRM Humanoid52
```

Result 的不可变 ID 继续使用 ULID；可读身份进入版本化 `identity` 字段和导出文件名，不编码进数据库主键。
推荐导出名：

```text
<model-id>__<native-skeleton>__to__<target-skeleton>__<result-id>.vrma
```

### 3.2 结果身份

`ModelResult` 与 `VrmMotionResult` 必须至少记录：

- model id/version、runtime variant、checkpoint revision；
- native skeleton/representation/fps；
- Motion IR/canonical skeleton/representation；
- avatar/retarget profile 与每 actor export；
- 实际选择的 memory strategy 和运行设备。

注册表、Worker metadata、ModelResult、Motion IR、VrmMotionResult 和 Web 展示必须交叉一致；任何悬空或漂移
均 fail closed。

## 4. 生产目录不变量

### 4.1 Checkout 允许内容

- `apps/`、`packages/`、`plugins/`、`registries/`、`src/`、`tests/`、`doc/`、`scripts/`；
- 锁文件、构建声明、轻量静态 Web 资源；
- 不含 `.venv*`、模型权重、Hugging Face cache、日志、SQLite、结果、Worker job root、pytest basetemp、
  fresh-install wheelhouse 或浏览器验收截图。

### 4.2 运行数据布局

所有写入通过 `VireaHome`：

```text
VIREA_HOME/
  runtimes/<runtime-variant>/environment/
  model-store/blobs/by-source/
  model-store/manifests/
  model-store/snapshots/<installation-id>/
  model-store/refs/
  cache/huggingface/
  logs/<service-or-job>/
  jobs/<job-id>/
  results/<result-id>/
  tmp/
  machine/reports/
```

pytest 使用系统临时目录或显式的外部目录；注释 sidecar 缓存进入 `VIREA_HOME/cache/annotations`。生产代码不得
扫描 `Path.cwd()` 猜测 runtime、Python 或模型位置。

### 4.3 迁移与清理

先将唯一真实验收证据和可复用权重移动到 checkout 外的受控目录，再删除可再生成的测试目录。根级 Flood 包
只迁移 `src/`、`pyproject.toml`、`uv.lock` 和必要说明；`.venv/`、`runtime/`、下载缓存绝不进入 plugin。
清理操作仅针对经过绝对路径校验的已知直接子目录，并记录是否可恢复。

## 5. 资源准入与内存策略

### 5.1 机器报告

安装前报告以下实时值，而不是只记录总量：

- GPU 型号、compute capability、驱动/ABI、总显存与可用显存；
- 总物理内存、可用物理内存、swap/pagefile 可用量；
- runtime 与 model-store 所在卷的可用磁盘；
- 可获取 Python、构建工具和平台架构。

### 5.2 Runtime memory profile

每个 runtime variant 声明一个或多个已经实现的 profile：

```yaml
# CMDM/MoMADiff 的 CUDA RuntimeSpec
resource_profiles:
  - id: cuda
    strategy: cuda_full
    min_free_vram_gib: 6
    min_free_ram_gib: 8

# 独立 CPU RuntimeSpec；不是修改 CUDA lock 的设备字符串
resource_profiles:
  - id: cpu
    strategy: cpu
    min_free_ram_gib: 12
```

声明 profile 不等于支持。Worker 必须消费选择结果并按相同策略加载；production acceptance 必须记录并
验证实际设备放置。不存在可行 profile、RAM/VRAM 任一不足或 Worker 不认识该 profile时，安装必须在网络
下载和环境构建前终止。

磁盘准入需覆盖权重、环境、下载临时文件和原子发布的峰值；不得用 pagefile 代替物理内存最低值。允许 swap
只能作为附加 headroom，且必须明确性能降级。

### 5.3 状态

```text
DETECTED -> BUILDABLE(profile selected) -> DOWNLOADING -> BUILDING_RUNTIME
         -> LOADING_MODEL -> ACCEPTANCE_TESTING -> READY
```

任何实时资源变化都可在 `DOWNLOADING` 前或 Worker 启动前再次将任务转为 `RESOURCE_REJECTED`；旧的有效
READY 安装不能因一次失败重试而下线。

推理前重测由同一 authoritative `VIREA_HOME` 的 ControlPlane 在 durable resource lease 内完成，并发生在
spawn Worker 之前。租约协调共享该 home 的 VIREA 进程，不协调其他 home 或无关外部进程；观测后资源仍可
变化，因此它缩小竞争窗口但不提供机器全局“绝不 OOM”保证。租约覆盖 spawn→attest→load→infer→unload→
proven exit；无法证明 Worker 退出时保持 fail closed。

## 6. 当前六模型收口名单

最终名单以当前 manifest、正式制品、许可和真实推理结果为准，不以登记数量凑数。当前六个
`integrated_experimental` 是 FloodDiffusionTiny、MoMADiff、MARDM、ACMDM、CMDM 与 PRISM；前五个只覆盖
Windows native，PRISM 只覆盖 `wsl:Ubuntu-24.04`。SentiAvatar、MoMask 等研究条目不借用这六条链，仍按
各自 manifest 状态处理。

PRISM 的工程准入约束：正式代码固定到 `ZeyuLing/PRISM@3c58bc5d946f0827171a3712ed36314f4b1a5186`，
正式权重固定到 `ZeyuLing/PRISM-TP2M-1.4B@825daaa27f4f3845eb0978674c3acb378a12cda6`；完整
snapshot 的 9 个文件共 32,669,418,445 bytes（约 30.42 GiB）。上游内部 138D 经正式 processor/root
rollout 后，Worker 公开 `[T,69]`、SMPL-H body-22、30 FPS carrier。tokenizer 固定到 `google/umt5-xxl`，
statistics 固定到 MotionHub；既有实机部署验证 UMT5 CPU、transformer/VAE CUDA 的 component-split。
该 profile 的安装前独立下限是 12 GiB free VRAM、28 GiB free physical RAM 和 40 GiB free storage；
28 GiB 由 25.075 GiB UMT5 文件及此前 31.063 GiB WSL 成功部署校准。fresh managed E2E 记录了加载前
available 32,463,986,688 bytes；加载后 available 20,110,942,208 bytes、RSS 12,612,476,928 bytes；推理后
available 19,152,322,560 bytes、RSS 13,683,249,152 bytes；VmHWM 31,703,216,128 bytes。这里没有 GPU
allocation peak 记录，不能把 RAM VmHWM 或 GPU 总量写成 GPU peak，也不能把 RAM/VRAM 相加。
managed Runtime 只引用用户显式接受的外部资产，不在 VIREA wheel 发布源码或权重。PRISM 控制面有历史
doctor→browser 全链，但当前 v1.1 record 尚未登记；许可边界也不因技术运行解除。

ACMDM 的 Win64 / RTX 5090 校准覆盖 Runtime `0.1.3`、core epoch `virea-runtime-core-20260821.2`、80 帧
production acceptance 与 196 帧 manifest maximum。观测基准取 process RSS 与 system available drop 的较大
值、CUDA allocator/free drop 的较大值，再加至少 2 GiB headroom，推导 5 GiB RAM / 3 GiB VRAM；登记下限
仍保留 8 GiB / 6 GiB，且不外推其他 GPU/平台。资源校准没有 fresh browser observation，不替代 v1.1 E2E。

## 7. 接口与执行流

```text
doctor
  -> detect live resources
  -> resolve model/runtime/memory profile
  -> install official artifacts + isolated runtime
  -> probe built runtime and actual device placement
  -> load real checkpoint
  -> run manifest-authoritative real inference
  -> validate native shape/fps/skeleton/finite values
  -> adapter -> Motion IR -> canonical -> retarget -> VRMA
  -> result identity + artifacts
  -> Web load and visible playback
```

ControlPlane 不再按单一 HumanML adapter 硬编码；每个 model plugin 提供版本化 input binding、Worker contract、
adapter binding 和 acceptance contract。安装 locator 必须显式传入 Worker；Worker 不得从 cwd 猜权重。

## 8. 平台能力分级

- Tier A：在明确 execution domain 的实体机器上完成全链真实验收；可以标 `integrated_experimental`。
- Tier B：安装、runtime probe 与官方最小推理通过，但最终 Web/长序列证据不足；不得标完整集成。
- Tier C：固定上游可运行，或 VIREA 只有部分 adapter/Runtime/迁移证据而未完成当前 production E2E；保持
  `runnable_upstream`。
- Blocked：许可证、制品、资源或依赖不满足；安装前给出明确原因与替代模型/profile。

Windows、WSL、原生 Linux、macOS/Apple Silicon、NVIDIA/CPU/MPS/ROCm 均独立计 tier；一个平台成功不
外推到其他平台。五模型 Windows native 和 PRISM WSL Ubuntu 24.04 的 manifest Tier A 状态来自此前有界
实测；当前 v1.1 release evidence 仍待重采集。原生 Linux/macOS 仍未完成 production E2E。macOS 不得选择
CUDA runtime，旧 CUDA 扩展模型也不得在 Blackwell 上按上游老锁直接安装。

## 9. QA-L4 证据

每个晋级模型必须保存同一次事务的：

1. 不含目标框架的干净环境探测与 buildable 决策；
2. 安装前资源报告和被选择的 memory profile；
3. 官方 revision 与完整 expected-files 验证；
4. 隔离 runtime 的实际 Python/framework/device/ABI probe；
5. 非零、全有限、符合原生 shape/fps 的真实推理输出；
6. ModelResult、Motion IR、canonical 与 retarget 的交叉身份；
7. 每 actor VRMA 的 glTF/VRMC 结构、rest hips 和 root translation 数值验证；
8. 浏览器真实载入、动画时间推进、完整 Avatar 可见、console 零错误的外部证据；
9. acceptance 与 fresh generation 的 Runtime project/version/core epoch、已安装 contracts/model-sdk identity
   完全一致，并绑定当前 Web 0.4 hashed JavaScript body；
10. cancel、timeout、进程树回收、control-plane restart、旧 READY 回退；
11. sdist -> wheel -> 离线安装 -> checkout 外运行。

合成 tensor 只可用于数学回归；不能满足上述任何真实模型晋级门。用户客户端提交的布尔字段不能自证 Web
播放。

## 10. 回滚与完成条件

目录迁移采用可回滚的添加式阶段：先让新 plugin runtime 与外部 VIREA_HOME 路径通过全链，再删除根级包和
旧定位兼容；旧路径仅允许给出迁移错误，不得静默继续使用。资源 schema 采用向后可读、向前 fail-closed；没有
memory profile 的旧真实 runtime 不能安装。

目录治理、资源准入、结果身份和六个模型实现满足对应工程切片；旧 v1.0 六条 fresh 链已失效，当前 v1.1
有效 `passed = 0`。新记录必须写入本轮实际 collection provenance；历史 dirty workspace、
`source_revision: null`、`release_artifact_verified: false` 不能复制成当前事实，也不能把技术 source-candidate
当成冻结 release artifact。跨机型、跨系统、许可和持续质量证据仍不足，因此 `supported` 为 0，公开 GA
不能据此放行。

最终完成条件仍包括 frozen-tree full suite 与 fresh artifact 重跑、项目代码 LICENSE、PRISM 许可、
SentiAvatar MTA63 CC BY-NC、Showcase 页已全部内联的 16 个指定 GIF 权限、CMDM 许可链接 caveat、托管 CI 和生产 SLO/部署后验证。2026-08-21 的
164633 packaging run 只证明机制，并因含旧 Web 0.3 品牌而被后续源码状态取代。

<!--
type: engineering-brief
status: Implemented
owner: "@Joker-of-Gotham"
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 14
summary: VIREA 多模型生产化的目录治理、同 home 资源租约、结果身份、六模型 v1.1 evidence 重采集与发布边界。
canonical: doc/refactor/ENGINEERING_BRIEF_0.4_MULTI_MODEL_PRODUCTION.md
related:
  - doc/refactor/RELEASE_ACCEPTANCE_0.4.0.md
  - doc/refactor/QA_PLAN.md
  - doc/model-catalog/first-wave-2026-08-20.zh-CN.md
supersedes: []
superseded_by: []
-->
