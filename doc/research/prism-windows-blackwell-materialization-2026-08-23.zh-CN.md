---
type: research-log
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: PRISM Runtime 0.1.5 在 Windows Blackwell checkpoint materialization 阶段原生崩溃的根因研究。
canonical: doc/research/prism-windows-blackwell-materialization-2026-08-23.zh-CN.md
related:
  - prism-windows-blackwell-materialization-2026-08-23.en.md
  - ../models/prism.zh-CN.md
  - ../../plugins/models/prism-tp2m-1-4b/manifest.yaml
supersedes:
  - prism-checkpoint-loading-integrity-2026-08-23.zh-CN.md
superseded_by: []
---

# PRISM Windows Blackwell materialization 研究日志

> [中文](prism-windows-blackwell-materialization-2026-08-23.zh-CN.md) ·
> [English](prism-windows-blackwell-materialization-2026-08-23.en.md)

## 研究问题与判定标准

为什么 PRISM Runtime 0.1.5 在 Windows 原生 RTX 5070 Ti 加载 Transformer 时，紧随 Safetensors 缺少 metadata
警告后以 `3221225477`（`0xC0000005`）终止？怎样才能避开该 native 边界，同时不复制 5.68 GB checkpoint、
不削弱 state 校验？

成功必须满足：官方 archive 保持不变；不使用 pickle、联网、整份 checkpoint 直接装入 CUDA、Accelerate
checkpoint dispatch 或整模型 dtype 转换；完整核验 key/shape；每次只 stage 一个 tensor；Windows、Linux、WSL、
macOS 的 CPU 语义一致；若其他 native 依赖仍终止，必须留下可操作诊断。

## 固定证据

| 证据 | 固定事实 | 工程含义 |
|---|---|---|
| [PRISM 官方 snapshot](https://huggingface.co/ZeyuLing/PRISM-TP2M-1.4B/tree/825daaa27f4f3845eb0978674c3acb378a12cda6) | 只读取 header 得到 Transformer 1,418,849,296 个 F32 参数、VAE 17,408,758 个 F32 参数，二者 metadata map 均为空。 | 警告不代表 tensor 数据损坏；需要 dtype 转换，但格式 metadata 不是模型身份。 |
| [Safetensors 格式](https://github.com/huggingface/safetensors/blob/main/README.md#format) | `__metadata__` 是允许出现的特殊 key；archive 必需结构是 tensor dtype、shape 与 offsets。 | 缺少可选 map 不能被视为终止错误。 |
| [Accelerate 1.14 loader](https://github.com/huggingface/accelerate/blob/v1.14.0/src/accelerate/utils/modeling.py) | 单设备 map 会调用 `safe_load_file(checkpoint, device=target)`，再通过 Accelerate 工具 materialize meta 参数。 | Runtime 0.1.5 进入了整文件直达 CUDA 与上游 dispatch/materialization 边界。 |
| [Accelerate Blackwell 崩溃报告](https://github.com/huggingface/accelerate/issues/3933) | Windows Blackwell `sm_120` 上，直接 Safetensors 加载和手动 CPU→GPU 成功，`device_map` materialization 却无 Python traceback 原生终止。 | VIREA 的 PRISM 单设备组件不能继续使用该 dispatch 路径。 |
| [PyTorch 已 triage 崩溃](https://github.com/pytorch/pytorch/issues/175614) | 对应 Windows/CUDA hard crash 仍作为上游 open issue 跟踪。 | 目前不能把简单升级依赖声称为已验证修复。 |

观测条件为 Runtime 0.1.5、Windows 原生 CUDA 12.8、Python 3.11、Accelerate 1.14.0、Safetensors 0.8.0、
16 GB RTX 5070 Ti 与 64 GB 系统 RAM。Worker 在 readiness 期间、inference 之前退出。

## 发现与负面结果

metadata 内容只是最后成功 flush 的警告，不是根因。Accelerate 输出警告后会补成 `format=pt` 并继续。VIREA
传入单项 CUDA device map，因此 Accelerate 先把完整 F32 archive 直接加载到 CUDA，再逐项 materialize meta
parameter。上游 Windows/Blackwell 报告呈现相同的 native termination，且没有 Python exception。

因此 Runtime 0.1.5 是第二次负面结果：它的 state 校验正确，但 dispatch 机制跨入了本地 CPU contract test
没有覆盖的上游 native 边界。重复重试同一路径不能建立可靠性，故被否决。

## 工程决策

Runtime 0.1.6 保留 meta-device 构造和精确 Safetensors key/shape 核验，但完全移除 Accelerate checkpoint
dispatch。archive 只在 CPU 打开；每次获取一个已验证 tensor，浮点 tensor 在最终阻塞传输时转换为目标推理
dtype，再把 parameter 或 persistent buffer 直接安装到选定设备；整数与 Boolean buffer 保持源 dtype。最后核验
不存在 meta tensor、错误 device 或错误浮点 dtype，并在 readiness 前同步 CUDA。

所有 Worker 强制 `PYTHONFAULTHANDLER=1`。Supervisor 能识别 Windows exception `0xC0000005` 的有符号与
无符号形式，持久化可读的 native access violation 描述，并保留有界 stdout/stderr 尾部。

## 可复现证据与边界

自动化证据使用真实 Diffusers `ModelMixin` 和无 metadata Safetensors，覆盖两个允许文件名、archive 只经 CPU
访问、浮点 dtype 转换、整数 buffer 保留、完整 state 校验，并显式断言绝不调用 Accelerate checkpoint
dispatch。合并前还必须通过 Runtime/registry/lock、Worker 环境、退出码分类、文档和仓库回归。

CUDA contract test 还在 Windows、RTX 5090 Laptop GPU（`sm_120`、24,463 MiB）、NVIDIA driver 610.74、
Python 3.11 与锁定 PyTorch 2.11.0+cu128 上实际运行：把一个无 metadata 的 4,096 × 4,096 F32 linear
checkpoint 经 CPU 自有 staging 转成 CUDA bfloat16，保留 persistent/non-persistent buffer，同步 CUDA 并完成
finite GPU forward；该环境下 11 项 Runtime test 全部通过。这是替代边界的直接 Blackwell 证据，不是外部完整
PRISM checkpoint 的证据。

当前 workspace 没有 32.7 GB 外部 snapshot 与报告中的 GPU，因此仍需在报告设备上执行 fresh Windows
Blackwell checkpoint acceptance；registry 继续标记 `requires_reacceptance`。任何软件都不能诚实保证未来所有
driver、native library、OS build、硬件 revision 与模型永不出错；工程上必须移除已知危险路径，并让每个声明
target 在失败时关闭且保留证据。

决策：以 Runtime 0.1.6 推进有界 materialization 修复，继续保持 `integrated_experimental`，复用未改变的已验证
资产，并在 fresh 真实 checkpoint acceptance 通过前不提高支持证据等级。
