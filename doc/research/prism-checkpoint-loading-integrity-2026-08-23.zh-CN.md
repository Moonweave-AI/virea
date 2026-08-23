---
type: research-log
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: PRISM 官方 checkpoint 命名、dtype 安全低内存加载与不可变源码完整性的根因研究。
canonical: doc/research/prism-checkpoint-loading-integrity-2026-08-23.zh-CN.md
related:
  - prism-checkpoint-loading-integrity-2026-08-23.en.md
  - ../models/prism.zh-CN.md
  - ../../plugins/models/prism-tp2m-1-4b/manifest.yaml
supersedes: []
superseded_by: []
---

# PRISM checkpoint 加载与资产完整性研究日志

> [中文](prism-checkpoint-loading-integrity-2026-08-23.zh-CN.md) ·
> [English](prism-checkpoint-loading-integrity-2026-08-23.en.md)

## 研究问题与判定标准

研究问题：VIREA 怎样才能按目标推理 dtype 加载固定的官方 PRISM Transformer 与 VAE，同时不重命名或复制
大权重、不执行整模型 dtype 转换、不联网，并且不修改不可变源码资产？

成功必须同时满足：接受官方精确文件布局；只使用 Safetensors；dispatch 前核验全部 state key 与 tensor
shape；控制构造阶段内存峰值；Windows、Linux、WSL、macOS 行为一致；源码资产完整性树逐字节不变。任何
pickle 回退、隐藏资产改写、忽略完整性路径或未校验 state mismatch 都判定失败。

## 固定证据

| 证据 | 固定事实 | 工程含义 |
|---|---|---|
| [PRISM 论文](https://arxiv.org/abs/2603.08590) | 模型由 1.4B Kinematic-Unit Flow Transformer 与 causal Motion VAE 组成。 | 两个组件 checkpoint 都是模型身份，不是可省略缓存。 |
| [官方 loader](https://github.com/ZeyuLing/PRISM/blob/3c58bc5d946f0827171a3712ed36314f4b1a5186/prism/pipelines/prism_from_pretrained.py) | `_load_state_dict_from_dir` 明确加载 `model.safetensors`；VAE 分支还注明 Diffusers 期待 `diffusion_pytorch_model.safetensors`。 | 对官方目录直接调用 Diffusers `from_pretrained` 与固定布局不兼容。 |
| [官方模型 snapshot](https://huggingface.co/ZeyuLing/PRISM-TP2M-1.4B/tree/825daaa27f4f3845eb0978674c3acb378a12cda6) | `transformer/model.safetensors` 为 5,675,480,768 bytes，`vae/model.safetensors` 为 69,661,320 bytes。 | 不能只为适配库文件名规则而重命名或再复制 5.68 GB Transformer。 |
| [Diffusers 模型布局参考](https://huggingface.co/docs/diffusers/v0.31.0/en/using-diffusers/loading) | 标准组件权重名为 `diffusion_pytorch_model.safetensors`。 | 缺文件是确定性的命名解析问题，不是下载损坏。 |
| [Accelerate 大模型接口](https://huggingface.co/docs/accelerate/main/en/package_reference/big_modeling) | `init_empty_weights` 与 `load_checkpoint_and_dispatch` 接受直接 checkpoint 文件和 device map。 | 可通过公开接口按目标 dtype 加载官方单个 Safetensors，而无需先分配完整默认精度模型。 |

Runtime 依赖证据为 `diffusers==0.39.0`、`accelerate==1.14.0`、`safetensors==0.8.0`、Python 3.11，官方
源码与模型 revision 如上。实际失败 installation 为 `01M0QHJ0Z6RMYE95RP6C4G58SJ`；Worker readiness 前因
loader 查找标准 Diffusers 文件名而退出。

## 发现与负面结果

Runtime 0.1.4 是一次负面结果：它正确地把 dtype 选择移入库加载阶段，却错误假设官方 checkpoint 使用
Diffusers 标准组件文件名，结果消除了 dtype 警告、同时引入确定性的 missing-file 失败。此前 dtype 警告并非
终止 exception。

源码完整性失败是独立根因。若未禁用 bytecode，CPython 会在导入源码旁写入 `__pycache__/*.pyc`。Windows
read-only 目录模式不具备预期的 POSIX 目录写保护，因此导入 PRISM 后可能在已持久化 SHA-256 树之外新增文件。
忽略完整性树中的 bytecode 路径会削弱不可变资产合同，故被否决。

## 工程决策

Runtime 0.1.5 只允许 `model.safetensors` 与 `diffusion_pytorch_model.safetensors` 中恰好一个存在；本地加载
组件 config，在 meta device 构造空骨架，对比 checkpoint 与模型的全部名称和 shape，再由 Accelerate 按目标
dtype 加载并 dispatch 该直接文件。双文件歧义、缺文件、unexpected/missing key、shape mismatch、残留 meta
tensor 与仅 pickle checkpoint 全部失败关闭。

Worker supervisor 对原生域和 WSL 路由域统一强制 `PYTHONDONTWRITEBYTECODE=1`；PRISM loader 还在第一次
导入固定源码前设置 `sys.dont_write_bytecode`。完整性哈希仍然精确；树不一致诊断现在列出有界 added、missing、
changed 路径，可区分生成的 bytecode 与权重损坏。

## 可复现证据与边界

自动化证据覆盖两个受支持 Safetensors 文件名、真实 Diffusers `ModelMixin`、目标 dtype dispatch、shape
mismatch 拒绝、无 bytecode 源码导入、受控 Worker 环境、registry/version 一致性和完整性树路径诊断。
当前仓库设备没有 32.7 GB 外部 snapshot 与目标 GPU，不能在此执行完整 Windows 真实 checkpoint inference；
新 Runtime 仍需在用户设备执行 fresh installation acceptance。资产 revision 未变，checkpoint、tokenizer、
statistics 都会复用；此前已被污染的小型源码资产可能被隔离并重新获取一次。

决策：以 Runtime 0.1.5 把兼容性与不可变性修复推进到工程阶段；fresh 真实 checkpoint acceptance 通过前继续
保持 `integrated_experimental`。
