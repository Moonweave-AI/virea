---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: SentiAvatar SuSu 音频对话制品、多流输出与离线推理契约。
canonical: plugins/models/sentiavatar-susu/runtime/README.md
related:
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# SentiAvatar SuSu runtime / SentiAvatar SuSu 运行环境

This isolated Worker executes the pinned public SentiAvatar inference graph
entirely from VIREA-managed artifact roots. It uses the released Qwen2 motion
planner, Chinese HuBERT and K-means audio encoder, Audio-Motion Mask Transformer,
RVQ-VAE decoder, and optional Face VQ-VAE. No model component is downloaded by
the Worker and no external vLLM service is required.

此隔离 Worker 完全从 VIREA 管理的工件根目录执行固定版本的 SentiAvatar 官方推理图：
Qwen2 动作规划器、Chinese HuBERT 与 K-means 音频编码器、Audio-Motion Mask
Transformer、RVQ-VAE 解码器以及可选 Face VQ-VAE。Worker 不会自行下载模型，
也不依赖外部 vLLM 服务。

The upstream project is source-available for non-commercial use only. Install
and run it only after reviewing and accepting the SentiPulse Non-Commercial
Source License v1.0.

上游项目仅允许非商业用途。安装和运行前必须阅读并接受 SentiPulse
Non-Commercial Source License v1.0。
