# Pipeline 使用指南

本文只讲可执行操作。数据语义参阅 [七数据集审计](dataset-audit.zh-CN.md)，数学原理参阅 [Retarget 共同层](math-retarget/README.zh-CN.md)。

## 1. 前置条件

- Git
- Python 3.10+
- Node.js 20+
- 可选：FFmpeg（WebM 转 GIF）
- 可选：Chromium（Playwright 录制 Showcase）

> [!CAUTION]
> 不要把 raw dataset、processed 全量产物、VRM 模型或机器绝对路径放进 Git。

## 2. 安装

仓库提交 `uv.lock` 作为 Python 的精确依赖锁。

**推荐方式（`uv` 锁文件，跨平台统一）：**

```bash
git clone git@github.com:Moonweave-AI/virea.git
cd virea
uv sync --extra dev
npm ci
```

<details>
<summary><strong>Windows PowerShell（标准 venv）</strong></summary>

```powershell
git clone git@github.com:Moonweave-AI/virea.git
Set-Location virea
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm ci
```

</details>

<details>
<summary><strong>macOS / Linux（标准 venv）</strong></summary>

```bash
git clone git@github.com:Moonweave-AI/virea.git
cd virea
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm ci
```

</details>

没有 uv 时仍可用标准 venv/pip；该路径遵守 `pyproject.toml` 的版本范围，但不保证与锁文件逐包一致。`npm ci` 必须成功，否则 Viewer 对 Three.js 与 three-vrm 的请求会失败。

录制 Showcase 时再安装浏览器：

```bash
npx playwright install chromium
```

Linux 若提示缺少系统库，使用 Playwright 官方针对当前发行版的 dependency 安装方式；不要把系统可执行文件绝对路径写进仓库。

## 3. 数据目录与配置优先级

`configs/project.yaml` 只保存可移植默认值。机器路径通过环境变量覆盖：

| 变量 | 作用 |
|---|---|
| `VIREA_DATA_SOURCE` | `demo` 或 `full` |
| `VIREA_DATA_ROOT` | full 数据的上层目录；未显式设置 raw root 时尝试其 `raw/` 子目录 |
| `VIREA_RAW_ROOT` | 七数据集 raw root（最高优先级） |
| `VIREA_PROCESSED_ROOT` | processed artifact root |
| `VIREA_SERVE_HOST` / `VIREA_SERVE_PORT` | API/Viewer 绑定地址 |
| `VIREA_THREE_ROOT` / `VIREA_THREE_VRM_ROOT` | 可选 JS runtime 覆盖；正常情况使用 `node_modules` |
| `VIREA_SHOWCASE_SERVER` / `VIREA_SHOWCASE_VRM` | Showcase recorder 的服务 URL 与本地 VRM |
| `VIREA_ALLOW_TRUSTED_RAW_PICKLE` | 仅对已核验的本地 GRAB/SuSu 旧 object 容器显式设为 `1`；默认禁用 |

<details>
<summary><strong>Windows PowerShell 设置示例</strong></summary>

```powershell
$env:VIREA_RAW_ROOT = "<full-raw-root>"
$env:VIREA_PROCESSED_ROOT = "<processed-root>"
```

</details>

<details>
<summary><strong>macOS / Linux 设置示例</strong></summary>

```bash
export VIREA_RAW_ROOT="<full-raw-root>"
export VIREA_PROCESSED_ROOT="<processed-root>"
```

</details>

任何日志、metadata、截图或提交中都只记录 portable relative path 或 hash，不记录真实绝对路径。

### 旧 object 容器的信任门禁

GRAB 与 SuSuInterActs 的既有 `.npz`/`.npy` 结构需要 NumPy pickle 才能展开嵌套对象。pickle 能执行代码，因此 Viewer 的只读预览也不能默认加载。只有数据来自已核验的本地副本、且你已经单独确认其来源与内容哈希时，才可为一次离线会话开启：

```bash
# Windows: $env:VIREA_ALLOW_TRUSTED_RAW_PICKLE = "1"
# macOS/Linux: export VIREA_ALLOW_TRUSTED_RAW_PICKLE=1
python -m virea serve --data-source full --host 127.0.0.1
```

开启后必须继续只监听 loopback；不要与公开 CORS、远程端口或未知数据共同使用。长期方案是把对象容器迁移成 `allow_pickle=False` 可读取的数值数组和 JSON/内容寻址 sidecar。服务健康接口只回显该门禁是否开启，不返回机器路径。

## 4. Demo 数据

下载脚本额外依赖 `huggingface_hub`：

```bash
python -m pip install huggingface_hub
python scripts/download_demo.py --raw-only --accept-local-only
```

也可使用 `--processed-only`，或不传过滤参数下载 raw + processed。下载配置在 `configs/demo_download.json`：仓库固定到完整 Git commit；脚本从该不可变 revision 读取每个文件的 Hub LFS SHA-256 或 Git blob SHA-1，下载后校验大小与内容，并生成本地 `demo/manifest.json`。目标目录中出现未列入 revision 的额外文件也会使验证失败。

> [!NOTE]
> 该 Hub dataset card 在固定 revision 上没有机器可读许可证，因此配置决定为 `local-only`。脚本默认拒绝下载，只有显式传入 `--accept-local-only` 才继续；这只是本地使用确认，不会授予再分发权限。公开 Demo 的 Release gate 仍为 No-Go，直到各数据集资产均得到独立的 `allowed` 决定。

从本机 full root 构建 fixture：

```bash
python -m virea build-demo --samples-per-dataset 7 --overwrite
```

这会复制第三方内容，只能在许可允许的本地范围使用；不要因为目录名叫 `demo` 就默认可以提交。

下载到的旧 processed demo 若是 processing `v0.1.0`，不具备 canonical v3 的 rest、hand evidence/replay 与 normalized-pose 契约。Reader 可以保留其已有 2D 几何和语义用于迁移核对，但会扣留 legacy canonical sequence，不向 Avatar 播放。应保留旧目录用于对照，并从 raw demo 重建到新的 processing `v0.4.0` root：

```bash
python -m virea process --data-source demo --workers 4 --force
```

## 5. 批处理

**Demo：**

```bash
python -m virea process --data-source demo --workers 4 --force
```

**Full（指定数据集）：**

```bash
python -m virea process --data-source full --datasets amass babel --workers 8 --force
```

**常用参数：**

| 参数 | 含义 |
|---|---|
| `--datasets` | 限定一个或多个 registry key |
| `--query` | sample id 文本过滤 |
| `--limit-per-dataset` | 每数据集上限，`0` 表示全部 |
| `--max-frames` | 调试截断；正式重建时通常省略 |
| `--workers` | `0` 自动选择，正数固定并行数 |
| `--skip-existing` / `--no-skip-existing` | 是否跳过已存在产物 |
| `--force` | 即使已有产物也重新处理 |

**关键边界：**

- RFC-0001 要求新语义写到新目录，不能覆盖 legacy root。当前配置的 `processing_version` 必须是 `v0.4.0`，产物必须同时声明 canonical motion/artifact/sample/payload v3、canonical skeleton/rest v3 与 `rest_relative_normalized_pose_delta`。
- 正式 persist 会同时检查 resolved dataset profile 的 `validation_status` 和 `hand_solver_validation_status`；任一为 `draft` 都 fail-closed，`--skip-existing` 不能绕过。
- 位置 evidence 的 `32/90` DOF 是拓扑可观测上限。PIP 弯曲小于 `0.5°` 时 signed flexion/bend plane 逐帧不可观测，公共 solver 以 float64 分析后执行 `neutral_zero_swing`；阈值、resolution 与逐 bone 左闭右开帧区间随 policy hash/certificate 持久化并由 Reader 重放。
- Reader 每次读取 v3 都重新验证内容，不用 path/size/mtime 缓存代替完整性检查；Viewer 还会对实际播放的 hand quaternion 切片重算 little-endian float32 SHA-256。Adapter 和 Viewer 都不得另行猜测弯曲平面或修正姿态。

## 6. 启动 Viewer

```bash
python -m virea serve --data-source demo --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。推荐验收顺序：

1. 选择 dataset 与 sample；
2. 检查 source skeleton、FPS、duration、annotations 与 channels；
3. 检查 processed target FK 和同一语义 payload；
4. 确认 hand certificate 通过、Viewer pose mutation 为零；
5. 从本地文件选择器加载真实 `.vrm`；
6. 检查 Avatar 独立面板、timeline、head/hand/torso/leg marker；
7. 改变播放速度、seek、filter 与窗口宽度；
8. 仅在需要保留验收证据时显式指定项目内输出目录，并记录浏览器版本、模型 hash 与 sample/artifact hash。

不要把真实模型路径设成仓库默认值。普通 GLB 或缺少 humanoid mapping 时应看到明确降级说明。

## 7. Showcase 录制

先启动 Viewer，再调用 recorder。

<details>
<summary><strong>Windows PowerShell</strong></summary>

```powershell
$env:VIREA_SHOWCASE_SERVER = "http://127.0.0.1:8000"
$env:VIREA_SHOWCASE_VRM = "<local-avatar.vrm>"
node scripts/render_showcase.mjs `
  --data-source full `
  --manifest doc/showcase/showcase-v3-samples.json `
  --out-dir showcase-output `
  --preview-seconds 15 `
  --seconds 4.5
```

</details>

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
export VIREA_SHOWCASE_SERVER="http://127.0.0.1:8000"
export VIREA_SHOWCASE_VRM="<local-avatar.vrm>"
node scripts/render_showcase.mjs \
  --data-source full \
  --manifest doc/showcase/showcase-v3-samples.json \
  --out-dir showcase-output \
  --preview-seconds 15 \
  --seconds 4.5
```

</details>

录制器会生成每库四个条目、共 28 项的本地画廊，不再把不同 FPS 都截成固定 180 帧。媒体只能在 processing v0.4/canonical v3 的 solver replay、真实样本、真实 VRM 回归和 IP decision 为 `allowed` 后公开提交。布局、manifest 与 promotion 门禁见 [Showcase 说明](showcase/README.md)。

## 8. 验证

**快速代码检查：**

```bash
python -m compileall -q src
python -m pytest -q
npm run check
npm run test:viewer
python scripts/check_docs.py
```

**真实 VRM 浏览器门禁（需要 Viewer 服务已启动、raw/VRM 路径只读通过环境变量传入）：**

<details>
<summary><strong>Windows PowerShell</strong></summary>

```powershell
$env:VIREA_QA_BASE_URL = "http://127.0.0.1:8000"
$env:VIREA_VRM_PATH = "<local-avatar.vrm>"
$env:VIREA_QA_BROWSER_PATH = "<installed-browser.exe>"   # Playwright 已装 Chromium 时可省略
$env:VIREA_QA_OUTPUT_DIR = (Join-Path (Resolve-Path ".") "qa-evidence")  # 可选
npm run qa:vrm
```

</details>

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
export VIREA_QA_BASE_URL="http://127.0.0.1:8000"
export VIREA_VRM_PATH="<local-avatar.vrm>"
export VIREA_QA_OUTPUT_DIR="$(pwd)/qa-evidence"  # 可选
npm run qa:vrm
```

</details>

默认截图写入项目内的进程级运行目录并在脚本退出时清除；只有需要保留验收证据时才设置 `VIREA_QA_OUTPUT_DIR`。

该脚本默认先预热 30 秒，再构造至少 100 条同时 active 的 annotation，连续执行 3 轮 10 秒测量，以三轮最坏 p95 < 20 ms 为通过条件。它同时核验精确 sample、真实 humanoid bone、marker/texture 池不增长、Long Task、CDP task/script/layout/style/heap 指标、760 px 布局与浏览器 console。

> [!NOTE]
> 该门禁只证明指定 VRM、指定 sample 与合成多标签压力场景。单一样本通过不等于七库固定 49 样本 QA 与每库四项视觉回归完成，也不证明所有 body-part marker、长距离 locomotion camera 或 VRM spring-bone 动态均已验收。

**读写烟测：**

```bash
python scripts/smoke_pipeline.py --data-source demo --max-frames 8
python scripts/smoke_pipeline.py --data-source full --max-frames 8
```

正式验收按 [分层清单](validation.zh-CN.md) 记录每一层；被 skip 的数据集仍然是未验证。

## 9. 常见故障

| 现象 | 检查 |
|---|---|
| 页面停在 Connecting | 查看服务终端；确认 `npm ci` 后重启；检查 `/vendor/three` 与 `/vendor/three-vrm` |
| 动作速度不对 | 比较 frame count、source/effective FPS、duration 与 elapsed-time sampler |
| 地面变墙面 | 停止发布；检查 profile basis、`root_rotation_semantics`、translation unit，不调相机掩盖 |
| Source 已畸形 | 先查 Adapter/Codec；不要把问题归咎于 VRM retarget |
| 缓存后标注消失或 Avatar 无动作 | 比较在线 payload 与 PreviewReader；缺少 v3 manifest/rest/hand replay 契约的旧产物只能从 raw rebuild |
| Hand certificate 或 replay 失败 | 停止播放；核对 pre-solver hands、32-joint evidence/order、observation、policy/hash 和连续段，不在 Viewer 夹角补救 |
| GRAB/Motion-X/AMASS 手动作被 neutralize | 核对 profile 是否缺 source-rest hand-frame 标定；未标定通道不得改成 direct 以"恢复"动作 |
| 物体/热力图缺失 | 查看 channel availability；确认是否真的有 pose/contact points/mesh |
| 自定义 SuSu 无法正式处理 | profile 仍是 draft；用同帧 positions/BVH 完成 layout/space/unit 校准 |
| GRAB/SuSu 提示旧对象容器被禁用 | 安全默认值；只对已核验的本地数据设置 `VIREA_ALLOW_TRUSTED_RAW_PICKLE=1` 并重启，公开服务保持禁用 |

## 10. 清理与回滚

不要原地删除或改写 legacy v0.1/v0.2/v0.3 目录。Processing v0.4 重建使用独立 processed root；回滚只需切换 `VIREA_PROCESSED_ROOT`，旧 canonical sequence 仍保持 fail-closed。删除大型本地产物前先确认目标绝对路径位于预期 processed root，并优先保留失败 manifest 与 hashes。


<!--
---
type: how-to
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 60
summary: Windows、macOS 与 Linux 上安装、配置数据、处理、查看和重建 VIREA artifact 的操作指南。
canonical: doc/pipeline.zh-CN.md
related:
  - ../README.md
  - engineering-design.zh-CN.md
  - validation.zh-CN.md
  - rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md
  - adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md
supersedes: []
superseded_by: []
---
-->
