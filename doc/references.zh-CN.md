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

- [AMASS 官方主页](https://amass.is.tue.mpg.de/)、[作者仓库](https://github.com/nghorbani/amass)、[可视化 notebook](https://github.com/nghorbani/amass/blob/master/notebooks/01-AMASS_Visualization.ipynb) 与 [SOMA Stage-II writer](https://github.com/nghorbani/soma/blob/main/src/soma/amass/prepare_amass_npz.py)：SMPL family motion、root/body/hand切片、poses/trans/framerate 和 Stage-II 来源。
- [BABEL Data](https://babel.is.tue.mpg.de/data.html)：AMASS carrier 上的 sequence 与 frame-level 时间标注定义。
- [BEAT 作者仓库](https://github.com/PantoMatrix/BEAT)、[BVH hierarchy/channel 说明](https://research.cs.wisc.edu/graphics/Courses/cs-838-1999/Jeff/BVH.html) 与 [Blender BVH importer](https://github.com/blender/blender-addons/blob/b42d68627734cb18af0e6f41537063984313a284/io_anim_bvh/import_bvh.py#L603-L608)：75-joint raw BVH、120 FPS、声明欧拉顺序、audio、face 与 semantic file。
- [GRAB 作者仓库](https://github.com/otaheri/GRAB) 与 [官方主页](https://grab.is.tue.mpg.de/)：120 FPS SMPL-X、物体刚体运动与 contact 数据。
- [HumanML3D 作者仓库](https://github.com/EricGuo5513/HumanML3D)、固定提交的 [263D 构造](https://github.com/EricGuo5513/HumanML3D/blob/9176e8fb446b71c7d2a725eb5cf6fec1ae3b3c23/motion_representation.ipynb)、[Skeleton IK/FK](https://github.com/EricGuo5513/HumanML3D/blob/9176e8fb446b71c7d2a725eb5cf6fec1ae3b3c23/common/skeleton.py)、[joint topology](https://github.com/EricGuo5513/HumanML3D/blob/9176e8fb446b71c7d2a725eb5cf6fec1ae3b3c23/paramUtil.py) 与 [CVPR 论文](https://openaccess.thecvf.com/content/CVPR2022/html/Guo_Generating_Diverse_and_Natural_3D_Human_Motions_From_Text_CVPR_2022_paper.html)：20 FPS、22 joints、root/RIC 与 child-edge 6D 语义。
- [Motion-X 作者仓库](https://github.com/IDEA-Research/Motion-X) 与 [AIST translation converter](https://github.com/IDEA-Research/Motion-X/blob/main/non-mocap-dataset-process/aist.py)：30 FPS、322D layout、AIST `/94` 与 Z translation flip、sequence/body/hand/face text 及再分发边界。
- [SentiAvatar / SuSuInterActs 作者仓库](https://github.com/SentiAvatar/SentiAvatar) 与 [项目主页](https://sentiavatar.github.io/)：20 FPS、body/hand 6D、对话、face/audio 与官方 exporter 的入口。

工程约束：官方资料与本地文件事实分开记录。BEAT 当前直接解析 raw BVH；本地 hierarchy证明 Y-up 时，不因 README 的 Blender 场景描述再做一次 Z-up 转换。旧 body22 NPZ只作 legacy provenance。

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
