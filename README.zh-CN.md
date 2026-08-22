---
type: readme
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: VIREA 的中文项目入口：从 clean clone、环境检测和显式执行域选择，到模型安装、生成和浏览器播放。
canonical: README.zh-CN.md
related:
  - README.md
  - doc/README.zh-CN.md
  - doc/getting-started.zh-CN.md
  - doc/reference/cli.zh-CN.md
supersedes: []
superseded_by: []
---

<p align="center">
  <img src="doc/assets/virea-hero.png" width="100%" alt="VIREA：多模型动作生成到可审计 VRMA 浏览器播放">
</p>

# VIREA

> [English](README.md) · [简体中文](README.zh-CN.md)

VIREA 把不同模型的隔离运行环境、原生动作表示、Motion IR、VRMA 和真实 VRM 浏览器播放串成一条可审计链。
模型资产不属于某个操作系统：用户先选择实际运行的执行域，VIREA 再为该域构建或复用对应 Runtime。

## 从这里开始

| 你的目标 | 中文文档 | English documentation |
|---|---|---|
| 从 clone 到第一个结果 | [中文教程](doc/getting-started.zh-CN.md) | [English tutorial](doc/getting-started.en.md) |
| 查看每个 CLI 命令和参数 | [中文 CLI 参考](doc/reference/cli.zh-CN.md) | [English CLI reference](doc/reference/cli.en.md) |
| 选择 Windows、Linux、WSL2 或 macOS 执行域 | [平台指南](doc/platforms/README.zh-CN.md) | [Platform guide](doc/platforms/README.en.md) |
| 选择模型、Runtime 与资源 profile | [模型目录](doc/models/README.zh-CN.md) | [Model catalog](doc/models/README.zh-CN.md) |
| 排查本地安装、状态或资源问题 | [排错指南](doc/operations/troubleshooting.zh-CN.md) | [Troubleshooting summary](doc/getting-started.en.md#7-troubleshooting-and-safe-maintenance) |
| 维护文档 | [文档规范](doc/development/documentation.zh-CN.md) | [Documentation policy](doc/development/documentation.en.md) |

## 先决条件

- Git；
- Python 3.12（项目声明 Python 3.10+，开发基线见 `.python-version`）；
- [uv](https://docs.astral.sh/uv/)；
- Node.js 24（见 `.node-version`）、npm 与 pnpm 10；
- 运行 GPU Runtime 时，目标执行域必须具备该 Runtime 声明的驱动、ABI 与可用资源。

## 最短可复现路径

下面每行都可以复制执行。尖括号内容是你必须替换的占位符；不要把模型、缓存、日志或虚拟环境写进 checkout。

### Windows PowerShell

```powershell
# 克隆源码；它只包含代码、锁文件、注册表和轻量文档，不包含模型权重。
git clone https://github.com/Moonweave-AI/virea.git

# 进入刚克隆的项目根目录，后续命令均从这里运行。
Set-Location virea

# 把 uv 的开发环境放到仓库外，避免在项目中创建 .venv。
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\VIREA\dev-venv"

# 指定用户本地状态目录：安装记录、隔离 Runtime、结果和日志都写到这里。
$env:VIREA_HOME = "$env:LOCALAPPDATA\VIREA\home"

# 按 uv.lock 创建所有 Python workspace 包和开发依赖；--locked 禁止重新解析版本。
uv sync --locked --all-packages --extra dev

# 按 package-lock.json 安装旧 Viewer 的 Node 依赖；不要用 npm install 替换它。
npm ci

# 按 pnpm-lock.yaml 安装 Web workspace；--frozen-lockfile 禁止改写锁文件。
pnpm install --frozen-lockfile

# 编译浏览器控制台到 apps/web/dist；不会启动服务或下载模型。
pnpm --filter @virea/web build

# 创建或升级 VIREA_HOME 的本地 SQLite 状态；不会改系统 Python 或驱动。
uv run virea setup --virea-home $env:VIREA_HOME

# 探测本机与可用执行域，并输出下一步修复建议；不导入模型框架或下载模型。
uv run virea doctor --json --record --explain --repair-plan --virea-home $env:VIREA_HOME
```

### Linux / WSL2 / macOS shell

```bash
# 克隆并进入项目根目录；请将 URL 换成你的 fork（如适用）。
git clone https://github.com/Moonweave-AI/virea.git
cd virea

# 使用仓库外的开发环境。Linux/WSL 用 XDG 数据目录；macOS 可改为 ~/Library/Application\ Support/VIREA/dev-venv。
export UV_PROJECT_ENVIRONMENT="${XDG_DATA_HOME:-$HOME/.local/share}/virea/dev-venv"

# 用户本地 VIREA 状态目录；模型资产、Runtime、日志和结果不会写到 clone 中。
export VIREA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/virea/home"

# 按锁文件安装 Python、Node/Viewer 与 Web 依赖，并构建 Web 静态资源。
uv sync --locked --all-packages --extra dev
npm ci
pnpm install --frozen-lockfile
pnpm --filter @virea/web build

# 初始化本地状态并仅探测/记录机器事实；不下载或运行模型。
uv run virea setup --virea-home "$VIREA_HOME"
# 探测可选执行域和资源，写入本地机器报告，并只输出修复建议。
uv run virea doctor --json --record --explain --repair-plan --virea-home "$VIREA_HOME"
```

## 选择执行域，然后安装模型

从 `doctor --json` 的 `execution_domains` 读取 canonical ID：`windows-native`、`linux-native`、
`macos-native` 或准确的 `wsl:<distribution>`。多域机器上必须显式选择；失败不会静默切换到另一系统。

```bash
# 显示模型清单。--json 输出机器可读 JSON；不安装或下载任何内容。
uv run virea model list --json

# 查看一个模型在每个执行域中的 Runtime、profile、资源与许可要求。
uv run virea model info flood-diffusion-tiny

# 先输出安装计划。MODEL、DOMAIN、RUNTIME、PROFILE 必须替换为 doctor/model info 给出的值。
uv run virea model install MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --virea-home "$VIREA_HOME"

# 在确认计划后才添加 --apply；它可能下载或引用模型资产、构建隔离 Runtime 并运行安装验收。
uv run virea model install MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --apply --virea-home "$VIREA_HOME"

# 只读检查最新安装是否仍为 READY，且资产与验收记录可访问。
uv run virea model verify MODEL --virea-home "$VIREA_HOME"
```

完整命令、占位符和每个选项的含义在[中文 CLI 参考](doc/reference/cli.zh-CN.md)与
[English CLI reference](doc/reference/cli.en.md)。

## 运行、生成与播放

```bash
# 使用已经 READY 的同一执行域 Runtime 提交一个文本到动作任务；--timeout 单位为秒，最大 7200。
uv run virea generate --model MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --task text_to_motion --prompt "A person walks forward" --seconds 4 --fps 20 --seed 42 --timeout 1800 --virea-home "$VIREA_HOME"

# 启动只绑定本机回环地址的控制面；--port 是浏览器访问端口。
uv run virea serve --host 127.0.0.1 --port 8000 --virea-home "$VIREA_HOME"
```

然后打开 `http://127.0.0.1:8000/app/`，选择相同的执行域、模型和结果，加载本地 `.vrm` Avatar。

## 能力、实测和发布不是同一件事

- `Runtime` 的平台声明表示已锁定、可解析的实现，不等于该模型已在所有设备上完成推理；
- 观测证据只说明某个 model/runtime/domain/device 组合运行过，不能外推到其他系统或 GPU；
- 当前公共/商业 GA 仍受许可证、第三方资产、平台实测和发布治理门禁约束。请查看
  [发布验收](doc/refactor/RELEASE_ACCEPTANCE_0.4.0.md)和
  [状态语义](doc/reference/status-semantics.zh-CN.md)。

## 维护与贡献

运行 `python scripts/generate_docs.py --check`、`python scripts/check_docs.py` 和相关测试，确保文档表格和链接
没有漂移。贡献约定见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全报告见 [SECURITY.md](SECURITY.md)，第三方条款见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
