# PRISM 正式来源、迁移证据与接入审计（2026-08-21）

## 结论

VIREA 已登记正式 PRISM TP2M 1.4B 的模型身份，并把既有 WSL2 实机部署迁移为 managed Linux/WSL
Runtime、离线 Worker 与严格的 SMPL-H body-22 / 69D / 30 FPS 控制面合同。随后 PRISM 在
`wsl:Ubuntu-24.04` 完成同链 doctor→install→真实 checkpoint inference→Motion IR→Canonical211→VRMA→
fresh browser 验收，当前状态为受限的 `integrated_experimental`。它不是 `supported`，也不解除外部资产、
上游源码和模型许可的公开再分发限制。

早期调查曾发现 Motius 中名为 PRISM-KT 的独立实现。论文 v3 与作者正式 README 已明确把正式代码指向 `ZeyuLing/PRISM`，所以 VIREA 不把 Motius 制品冒充论文正式发布，也没有复制两边的源码或权重。

## 固定来源

| 证据 | 固定版本 | 已核实事实 |
| --- | --- | --- |
| [论文](https://arxiv.org/abs/2603.08590) | arXiv v3 | 标题、作者、正式 code URL、统一 T2M/pose-conditioned/streaming 任务 |
| [PRISM 代码](https://github.com/ZeyuLing/PRISM/tree/3c58bc5d946f0827171a3712ed36314f4b1a5186) | `3c58bc5d946f0827171a3712ed36314f4b1a5186` | standalone `prism/`、四个 inference scripts、loader 与 processor；仓库无 LICENSE |
| [PRISM-TP2M-1.4B](https://huggingface.co/ZeyuLing/PRISM-TP2M-1.4B/tree/825daaa27f4f3845eb0978674c3acb378a12cda6) | `825daaa27f4f3845eb0978674c3acb378a12cda6` | 完整 snapshot 的 9 个文件共 32,669,418,445 bytes；无 license metadata |
| [google/umt5-xxl](https://huggingface.co/google/umt5-xxl/tree/66cb9e7e85526fe440a945569e42c72fb6cbc0ad) | `66cb9e7e85526fe440a945569e42c72fb6cbc0ad` | PRISM text encoder 使用的权威 tokenizer 文件；独立固定、离线加载 |
| [MotionHub statistics](https://huggingface.co/datasets/ZeyuLing/MotionHub/tree/c3f6c8eb8a4ba9e5ca521cdc0af9264756b66726/statistics) | `c3f6c8eb8a4ba9e5ca521cdc0af9264756b66726` | `smplh_universal_stats_aug.json`；独立固定、离线加载 |
| [VersatileMotion](https://github.com/ZeyuLing/VersatileMotion/tree/e521f36dd5ad317bd8b47e69878d0eac79915e58) | `e521f36dd5ad317bd8b47e69878d0eac79915e58` | PRISM README 指向的许可位置；该固定提交无 LICENSE，模型实现仍在 TODO |

固定 Git commit 由 `git ls-remote <repo> HEAD` 复核；Hugging Face revision、文件名和文件大小由官方 Hub API 复核。VIREA 没有再计算文件 SHA-256，也没有以内容哈希门禁拖慢安装。

## 原生数学合同

正式 `SMPLPoseProcessor` 的 `abs_rel` + `smpl_22` + `rotation_6d` 网络路径给出每帧 138 个 float：

- `0:3`：absolute root translation；
- `3:6`：per-frame root translation delta；
- `6:12`：root global orientation rotation-6D；
- `12:138`：21 个非 root body joint 的 parent-local rotation-6D。

正式 converter 把 rotation matrix 的第一列 `[R00,R10,R20]` 与第二列 `[R01,R11,R21]` 依次拼接，而不是 `view(3,2)` 的交错布局。正式 pipeline 的默认 root decode 使用第一帧 absolute translation，随后对 frame 1 onward 的 delta 做累计。

managed Worker 在执行正式 processor 与 root rollout 后保存完整上游原始输出，同时向控制面发布精确
`(T,69)` float32 carrier：absolute translation 3、global orientation axis-angle 3、21 个 parent-local body
axis-angle 63。Adapter 严格检查该 69D carrier、finite 和 30 FPS，再转换为 Motion IR；内部 138D 不被
误写成公共结果 identity。生成不依赖 SMPL mesh geometry，不虚构 hands，也不声称 Canonical211/VRM
对上游未生成通道无损。

## 为什么早期 blocked 结论已失效

固定模型 snapshot 本身没有 tokenizer 与 statistics。既有 WSL 部署和正式上游引用确定了可复现来源：

1. tokenizer 固定到 `google/umt5-xxl` 的明确 revision；
2. statistics 固定到 `ZeyuLing/MotionHub` 的 `smplh_universal_stats_aug.json`；
3. generation 使用 model-free processor，不把空 SMPL 目录冒充资产，也不要求 mesh/body-model 文件。

因此“缺依赖所以技术上不可部署”的结论不再成立。许可边界仍然独立存在：代码仓库、模型卡和它指向的
VersatileMotion 仓库均没有可由 VIREA 代授的许可证。发行包只携带 VIREA integration/runtime source；
PRISM 源码与模型作为用户显式接受并从固定上游获取或引用的 external assets，不随 VIREA 再分发。

## 当前晋级结果与仍存边界

managed Runtime 使用 component-split placement：UMT5 留在 CPU，transformer/VAE 使用 CUDA；安装前分别
要求 28 GiB free physical RAM、12 GiB free VRAM 与 40 GiB free storage，预算不能相加。当前 fresh managed
E2E 的内存观测是：加载前 available 32,463,986,688 bytes；加载后 available 20,110,942,208 bytes、RSS
12,612,476,928 bytes；推理后 available 19,152,322,560 bytes、RSS 13,683,249,152 bytes；VmHWM
31,703,216,128 bytes。本轮没有记录 GPU allocation peak，不能把 RAM VmHWM 或 GPU 总量改写成 GPU 峰值。

晋级证据 `e2e-browser-prism-tp2m-1-4b-20260821085331248-39264` 绑定 doctor
`01M0HR90CBFEXYGP0X5H0RJC5K`、installation `01M0HRA3NWZ1CHC8F0PBM8FD9F`、fresh job
`01M0HRD5QP3WRHD4W1NEXGGNX1`、result `01M0HREAR9ZH5219NPK930XVT0` 与 127,768-byte VRMA。Registry
runner 记录 Avatar fully visible、AnimationMixer 0.1167→0.8334、43 个 render frames、WebGL2/SwiftShader
以及 console/page/request 的 0 errors；根任务的独立应用内 Browser 又确认同一结果 fully visible、mixer
推进、硬件 WebGL2 RTX renderer 与 0 errors。两种浏览器观察各自保留，不互相改写。

该通过只覆盖 Windows 宿主上的 WSL Ubuntu 24.04、RTX 5090 Laptop GPU 和
`cuda_component_split`。原生 Linux、Windows native、macOS、其他 GPU 与生产 SLO 仍未完成 E2E；许可复核
继续限制公开发行与商业使用，但不会再被错误描述成技术不可运行。

<!--
type: research-log
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: PRISM TP2M 1.4B 正式来源、WSL fresh 全链、69D 公共合同、managed Runtime、RAM 观测与许可边界审计。
canonical: doc/research/prism-official-integration-audit-2026-08-21.zh-CN.md
related:
  - doc/model-catalog/first-wave-2026-08-20.zh-CN.md
  - doc/refactor/ENGINEERING_BRIEF_0.4_MULTI_MODEL_PRODUCTION.md
supersedes: []
superseded_by: []
-->
