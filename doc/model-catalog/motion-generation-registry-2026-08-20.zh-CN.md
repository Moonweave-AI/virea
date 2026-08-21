# VIREA Motion Generation 模型总清单

> 快照日期：**2026-08-20**
> Registry：`virea.motion_model_registry.v1.0.0`
> 唯一模型/系统/研究条目：**519**
> 原始能力分类行：**562**

## 0. “支持”不是把名字塞进 README

本清单是 **VIREA 的候选模型注册表与兼容范围**。同一模型即使横跨生成、编辑、交互和 policy，也只计为一个唯一条目；能力通过数组表达，不再靠重复计数制造一种很努力的幻觉。

- **registered**：已纳入架构兼容与跟踪范围。
- **implemented**：必须具备隔离 runtime、可复现权重获取、Worker、真实 checkpoint 推理、原生输出 decoder、Motion IR 转换、VRM 回归、许可事实和 production acceptance；test-only fixture 不构成发布证据。
- **adjacent**：视频/avatar、数据集、攻击、训练方法或评测工作；只有在暴露稳定 3D motion 中间态后才可成为直接 Worker。
- 每个模型的代码、权重、平台和许可证状态必须在实现插件时单独复核。论文存在不等于权重存在，更不等于某个古老 CUDA 环境愿意配合人类的愿望。

## 1. 收录范围

1. 文本、语音、音频、音乐、图像、视频、草图、关键帧、轨迹和多模态条件的 3D motion generation；
2. body、whole-body、hands、face、sign、dance 和 co-speech；
3. editing、in-betweening、stylization 和 retarget-aware generation；
4. HHI、HOI、HSI 和 long-horizon behavior；
5. humanoid/physics policy，以及 policy rollout 到 VIREA Motion IR 的桥接；
6. 2025–2026 尽量全量收录，同时保留 2024 及更早的重要基础模型。

纯重建、纯识别、纯数据集或仅输出最终视频且不暴露动作表示的工作不会冒充普通动作模型，而是标为 supporting 或 adjacent。

## 2. 去重后的统计

### 按主年份

- `2023`：51
- `2024`：65
- `2025`：237
- `2026`：113
- `2022_and_earlier`：40
- `cross_year`：13

### 按能力类别

> 一个模型可以属于多个类别，因此此处计数不应相加。

- `text_and_general_motion`：173
- `foundational_text_and_general_motion`：78
- `human_object_interaction`：48
- `foundational_speech_music_and_interaction`：40
- `historical_foundations`：40
- `human_human_interaction`：40
- `music_and_dance`：21
- `supporting_method_dataset_or_evaluation`：20
- `human_scene_interaction`：18
- `streaming_avatar_and_speech_gesture`：16
- `motion_editing_inbetweening_and_stylization`：15
- `speech_gesture_and_avatar_motion`：14
- `adjacent_video_avatar_or_non_generator`：10
- `motion_editing_inbetweening_and_retargeting`：8
- `physics_and_humanoid_policy`：7
- `human_scene_and_behavior_generation`：6
- `hand_and_sign_motion`：5

### 按接入轨道

> 一个模型可以走多个轨道，因此此处计数不应相加。

- `direct.motion_ir.body_or_whole_body`：243
- `extended.object_contact`：48
- `direct_or_bridge`：40
- `direct_or_extended.motion_ir`：40
- `extended.multi_actor`：40
- `direct.motion_ir.body`：27
- `direct.motion_ir.editing_and_retarget`：23
- `extended.scene_and_long_horizon_behavior`：23
- `module.not_worker`：20
- `direct.motion_ir.streaming_whole_body_face_hands`：16
- `direct.motion_ir.streaming_or_offline_whole_body`：14
- `adjacent.no_stable_motion_tensor`：10
- `bridge.policy_trajectory`：7
- `extended.hand_sign_and_fingers`：5

## 3. 12 类通用 Adapter Family

| Adapter family | 覆盖范围 | 统一输出 |
|---|---|---|
| `humanml3d_263d_body22` | HumanML3D/KIT-style 22-joint body and 263D feature pipelines | body22 plus reconstructed root trajectory |
| `smpl_smplh_axis_angle` | SMPL/SMPL-H body and optional hand rotations | body plus optional 30-finger track |
| `smplx_whole_body` | SMPL-X body, hands, jaw/face coefficients and shape | whole-body, hands, expressions and provenance tracks |
| `generic_bvh_or_named_skeleton` | BVH/FBX or arbitrary named skeletons | skeleton profile plus local rotations and root transform |
| `joint_positions_fk_ik` | 3D joint positions, sparse keypoints and trajectory-conditioned outputs | position evidence followed by calibrated IK/retarget |
| `rotation6d_named_joints` | 6D rotation outputs such as SuSu-style body and hand tracks | named local rotations plus source-rest calibration |
| `streaming_audio_motion` | causal audio-to-body/hand/face motion chunks | timestamped chunk stream with continuity state |
| `multi_actor_motion` | dyadic, group and variable-cardinality interaction models | multiple actor tracks with shared world/time semantics |
| `human_object_scene` | objects, contacts, scene geometry and affordance-conditioned motion | actor, object, contact and scene tracks |
| `hand_sign` | bimanual hand motion and sign-language generation | finger-complete hands, wrists, upper body and linguistic timing |
| `physics_policy_bridge` | humanoid policies, actions, torques or simulator trajectories | rollout trajectory converted to auditable kinematic motion |
| `adjacent_rendered_avatar` | video/talking-avatar systems without a stable exposed motion tensor | not directly supported; only via an explicit intermediate-motion export |

模型插件只负责下载/加载、推理和原生结果声明。结构探测器只服务外部未知结果，不能对已注册模型猜骨架、猜 FPS、猜单位或猜 rotation space。

## 4. 全量唯一条目

## 2026（113 个唯一条目）

| 模型/系统 | 类别 | VIREA 接入轨道 | 优先级 | 证据状态 |
|---|---|---|---:|---|
| FGDM | hand_and_sign_motion | extended.hand_sign_and_fingers | P1 | discovery_indexed_primary_verification_pending |
| Phonology-Guided Sign Language Motion Generation | hand_and_sign_motion | extended.hand_sign_and_fingers | P1 | discovery_indexed_primary_verification_pending |
| TSHaMo | hand_and_sign_motion | extended.hand_sign_and_fingers | P1 | discovery_indexed_primary_verification_pending |
| U-Mind | hand_and_sign_motion | extended.hand_sign_and_fingers | P1 | discovery_indexed_primary_verification_pending |
| HandX | hand_and_sign_motion<br>human_object_interaction | extended.hand_sign_and_fingers<br>extended.object_contact | P1 | discovery_indexed_primary_verification_pending |
| HINT | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| InterMoE | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| InterPrior | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Rhythm | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| InfBaGel | human_human_interaction<br>human_object_interaction | extended.multi_actor<br>extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| InterReal | human_human_interaction<br>human_object_interaction | extended.multi_actor<br>extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| Learning to Assist | human_human_interaction<br>human_object_interaction | extended.multi_actor<br>extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| ReMoGen | human_human_interaction<br>human_object_interaction | extended.multi_actor<br>extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| Stability-Driven Co-Manipulation | human_human_interaction<br>human_object_interaction | extended.multi_actor<br>extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| TeamHOI | human_human_interaction<br>human_object_interaction | extended.multi_actor<br>extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| DuoGesture | human_human_interaction<br>streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands<br>extended.multi_actor | P0 | discovery_indexed_primary_verification_pending |
| [DyaDiT](https://openaccess.thecvf.com/content/CVPR2026/html/Peng_DyaDiT_A_Multi-Modal_Diffusion_Transformer_for_Socially_Favorable_Dyadic_Gesture_CVPR_2026_paper.html) | human_human_interaction<br>streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands<br>extended.multi_actor | P0 | primary_verified |
| InteracTalker | human_human_interaction<br>streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands<br>extended.multi_actor | P0 | discovery_indexed_primary_verification_pending |
| [UMF](https://arxiv.org/abs/2603.27040) | human_human_interaction<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>extended.multi_actor | P1 | primary_linked |
| ArtHOI | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| Contact Matrix | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| MaMi-HOI | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| ViHOI | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| Hoi3DGen | human_object_interaction<br>human_scene_and_behavior_generation | extended.object_contact<br>extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| [Real-Time Human-Centric World Model for Upper-Body HOI](https://arxiv.org/abs/2607.23517) | human_object_interaction<br>human_scene_and_behavior_generation | extended.object_contact<br>extended.scene_and_long_horizon_behavior | P2 | primary_verified |
| Dynamic Worlds, Dynamic Humans | human_scene_and_behavior_generation | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| MaskAdapt | human_scene_and_behavior_generation | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| SceMoS | human_scene_and_behavior_generation | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| [PHYLOMAN](https://openaccess.thecvf.com/content/CVPR2026F/html/Zhang_PHYLOMAN_Generative_Behavior_Control_via_Fusing_LLM_Planning_and_Physics-based_CVPRF_2026_paper.html) | human_scene_and_behavior_generation<br>physics_and_humanoid_policy | bridge.policy_trajectory | P2 | primary_verified |
| ExpertEdit | motion_editing_inbetweening_and_retargeting | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| InterEdit | motion_editing_inbetweening_and_retargeting | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| MotionMERGE | motion_editing_inbetweening_and_retargeting | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| Skinned Motion Retargeting with Spatially Adaptive Interaction Guidance | motion_editing_inbetweening_and_retargeting | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| Unified Conditional Flow for Motion Generation, Editing and Intra-Structural Retargeting | motion_editing_inbetweening_and_retargeting | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| Self-Intersection-Aware Sphere Proxy | motion_editing_inbetweening_and_retargeting<br>supporting_method_dataset_or_evaluation | direct.motion_ir.editing_and_retarget<br>module.not_worker | P1 | discovery_indexed_primary_verification_pending |
| [Motion-Adapter](https://arxiv.org/abs/2604.16135) | motion_editing_inbetweening_and_retargeting<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>direct.motion_ir.editing_and_retarget | P1 | primary_linked |
| MotionMaster | motion_editing_inbetweening_and_retargeting<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| AtomicDance | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| InfiniteDance | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MACE-Dance | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MambaDance | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [OpenDanceNet](https://openaccess.thecvf.com/content/CVPR2026/html/Zhang_OpenDance_Multimodal_Controllable_3D_Dance_Generation_with_Large-scale_Internet_Data_CVPR_2026_paper.html) | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | primary_verified |
| TokenDance | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [RoboPerform](https://openaccess.thecvf.com/content/CVPR2026/html/Li_Do_You_Have_Freestyle_Expressive_Humanoid_Locomotion_via_Audio_Control_CVPR_2026_paper.html) | music_and_dance<br>physics_and_humanoid_policy | bridge.policy_trajectory | P1 | primary_verified |
| One-Shot Humanoid Whole-Body Motion Adaptation with Walking Priors | physics_and_humanoid_policy | bridge.policy_trajectory | P3 | discovery_indexed_primary_verification_pending |
| WaveSync | physics_and_humanoid_policy<br>streaming_avatar_and_speech_gesture | bridge.policy_trajectory<br>direct.motion_ir.streaming_whole_body_face_hands | P0 | discovery_indexed_primary_verification_pending |
| [DMC](https://arxiv.org/abs/2602.18199) | physics_and_humanoid_policy<br>text_and_general_motion | bridge.policy_trajectory<br>direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [MotionVLA](https://arxiv.org/abs/2606.15142) | physics_and_humanoid_policy<br>text_and_general_motion | bridge.policy_trajectory | P1 | primary_linked |
| [Re²MoGen](https://arxiv.org/abs/2604.17807) | physics_and_humanoid_policy<br>text_and_general_motion | bridge.policy_trajectory<br>direct.motion_ir.body_or_whole_body | P1 | primary_verified |
| MAG | speech_gesture_and_avatar_motion<br>streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_or_offline_whole_body<br>direct.motion_ir.streaming_whole_body_face_hands | P0 | discovery_indexed_primary_verification_pending |
| ReCoM | speech_gesture_and_avatar_motion<br>streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_or_offline_whole_body<br>direct.motion_ir.streaming_whole_body_face_hands | P0 | discovery_indexed_primary_verification_pending |
| 3DGesPolicy | streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands | P0 | discovery_indexed_primary_verification_pending |
| Accelerated Rolling Diffusion for Streaming Co-Speech Gesture | streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands | P0 | discovery_indexed_primary_verification_pending |
| CoordSpeaker | streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands | P0 | discovery_indexed_primary_verification_pending |
| [EchoAvatar](https://arxiv.org/abs/2605.28272) | streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands | P0 | primary_linked |
| GlobalDiff | streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands | P0 | discovery_indexed_primary_verification_pending |
| HolisticSemGes | streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands | P0 | discovery_indexed_primary_verification_pending |
| Latent Dynamics for Full Body Avatar Animation | streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands | P0 | discovery_indexed_primary_verification_pending |
| [LiveGesture](https://openaccess.thecvf.com/content/CVPR2026/html/Saleem_LiveGesture_Streamable_Co-Speech_Gesture_Generation_Model_CVPR_2026_paper.html) | streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands | P0 | primary_verified |
| PersonaGest | streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands | P0 | discovery_indexed_primary_verification_pending |
| [SentiAvatar-SuSuInterActs](https://github.com/SentiAvatar/SentiAvatar) | streaming_avatar_and_speech_gesture | direct.motion_ir.streaming_whole_body_face_hands | P0 | primary_linked |
| Bilingual T2M Baselines | supporting_method_dataset_or_evaluation<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>module.not_worker | P1 | discovery_indexed_primary_verification_pending |
| [MotionRFT](https://arxiv.org/abs/2603.27185) | supporting_method_dataset_or_evaluation<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>module.not_worker | P1 | primary_linked |
| [VideoMDM](https://arxiv.org/abs/2606.13364) | supporting_method_dataset_or_evaluation<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>module.not_worker | P1 | primary_linked |
| [ActionPlan](https://arxiv.org/abs/2603.13500) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [ARDY](https://arxiv.org/abs/2607.08741) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| ATM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [BiTDiff](https://arxiv.org/abs/2604.04395) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| CMC | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [CMDM](https://arxiv.org/abs/2602.18057) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [CoMoVi](https://arxiv.org/abs/2601.10632) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [DC-Motion](https://arxiv.org/abs/2606.14721) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [DiMo](https://arxiv.org/abs/2602.04188) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [DrawMotion](https://arxiv.org/abs/2605.20955) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| FEEL | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| FineMoLA | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [FineXtrol](https://arxiv.org/abs/2511.18927) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [FlowCoMotion](https://arxiv.org/abs/2604.11083) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [FrankenMotion](https://arxiv.org/abs/2601.10909) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| Geometric Neural Distance Fields for Motion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| HESP | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [IAM](https://arxiv.org/abs/2604.25164) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [IRG-MotionLLM](https://arxiv.org/abs/2512.10730) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [Kimodo](https://arxiv.org/abs/2603.15546) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [LaMoGen-Symbolic](https://arxiv.org/abs/2603.11605) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [LG-Tok](https://arxiv.org/abs/2602.08337) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| Marrying T2M with Skeleton Action Recognition | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Modular Body-Part Phase Control | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MoGeFlow | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [MonoFirll](https://openaccess.thecvf.com/content/CVPR2026/html/Cao_OpenT2M_No-frill_Motion_Generation_with_Open-source_Large-scale_High-quality_Data_CVPR_2026_paper.html) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_verified |
| [MoRAE](https://arxiv.org/abs/2607.29180) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| MoSCo | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MoTiGA | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MotionGPT3-Flow | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MotionHiFlow | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [MoTok](https://arxiv.org/abs/2603.19227) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| Neural Riemannian Motion Fields | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Next-Scale Autoregressive Motion Model | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [Odoriko](https://arxiv.org/abs/2606.21135) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| Open the Motion Door | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [ParTY](https://arxiv.org/abs/2603.09611) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [PRISM](https://arxiv.org/abs/2603.08590) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| ReAlign | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Retrieval-Guided Diffusion Noise Optimization for Motion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [Riemannian Motion Generation](https://arxiv.org/abs/2603.15016) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [ScaleMoGen](https://arxiv.org/abs/2605.11704) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [SegMo](https://arxiv.org/abs/2512.21237) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [Sketch2Motion](https://arxiv.org/abs/2605.28394) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| Superman | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| TCA-T2M | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | identifier_conflict_requires_verification |
| [TriC-Motion](https://arxiv.org/abs/2602.08462) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [UMO](https://arxiv.org/abs/2603.15975) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| [UniMotion-2026](https://arxiv.org/abs/2603.22282) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |

## 2025（237 个唯一条目）

| 模型/系统 | 类别 | VIREA 接入轨道 | 优先级 | 证据状态 |
|---|---|---|---:|---|
| ALERT-Motion | adjacent_video_avatar_or_non_generator | adjacent.no_stable_motion_tensor | X | discovery_indexed_primary_verification_pending |
| EchoMimic | adjacent_video_avatar_or_non_generator | adjacent.no_stable_motion_tensor | X | discovery_indexed_primary_verification_pending |
| EchoMimicV2 | adjacent_video_avatar_or_non_generator | adjacent.no_stable_motion_tensor | X | discovery_indexed_primary_verification_pending |
| EchoMimicV3 | adjacent_video_avatar_or_non_generator | adjacent.no_stable_motion_tensor | X | discovery_indexed_primary_verification_pending |
| LLM Knowledge of Human Motion for 3D Avatar Control | adjacent_video_avatar_or_non_generator | adjacent.no_stable_motion_tensor | X | discovery_indexed_primary_verification_pending |
| OmniAvatar | adjacent_video_avatar_or_non_generator | adjacent.no_stable_motion_tensor | X | discovery_indexed_primary_verification_pending |
| PersonaHOI | adjacent_video_avatar_or_non_generator | adjacent.no_stable_motion_tensor | X | discovery_indexed_primary_verification_pending |
| SpeakerVid-5M | adjacent_video_avatar_or_non_generator | adjacent.no_stable_motion_tensor | X | discovery_indexed_primary_verification_pending |
| ChoreoMuse | adjacent_video_avatar_or_non_generator<br>music_and_dance | adjacent.no_stable_motion_tensor<br>direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Human Motion Unlearning | adjacent_video_avatar_or_non_generator<br>supporting_method_dataset_or_evaluation | adjacent.no_stable_motion_tensor<br>module.not_worker | X | discovery_indexed_primary_verification_pending |
| DGFM | foundational_speech_music_and_interaction<br>music_and_dance | direct.motion_ir.body_or_whole_body<br>direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| ARFlow | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| DuetGen | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Dyadic Mamba | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| E-React | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Interact2Ar | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Interactive Humanoid | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| InterMamba | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| InterMask | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Invisible Strings | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Large-Scale Multi-Character Interaction Synthesis | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Leader and Follower | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| MARRS | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Multi-Person Interaction Generation from Two-Person Priors | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| PhysInter | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| PINO | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Ponimator | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Ready-to-React | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Seamless Interaction | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| SocialGen | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Text2Interact | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Think Then React | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| TIMotion | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| Towards Immersive Human-X Interaction | human_human_interaction | extended.multi_actor | P2 | discovery_indexed_primary_verification_pending |
| HERO | human_human_interaction<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>extended.multi_actor | P1 | discovery_indexed_primary_verification_pending |
| MoReact | human_human_interaction<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>extended.multi_actor | P1 | discovery_indexed_primary_verification_pending |
| SOLAMI | human_human_interaction<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>extended.multi_actor | P1 | discovery_indexed_primary_verification_pending |
| ARDHOI | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| ChainHOI | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| CoDA | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| CoopDiff | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| DiffGrasp | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| Directionally Controllable 3D Whole-Body Grasp | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| EigenActor | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| EJIM | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| GenHOI | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| HHOI | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| HOI-Dyn | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| HOI-PAGE | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| HOIDiNi | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| HOIGPT | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| HOSIG | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| Human-Object Interaction from Human-Level Instructions | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| InteractAnything | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| InteractMove | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| InterMimic | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| InterPose | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| MaskedManipulator | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| MotionVerse | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| OnlineHOI | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| Phys-Reach-Grasp | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| PhysicsFC | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| ROG | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| SemGeoMo | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| SkillMimic | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| SkillMimic-v2 | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| SMGDiff | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| SyncDiff | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| TriDi | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| UniHM | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| ZeroHOI | human_object_interaction | extended.object_contact | P2 | discovery_indexed_primary_verification_pending |
| RMD-HOI | human_object_interaction<br>human_scene_interaction | extended.object_contact<br>extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| Being-M0.5 | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| Event-Driven Storytelling with Multiple Lifelike Humans | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| FantasyHSI | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| GenHSI | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| GHOST | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| Half-Physics | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| HSI-GPT | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| Joint Command-and-Intention Understanding for HSI | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| Prime and Reach | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| SceneAdapt | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| SceneMI | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| SIMS | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| Sitcom-Crafter | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| SSOMotion | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| TokenHSI | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| TSTMotion | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| Uni-Inter | human_scene_interaction | extended.scene_and_long_horizon_behavior | P2 | discovery_indexed_primary_verification_pending |
| AnyMoLe | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| AStF | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| ClusterStyle | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| MixerMDM | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| MotionPersona | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| MotionReFit | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| Part-Wise Phase Editable Motion In-Betweening | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| SimMotionEdit | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| StableMotion | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| StyleMotif | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| TF-JAX-IK | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| Visual Persona | motion_editing_inbetweening_and_stylization | direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| MotionLab | motion_editing_inbetweening_and_stylization<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| PRIMAL | motion_editing_inbetweening_and_stylization<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| SALAD | motion_editing_inbetweening_and_stylization<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>direct.motion_ir.editing_and_retarget | P1 | discovery_indexed_primary_verification_pending |
| Align Your Rhythm | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Dance Like a Chicken / LoRA-MDM | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| DanceMosaic | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| FlowerDance | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| GCDance | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MatchDance | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MEGADance | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MotionRAG-Diff | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| PAMD | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| ReactDance | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| TempoMOE | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| UniMuMo | music_and_dance | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Contextual Gesture | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| EchoMotion | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| ExGes | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| GestureLSM | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Grounded Gestures | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Hierarchical Implicit Periodicity Co-Speech Generator | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| HoloGest | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| HOP | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Intentional Gesture | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| M3G | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MECo | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| SemTalk | speech_gesture_and_avatar_motion | direct.motion_ir.streaming_or_offline_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Motion-2-to-3 | supporting_method_dataset_or_evaluation<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>module.not_worker | P1 | discovery_indexed_primary_verification_pending |
| Quest for Generalizable Motion Generation | supporting_method_dataset_or_evaluation<br>text_and_general_motion | direct.motion_ir.body_or_whole_body<br>module.not_worker | P1 | discovery_indexed_primary_verification_pending |
| ACMDM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| ACMo | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Aleatoric Uncertainty Motion Generator | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| ANT | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| AnyTop | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| AtoM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Back to Basics | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Being-M0 | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| BioMoDiffuse | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| CASIM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| CLoSD | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| COMET | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| ControlMM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| DART | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| DeMoGen | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| DisCoRD | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| DSDFM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| EnergyMoGen | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Fg-T2M++ | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| FlexMotion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Free-T2M | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Free3D | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| FunPhase | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| GenM3 | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| GENMO | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Go to Zero / MotionMillion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| GORP / Sparse Signal to Smooth Motion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| HGM³ | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| HiSTF Mamba | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| HMVLM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| HumanAttr | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| HY-Motion 1.0 | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| IKMo | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| InfiniDreamer | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Kinetic Mining in Context | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| KinMo | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| LaMoGen-Laban | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| LaMP | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Language of Motion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Less Is More | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Light-T2M | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| [LLaMo-2025](https://arxiv.org/abs/2411.16805) | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | primary_linked |
| LS-GAN | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| LUMA | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MARDM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MCG-IMM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Mem-MLP | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MG-MotionLLM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MoCLIP | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MoGIC | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MoLingo | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MonSTeR | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MoRAG | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Morph | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MoSa | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MOST | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Motion Anything | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Motion-Agent | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Motion-R1 | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MotionCraft | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MotionDreamer | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MotionFLUX | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MotionGlot | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MotionGPT3 | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MotionPCM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MotionStreamer | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Move in 2D | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MSQ | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| MVLift | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| No MoCap Needed | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| OmniMoGen | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| OmniMotion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| OmniMotion-X | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| PackDiT | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| PedGen | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| PersonalBooth | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| PlanMoGPT | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| PMG-SparseAnchor | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| PMG-TextFewFrames | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Pose-Guided Residual Refinement | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Pressure2Motion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Pulp Motion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| PUMPS | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| ReinDiffuse | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| ReMoGPT | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| ReMoMask | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| ScaMo | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Semantics-Aware Motion from Audio Instructions | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| SFControl | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Shape My Moves | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| SimDiff | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Sketch2Anim | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| SmooGPT | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| SnapMoGen | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Sparse Interpretable Motion Characterization | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| StickMotion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| TCM | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Temporal-Spatial Composition of Motion Diffusion Models | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| TransPhase | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| UniEgoMotion | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| Unified Multi-Modal Interactive and Reactive Motion via Rectified Flow | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| UniMo | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| UniMoGen | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| UniMotion-3DV2025 | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| UniPose | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| VimoRAG | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |
| X-MoGen | text_and_general_motion | direct.motion_ir.body_or_whole_body | P1 | discovery_indexed_primary_verification_pending |

## 2024（65 个唯一条目）

| 模型/系统 | 类别 | VIREA 接入轨道 | 优先级 | 证据状态 |
|---|---|---|---:|---|
| CondMDI | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| DiffPoseTalk | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| ExpGest | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| InterDance | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| L3EM | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| Lodge++ | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| MoMu-Diffusion | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| Open-Domain Multi-Person Motion Synthesis | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| PIDM | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| SMooDi | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| synNsync | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| SynTalker | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| TesMo | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| Word-Conditioned 3D ASL Motion Generation | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| MotionLCM | foundational_speech_music_and_interaction<br>foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body<br>direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| AvatarGPT | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| BAD | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| BAMM | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| BiPO | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| CAMDM | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| CoMA | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| CoMo | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Cross-Diffusion Motion | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| EMDM | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Everything2Motion | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| FG-MDM | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| FreeMotion-MoCapFree | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| FreeMotion-NumberFree | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| FTMoMamba | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| GPHLVM | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| GuidedMotion | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| HumanTOMATO | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Kinematic Phrases | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| KMM | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| LEAD | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Length-Aware Motion Synthesis | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| LGTM | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| LMM | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| M2D2M | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| M3GPT | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MHC | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MMM | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MMoFusion | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MoGenTS | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Mogo | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MoMask | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MoTe | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Motion Mamba | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MotionChain | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MotionCLR | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MotionGPT-2 | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MotionLLM | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MotionMix | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| MotionRL | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| ParCo | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| ProMotion | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| RMD | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| SATO | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| SoPo | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| StableMoFusion | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| T2M-X | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| Text Motion Translator | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| TLcontrol | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| UDE-2 | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |
| UniMTS | foundational_text_and_general_motion | direct.motion_ir.body_or_whole_body | P0 | discovery_indexed_primary_verification_pending |

## 2023（51 个唯一条目）

| 模型/系统 | 类别 | VIREA 接入轨道 | 优先级 | 证据状态 |
|---|---|---|---:|---|
| AMUSE | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| CHOIS | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| COLLAGE | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| Duolando | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| EDGE | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| EMAGE | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| F-HOI | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| FineDance | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| GestureDiffuCLIP | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| HGHOI | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| HIMO | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| InterControl | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| InterDiff | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| InterFusion | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| InterGen | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| Listen-Denoise-Action | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| Lodge | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| NIFTY | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| OMOMO | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| PhysReaction | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| ReGenNet | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| ReMoS | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| Rhythmic Gesticulator | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| Two in One | foundational_speech_music_and_interaction | direct_or_extended.motion_ir | P0 | discovery_indexed_primary_verification_pending |
| AttT2M | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| DNO | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| EMS | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| Fg-T2M | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| FineMoGen | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| FlowMDM | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| GMD | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| GraphMotion | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| MAA | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| MLD | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| MoDi | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| MoFusion | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| MotionDiffuse | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| MotionFix | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| MotionGPT | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| OmniControl | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| OOHMG | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| PhysDiff | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| PriorMDM | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| ProgMoGen | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| ReMoDiffuse | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| SINC | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| STMC | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| Story-to-Motion | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| T2M-GPT | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| TMR | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |
| UDE | foundational_text_and_general_motion | direct.motion_ir.body | P0 | discovery_indexed_primary_verification_pending |

## 2022_and_earlier（40 个唯一条目）

| 模型/系统 | 类别 | VIREA 接入轨道 | 优先级 | 证据状态 |
|---|---|---|---:|---|
| ACTOR | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| AIST++ Baseline | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| AMP | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| ASE | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| Audio2Gesture | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| Bailando | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| Bailando++ | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| BEAT Baselines | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| CALM | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| CaMN | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| COINS | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| COUCH | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| DeepMimic | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| DiffGesture | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| DiffuseStyleGesture | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| DIMOS | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| FACT | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| GAMMA | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| GOAL | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| HMDM | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| HUMANISE | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| HumanML3D Baseline | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| InsActor | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| MDM | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| MoConVQ | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| MotionCLIP | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| NSM | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| PADL | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| PHC | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| PoseGPT | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| PULSE | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| SAGA | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| SAMP | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| SceneDiffuser | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| Speech2Gesture | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| StyleGestures | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| TalkSHOW | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| TEMOS | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| TM2T | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |
| ZeroEGGS | historical_foundations | direct_or_bridge | P0 | discovery_indexed_primary_verification_pending |

## cross_year（13 个唯一条目）

| 模型/系统 | 类别 | VIREA 接入轨道 | 优先级 | 证据状态 |
|---|---|---|---:|---|
| ALERT-Motion Attack | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| AnyLift Motion Reconstruction | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| BEAT2 | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| EasyTune | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| Exploring Motion-Language Alignment | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| FineMotion Dataset and Benchmark | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| GBC-100K | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| MotionGB | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| MotionMillion | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| OpenDanceSet | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| [OpenT2M Dataset and 2D-PRQ Tokenizer](https://arxiv.org/abs/2603.18623) | supporting_method_dataset_or_evaluation | module.not_worker | X | primary_verified |
| SpeakerVid-5M Dataset | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |
| SuSuInterActs | supporting_method_dataset_or_evaluation | module.not_worker | X | discovery_indexed_primary_verification_pending |


## 5. 推荐接入顺序

### P0：先形成通用纵向闭环

- HumanML3D/KIT 263D/body22：`MoMask`、`MotionLCM`、`MDM`、`T2M-GPT`、`MotionGPT`、`MonoFirll`。
- SMPL-X whole-body：`HumanTOMATO`、`EMAGE`、`SentiAvatar/SuSuInterActs`、`OmniMotion-X`。
- 流式语音：`LiveGesture`、`EchoAvatar`、`GestureLSM`、`SemTalk`、`ReCoM`。
- 通用骨架：`AnyTop`、`PUMPS` 和 generic BVH/FBX contract。

### P1：条件控制与编辑

关键帧、轨迹、草图、图像、视频、音乐、稀疏姿态、editing、in-betweening、stylization、hand 和 sign。

### P2：扩展 Motion IR

多角色、object/contact、scene/affordance 与 long-horizon behavior。没有对应轨道便硬接交互模型，只会把最有价值的交互语义剥掉，然后留下一具“能动”的骨架，十分符合软件行业对完成度的传统定义。

### P3：Policy bridge

`RoboPerform`、`MotionVLA`、`PHYLOMAN`、`CLoSD` 等输出 policy/action/trajectory 的系统进入独立桥接层，不与普通 motion tensor decoder 混合。

## 6. 维护约束

1. 新模型通过 registry PR 加入，不在 CLI、前端或 server 中硬编码。
2. 每个实现版本绑定论文/代码 revision、权重 hash、runtime hash、许可证 snapshot 和原生输出 schema。
3. `source_status != primary_verified` 不能直接标记 release-ready。
4. 同名论文保留独立 UID，例如 `LLaMo-2025`/`LLaMo-2026`、`UniMotion-3DV2025`/`UniMotion-2026`、两种 `LaMoGen` 和两种 `PMG`。
5. 索引冲突必须显式暴露。当前 `TCA-T2M` 的 arXiv 标识仍待独立核验。
