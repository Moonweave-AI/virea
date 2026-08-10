# VIREA local demo workspace

`demo/` 是被 Git 忽略的本地测试工作区，不是 clean clone 自带的数据集。

```text
demo/raw/        local-only raw fixture
demo/processed/  generated artifacts, isolated by processing version
demo/manifest.json
```

## 三条使用路径

1. 仅启动 Viewer：`python -m virea serve --data-source demo`。没有本地数据时样本列表为空。
2. 下载固定 local-only snapshot：先阅读许可提示，再运行 `python scripts/download_demo.py --accept-local-only`。
3. 从用户自备 full raw 构建：`python -m virea build-demo --samples-per-dataset 7 --overwrite`，随后处理。

下载或构建的 raw、processed 与派生媒体不得提交、上传或公开链接。旧 processed snapshot 可能是 pre-v3：Reader 只保留已有 2D 几何/语义，不把 legacy sequence 冒充 canonical v3 Avatar motion。Current v3 必须从 raw 重建到 processing `v0.4.0`。

公开的 current-v3 示例、来源说明与媒体哈希见 [Showcase 文档](../doc/showcase/README.md)。


<!--
---
type: reference
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-10
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 90
title: VIREA Local Demo Workspace
audience: Local users and migration reviewers
visibility: Public
summary: demo 目录的本地用途、下载门禁和 pre-v3 兼容边界。
canonical: demo/README.md
related:
  - ../README.md
  - ../doc/getting-started.zh-CN.md
  - ../doc/showcase/README.md
supersedes: []
superseded_by: []
---
-->
