---
type: readme
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 30
summary: VIREA 的项目入口、状态、最短运行路径和文档导航。
canonical: README.md
related:
  - doc/README.zh-CN.md
  - doc/rfcs/0001-annotation-time-retarget-v1.zh-CN.md
  - doc/adrs/0001-versioned-motion-semantics-and-artifacts.zh-CN.md
supersedes: []
superseded_by: []
---

# VIREA

VIREA 把异构人体动作、文本标注和多模态上下文转换成可验证、可回放的 VRM/glTF humanoid motion。

```text
七类数据集
  -> Adapter 保留源事实
  -> Dataset Profile 解释 FPS / basis / unit / rotation / root semantic
  -> Codec 解码源运动
  -> Retarget 生成 canonical motion
  -> Artifact 固化数学与语义
  -> Viewer 对照 source / processed / real VRM
```

VRM 不是 SMPL-X pose vector。SMPL、SMPL-H、SMPL-X、BVH、263D 和 6D rotation 是源运动表示；VRM 是建立在 glTF node、skin 和 humanoid bone mapping 上的 Avatar 规范。

## 状态

项目正在执行 [RFC-0001](doc/rfcs/0001-annotation-time-retarget-v1.zh-CN.md) 定义的 Major-refactor，目标产物版本为 `v0.2.0`。当前边界如下：

- `v0.1.0` 产物只能只读兼容；缺失的标注、profile、rest 或 channel 不会被猜测补齐。
- 新语义必须从 raw 数据重新构建，不能从历史 metadata 凭空恢复。
- Dataset Profile 按 `draft -> source_verified -> regression_verified -> release_ready` 推进；未验证 profile 不进入正式批处理或公开看板。
- 仓库中的旧 Showcase 媒体只证明文件存在，不自动证明 v0.2 数学、真实 VRM 对齐或再分发许可已通过。当前证据状态见 [Showcase 说明](doc/showcase/README.md)。

## 支持范围

| 数据集 | 源运动主路径 | 主要语义 |
|---|---|---|
| AMASS | SMPL/SMPL-H body axis-angle | 通常无原生动作文本；文件名只能作为推导信息 |
| BABEL | AMASS carrier motion | sequence 与时间区间动作标注 |
| BEAT | 上游 BVH 转换后的 body22 axis-angle | gesture、语义区间、原始 ordinal score、音频/表情可用性 |
| GRAB | SMPL-X 55-joint fullpose | 交互物体、动作上下文、逐帧接触 |
| HumanML3D | 263D feature 到 22-joint positions | caption 与可选时间区间 |
| Motion-X | 322D SMPL-X-derived array | sequence/body/hand/face text 与表情通道 |
| SuSuInterActs | body/hand 6D rotation 与可选 positions | 中文对话、face/audio channel |

逐数据集的原生事实、上游转换和仓库边界见 [数据集审计](doc/dataset-audit.zh-CN.md)。

## Quick start

要求：Python 3.10+、Node.js 20+。大型数据集与 `.vrm` 保持在仓库外。仓库提交
`uv.lock`；需要逐包一致的环境时使用 `uv sync --extra dev`，下面的 venv/pip 路径
用于没有 uv 的系统。

Windows PowerShell：

```powershell
git clone git@github.com:Moonweave-AI/virea.git
Set-Location virea
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
npm ci
python -m virea serve --data-source demo
```

macOS / Linux：

```bash
git clone git@github.com:Moonweave-AI/virea.git
cd virea
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
npm ci
python -m virea serve --data-source demo
```

页面若提示 Three.js 或 VRM runtime 不可用，先确认 `npm ci` 成功，再重启服务。完整数据准备、环境变量和处理命令见 [Pipeline 使用指南](doc/pipeline.zh-CN.md)。

## 使用外部数据与 VRM

路径通过 CLI 或环境变量传入，不写入代码或文档。示例只使用占位符：

```powershell
$env:VIREA_RAW_ROOT = "<full-raw-root>"
$env:VIREA_PROCESSED_ROOT = "<processed-v0.2-root>"
python -m virea process --data-source full --workers 8 --force
```

```bash
export VIREA_RAW_ROOT="<full-raw-root>"
export VIREA_PROCESSED_ROOT="<processed-v0.2-root>"
python -m virea process --data-source full --workers 8 --force
```

GRAB 与 SuSuInterActs 的既有公开容器包含 NumPy object/pickle。VIREA 默认拒绝读取，
因为仅查看预览也可能触发任意代码执行。只有在本地核验过来源与哈希后，才可为该次
离线会话显式设置 `VIREA_ALLOW_TRUSTED_RAW_PICKLE=1` 并重启；公开或远程服务不得开启，
分发前应迁移为不含 object dtype 的数组格式。AMASS、BABEL、BEAT、HumanML3D 与
Motion-X 的数值入口始终使用 `allow_pickle=False`。

Viewer 从本地文件选择器加载 `.vrm`。Showcase renderer 也支持 `--vrm <path>` 或 `VIREA_SHOWCASE_VRM`；模型绝对路径和模型文件本身都不得提交。

## 验证

```bash
python -m compileall -q src
python -m pytest -q
npm run check
npm run test:viewer
python scripts/check_docs.py
python scripts/smoke_pipeline.py --data-source demo --max-frames 8
```

这些命令只验证其实际覆盖的层。只有 [分层验收清单](doc/validation.zh-CN.md) 中 source decode、basis、canonical、target FK、真实 VRM、真实时间播放、媒体与许可门禁全部有证据时，才可以声明某个数据集 `release_ready`。

## 文档

建议按以下顺序阅读：

1. [Pipeline 工程设计](doc/engineering-design.zh-CN.md)
2. [Annotation 与 Viewer 契约](doc/annotation-viewer.zh-CN.md)
3. [Retarget 数学共同层](doc/math-retarget/README.zh-CN.md)
4. [五类 source retarget](doc/README.zh-CN.md#五类-source-retarget)
5. [七数据集审计](doc/dataset-audit.zh-CN.md)
6. [分层验收清单](doc/validation.zh-CN.md)

完整导航见 [文档索引](doc/README.zh-CN.md)，权威资料见 [参考基线](doc/references.zh-CN.md)。

## Security、许可与贡献

- Raw dataset、对话、音频、人脸通道和 VRM 都视为不可信或受限资产；Viewer 不返回 raw 绝对路径，也不把未知外部 URL 自动变成链接。
- 公开提交模型、raw 数据或派生 GIF/视频前，必须在 Showcase manifest 中得到明确的 `allowed` 决定；`local-only`、`blocked`、缺失或未知都 fail-closed。
- 本仓库尚未声明代码 LICENSE，也未提供覆盖第三方数据、模型与 attribution 的 NOTICE。各数据集和 VRM 继续受各自条款约束；仓库内容不授予再分发权限，公开 Release 保持 No-Go，直到 Owner 与 IP reviewer 明确决定。
- 贡献应保持 Adapter / Codec / Retarget / Artifact / Viewer 边界，并同步更新 schema、测试、文档和真实样本证据。涉及公共 schema、坐标约定或处理版本的修改先更新 RFC/ADR。

Owner：`@Joker-of-Gotham`。文档和实现均需人工复核；自动检查通过不等于发布批准。
