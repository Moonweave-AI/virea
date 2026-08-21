# WP00 重构基线报告

快照日期：2026-08-20

历史工作分支：`codex/vmf-stage1`（仅用于识别 2026-08-20 基线；训练支线已于 2026-08-21 退役）

基线提交：`bba6c414dd99ec632046825f43ea11e711b56afe`

## 结论

本报告冻结重构前可以由轻量、无真实数据 fixture 复现的公共契约。新增测试只读取生产模块和 schema，不下载数据、不加载 checkpoint、不启动网络服务，也不改写生产代码。因此它是兼容性证据基线，不是完整模型质量、真实 Avatar 视觉或发布批准。

工作树在 WP00 开始前已有大量未提交改动和未跟踪目录；本切片没有移动、覆盖或清理这些内容，只新增 `tests/characterization/` 与本目录下两份文档。

## 已冻结的契约

| 边界 | 当前契约 | Characterization 证据 |
| --- | --- | --- |
| Canonical motion | 7 root 维、21 个 core quaternion、30 个 hand quaternion，共 211 个 little-endian-compatible `float32` 数值；quaternion 为 `xyzw`、单位化并在 pack 时做相邻帧同半球连续化 | `tests/characterization/test_canonical211_contract.py` |
| Schema URI | canonical artifact `urn:virea:schema:canonical-artifact:3.0.0`；motion sample `urn:virea:schema:motion-sample:3.0.0`；preview payload `urn:virea:schema:preview-payload:1.0.0` | `tests/characterization/test_public_surface_contract.py` |
| CLI | `virea process`、`virea serve`、`virea build-demo`，包括当前 handler 与默认参数 | `tests/characterization/test_public_surface_contract.py` |
| Preview HTTP | `/` 与 15 个 `/api/*` 路由的方法、路径和 route name | `tests/characterization/test_public_surface_contract.py` |
| Viewer | normalized humanoid 使用 `A^-1 q A` 局部旋转共轭；VRM 0/1 世界对齐保持规范默认；legacy/target-rest/rest-frame 修正计数均为 0 | `tests/characterization/viewer_contract.test.mjs` |

直接证据来自：

- `src/virea/motion/canonical.py`
- `src/virea/cli.py`
- `src/virea/server/app.py`
- `src/virea/pipelines/artifact_manifest.py`
- `src/virea/data/annotations.py`
- `schemas/canonical_artifact.schema.json`
- `schemas/motion_sample.schema.json`
- `schemas/preview_payload.schema.json`
- `apps/viewer-web/vrm-canonical-alignment.js`
- `apps/viewer-web/vrm-viewer.js`

## 本次验证

环境：Python 3.12.13、Node.js v24.13.0。该段是历史表征快照，不是当前安装指南。

```text
$ $env:PYTHONPATH='src;.'
$ python -m pytest tests/characterization -q
......                                                                   [100%]
6 passed in 0.48s

$ node --test tests/characterization/viewer_contract.test.mjs
3 passed, 0 failed
```

测试的输入全部在测试中合成。HTTP 测试只检查 FastAPI route table，不访问数据目录或端点。

## 当前架构基线

- Python 包采用 `src/virea/` 布局，`virea.cli:main` 是 console script；核心依赖声明在 `pyproject.toml`。
- canonical 数学与布局位于 `src/virea/motion/canonical.py`；artifact/schema 常量分布在 motion、pipeline 与 annotation 模块。
- Preview Runtime 使用 FastAPI，应用工厂为 `src/virea/server/app.py:create_app`。
- Viewer 是 `apps/viewer-web/` 下的 ES module，normalized humanoid 对齐的纯函数位于 `vrm-canonical-alignment.js`。
- 仓库根没有 `.github/`，当前没有可由本报告确认的 CI 门禁。

## 未在 WP00 验证的范围

- 未运行完整 Python/Viewer 测试套件，未执行真实数据、真实 VRM、浏览器视觉或 GPU/模型推理回归。
- `doc/validation.zh-CN.md` 记录的 `155 passed / 36 skipped` 与 Viewer `57 passed` 是 2026-08-10 的历史结果，本次没有重跑，不能当作当前工作树结果。
- 未验证 draft dataset profile 的发布状态，也未验证新增 2025–2026 模型的质量或可复现性。
- 本报告不冻结内部私有函数、文件组织或模型实现；后续可以在保持上述外部契约或提供显式兼容层的前提下重构。

## 后续切片入口

后续重构应先让新 adapter/registry 实现通过本目录测试，再按模型逐个增加 test-only adapter fixture、官方 checkpoint 真实推理、production acceptance 和真实数据 opt-in 测试；fixture 不作为发布证据。若必须更改 schema URI、211 布局、CLI 或 Preview 路由，应先提供版本化新契约与旧契约兼容/迁移测试。

<!--
type: report
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-20
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: VIREA 0.3 重构前公共契约、可复现证据与未验证范围的基线报告。
canonical: doc/refactor/BASELINE_REPORT.md
related:
  - doc/refactor/KNOWN_BEHAVIOR.md
  - doc/refactor/QA_PLAN.md
  - doc/refactor/WP00_WP15_IMPLEMENTATION_MAP.md
  - doc/rfcs/0003-virea-0.3-multi-model-refactor.zh-CN.md
supersedes: []
superseded_by: []
-->
