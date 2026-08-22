---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: Windows native 执行域的外部环境、资源探测、CUDA/CPU 路径和故障恢复。
canonical: doc/platforms/windows.zh-CN.md
related:
  - windows.en.md
  - README.zh-CN.md
  - wsl2.zh-CN.md
  - ../getting-started/installation.zh-CN.md
supersedes: []
superseded_by: []
---

# Windows

> [中文](windows.zh-CN.md) · [English](windows.en.md)

## 推荐目录

生产状态默认位于用户数据目录。源码开发时也把 uv 环境放到 checkout 之外：

```powershell
# 将 uv 开发环境放到 checkout 外。
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\VIREA\dev-venv"
# 指定 checkout 外状态目录。
$vireaHome = "$env:LOCALAPPDATA\VIREA\home"
# 按锁文件安装 Python workspace。
uv sync --locked --all-packages --extra dev
# 初始化外部状态目录。
uv run virea setup --virea-home $vireaHome
# 探测 Windows native 执行域、资源和可修复问题。
uv run virea doctor --json --record --explain --repair-plan --virea-home $vireaHome
```

不要在仓库根目录创建 `.venv`、权重缓存、日志或 job。模型安装器会在下载前分别检查可用显存、物理内存、
pagefile 和磁盘。

## CUDA 与 CPU

- NVIDIA Runtime 只在目标隔离 Python 的 Torch/ABI/compute capability 复验成功后标记 ready。
- 支持 `cpu` 的模型可以在 CUDA profile 资源不足时选择 whole-model CPU；没有实现 CPU/offload 的模型不会
  把 RAM 假装成 VRAM。
- CMDM 与 MoMADiff 的独立 CPU locks 已在 Windows 完成构建和隔离 Worker import；这只证明 Runtime 可构建，
  不等于 CPU checkpoint inference 或 doctor→browser 已通过。
- Windows 宿主需要运行 Linux Runtime 时使用 [WSL2 执行域](wsl2.zh-CN.md)，不得把 WSL Python 路径交给
  Windows `uv`。

## 恢复

`virea support` 输出诊断摘要；`virea state inspect` 查看状态；`virea model verify <model-id>` 重新验证
READY snapshot。强制终止后，控制面会按进程创建身份、可执行文件和完整参数核验孤儿 Worker，身份不匹配时
绝不误杀。
