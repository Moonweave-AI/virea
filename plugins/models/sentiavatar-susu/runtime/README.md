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

The Worker declares both its supported and active memory strategy before any
checkpoint is loaded. VIREA validates this declaration before load and verifies
it again after load, so an invalid CPU/CUDA binding fails immediately instead
of spending minutes loading weights before acceptance fails.

Worker 会在加载任何 checkpoint 前同时声明支持的内存策略和当前生效策略。VIREA
会在加载前校验该声明，并在加载后再次验证；CPU/CUDA 绑定错误会立即失败，不会先花费
数分钟加载权重再在验收阶段失败。

An unauthenticated Hugging Face warning only indicates a lower download rate
limit. It is not a model-load error. VIREA excludes Hub transfer metadata from
the immutable model asset and the installed Worker performs no network fetches.

Hugging Face 未认证警告只表示下载限额较低，并非模型加载错误。VIREA 不会把 Hub
传输元数据计入不可变模型制品，安装完成后的 Worker 也不会访问网络下载组件。

The pinned upstream HuBERT K-means estimator was serialized with scikit-learn
1.0.2, which does not provide the Python 3.11 cross-platform wheel required by
VIREA. The Worker does not call version-sensitive estimator methods: it extracts
the immutable centers and requires one finite `500 x 768` float32 matrix before
using the upstream squared-distance assignment formula.
Before deserialization, VIREA requires the exact pinned official file SHA-256.
It then requires the real scikit-learn `MiniBatchKMeans` estimator type before
copying only its validated centers. This compatibility path does not accept
arbitrary or user-supplied pickle/joblib files.

固定的上游 HuBERT K-means estimator 由 scikit-learn 1.0.2 序列化，而该版本
没有 VIREA 跨平台 Python 3.11 所需的 wheel。Worker 不调用受版本影响的 estimator
方法，只提取不可变聚类中心，并要求其为有限的 `500 x 768` float32 矩阵，然后才按
上游平方距离公式分配 token。
反序列化前，VIREA 必须确认文件 SHA-256 与固定官方制品完全一致；随后还会验证真实
scikit-learn `MiniBatchKMeans` estimator 类型，再只复制通过校验的聚类中心。该兼容
路径不接受任意或用户提供的 pickle/joblib 文件。

The pinned Chinese HuBERT release contains a legacy PyTorch `.bin` state dict.
VIREA verifies its exact SHA-256, loads tensor weights only, requires the exact
211-tensor contract, and applies it strictly to a locally constructed HuBERT
model. This avoids Transformers' version-dependent legacy loader and keeps the
same model asset usable on Windows, Linux/WSL, Apple Silicon, and Intel macOS.

固定的 Chinese HuBERT 制品包含旧式 PyTorch `.bin` state dict。VIREA 会先验证其
精确 SHA-256，只加载 tensor 权重，要求严格的 211-tensor 合同，再以 strict 模式写入
本地构造的 HuBERT 模型。这样无需依赖 Transformers 随版本变化的旧格式加载器，同一
模型制品即可用于 Windows、Linux/WSL、Apple Silicon 与 Intel macOS。

The upstream project is source-available for non-commercial use only. Install
and run it only after reviewing and accepting the SentiPulse Non-Commercial
Source License v1.0.

上游项目仅允许非商业用途。安装和运行前必须阅读并接受 SentiPulse
Non-Commercial Source License v1.0。
