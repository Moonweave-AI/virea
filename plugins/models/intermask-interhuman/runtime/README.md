---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: InterMask 双人动作固定制品、共享坐标系与离线推理契约。
canonical: plugins/models/intermask-interhuman/runtime/README.md
related:
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# InterMask InterHuman VIREA Worker / VIREA 运行时

The Worker loads the official InterMask Mask Transformer and RVQ-VAE from the
pinned upstream source, then publishes both actors' denormalized 262D carriers.
Text-to-interaction and reaction generation share the same real checkpoint path.

Worker 从固定版本上游源码加载官方 Mask Transformer 与 RVQ-VAE，并发布两个角色的
反归一化 262D 载体。文本双人交互与反应生成共用同一真实权重链路。

The Google Drive checkpoint folder is referenced rather than redistributed;
VIREA validates four exact files before building the runtime.

Google Drive 权重目录仅被引用而不会被 VIREA 重新分发；构建运行时前会验证四个精确文件。
