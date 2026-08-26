---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: 一次选择并持久化 VIREA 数据根目录，避免将模型和环境写入系统盘。
canonical: doc/getting-started/persistent-data-root.zh-CN.md
related:
  - persistent-data-root.en.md
  - ../getting-started.zh-CN.md
  - ../reference/cli.zh-CN.md
  - ../../scripts/configure-virea.ps1
  - ../../scripts/configure-virea.sh
supersedes: []
superseded_by: []
---

# 选择并持久化 VIREA 数据根目录

> [中文](persistent-data-root.zh-CN.md) · [English](persistent-data-root.en.md) · [从 clone 到结果](../getting-started.zh-CN.md)

在安装依赖和模型**之前**只做一次。选择一块你愿意让 VIREA 长期使用的、大容量数据盘根目录；clone 与所有由 VIREA
管理的可变目录都会位于其下：

```text
<数据根>/
  virea/          # git clone 与 node_modules
  home/           # VIREA_HOME：模型、任务、结果、日志、状态、HF 缓存
  dev-venv/       # uv 项目虚拟环境
  uv-cache/       # uv 下载/构建缓存
  npm-cache/      # npm 缓存
  pnpm-store/     # pnpm 包仓库
```

`<数据根>` 不是 clone 目录本身，也不能位于 clone 内；配置脚本会拒绝这种不安全布局。脚本不会重定向操作系统全局临时
目录，以免影响无关应用；上面列出的 VIREA 状态与缓存路径都会被重定向。

## Windows PowerShell：复制路径与引号

普通半角直引号（`'` 或 `"`）仅是 **PowerShell 语法**，绝不是文件夹名的一部分。如果 Explorer、终端或聊天文本把路径
显示为一对外层引号，回答 `Read-Host` 时请去掉这对外层引号。

```powershell
# 仅为示例：X: 代表你选择的数据盘。若你的盘符是 E:、F: 等，不要真的创建 X: 盘。
# 单引号只界定 PowerShell 字符串；真实文件夹是 X:\VIREA-DATA，不包含任何引号字符。
$vireaDataRoot = 'X:\VIREA-DATA'

# 如不存在则创建数据根。-Force 允许目录已存在；-Path 接收上面的字符串。
New-Item -ItemType Directory -Force -Path $vireaDataRoot | Out-Null

# 进入数据根、把源码 clone 为其 virea 子目录，再进入 clone。模型不会放在 clone 中。
Set-Location $vireaDataRoot
git clone https://github.com/Moonweave-AI/virea.git
Set-Location virea

# 为当前用户及当前终端持久写入 VIREA、uv、Hugging Face、npm 与 pnpm 路径。
# -DataRoot 传数据根，不传 clone，也不传 home/；变量作为参数时不需要额外加引号。
& .\scripts\configure-virea.ps1 -DataRoot $vireaDataRoot
```

脚本会在每个可能较慢的操作前输出 `[VIREA 1/6]` 至 `[VIREA 6/6]`，完成后输出 `[VIREA complete]`。若卡在某一
阶段，最后一行可直接定位到校验、建目录、写 manifest、持久化环境变量或 Windows 通知中的等待/失败位置。

交互式输入同样支持带空格的目录：

```powershell
# 此提示处只粘贴文件夹路径：X:\VIREA-DATA 或 X:\My AI Data。不要粘贴外层 ' 或 " 字符。
$vireaDataRoot = Read-Host "输入所选数据盘的根路径"

# 原样传入读取到的文本。变量是一个参数，PowerShell 不会把空格拆成多个参数。
& .\scripts\configure-virea.ps1 -DataRoot $vireaDataRoot
```

若不使用变量而是直接写路径，只有路径含空格时才需要加引号；引号仍只是语法，不会保存到路径里：

```powershell
# 含空格的正确直接写法：引号把它组合为一个 PowerShell 参数，但不会成为路径内容。
& .\scripts\configure-virea.ps1 -DataRoot 'X:\My AI Data'
```

请使用键盘输入的半角直引号，不要使用中文/排版的弯引号。不要自行加 `\home`、`\virea`、`\models` 或 `\cache` 后缀：
脚本会创建固定子目录。

## Linux、WSL2 与 macOS：复制路径与引号

Shell 引号也只用于界定参数，不属于路径。`read` 提示处只粘贴路径本身，不能包含外层引号。变量展开必须加引号，才能让
含空格路径保持为一个参数。

```bash
# 仅为示例：选择实际挂载的数据盘。引号只界定 shell 文本；真实目录是 /mnt/virea-data。
virea_data_root='/mnt/virea-data'

# 创建根目录、在其下 clone 源码并进入 clone。
mkdir -p "$virea_data_root"
cd "$virea_data_root"
git clone https://github.com/Moonweave-AI/virea.git
cd virea

# 创建持久目录，并向选择的 shell 启动文件添加 source 行。
# --data-root 必填；为变量展开加引号，避免含空格路径被拆为多个参数。
./scripts/configure-virea.sh --data-root "$virea_data_root"

# 立即在当前 shell 生效生成的设置；新的兼容 shell 会自动加载它。
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"
```

Linux、WSL2 与 macOS 使用相同的六阶段可见输出。首次运行显示 `Added hook:`；以后运行显示
`Hook already present:`，表明启动文件没有被重复追加。

### 从 Windows 选择 WSL 执行域时

Windows 控制面不会把 Windows 的 Runtime 或依赖缓存冒充成 Linux 环境。每个准备从 Windows 选择的
`wsl:<distribution>` 都必须在该发行版内部完成一次上述 POSIX 配置；`wsl.exe --exec` 不会读取交互 shell
启动文件，因此 VIREA 会把脚本生成的 `environment.sh` 当作数据严格解析，而不会执行其中内容。缺失、损坏、
相对路径或不属于同一数据根的配置会使该 WSL 域显示 `configuration-required`，不会回退到
`~/.local/share/virea` 或 Windows 的缓存目录。

```powershell
# 从 Windows 进入 doctor 显示的精确发行版；-d 后是发行版名称，不是泛指“WSL”。
wsl.exe -d Ubuntu-24.04
```

```bash
# 以下命令在刚进入的 WSL shell 内运行。把示例改成该发行版能访问的现有 git clone。
cd '/mnt/e/moonweave-ai/VIREA_LOCAL/virea'

# 为这个 WSL 域选择独立子根，避免 Linux 与 Windows venv 使用同一 home；引号不属于目录名。
wsl_data_root='/mnt/e/moonweave-ai/VIREA_LOCAL/domains/Ubuntu-24.04'

# 写入这个发行版自己的 VIREA_HOME、UV_CACHE_DIR 与 HF_HOME；--data-root 接收上面的根，不接收 home/。
./scripts/configure-virea.sh --data-root "$wsl_data_root"

# 让当前 WSL shell 立即生效；以后新 shell 会由已安装的 hook 自动加载。
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"

# 返回 Windows 后重新运行 uv run virea 或 doctor，新的执行域报告才会读取该配置。
exit
```

模型 checkpoint 仍由控制面作为与操作系统无关的资产复用；只有 WSL 的隔离 Runtime 与依赖缓存使用这个
发行版自己的子根，所以更新源码或修复 Runtime 不需要删除、复制或重新下载已经验证的模型文件。

## 首次配置之后

打开新终端、进入 clone 后，正常命令不再重复传根路径：

```powershell
# Windows：显示新终端继承的持久根目录；它应以 \home 结尾。
$env:VIREA_HOME

# 在该继承目录启动完整逐步向导：自动执行 setup、检测、模型/Runtime 选择、确认、生成与可选浏览器播放。
uv run virea
```

```bash
# Linux、WSL2 或 macOS：显示启动文件 hook 已加载的根目录；它应以 /home 结尾。
printf '%s\n' "$VIREA_HOME"

# 在该继承目录启动完整逐步向导：自动执行 setup、检测、模型/Runtime 选择、确认、生成与可选浏览器播放。
uv run virea
```

自动化仍可显式传 home，但应使用已经定义的环境变量，而不是手工复制路径：PowerShell 使用 `$env:VIREA_HOME`，POSIX
shell 使用 `"$VIREA_HOME"`。

## 更新另一台已经部署过的设备

版本更新不要求重新 clone、删除 `VIREA_HOME` 或重新下载全部模型。下面命令会更新源码、主 workspace 的锁定环境和 Web
build。每个模型的隔离 Runtime 按设计不属于主 workspace；但下一次 `uv run virea` 会比较所选 Runtime 已记录的源码内容
身份与当前锁定源码闭包，只重建缺失或过期的隔离环境。模型 artifact、任务、结果和日志继续使用这台设备最初配置的持久
home。

```powershell
# 进入另一台设备现有的 clone。-LiteralPath 把整段路径作为原样路径；请替换为那台设备的实际 clone。
Set-Location -LiteralPath 'X:\VIREA-DATA\virea'

# 只列出未提交改动，不修改文件。输出为空才适合直接更新；若有改动，先自行提交或保存。
git status --short

# 更新前先在正在运行 VIREA/Web 的终端按 Ctrl+C；已运行的 Python 进程无法自行替换已导入的旧代码。

# 只接受 origin/main 的 fast-forward 更新；不会合并本地分叉，也不会读取或删除 VIREA_HOME 中的模型。
# origin 是默认远端名，main 是要更新的主分支，--ff-only 禁止自动生成 merge commit。
git pull --ff-only origin main

# 严格按 uv.lock 同步所有 Python workspace 包和 dev 工具。
# --locked 禁止重新解析版本；--all-packages 包含所有 workspace 包；--extra dev 包含测试/构建依赖。
uv sync --locked --all-packages --extra dev

# 严格按 package-lock.json 还原根级 Node 依赖；ci 会先清理该 clone 的 node_modules，但不碰数据根其他目录。
npm ci

# 严格按 pnpm-lock.yaml 同步 Web workspace；--frozen-lockfile 禁止修改锁文件。
pnpm install --frozen-lockfile

# 对新 Web 源码执行 TypeScript 检查并重建 apps/web/dist；--dir 指定命令在 apps/web 包中运行。
pnpm --dir apps/web build

# 确认这个新终端仍指向原有持久 home；期望值以 \home 结尾，且不得是 clone 或系统临时目录。
$env:VIREA_HOME

# 只读核验某个既有安装。把 MODEL_ID 替换成 model list/向导显示的真实模型 ID；不要输入尖括号。
uv run virea model verify MODEL_ID

# 从原 home 启动完整向导。READY 安装会复用；向导不会要求先删除模型。
uv run virea
```

Linux、WSL2 与 macOS 使用同一流程，只把第一步和环境变量显示改为 POSIX shell 写法：

```bash
# 进入现有 clone；引号只保护含空格路径，不是路径内容。
cd '/mnt/virea-data/virea'

# 只读检查工作树，然后仅 fast-forward 更新 main。
git status --short
# 先用 Ctrl+C 停止正在运行的 VIREA/Web；重启后的进程才会导入更新代码。
git pull --ff-only origin main

# 同步锁定的 Python 与 Node 环境，并重建当前 Web。
uv sync --locked --all-packages --extra dev
npm ci
pnpm install --frozen-lockfile
pnpm --dir apps/web build

# 显示启动文件持久加载的原 home，然后只读核验目标模型。
printf '%s\n' "$VIREA_HOME"
# 从同一个持久 home 只读核验 MODEL_ID；这条命令不会重新安装或删除模型。
uv run virea model verify MODEL_ID

# 进入完整交互式流程；已验证的本地制品会被复用。
uv run virea
```

`model verify` 若仍返回 `ready: true`，无需修复。若新版本改变了模型 manifest、checkpoint revision、
`runtime_core_epoch` 或 Runtime 源码内容，它可能返回 `installed: true` 但 `ready: false`：模型文件仍在，但新代码会拒绝运行
过期的隔离环境。V2 源码身份会同时比较仓库源码闭包，以及每个隔离 Runtime 中实际安装的 distribution 文件字节；因此，
即使旧构建误写了当前 marker，同版本的过期 wheel 也无法继续复用。该机制统一适用于 Windows/Linux/macOS 原生环境、WSL，
以及所有 CPU/CUDA Runtime 变体。携带旧 V1 marker 的 Runtime 会在首次使用时自动重建一次。身份覆盖 lockfile 与传递性的
本地包闭包（模型包装包、共享 Worker、Model SDK、contracts），所以即使版本号和文件修改时间都没变，Worker 源码修正
也能被识别，不再依赖人工提升版本/epoch。先运行不带 `--apply` 的
`uv run virea model repair MODEL_ID --execution-domain DOMAIN` 查看计划；确认后才追加 `--apply`。`DOMAIN` 是
`windows-native`、`linux-native`、`macos-native` 或实际 `wsl:发行版` ID。重建过期 Python Runtime 不会重新下载通过校验的
checkpoint；只有新 manifest 明确要求不同 artifact revision，或文件缺失/损坏时，才需要下载对应内容。如果已经打开的
Web 页面报告 `ModelResult coordinate_system does not match the manifest`，先用 `Ctrl+C` 停止旧服务，完整执行上面的更新命令，
再运行 `uv run virea`；不要删除 model store 或 checkpoint。

## 迁移到另一块盘

停止 VIREA 进程，选取新的空数据根后，在 clone 内对这个新根重新运行相同配置脚本。脚本只修改未来终端的环境设置，
**不会**替你移动已有模型、任务或缓存。复制/迁移既有状态必须作为单独、经过确认的操作，确保不会静默复制或删除大型
模型目录。
