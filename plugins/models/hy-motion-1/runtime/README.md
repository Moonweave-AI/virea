---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: HY-Motion 1.0 固定制品、多编码器与离线推理契约。
canonical: plugins/models/hy-motion-1/runtime/README.md
related:
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# HY-Motion 1.0 VIREA Worker / VIREA 运行时

This package wraps the pinned official HY-Motion inference pipeline. VIREA owns
artifact acquisition, runtime isolation, cancellation, and result publication;
the upstream diffusion and decoder code remains the source of generated motion.

本包封装固定版本的 HY-Motion 官方推理管线。VIREA 负责制品获取、运行时隔离、取消与结果发布；
实际动作仍由上游扩散模型和解码器生成。

The Worker never downloads implicitly. The source checkout, Standard checkpoint,
Qwen3-8B text encoder, and CLIP-L/14 encoder must all be present in the installed
artifact roots supplied by the supervisor.

Worker 不会在运行时隐式联网；源码、Standard 权重、Qwen3-8B 文本编码器和 CLIP-L/14
编码器都必须来自 Supervisor 提供的已安装制品目录。
