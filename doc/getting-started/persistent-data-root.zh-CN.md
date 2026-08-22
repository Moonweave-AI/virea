---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
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

## 迁移到另一块盘

停止 VIREA 进程，选取新的空数据根后，在 clone 内对这个新根重新运行相同配置脚本。脚本只修改未来终端的环境设置，
**不会**替你移动已有模型、任务或缓存。复制/迁移既有状态必须作为单独、经过确认的操作，确保不会静默复制或删除大型
模型目录。
