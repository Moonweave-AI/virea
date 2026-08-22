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
| 排查本地安装、状态或资源问题 | [排错指南](doc/operations/troubleshooting.zh-CN.md) | [Troubleshooting summary](doc/getting-started.en.md#8-advanced-troubleshooting-and-safe-maintenance) |
| 维护文档 | [文档规范](doc/development/documentation.zh-CN.md) | [Documentation policy](doc/development/documentation.en.md) |

## 先决条件

- Git；
- Python 3.12（项目声明 Python 3.10+，开发基线见 `.python-version`）；
- [uv](https://docs.astral.sh/uv/)；
- Node.js 24（见 `.node-version`）、npm 与 pnpm 10；
- 运行 GPU Runtime 时，目标执行域必须具备该 Runtime 声明的驱动、ABI 与可用资源。

## 最短可复现路径

下面每行都可以复制执行。尖括号内容是你必须替换的占位符；不要把模型、缓存、日志或虚拟环境写进 checkout。
输入数据根前请先看[数据根路径与引号规则](doc/getting-started/persistent-data-root.zh-CN.md)：Windows 复制路径时外层引号不属于路径。

### Windows PowerShell

```powershell
# 列出本机文件系统卷和可用空间，再选择容量充足的数据盘。
Get-PSDrive -PSProvider FileSystem

# 一次性读取所选数据盘根路径；clone 与所有本地依赖目录都放在它下面。
# 提示处只粘贴目录本身，例如 X:\VIREA-DATA；外层单/双引号不是路径内容，不能输入。
$vireaDataVolume = Read-Host "输入所选数据盘的根路径"

# 如有需要先创建根目录，在其中 clone 源码，再进入 clone；源码不含模型权重。
New-Item -ItemType Directory -Force -Path $vireaDataVolume | Out-Null
Set-Location $vireaDataVolume
git clone https://github.com/Moonweave-AI/virea.git
Set-Location virea

# 持久写入 VIREA_HOME、UV_PROJECT_ENVIRONMENT、UV_CACHE_DIR、HF_HOME 与 Node 缓存；当前与以后 Windows 终端都会继承。
& .\scripts\configure-virea.ps1 -DataRoot $vireaDataVolume

# 按 uv.lock 创建所有 Python workspace 包和开发依赖；--locked 禁止重新解析版本。
uv sync --locked --all-packages --extra dev

# 按 package-lock.json 安装旧 Viewer 的 Node 依赖；不要用 npm install 替换它。
npm ci

# 按 pnpm-lock.yaml 安装 Web workspace；--frozen-lockfile 禁止改写锁文件。
pnpm install --frozen-lockfile

# 编译浏览器控制台到 apps/web/dist；不会启动服务或下载模型。
pnpm --filter @virea/web build

# 启动逐步交互向导：初始化状态、检测执行域、选择模型/Runtime/profile、确认安装，然后提供生成与浏览器播放。
uv run virea
```

### Linux / WSL2 / macOS shell

```bash
# 一次性读取已挂载的数据盘根路径；clone 与所有本地依赖目录都放在它下面。
# 提示处只粘贴目录本身，例如 /mnt/virea-data；外层单/双引号不是路径内容，不能输入。
printf '%s' "输入所选数据盘根路径: "
read -r virea_data_root

# 如有需要先创建根目录，在其中 clone 源码，再进入 clone。
mkdir -p "$virea_data_root"
cd "$virea_data_root"
git clone https://github.com/Moonweave-AI/virea.git
cd virea

# 创建 VIREA 目录并安装 shell hook；之后新终端会自动继承所有持久目录设置。
./scripts/configure-virea.sh --data-root "$virea_data_root"

# 立即在当前 shell 载入生成的设置；以后 shell 将通过已安装的 hook 自动载入。
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"

# 按锁文件安装 Python、Node/Viewer 与 Web 依赖，并构建 Web 静态资源。
uv sync --locked --all-packages --extra dev
npm ci
pnpm install --frozen-lockfile
pnpm --filter @virea/web build

# 启动逐步交互向导：初始化状态、检测执行域、选择模型/Runtime/profile、确认安装，然后提供生成与浏览器播放。
uv run virea
```

## 高级：手动选择执行域并安装模型

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

## 高级：手动运行、生成与播放

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
