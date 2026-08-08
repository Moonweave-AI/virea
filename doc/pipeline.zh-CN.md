---
type: how-to
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 60
summary: Windows、macOS 与 Linux 上安装、配置数据、处理、查看和重建 VIREA artifact 的操作指南。
canonical: doc/pipeline.zh-CN.md
related:
  - ../README.md
  - engineering-design.zh-CN.md
  - validation.zh-CN.md
supersedes: []
superseded_by: []
---

# Pipeline 使用指南

本文只讲可执行操作。数据语义读 [七数据集审计](dataset-audit.zh-CN.md)，数学读 [Retarget 共同层](math-retarget/README.zh-CN.md)。

## 1. 前置条件

- Git；
- Python 3.10 或更高版本；
- Node.js 20 或更高版本；
- 可选：FFmpeg，用于 WebM 转 GIF；
- 可选：Chromium，由 Playwright 录制 Showcase。

不要把 raw dataset、processed 全量产物、VRM 模型或机器绝对路径放进 Git。

## 2. 安装

仓库提交 `uv.lock` 作为 Python 的精确依赖锁。安装了 uv 时，Windows、macOS 与 Linux
统一使用下面的可复现路径：

```bash
git clone git@github.com:Moonweave-AI/virea.git
cd virea
uv sync --extra dev
npm ci
```

没有 uv 时仍可用标准 venv/pip；该路径遵守 `pyproject.toml` 的版本范围，但不会保证
与锁文件逐包一致。

Windows PowerShell：

```powershell
git clone git@github.com:Moonweave-AI/virea.git
Set-Location virea
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm ci
```

macOS：

```bash
git clone git@github.com:Moonweave-AI/virea.git
cd virea
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm ci
```

Linux：

```bash
git clone git@github.com:Moonweave-AI/virea.git
cd virea
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm ci
```

`npm ci` 必须成功，否则 Viewer 对 Three.js 与 three-vrm 的请求会失败。录制 Showcase 时再安装浏览器：

```bash
npx playwright install chromium
```

Linux 若提示缺少系统库，使用 Playwright 官方针对当前发行版的 dependency 安装方式；不要把系统可执行文件绝对路径写进仓库。

## 3. 数据目录与配置优先级

`configs/project.yaml` 只保存可移植默认值。机器路径通过环境变量覆盖：

| 变量 | 作用 |
|---|---|
| `VIREA_DATA_SOURCE` | `demo` 或 `full` |
| `VIREA_DATA_ROOT` | full 数据的上层目录；未显式 raw root 时尝试其 `raw/` |
| `VIREA_RAW_ROOT` | 七数据集 raw root，最高优先级 |
| `VIREA_PROCESSED_ROOT` | processed artifact root |
| `VIREA_SERVE_HOST` / `VIREA_SERVE_PORT` | API/Viewer bind address |
| `VIREA_THREE_ROOT` / `VIREA_THREE_VRM_ROOT` | 可选 JS runtime 覆盖；正常情况使用 `node_modules` |
| `VIREA_SHOWCASE_SERVER` / `VIREA_SHOWCASE_VRM` | Showcase recorder 的服务 URL 与本地 VRM |
| `VIREA_ALLOW_TRUSTED_RAW_PICKLE` | 仅对已核验的本地 GRAB/SuSu 旧 object 容器显式设为 `1`；默认禁用 |

Windows：

```powershell
$env:VIREA_RAW_ROOT = "<full-raw-root>"
$env:VIREA_PROCESSED_ROOT = "<processed-root>"
```

macOS / Linux：

```bash
export VIREA_RAW_ROOT="<full-raw-root>"
export VIREA_PROCESSED_ROOT="<processed-root>"
```

任何日志、metadata、截图或提交中都只记录 portable relative path 或 hash，不记录这里的真实绝对路径。

### 旧 object 容器的信任门禁

GRAB 与 SuSuInterActs 的既有 `.npz`/`.npy` 结构需要 NumPy pickle 才能展开嵌套对象。
pickle 能执行代码，因此 Viewer 的只读预览也不能默认加载。只有数据来自已核验的本地副本、
且你已经单独确认其来源与内容哈希时，才可为一次离线会话开启：

```powershell
$env:VIREA_ALLOW_TRUSTED_RAW_PICKLE = "1"
python -m virea serve --data-source full --host 127.0.0.1
```

```bash
export VIREA_ALLOW_TRUSTED_RAW_PICKLE=1
python -m virea serve --data-source full --host 127.0.0.1
```

开启后必须继续只监听 loopback；不要与公开 CORS、远程端口或未知数据共同使用。长期方案是把
对象容器迁移成 `allow_pickle=False` 可读取的数值数组和 JSON/内容寻址 sidecar。服务健康接口只
回显该门禁是否开启，不返回机器路径。

## 4. Demo 数据

下载脚本额外依赖 `huggingface_hub`：

```bash
python -m pip install huggingface_hub
python scripts/download_demo.py --raw-only --accept-local-only
```

也可使用 `--processed-only`，或不传过滤参数下载 raw + processed。下载配置在
`configs/demo_download.json`：仓库固定到完整 Git commit；脚本从该不可变 revision 读取每个
文件的 Hub LFS SHA-256 或 Git blob SHA-1，下载后校验大小与内容，并生成本地
`demo/manifest.json`。目标目录中出现未列入 revision 的额外文件也会使验证失败。

重要边界：该 Hub dataset card 在固定 revision 上没有机器可读许可证，因此配置决定为
`local-only`。脚本默认拒绝下载，只有显式传入 `--accept-local-only` 才继续；这只是本地使用
确认，不会授予再分发权限。公开 Demo 的 Release gate 仍为 No-Go，直到各数据集资产均得到
独立的 `allowed` 决定。

从本机 full root 构建 fixture：

```bash
python -m virea build-demo --samples-per-dataset 7 --overwrite
```

这会复制第三方内容，只能在许可允许的本地范围使用；不要因为目录名叫 `demo` 就默认可以提交。

## 5. 批处理

Demo：

```bash
python -m virea process --data-source demo --workers 4 --force
```

Full 中只处理指定数据集：

```bash
python -m virea process --data-source full --datasets amass babel --workers 8 --force
```

常用参数：

| 参数 | 含义 |
|---|---|
| `--datasets` | 限定一个或多个 registry key |
| `--query` | sample id 文本过滤 |
| `--limit-per-dataset` | 每数据集上限，0 表示全部 |
| `--max-frames` | 调试截断；正式重建通常省略 |
| `--workers` | 0 自动选择，正数固定并行数 |
| `--skip-existing` / `--no-skip-existing` | 是否跳过已存在产物 |
| `--force` | 即使已有产物也重新处理 |

RFC-0001 要求 v0.2 写到新目录，不能覆盖 v0.1。运行前检查 `configs/project.yaml` 的 `processing_version` 和 `VIREA_PROCESSED_ROOT`；若仍指向 `v0.1.0`，只能做兼容调试，不能把输出当作 v0.2 release artifact。

## 6. 启动 Viewer

```bash
python -m virea serve --data-source demo --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。推荐验收顺序：

1. 选择 dataset 与 sample；
2. 检查 source skeleton、FPS、duration、annotations 与 channels；
3. 检查 processed target FK 和同一语义 payload；
4. 从本地文件选择器加载真实 `.vrm`；
5. 检查 Avatar 独立面板、timeline、head/hand/torso/leg marker；
6. 改变播放速度、seek、filter 与窗口宽度；
7. 保存截图、浏览器版本、模型 hash 与 sample/artifact hash。

不要把真实模型路径设成仓库默认值。普通 GLB 或缺少 humanoid mapping 时应看到明确降级说明。

## 7. Showcase 录制

先启动 Viewer，再调用 recorder。

Windows：

```powershell
$env:VIREA_SHOWCASE_SERVER = "http://127.0.0.1:8000"
$env:VIREA_SHOWCASE_VRM = "<local-avatar.vrm>"
node scripts/render_showcase.mjs `
  --data-source demo `
  --manifest doc/showcase/showcase-samples.json `
  --out-dir doc/showcase/videos
```

macOS / Linux：

```bash
export VIREA_SHOWCASE_SERVER="http://127.0.0.1:8000"
export VIREA_SHOWCASE_VRM="<local-avatar.vrm>"
node scripts/render_showcase.mjs \
  --data-source demo \
  --manifest doc/showcase/showcase-samples.json \
  --out-dir doc/showcase/videos
```

媒体只能在 v0.2 真实样本/真实 VRM 回归和 IP decision 为 `allowed` 后公开提交。录制与 GIF 转换细节见 [Showcase 说明](showcase/README.md)。

## 8. 验证

快速代码检查：

```bash
python -m compileall -q src
python -m pytest -q
npm run check
npm run test:viewer
python scripts/check_docs.py
```

真实 VRM 浏览器门禁（Viewer 服务已启动；路径只通过环境变量传入，截图默认写入系统临时目录）：

```powershell
$env:VIREA_QA_BASE_URL = "http://127.0.0.1:8000"
$env:VIREA_VRM_PATH = "<local-avatar.vrm>"
$env:VIREA_QA_BROWSER_PATH = "<installed-browser.exe>" # Playwright 已安装 Chromium 时可省略
npm run qa:vrm
```

```bash
export VIREA_QA_BASE_URL="http://127.0.0.1:8000"
export VIREA_VRM_PATH="<local-avatar.vrm>"
npm run qa:vrm
```

该脚本默认先预热 30 秒，再构造至少 100 条同时 active 的 annotation，连续执行 3 轮
10 秒测量，并以三轮最坏 p95 小于 20 ms 为通过条件。它同时核验精确 sample、真实
humanoid bone、marker/texture 池不增长、Long Task、CDP task/script/layout/style/heap
指标、760 px 布局与浏览器 console。可用 `VIREA_QA_WARMUP_MS`、
`VIREA_QA_DURATION_MS`、`VIREA_QA_REPEATS` 和 `VIREA_QA_STRESS_ANNOTATIONS`
显式覆盖默认值；验收记录必须保留实际值、浏览器、CPU/GPU、viewport 和 DPR。

该门禁只证明指定 VRM、指定 sample 与合成多标签压力场景；单一样本通过不等于七库
`7 x 7` 视觉回归完成，也不证明所有 body-part marker、长距离 locomotion camera 或
VRM spring-bone 动态均已验收。

读写烟测：

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
| 缓存后标注消失 | 比较在线 payload 与 PreviewReader；旧 v0.1 只能 rebuild |
| 物体/热力图缺失 | 查看 channel availability；确认是否真的有 pose/contact points/mesh |
| 自定义 SuSu 无法正式处理 | profile 仍是 draft；用同帧 positions/BVH 完成 layout/space/unit 校准 |
| GRAB/SuSu 提示旧对象容器被禁用 | 这是安全默认值；只对已核验的本地数据设置 `VIREA_ALLOW_TRUSTED_RAW_PICKLE=1` 并重启，公开服务保持禁用 |

## 10. 清理与回滚

不要原地删除或改写 v0.1。v0.2 重建使用独立 processed root；回滚只切换 `VIREA_PROCESSED_ROOT` 和兼容 Viewer。删除大型本地产物前先确认目标绝对路径位于预期 processed root，并优先保留失败 manifest 与 hashes。
