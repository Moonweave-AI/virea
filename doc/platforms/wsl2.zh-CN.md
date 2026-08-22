---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: WSL2 作为独立 Linux 执行域时的构建、路径、GPU、状态与浏览器边界。
canonical: doc/platforms/wsl2.zh-CN.md
related:
  - wsl2.en.md
  - README.zh-CN.md
  - windows.zh-CN.md
  - linux.zh-CN.md
  - ../models/prism.zh-CN.md
supersedes: []
superseded_by: []
---

# WSL2

> [中文](wsl2.zh-CN.md) · [English](wsl2.en.md)

WSL2 是独立执行域，不是 Windows Python 的一个 accelerator 标签。doctor、`uv`、模型缓存、隔离环境、Worker
和资源探测必须全部位于同一个发行版。

必须先在目标发行版**内部**按 [Linux 数据根配置](linux.zh-CN.md)完成一次性目录设置。路径提示处只粘贴 Linux
目录本身（例如 `/mnt/virea-data`），外层单/双引号不是路径内容，不能输入。

```bash
# 在选定 WSL 发行版内启动向导；它会检测精确 WSL 域，并在安装前要求选择模型、Runtime 和 profile。
uv run virea
```

## 两种入口

1. 在 WSL 内直接运行完整 VIREA：使用 Linux 安装和 `~/.local/share/virea`。
2. Windows 控制面编排 `wsl:<distro>`：所有构建/Worker 命令经 `wsl.exe -d <distro> --exec ...` 执行，
   VIREA_HOME 使用发行版内路径，Windows 只保存控制和证据索引。

禁止把 `\\wsl.localhost` 或 WSL Python 路径交给 Windows `uv sync`；路径必须由执行域映射器转换并在目标域内
再次验证。

## GPU 与内存

WSL 内用 `nvidia-smi` 与目标 Torch 实际探测 CUDA。Windows 的总显存不能替代 WSL 中的可用显存；WSL RAM
和 swap 限额也必须单独读取。PRISM 的组件拆分策略把文本编码器放在 CPU、Transformer/VAE 放在 CUDA，
因此同时要求 28 GiB free physical RAM、12 GiB free VRAM 与 40 GiB free storage；这些预算不能相加。
CMDM/MoMADiff CPU locks 已在 `wsl:Ubuntu-24.04` 完成构建和隔离 Worker import，但这不是 checkpoint 推理或
browser evidence。

PRISM 是当前唯一完成 WSL production E2E 的模型：`wsl:Ubuntu-24.04` 中的 component-split Runtime 已从
doctor、installation、真实 checkpoint inference 贯通 Motion IR、127,768-byte VRMA 与 fresh browser。该记录
只覆盖 RTX 5090 Laptop GPU + CPU UMT5 placement，不证明其他 WSL 发行版、原生 Linux、CPU-only 或其他 GPU。

## 浏览器

API/Web 可以在 WSL 内监听 loopback 并由 Windows 浏览器访问，也可以由 Windows 控制面代理。E2E 证据必须
记录实际 Worker 执行域与浏览器平台，不能把 Windows 浏览器自动写成 Windows 模型推理。

当前 PRISM registry runner 记录的是 WSL Worker + Windows headless Chromium/WebGL2/SwiftShader；根任务的
独立应用内 Browser 又确认同一 result 在硬件 WebGL2 RTX renderer 下完整可见、mixer 推进且 0 errors。两份
观察不能互相覆盖，也不能改写执行域。

当前 Windows 宿主监督器可以启动并停止 WSL Worker；崩溃后恢复仍只能可靠核验宿主 `wsl.exe` wrapper，
不能把 wrapper PID 冒充发行版内部进程身份。需要恢复遗留 WSL Worker 时应在同一发行版内核验并回收，
在内外身份链完整持久化前不得宣称跨 WSL orphan recovery 已普遍通过。
