---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: 在不污染 checkout 的前提下安装 VIREA、初始化外部状态并记录机器报告。
canonical: doc/getting-started/installation.zh-CN.md
related:
  - installation.en.md
  - ../getting-started.zh-CN.md
  - first-generation.zh-CN.md
  - ../platforms/README.zh-CN.md
  - ../operations/runtime-data-and-retention.zh-CN.md
supersedes: []
superseded_by: []
---

# 安装

> [中文](installation.zh-CN.md) · [English](installation.en.md) · [完整 clone 教程](../getting-started.zh-CN.md)

## 前置

- Git、uv、Node.js 与 pnpm；
- 足够的外部磁盘空间；
- 目标模型需要的 GPU/CPU 与驱动；
- checkpoint 或人体模型受限时，接受对应第三方条款。

## 源码开发

先按[完整 clone 教程](../getting-started.zh-CN.md)克隆项目，并把 `UV_PROJECT_ENVIRONMENT` 和 `VIREA_HOME` 指向
checkout 之外；Windows/Unix 的精确路径输入、复制路径和空格规则见[数据根路径与引号规则](persistent-data-root.zh-CN.md)，再执行：

```bash
# 严格按 uv.lock 安装 Python workspace 与开发依赖；不会下载模型权重。
uv sync --locked --all-packages --extra dev
# 严格按 pnpm-lock.yaml 安装当前 Web workspace；不允许改锁文件。
pnpm install --frozen-lockfile
# 构建浏览器静态资源，不启动服务。
pnpm --filter @virea/web build
# 启动推荐的逐步交互向导：初始化状态、检测执行域、选择模型/Runtime/profile，安装前确认，再提供生成与播放。
uv run virea
```

`doctor --record` 在 `machine/reports/` 保存不可覆盖报告；安装验收会选择安装开始前最新的有效报告，而不是
读取可能已被后来机器状态覆盖的全局 latest。

仓库根目录不得出现 `.venv`、模型缓存、日志、SQLite、job/result 或 pytest 临时目录。
