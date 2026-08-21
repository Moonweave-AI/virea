---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: 在不污染 checkout 的前提下安装 VIREA、初始化外部状态并记录机器报告。
canonical: doc/getting-started/installation.zh-CN.md
related:
  - first-generation.zh-CN.md
  - ../platforms/README.zh-CN.md
  - ../operations/runtime-data-and-retention.zh-CN.md
supersedes: []
superseded_by: []
---

# 安装

## 前置

- Git、uv、Node.js 与 pnpm；
- 足够的外部磁盘空间；
- 目标模型需要的 GPU/CPU 与驱动；
- checkpoint 或人体模型受限时，接受对应第三方条款。

## 源码开发

先按 [平台文档](../platforms/README.zh-CN.md) 把 `UV_PROJECT_ENVIRONMENT` 和 `VIREA_HOME` 指向
checkout 之外，再执行：

```text
uv sync --locked --all-packages --extra dev
pnpm install --frozen-lockfile
pnpm --filter @virea/web build
uv run virea setup --virea-home <external-home>
uv run virea doctor --json --record --explain --repair-plan --virea-home <external-home>
```

`doctor --record` 在 `machine/reports/` 保存不可覆盖报告；安装验收会选择安装开始前最新的有效报告，而不是
读取可能已被后来机器状态覆盖的全局 latest。

## 检查

```text
uv run virea model list --json
uv run virea state inspect --virea-home <external-home>
```

仓库根目录不得出现 `.venv`、模型缓存、日志、SQLite、job/result 或 pytest 临时目录。
