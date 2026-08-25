---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: DART BABEL SMPL-X 固定制品、动作原语与离线推理契约。
canonical: plugins/models/dart-smplx/runtime/README.md
related:
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# DART BABEL SMPL-X runtime / DART BABEL SMPL-X 运行环境

This Worker executes the pinned official DART denoiser, motion-primitive VAE,
diffusion sampler, SMPL-X reconstruction, and overlap blending entirely from
installed local assets. It does not use synthetic motion or implicit downloads.

该 Worker 使用已安装的本地资产执行固定版本的官方 DART 去噪器、动作原语
VAE、扩散采样、SMPL-X 重建和重叠融合，不使用伪造动作，也不会隐式下载。

The small `pytorch3d.transforms` compatibility package contains only the four
pure-PyTorch rotation conversions used by DART. This removes compiled PyTorch3D
wheel restrictions on Windows and macOS without changing checkpoint math.

内置的小型 `pytorch3d.transforms` 兼容包仅包含 DART 所需的四个纯 PyTorch 旋转
转换，从而去除 Windows/macOS 上编译型 PyTorch3D wheel 的限制，不改变权重计算。
