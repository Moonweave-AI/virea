---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: ReMoMask 固定制品、发布版 CLIP 检索闭包与离线推理契约。
canonical: plugins/models/remomask-humanml3d/runtime/README.md
related:
  - ../manifest.yaml
supersedes: []
superseded_by: []
---

# ReMoMask HumanML3D VIREA runtime / VIREA 运行环境

This package materializes the immutable ReMoMask source commit and Hugging
Face revision, then runs the released RVQVAE, auxiliary/2D mask transformer,
auxiliary/2D residual transformer, and BiMoCo retrieval graph. The Worker saves
the official inverse-normalized HumanML3D 263D vector as finite float32 NPY; it
does not substitute a synthetic joint track.

The released retrieval configuration declares `ViT-B-32.pt` with 512 input and
projection dimensions, and the released `best_model.pt` contains
`text_encoder.clip_model.*` tensors. The pinned repository's later
`AutoModel` constructor cannot load that release. VIREA therefore extracts the
exact inference-only CLIP query encoder and projection-head equations encoded by
the release configuration/checkpoint. No retrieval or generation equation and
no checkpoint tensor is replaced.

The upstream Python 3.10/Torch 2.1 environment is replaced by current locked
CPU and CUDA 12.8 wheel sets. Training, visualization, evaluator, and dataset
dependencies are intentionally absent from this inference closure.

该包物化不可变的 ReMoMask 源码提交与 Hugging Face revision，随后执行发布版
RVQVAE、辅助/二维 Mask Transformer、辅助/二维 Residual Transformer 和
BiMoCo 检索图。Worker 保存有限值 float32 NPY 格式的官方反归一化
HumanML3D 263 维向量，不会替换成合成骨骼轨迹。

发布配置声明 512 维输入与投影的 `ViT-B-32.pt`，发布权重
`best_model.pt` 也包含 `text_encoder.clip_model.*` 张量；固定仓库后来加入
的 `AutoModel` 构造器无法加载该发布物。因此 VIREA 精确提取发布配置与权重
编码的 CLIP 查询编码器和投影头推理公式，不替换任何检索/生成公式或权重张量。

上游 Python 3.10、Torch 2.1 环境替换为当前锁定的 CPU 与 CUDA 12.8
wheel；训练、可视化、评测和数据集依赖不会进入推理闭包。
