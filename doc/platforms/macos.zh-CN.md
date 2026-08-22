---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: macOS native 的外部环境、Apple Silicon MPS/CPU Runtime 和进程生命周期要求。
canonical: doc/platforms/macos.zh-CN.md
related:
  - macos.en.md
  - README.zh-CN.md
  - ../getting-started/installation.zh-CN.md
supersedes: []
superseded_by: []
---

# macOS

> [中文](macos.zh-CN.md) · [English](macos.en.md)

```bash
# 选择已挂载且容量充足的数据卷；将 /Volumes/VIREA 换成实际卷。
export VIREA_DATA_ROOT="/Volumes/VIREA/virea"
# 将 uv 开发环境放到 checkout 与系统卷之外。
export UV_PROJECT_ENVIRONMENT="$VIREA_DATA_ROOT/dev-venv"
# 将 uv 的下载与构建缓存也放到所选数据卷。
export UV_CACHE_DIR="$VIREA_DATA_ROOT/uv-cache"
# 将模型资产、Runtime、下载、日志和结果放到所选数据卷。
export VIREA_HOME="$VIREA_DATA_ROOT/home"
# 按锁文件安装 Python workspace。
uv sync --locked --all-packages --extra dev
# 初始化外部状态目录。
uv run virea setup --virea-home "$VIREA_HOME"
# 探测 macOS native 域、资源和可修复问题。
uv run virea doctor --json --record --explain --repair-plan --virea-home "$VIREA_HOME"
```

Apple Silicon 的 MPS、Apple/Intel CPU 与 CUDA Runtime 是不同构建。只有 Worker 明确实现 MPS 或 CPU 路径时，
解析器才会选择它；不能加载 cu128 wheel 后把设备名改为 `mps`。

macOS 没有 Linux `/proc`。Worker 身份、孤儿恢复和进程树终止必须使用 Darwin 原生进程信息，并在 PID、创建
时间、可执行文件和完整参数无法同时核实时 fail closed。平台路径完成实现但未取得实机证据时，状态写“待
macOS 验收”，而不是“macOS 不支持”。

CMDM 与 MoMADiff 当前声明 `osx-arm64` / `osx-64` CPU Runtime；其 lock 尚未在 macOS 实机完成 build/import，
更没有 checkpoint inference 或 browser evidence。CUDA profiles 不得出现在 macOS 可选策略中，MPS Worker
也仍未实现。
