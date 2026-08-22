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
# 一次性读取已挂载数据卷的根路径。
printf '%s' "输入所选数据卷根路径: "
read -r virea_data_root
# 创建 VIREA 目录并安装 shell hook；之后新终端自动继承目录设置。
./scripts/configure-virea.sh --data-root "$virea_data_root"
# 在当前 shell 立即加载生成的设置；之后兼容 shell 将自动加载 hook。
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"
# 按锁文件安装 Python workspace。
uv sync --locked --all-packages --extra dev
# 初始化外部状态目录。
uv run virea setup
# 探测 macOS native 域、资源和可修复问题。
uv run virea doctor --json --record --explain --repair-plan
```

Apple Silicon 的 MPS、Apple/Intel CPU 与 CUDA Runtime 是不同构建。只有 Worker 明确实现 MPS 或 CPU 路径时，
解析器才会选择它；不能加载 cu128 wheel 后把设备名改为 `mps`。

macOS 没有 Linux `/proc`。Worker 身份、孤儿恢复和进程树终止必须使用 Darwin 原生进程信息，并在 PID、创建
时间、可执行文件和完整参数无法同时核实时 fail closed。平台路径完成实现但未取得实机证据时，状态写“待
macOS 验收”，而不是“macOS 不支持”。

CMDM 与 MoMADiff 当前声明 `osx-arm64` / `osx-64` CPU Runtime；其 lock 尚未在 macOS 实机完成 build/import，
更没有 checkpoint inference 或 browser evidence。CUDA profiles 不得出现在 macOS 可选策略中，MPS Worker
也仍未实现。
