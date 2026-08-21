# WP00 已知行为与兼容边界

本文记录 2026-08-20 工作树中已经存在、后续重构需要明确保留或显式迁移的行为。它描述现状，不把现状全部认定为理想设计。

## Canonical 211

- `FRAME_DIM = 7 + 21 * 4 + 30 * 4 = 211`。每帧顺序为 root translation 3、root rotation 4、core rotation 84、hand rotation 120。
- canonical schema 为 `virea.canonical_motion.v3.0.0`，skeleton 为 `virea_canonical_skeleton.v3`，rotation semantics 为 `rest_relative_normalized_pose_delta`。
- `pack_sequence` 把输入转换为 `float32`，拒绝 shape 错误、NaN/Infinity 和零长度 quaternion；每个 quaternion 单位化，并在相邻帧 dot product 小于 0 时翻转当前帧符号。
- `unpack_sequence` 要求精确 `(T, 211)`，并以 `1e-4` 容差拒绝非单位 quaternion。它不自行重新单位化或重新做同半球处理。
- `pack_sequence(**unpack_sequence(sequence))` 对有效、已规范化的 packed sequence 在浮点容差内保持不变。

实现证据：`src/virea/motion/canonical.py`。冻结证据：`tests/characterization/test_canonical211_contract.py`。

## Schema 身份

| 文档 | `$id` | payload/version const |
| --- | --- | --- |
| canonical artifact | `urn:virea:schema:canonical-artifact:3.0.0` | `virea.canonical_artifact.v3.0.0` |
| motion sample | `urn:virea:schema:motion-sample:3.0.0` | `virea.motion_sample.v3.0.0` |
| preview payload | `urn:virea:schema:preview-payload:1.0.0` | `virea.preview_payload.v1.0.0` |

Canonical artifact 还固定 processing `v0.4.0`、canonical v3、211、`<f4` 和 `xyzw`。Preview 中 VRM motion 固定为 `virea.vrm_motion_payload.v3.0.0`，并引用 canonical v3 rotation semantics。后续 schema 演进应新增版本，不应原地改变已有 URI 的含义。

## CLI parser

当前命令和默认值：

- `process`：`data_source=""`、`datasets=[]`、`query=""`、`limit_per_dataset=0`、`max_frames=None`、`workers=0`、`skip_existing=True`、`force=False`。
- `serve`：`data_source="demo"`、`host=""`、`port=None`、`reload=False`。
- `build-demo`：`samples_per_dataset=100`、`overwrite=False`。

Parser 要求必须给出 subcommand；三个 handler 分别是 `_cmd_process`、`_cmd_serve`、`_cmd_build_demo`。新增命令可以添加，但重命名或改变上述默认值属于用户可见变更，需要迁移说明和契约测试更新。

## Preview HTTP 路由

当前应用工厂公开以下业务路由：

| 方法 | 路径 | route name |
| --- | --- | --- |
| GET | `/` | `root` |
| GET | `/api/health` | `health` |
| GET | `/api/catalog` | `catalog` |
| GET | `/api/artifacts/sidecars/{digest}` | `artifact_sidecar` |
| GET | `/api/datasets` | `datasets` |
| GET | `/api/samples` | `samples` |
| GET | `/api/preview/source` | `preview_source` |
| GET | `/api/preview/processed` | `preview_processed` |
| GET | `/api/preview/motion` | `preview_motion` |
| GET | `/api/preview/quality` | `preview_quality_endpoint` |
| GET | `/api/preview/source/binary` | `preview_source_binary` |
| GET | `/api/preview/processed/binary` | `preview_processed_binary` |
| GET | `/api/preview/on-demand` | `preview_on_demand` |
| GET | `/api/preview` | `preview_legacy` |
| POST | `/api/process` | `process` |
| POST | `/api/batch` | `batch_process` |

Characterization 只创建 app 并检查 route table，不触发 handler 或真实数据读取。

## Viewer normalized humanoid

- Viewer 通过 `vrm.humanoid.setNormalizedPose(pose)` 应用姿态。
- 若 avatar-to-canonical 世界对齐为 `A`、canonical 局部旋转为 `q`，传入 normalized humanoid 的局部旋转为 `A^-1 q A`；测试用向量作用等式验证该性质，而不是只比较某个固定 quaternion。
- VRM 0 的规范默认是 180° Y yaw `[0, 1, 0, 0]`，VRM 1 默认是 identity `[0, 0, 0, 1]`；未知 meta version 返回 `null` 并由加载路径拒绝。
- 诊断契约当前固定 `legacyTerminalSelfConjugationCount=0`、`targetRestCorrectionCount=0`、`restFrameCorrectionCount=0`。
- `vrm-viewer.js` 中没有针对 AMASS、BABEL、BEAT、GRAB、HumanML3D、Motion-X、MoMask、MDM、FLOOD 或 SentiAvatar 名称的专修分支。WP00 测试冻结这一“normalized humanoid + 零已知模型专修”边界。

已知文字不一致：`setMotionPayload` 的成功状态仍显示 `Canonical v2 normalized-pose motion contract accepted`，而 schema 与验证逻辑为 canonical v3。后续可以修正文案，但不应借此改变 v3 数学/数据契约。

## 当前不一致与风险

- `pyproject.toml` 和 FastAPI app 报告版本 `0.2.0`，`src/virea/__init__.py` 报告 `0.1.0`。在统一版本来源前，调用方可能观察到不同版本。
- schema/version 常量分布在多个 Python/JSON/JavaScript 文件；若只修改其中一处，会造成 artifact、API 与 Viewer 拒绝彼此。Characterization 测试目前覆盖主要交叉引用，但不是完整 schema validation。
- 现有完整测试包含真实数据和本地资源 opt-in；WP00 测试刻意不依赖这些资源，因此只证明接口和纯数学基线，不证明模型效果。
- 当前没有仓库级 CI 配置。后续将 characterization 纳入 CI 前，需要先确定支持的 Python/Node 版本矩阵。

<!--
type: reference
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-20
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: VIREA 重构必须保留或显式迁移的 canonical、CLI、API 与 Viewer 行为边界。
canonical: doc/refactor/KNOWN_BEHAVIOR.md
related:
  - doc/refactor/BASELINE_REPORT.md
  - doc/refactor/QA_PLAN.md
  - doc/adrs/0003-multi-package-isolated-model-runtimes.zh-CN.md
supersedes: []
superseded_by: []
-->
