---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-10
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: 从 git clone 到执行域选择、模型安装、动作生成和浏览器播放的 VIREA 中文可复现教程。
canonical: doc/getting-started.zh-CN.md
related:
  - README.zh-CN.md
  - getting-started.en.md
  - reference/cli.zh-CN.md
  - platforms/README.zh-CN.md
  - ../CONTRIBUTING.md
supersedes: []
superseded_by: []
---

# 从 git clone 到第一个 VIREA 结果

> [中文](getting-started.zh-CN.md) · [English tutorial](getting-started.en.md) · [完整 CLI 参数参考](reference/cli.zh-CN.md)

本页是新用户的唯一入口。它将可变数据放在 checkout 之外，先检测你的实际执行域，再由你显式选择目标域后
安装模型或创建任务。英文逐步说明见 [English tutorial](getting-started.en.md)。

## 1. 安装前提工具

准备 Git、Python 3.12、[uv](https://docs.astral.sh/uv/)、Node.js 24、npm 与 pnpm 10。项目支持 Python
3.10+；`.python-version` 和 `.node-version` 固定了可复现开发基线。使用 GPU Runtime 时，选定执行域还必须具备
该 Runtime 所要求的驱动和 ABI；第 3 步的 `doctor` 会报告当前事实。

## 2. 克隆项目并设置仓库外本地目录

仓库只保存源码、锁文件、注册表与轻量文档。虚拟环境、模型资产、隔离 Runtime、job、结果和日志都应位于
仓库外、位于容量充足数据盘上的 `VIREA_HOME`。持久命令在未给出 `VIREA_HOME`/`--virea-home` 时会拒绝执行，
不会再静默使用 `LOCALAPPDATA`、`$HOME` 或 clone。

### Windows PowerShell

```powershell
# 从公开仓库克隆源码；贡献时可将 URL 换成自己的 fork。
git clone https://github.com/Moonweave-AI/virea.git

# 进入刚克隆的项目根目录；后续命令都从此目录执行。
Set-Location virea

# 显示本机文件系统卷和可用空间，再选择自己的数据盘。
Get-PSDrive -PSProvider FileSystem

# 读取所选数据盘的根路径，并在其下创建 VIREA 目录。
$vireaDataVolume = Read-Host "输入所选数据盘的根路径"
$vireaDataRoot = Join-Path $vireaDataVolume "VIREA"

# 将 uv 的锁定项目环境放在 checkout 与 Windows 用户应用数据目录之外。
$env:UV_PROJECT_ENVIRONMENT = Join-Path $vireaDataRoot "dev-venv"

# 将 uv 的下载 wheel 与构建缓存也放在所选数据盘。
$env:UV_CACHE_DIR = Join-Path $vireaDataRoot "uv-cache"

# 将模型资产、Runtime、下载、日志和结果写入所选数据盘。
$env:VIREA_HOME = Join-Path $vireaDataRoot "home"

# 完全按 uv.lock 安装 Python workspace 与开发依赖；--locked 禁止重新解析版本。
uv sync --locked --all-packages --extra dev

# 严格按 package-lock.json 安装旧 Viewer 依赖；不要用 npm install 替代。
npm ci

# 严格按 pnpm-lock.yaml 安装当前 Web workspace；--frozen-lockfile 不允许写锁文件。
pnpm install --frozen-lockfile

# 编译 Web 到 apps/web/dist；不会启动服务器、下载权重或运行模型。
pnpm --filter @virea/web build
```

### Linux、WSL2 与 macOS shell

```bash
# 克隆源码并进入项目根目录。
git clone https://github.com/Moonweave-AI/virea.git
cd virea

# 选择已挂载且容量充足的数据盘；将 /data/virea 换成实际路径。
export VIREA_DATA_ROOT="/data/virea"

# 将 uv 的锁定项目环境放在 clone 和系统盘之外。
export UV_PROJECT_ENVIRONMENT="$VIREA_DATA_ROOT/dev-venv"

# 将 uv 的下载与构建缓存也放在所选数据盘。
export UV_CACHE_DIR="$VIREA_DATA_ROOT/uv-cache"

# 将所有 VIREA 状态写入选定的数据盘。
export VIREA_HOME="$VIREA_DATA_ROOT/home"

# 依次复现 Python、Viewer、Web 依赖并构建浏览器界面。
uv sync --locked --all-packages --extra dev
npm ci
pnpm install --frozen-lockfile
pnpm --filter @virea/web build
```

`npm ci` 管理旧 Viewer 工具链，`pnpm` 管理 0.4 Web workspace。请按此顺序运行，且不要并发写同一 checkout 的
`node_modules`。

## 3. 初始化状态并检测执行域

```bash
# 创建或升级 VIREA_HOME 中的本地状态；不会修改系统 Python、显卡驱动或全局包。
uv run virea setup --virea-home "$VIREA_HOME"

# 输出 JSON、写入本地诊断记录、解释发现并提供只读修复计划；不会下载或导入模型框架。
uv run virea doctor --json --record --explain --repair-plan --virea-home "$VIREA_HOME"
```

PowerShell 请把 `"$VIREA_HOME"` 替换为 `$env:VIREA_HOME`。从输出的 `execution_domains` 读取 canonical ID：

| ID | 含义 |
|---|---|
| `windows-native` | 原生 Windows 进程、路径和资源观测。 |
| `linux-native` | 原生 Linux 进程、路径和资源观测。 |
| `macos-native` | 原生 macOS 进程、路径和资源观测。 |
| `wsl:<distribution>` | 某个具体 WSL 发行版，例如 `wsl:Ubuntu-24.04`。 |

如果检测到多个候选域，必须显式选择。选择失败时 VIREA 不会悄悄切换到其他操作系统、加速器或资源 profile。

## 4. 查看、规划并应用模型安装

```bash
# 列出已知模型；--json 适合脚本读取，不会安装或下载任何内容。
uv run virea model list --json

# 查看模型的任务、资产、Runtime、profile、许可和按执行域返回的原因。
uv run virea model info flood-diffusion-tiny

# 仅输出精确安装计划，不修改 VIREA_HOME。大写占位符必须替换为 doctor/model info 返回的值。
uv run virea model install MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --virea-home "$VIREA_HOME"

# 审核计划后才加入 --apply；它可能获取/校验资产、构建隔离 Runtime 并执行安装验收。
uv run virea model install MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --apply --virea-home "$VIREA_HOME"

# 只读验证最新安装是否为 READY，且资产和验收事实仍可访问。
uv run virea model verify MODEL --virea-home "$VIREA_HOME"
```

| 占位符 | 含义 | 如何获取 |
|---|---|---|
| `MODEL` | 稳定模型 manifest ID，例如 `flood-diffusion-tiny`。 | `virea model list` 或 `virea model info`。 |
| `DOMAIN` | canonical 执行域 ID。 | `virea doctor --json`。 |
| `RUNTIME` | 可选的高级 Runtime variant 覆盖项。 | `model info` 中该 `DOMAIN` 可用的 Runtime ID。 |
| `PROFILE` | 可选的高级资源策略覆盖项。 | `model info` 中该 Runtime 的 profile。 |

`--runtime` 和 `--resource-profile` 都是可选项；一旦使用其中任意一个，就必须同时给出
`--execution-domain`。若 manifest 要求许可确认，请先阅读条款，再加 `--accepted-license`；它只记录本地确认，
不授予再分发或商业权利。

## 5. 创建一个动作任务

```bash
# 向所选、已 READY 的 Runtime 提交受限 text-to-motion 任务。
# --seconds 是请求时长；--fps 是目标采样率；--seed 在模型支持时可复现随机结果；--timeout 单位为秒，最大 7200。
uv run virea generate --model MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --task text_to_motion --prompt "A person walks forward" --seconds 4 --fps 20 --seed 42 --timeout 1800 --virea-home "$VIREA_HOME"

# 对返回的 job ID 只读校验安装、原生结果、Motion IR 和 VRMA 事实。
uv run virea validate-real-e2e --virea-home "$VIREA_HOME" --job-id JOB_ID --expect success
```

保存返回的 `job_id` 与 `result_id`。它们绑定模型资产 snapshot、所选 Runtime、执行域、资源 profile 和输出产物。
单台设备的一次成功只是一条精确配置的观测，不能外推成所有系统或 GPU 已验证。

## 6. 在浏览器中播放结果

```bash
# 在本机回环地址启动控制面。--host 避免对外暴露；--port 决定浏览器访问端口。
uv run virea serve --host 127.0.0.1 --port 8000 --virea-home "$VIREA_HOME"
```

打开 `http://127.0.0.1:8000/app/`，加载本地 `.vrm` Avatar，选择相同执行域和模型并打开结果。按 `Ctrl+C` 停止
服务。`--reload` 与 legacy `--data-source` 的说明见 [CLI 参数参考](reference/cli.zh-CN.md#serve)。

## 7. 排错与安全维护

```bash
# 输出本地支持摘要；--jobs 指定纳入多少条最近任务摘要。
uv run virea support --jobs 20 --virea-home "$VIREA_HOME"

# 只读查看本地状态。
uv run virea state inspect --virea-home "$VIREA_HOME"

# 预览模型修复；只有加入 --apply 才会创建新的安装事务。
uv run virea model repair MODEL --execution-domain DOMAIN --virea-home "$VIREA_HOME"

# 预览可回收且不再引用的模型数据；--dry-run 明确保证不删除任何内容。
uv run virea model gc --dry-run --older-than-hours 168 --virea-home "$VIREA_HOME"
```

不要手工编辑 VIREA SQLite 数据库、移动安装目录，或为了“修一个模型”而删除整个 `VIREA_HOME`。请先使用
`model repair`、`model remove` 或 `gc` 的预览，再决定是否使用 `--apply`。全部参数、默认行为与风险均在
[CLI 参数参考](reference/cli.zh-CN.md)。

## 下一篇

- [CLI 参考：所有命令和参数](reference/cli.zh-CN.md)
- [平台与执行域](platforms/README.zh-CN.md)
- [模型目录与能力矩阵](models/README.zh-CN.md)
- [文档维护规范](development/documentation.zh-CN.md)
