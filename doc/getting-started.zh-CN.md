# Getting Started

本教程将"安装成功""有可浏览数据""正在播放 current canonical v3"作为三个独立的验证目标分别说明。

## 先选择目标

| 目标 | 数据要求 | 预期结果 |
|---|---|---|
| 检查安装与 UI | 无 | Viewer 正常打开；clean clone 下样本列表为空 |
| 核对旧 demo | 明确接受 local-only 下载 | legacy 几何与迁移信息可查；pre-v3 Avatar motion 被扣留 |
| 查看当前 v3 动作 | 只读 full raw root；可选独立 processed root | 在线 current pipeline 或 replay-verified v3 artifact |

> [!IMPORTANT]
> Raw dataset、processed artifact、VRM 与 Showcase 输出不得提交到 Git。旧 demo 和由受限资产生成的媒体同样保持 local-only。

## 1. 安装

需要 Git、Python 3.10+ 与 Node.js 20+。

**推荐方式（`uv` 锁文件）：**

```bash
git clone git@github.com:Moonweave-AI/virea.git
cd virea
uv sync --extra dev
npm ci
```

<details>
<summary><strong>Windows PowerShell（标准 venv）</strong></summary>

```powershell
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
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm ci
```

</details>

没有 uv 时可以使用标准 venv；该路径遵守 `pyproject.toml` 的版本范围，但不保证与锁文件逐包一致。

## 2. 检查 UI

```bash
uv run python -m virea serve --data-source demo
```

打开终端显示的本地 URL。以下三项同时成立即表示基础安装成功：

1. 页面能打开；
2. Three.js / three-vrm runtime 没有加载错误；
3. 健康状态显示服务可用。

Clean clone 不包含 `demo/raw` 与 `demo/processed`，所以此时样本列表为空是预期结果。不要为了"看起来有内容"而让 Reader 把旧 sequence 静默当成 v3。

## 3. 可选：下载 local-only demo

下载脚本使用固定 Hub revision、逐文件摘要和显式许可确认。`huggingface_hub` 不是核心运行依赖，需要单独安装：

```bash
uv pip install huggingface-hub
uv run python scripts/download_demo.py --accept-local-only
```

下载内容只能留在本机。若下载的是旧 processed demo：

- Source / processed 的已有 2D 几何可用于迁移核对；
- pre-v3 canonical sequence 不会被标成 current v3；
- Avatar motion 会被 fail-closed 扣留；
- 查看 current v3 必须从对应 raw 数据重新处理。

## 4. 查看 current canonical v3

路径只通过环境变量或命令行传入。以下示例使用占位符，请勿把本机绝对路径写进文档、日志或提交。

<details>
<summary><strong>Windows PowerShell</strong></summary>

```powershell
$env:VIREA_RAW_ROOT = "<full-raw-root>"
$env:VIREA_PROCESSED_ROOT = "<processed-v0.4-root>"
uv run python -m virea serve --data-source full --host 127.0.0.1 --port 8000
```

</details>

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
export VIREA_RAW_ROOT="<full-raw-root>"
export VIREA_PROCESSED_ROOT="<processed-v0.4-root>"
uv run python -m virea serve --data-source full --host 127.0.0.1 --port 8000
```

</details>

在 Viewer 中选择数据集和样本，再通过本地文件选择器加载 `.vrm`。模型本体不会上传到服务器或复制进仓库。

### 受信 object container

GRAB 与部分 SuSuInterActs 容器可能包含 NumPy object/pickle。VIREA 默认拒绝加载，因为预览也可能触发代码执行。只有在离线核验来源和摘要后，才为当前本地进程显式启用：

```powershell
$env:VIREA_ALLOW_TRUSTED_RAW_PICKLE = "1"
```

公开、共享或远程服务不得开启该选项。结束受信会话后删除环境变量并重启服务。

## 5. 生成正式 artifact

```bash
uv run python -m virea process --data-source full --workers 8 --force
```

正式 persist 会同时检查 dataset profile 与 hand-solver profile。任一为 `draft` 时，命令会拒绝写入——这是真实状态门禁，不是故障。请勿通过修改 metadata 或复用旧目录来绕过。

## 6. 验证安装

```bash
uv run python -m compileall -q src
uv run python -m pytest -q
npm run check
npm run test:viewer
uv run python scripts/check_docs.py
```

真实数据与真实 VRM 测试需要显式环境变量。`skipped` 必须单独报告，不能算作 `passed`。

## 7. 下一步

| 方向 | 文档 |
|---|---|
| 批处理、版本化重建与排错 | [Pipeline 使用指南](pipeline.zh-CN.md) |
| 数据集表示、单位与 profile | [七数据集审计](dataset-audit.zh-CN.md) |
| 坐标、旋转、FK 与手部 solver | [Retarget 数学共同层](math-retarget/README.zh-CN.md) |
| 七数据集画廊与许可边界 | [Showcase](showcase/README.md) |
| 所有发布门禁 | [验收清单](validation.zh-CN.md) |


<!--
---
type: tutorial
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-10
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 60
title: VIREA Getting Started
audience: First-time contributors and local reviewers
visibility: Public
summary: 从 clean clone 到空壳 Viewer、local-only demo 或 current-v3 full-data 预览的三条可复现路径。
canonical: doc/getting-started.zh-CN.md
related:
  - ../README.md
  - pipeline.zh-CN.md
  - showcase/README.md
  - validation.zh-CN.md
supersedes: []
superseded_by: []
---
-->
