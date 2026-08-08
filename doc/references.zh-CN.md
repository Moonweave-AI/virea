---
type: reference
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 90
summary: 影响 VIREA schema、source decode、retarget、VRM runtime 与许可判断的一手资料。
canonical: doc/references.zh-CN.md
related:
  - dataset-audit.zh-CN.md
  - math-retarget/README.zh-CN.md
  - validation.zh-CN.md
  - research/source-authority-review.zh-CN.md
supersedes: []
superseded_by: []
---

# 权威资料与设计基线

只列官方规范、作者仓库、项目主页或论文原文。外部资料定义标准背景；它不证明本仓库已经正确执行，也不覆盖本地数据变体。

## glTF、VRM 与运行时

- [Khronos glTF 2.0 Specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html)：右手系、meter、node TRS、rotation quaternion、skin/joint 和 animation sampler 的规范事实源。
- [VRM 1.0 Humanoid Specification](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/humanoid.md)：humanoid bone 名到 glTF node 的映射与约束。
- [VRM Animation 1.0 Specification](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm_animation-1.0/README.md)：未来导出 VRMA 的通道与坐标边界。
- [three-vrm VRMHumanoid API](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMHumanoid.html)：Viewer 获取 raw/normalized humanoid bone node 的运行时接口。
- [three.js SkeletonUtils](https://github.com/mrdoob/three.js/blob/dev/examples/jsm/utils/SkeletonUtils.js)：成熟 skeleton retarget helper 的工程参考；不负责数据集 source decode 或 profile。

工程约束：VRM 是 glTF Avatar 规范，不是 SMPL-X 参数；canonical quaternion 使用 `xyzw`，local rotation 写入 humanoid 对应 node。3D annotation 锚点必须读真实 bone node。

## 参数化人体模型

- [SMPL 官方项目](https://smpl.is.tue.mpg.de/)：SMPL body model 的权威入口。
- [MANO / SMPL+H 官方项目](https://mano.is.tue.mpg.de/)：手部模型与 SMPL+H 背景。
- [SMPL-X 官方项目](https://smpl-x.is.tue.mpg.de/) 与 [论文](https://arxiv.org/abs/1904.05866)：body、hands、jaw、eyes、expression 的模型定义。

工程约束：joint mapping 是领域常量；FPS、basis、unit、数组切片和 sub-source provenance 仍由 dataset profile 决定。

## 七个数据集

- [AMASS 官方主页](https://amass.is.tue.mpg.de/) 与 [作者仓库](https://github.com/nghorbani/amass)：SMPL family motion、poses/trans/framerate 和许可入口。没有通用动作文本时，VIREA 的文件名词语只能是 derived。
- [BABEL Data](https://babel.is.tue.mpg.de/data.html)：AMASS carrier 上的 sequence 与 frame-level 时间标注定义。
- [BEAT 作者仓库](https://github.com/PantoMatrix/BEAT)：raw BVH、120 FPS、坐标、audio、face 与 semantic file 的官方说明。
- [GRAB 作者仓库](https://github.com/otaheri/GRAB) 与 [官方主页](https://grab.is.tue.mpg.de/)：120 FPS SMPL-X、物体刚体运动与 contact 数据。
- [HumanML3D 作者仓库](https://github.com/EricGuo5513/HumanML3D) 与 [CVPR 论文](https://openaccess.thecvf.com/content/CVPR2022/html/Guo_Generating_Diverse_and_Natural_3D_Human_Motions_From_Text_CVPR_2022_paper.html)：20 FPS、22 joints、text 与 motion feature 的上游定义。
- [Motion-X 作者仓库](https://github.com/IDEA-Research/Motion-X)：30 FPS、322D layout、sequence/body/hand/face text 与原始数据再分发边界。仓库 README 的 loader 切片是 322D 的直接依据。
- [SentiAvatar / SuSuInterActs 作者仓库](https://github.com/SentiAvatar/SentiAvatar) 与 [项目主页](https://sentiavatar.github.io/)：20 FPS、body/hand 6D、对话、face/audio 与官方 exporter 的入口。

工程约束：官方资料与“项目已经预转换的本地 NPZ/TSV/Parquet”分开记录。例如 BEAT 官方 raw 是 BVH，但 VIREA 当前主输入是上游转换后的 body22 axis-angle；不能重复应用 raw basis。

## Rotation 与运动学

- [Zhou 等人，CVPR 2019](https://openaccess.thecvf.com/content_CVPR_2019/html/Zhou_On_the_Continuity_of_Rotation_Representations_in_Neural_Networks_CVPR_2019_paper.html)：连续 6D rotation representation 与前两列 Gram–Schmidt 的论文原文。
- [glTF 2.0 Quaternion 约束](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#transformations)：rotation 的 `xyzw` 与单位 quaternion 约束。

工程约束：6D layout、row/column 和 local/global 不能凭经验选择。SuSu 官方公开实现是 columns/local；任何 rows/global 本地变体只有在同帧标定后才可建立独立 profile。

## 如何引用这些资料

文档中的结论标为三类：

- “标准背景”：由本页一手资料支持；
- “上游已完成”：由项目收到的文件结构、转换脚本或 manifest 支持；
- “当前仓库边界”：由当前 Adapter/Codec/Retarget 分支与测试支持。

三类证据冲突时不自动选一个继续发布，而是把 profile 降为 draft、保留原始字段并加入 validation error。许可条款也必须回到各数据集与 VRM 的原始入口复核；本页链接不是再分发授权。
