---
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-22
last_reviewed: 2026-08-22
review_cycle_days: 14
summary: Windows、Linux、WSL2、macOS 的统一执行域选择、Runtime 能力与观测证据边界。
canonical: doc/platforms/README.zh-CN.md
related:
  - windows.zh-CN.md
  - linux.zh-CN.md
  - wsl2.zh-CN.md
  - macos.zh-CN.md
  - ../reference/status-semantics.zh-CN.md
supersedes: []
superseded_by: []
---

# 平台与执行域

VIREA 的产品目标是 Windows、Linux、WSL2 与 macOS，而不是“只在 Windows 运行，其他平台提前拒绝”。
模型、checkpoint 与版本身份不属于某个操作系统；execution domain 只决定隔离 Runtime、路径视图、资源域
和加速后端。实现通过域边界保证探测、构建、Worker、租约和进程生命周期处于同一个操作系统环境。

| 可选择的 execution domain | 命令 / 文件系统 / 资源边界 | 文档 |
|---|---|---|
| `windows-native` | Windows native 进程、路径与资源观测 | [Windows](windows.zh-CN.md) |
| `wsl:<distribution>` | Windows 宿主编排的指定 WSL distribution，或 VIREA 完整运行于该 WSL | [WSL2](wsl2.zh-CN.md) |
| `linux-native` | 原生 Linux 进程、路径与资源观测 | [Linux](linux.zh-CN.md) |
| `macos-native` | macOS native 进程、路径与资源观测 | [macOS](macos.zh-CN.md) |

## 启动与选择流程

1. 启动时检测全部当前可达的 execution-domain candidates；检测只描述机器事实，不下载模型。
2. 客户端按所选模型展示每个域内声明的 Runtime/profile，以及暂不可用的精确原因。
3. 用户在下载、构建或启动 Worker 前选择 canonical domain ID；有多个候选时不得静默 native-first。
4. VIREA 复用同一份 OS-neutral `ModelAssetSnapshot`，仅在首次需要时懒构建或复用所选域的 Runtime
   deployment；选择新域不重复安装或下载模型资产。
5. 安装、Job、资源租约、Worker 与结果持久化同一选择，并在 spawn 前于同一域完成最终资源重测。

公共选择对象是 `ExecutionTargetSelection`：JSON 必填
`execution_target.execution_domain_id`，高级用户可选
`execution_target.runtime_variant_id` 与 `execution_target.resource_profile_id`。显式选择失败时必须保留
用户意图并返回该域的模型级阻断原因，不得静默切换到另一 OS、Runtime、accelerator 或 profile。

CLI 的真实选择参数为：

```bash
uv run virea model install MODEL --execution-domain DOMAIN [--runtime RUNTIME] [--resource-profile PROFILE]
uv run virea model repair MODEL --execution-domain DOMAIN [--runtime RUNTIME] [--resource-profile PROFILE]
uv run virea generate --model MODEL --execution-domain DOMAIN [--runtime RUNTIME] [--resource-profile PROFILE]
```

`--runtime` 与 `--resource-profile` 是高级覆盖项，使用时必须同时提供 `--execution-domain`。Web 选择器与 API
提交同一对象；任何表面都不得在失败后换域。

## 能力、阻断与证据是三张表

- **Selectable execution domains / declared Runtime capability** 来自 detector 与 RuntimeSpec：只回答哪个域
  被检测到、Worker 实现了哪些 ABI/profile。manifest 的自由文本 `availability` 不得被渲染成支持能力。
- **Known deployment blockers** 只来自结构化的 model/platform/stage blocker：回答某个已声明选项为何不能
  READY。空列表不等于真实推理或平台验收通过。
- **Observed evidence coverage** 只回答某个明确模型、域、accelerator 与验证范围已经被记录过什么；
  target-level 状态不得扩散给同一平台 ABI 的整行模型，证据也不参与候选域选择或排序。

缺少观测记录表示“待该配置实测”，不能改写为 OS 不受支持；缺少 Runtime 实现则是必须明确展示的模型级
能力缺口。六个 integrated 模型现在都声明并锁定了覆盖 `win-64`、`linux-64`、`osx-arm64` 与 `osx-64`
的 whole-model CPU Runtime。ACMDM、MARDM、FloodDiffusionTiny 与 PRISM 的新 CPU variant 目前只通过
合同/import/lock 基线，真实 CPU model load/infer 与原生 Linux/macOS observation 仍为空；PRISM 使用
96 GiB 保守 fail-closed RAM floor。当前没有登记结构化 portability blocker，但这不等于全平台完成。
项目仍不能宣称“任意模型已经在所有平台运行”，也不能用某次 Windows/WSL 观测把模型永久绑定到那个系统。

旧 validated evidence / validator v1.0 已失效；当前 record 的有效性、ID 与 promotion 结论只以 production
evidence registry 为准。历史或后续单域记录不得外推到原生 Linux、macOS、其他 GPU、CPU、ROCm、MPS
或多 GPU 配置。

## 所选域内的统一准入顺序

1. 在目标执行域内探测 OS、架构、Python、驱动、设备、可用 VRAM、可用 RAM、swap/pagefile 和磁盘。
2. 按模型声明的有序资源 profile 选择一个完整策略；不同内存池不相加。
3. 在下载权重前拒绝确实不可满足的策略，且不创建安装事务或缓存。
4. 构建隔离 Runtime 后，在同一解释器中复验 framework、ABI、设备和模型加载能力。
5. 同一 authoritative `VIREA_HOME` 的 ControlPlane 取得 durable resource lease 后，在 spawn Worker 前重测
   实时资源；不满足时拒绝启动并释放可安全释放的租约。

该协调边界只覆盖共享同一个 `VIREA_HOME` 的 VIREA ControlPlane/Worker。不同 `VIREA_HOME` 实例和无关的
外部进程不会进入同一互斥；观测后资源仍可能变化，因此租约与重测降低同域竞争窗口，但不是机器全局的
“绝不 OOM”保证。Worker 隔离、失败状态与进程回收负责约束故障影响，不能被写成资源永远充足。

自动生成的 [执行域 / Runtime / 阻断 / 观测矩阵](support-matrix.generated.md) 已按上述三条轴分栏；它只展示
事实源中的声明、结构化 blocker 与明确 model-scoped observation，不代替 production evidence registry
的有效性裁决。
