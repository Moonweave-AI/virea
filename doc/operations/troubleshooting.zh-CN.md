---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: 环境探测、资源准入、安装、Worker、结果和浏览器播放的分层排错入口。
canonical: doc/operations/troubleshooting.zh-CN.md
related:
  - troubleshooting.en.md
  - runtime-data-and-retention.zh-CN.md
  - ../platforms/README.zh-CN.md
  - ../quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# 排错

> [中文](troubleshooting.zh-CN.md) · [English](troubleshooting.en.md)

按失败发生的层级处理，不要通过关闭验证或修改结果文件绕过。

| 症状 | 首个检查 | 恢复动作 |
|---|---|---|
| 安装前 `RUNTIME_NOT_BUILDABLE` | 执行域总 RAM/VRAM、平台与 resource profile | 选择已实现且设备总容量满足要求的执行域/profile |
| 下载失败 | artifact revision、许可接受、网络与磁盘 | 重试 repair；失败不得产生 READY |
| Runtime build 失败 | 目标执行域的 uv/Python、lock 和 stdout/stderr tail | 修复执行域，不在 checkout 手装依赖 |
| Worker readiness 超时 | startup timeout、离线资产、模型加载日志 | `model verify` 后 repair；确认进程树已回收 |
| 推理超时/取消 | job state、Worker instance、PID/child tree | 等待有界取消；不得发布 result |
| VRMA 校验失败 | rest hips、root translation、track 数、finite | 修 exporter/adapter，不在 Viewer 中掩盖 |
| 浏览器角色消失或裁切 | VRM rest pose、VRMA absolute hips、console | 使用真实产物重跑 Viewer QA |

## 明明显卡/内存容量足够，却被提示内存不足

若提示仍是 `insufficient free accelerator memory` 或 `insufficient free physical memory`，请先更新 clone；这是旧版
resolver 把瞬时可用量作为部署门槛的行为。当前版本按总 RAM 和总 VRAM 判断安装/部署能力，当前可用值只作为观测。
例如 16 GiB 显卡即使桌面占用了一部分，也满足 16 GiB profile。固件/显示保留区造成的标称 16 GiB、实际
报告 15.9 GiB，只使用最多 512 MiB 的有界容差；它不会把明显更小的显卡放行。RAM 与 VRAM 仍完全独立，
绝不相加。

PRISM CUDA 已实现原生 Windows 与 Linux/WSL。64 GiB RAM + 16 GiB VRAM 的 Windows 主机应选择
component-split CUDA profile（28 GiB 总 RAM、12 GiB 总 VRAM），不要选择尚未实测、要求 96 GiB RAM 的
CPU fallback。更新源码后不需要删除已有模型资产或成功的隔离 Runtime。

如果 64 GiB Windows 主机中的 WSL 只报告约 20 GiB 总内存，整机硬件是足够的，真正不足的是 WSL2 虚拟机
配额。向导会显示 `configuration-required / 需要调整配置`，并为 PRISM 建议 32 GiB。请保留文件中其他设置，
在 Windows PowerShell 执行：

```powershell
# 打开当前 Windows 用户的 WSL2 全局虚拟机配置；$env:USERPROFILE 会解析为该用户的 profile 目录。
notepad "$env:USERPROFILE\.wslconfig"
```

```ini
; 保留其他 section/key；在唯一的 [wsl2] section 下，把 WSL2 虚拟机总内存设为 32 GiB。
[wsl2]
memory=32GB
```

```powershell
# 停止所有正在运行的 WSL 发行版，让新配额在下次启动时生效；执行前先保存 WSL 中未完成的工作。
wsl --shutdown

# WSL 重启后重新运行交互向导；这不会删除或重新下载模型资产。
uv run virea
```

```powershell
# 只以 fast-forward 更新当前 clone；它更新源码，不会下载或删除 VIREA_HOME 中的模型。
git pull --ff-only origin main

# 按提交的 lock 对齐 workspace；数据根中的模型、结果和 READY 安装保持不变。
uv sync --locked --all-packages --extra dev

# 重新进入向导；界面会分别显示总容量和当前可用量。
uv run virea
```

```bash
# Linux、WSL 或 macOS：从 clone 内执行同样的源码 fast-forward 更新。
git pull --ff-only origin main

# 对齐 workspace；持久数据根中的模型 snapshot 与 READY 安装会复用。
uv sync --locked --all-packages --extra dev

# 重新进入向导，只选择当前执行域实际提供的 Runtime。
uv run virea
```

## 仓库已经更新，但模型隔离 Runtime 仍使用旧代码

`uv sync --locked --all-packages --extra dev` 更新的是 VIREA 主 workspace；`VIREA_HOME/runtimes` 下的逐模型环境按设计与其
隔离。当前 VIREA 不再只依据 `project_version` 或 `runtime_core_epoch` 判断能否复用。每个构建完成的 Runtime 都记录一个
SHA-256 源码身份，覆盖 lockfile 和传递性的本地安装闭包（模型包装包、共享 Worker、Model SDK、contracts）。每次复用前，
`uv run virea` 都会把这份记录与当前 clone 比较；记录缺失或任意内容不一致都属于可自动重建的过期状态。

不要删除模型安装或 checkpoint。完成上面的普通 `git pull` 和 `uv sync` 后，运行 `uv run virea`，选择同一模型和执行域即可。
VIREA 会隔离旧 Python 环境、创建并探测新环境，然后原子发布；model store 中已经校验的模型 artifact 会直接复用。Windows
native、Linux native、macOS native 和 WSL 使用同一机制；WSL 的身份文件会在所选发行版自己的 Runtime 前缀中写入和探测。

## 下载成功，但最后显示 `Model state FAILED`

`fetched stable asset` 只说明下载和制品校验成功，不代表后续模型加载、推理、Motion IR 转换、重定向与 VRMA
导出已经通过。若流程到第 6/6 步发布时失败，实际失败层是安装验收。旧版紧凑界面只取诊断列表前 3 条，三个
“制品已获取”消息会把真正的 Worker `error_code` 和 `error_message` 挤掉。

当前版本会优先展示验收错误、失败阶段和安全重试动作；下次运行 `uv run virea` 时也会恢复上次失败摘要。
依赖自己的 `Downloading bytes`、`Reconstructing`、`Fetching files` 会全部收进 VIREA 的单一进度面。不要删除
数据根：重试会复用已验证的稳定制品。

```powershell
# 只把当前 clone fast-forward 到修正后的 main；不会改动持久数据根中的模型文件。
git pull --ff-only origin main

# 按仓库 lock 对齐全部 Python workspace 包；--locked 防止依赖版本漂移。
uv sync --locked --all-packages --extra dev

# 重新打开向导；选择失败模型后，会先展示保存的错误，再询问是否重试。
# 重试直接复用已验证下载，只重新执行未成为 READY 的 Runtime/验收部分。
uv run virea
```

```bash
# Linux、WSL2、macOS：只 fast-forward 当前 clone，不修改持久模型数据根。
git pull --ff-only origin main

# 依据提交的依赖 lock 对齐全部 workspace 包。
uv sync --locked --all-packages --extra dev

# 用同一交互命令恢复失败摘要并重试；已验证制品不会重新下载。
uv run virea
```

## 停止 Web 服务及全部模型进程

请在运行 `virea serve` 的终端按 `Ctrl+C`；只关闭浏览器标签页不会停止服务。正常退出会取消任务、终止 Worker
完整子进程树、重试第一次失败的终止，并只在没有存活 Worker 后释放锁。Runtime 构建和设备检测子进程也接收同一
取消信号，且位于可独立终止的进程组。若终端或机器异常崩溃，下次启动会先核对持久化进程身份再回收孤儿 Worker；
若身份不匹配则安全阻断，而不会误杀被系统复用 PID 的无关进程。

## Git 依赖的 Runtime 构建误报找不到 Git

有些模型 Runtime 的锁文件含固定的 `git+https` 依赖。现在 VIREA 会在**下载模型 artifact 之前**，在用户选定的
执行域中检查 Git。Windows 隔离构建会同时保留 `PATH` 与 `PATHEXT`，因此即使终端宿主漏传 `PATHEXT`，已经安装的
`git.exe` 也仍能被找到。

```powershell
# Windows native：确认这个 PowerShell 窗口实际能找到 Git。
# 输出如 "git version 2.x" 即表示该前置条件已经满足。
git --version
```

```bash
# Linux、macOS 或 WSL：必须在 VIREA 实际选中的那个系统内运行。
# 如果选择的是 WSL，不要在 Windows PowerShell 中执行此检查。
git --version
```

如果这里成功、但旧版 VIREA 报过 `Git executable not found`，更新 checkout 后直接重新运行 `uv run virea`；**不要**删除
VIREA home、model snapshot 或 cache。失败的构建不会发布为 `READY`；下一次尝试会复用已验证的稳定 artifact，只重建尚未
成功的隔离 Runtime。若 Git 确实不存在，先在选定执行域安装 Git，再运行同一命令。WSL 的 Git 必须装在选定 Linux 发行版内，
不是 Windows Git。

## 安装已完成、但最后报 `acceptance runtime selection differs from installation`

旧版 checkout 出现这条信息，是最后发布 `READY` 时的校验缺陷，**不是**检测到的系统、模型文件、Runtime 或推理失败。Worker
启动后会再次采样可用显存，`memory_free_bytes` 的数值可能变化；可用显存是一次观测，不是已选 GPU 的身份。修正后的 VIREA
仍严格比较执行域、Runtime、resource profile、内存策略、物理加速卡及 CUDA 可见性绑定，但不会仅因空闲显存变化而失败。

保留现有持久 home，更新 clone 后用相同选择重新跑一次交互式安装即可。此前终态为 `FAILED` 的 transaction 会保留为可排查
的历史记录，不会被删除或手动晋升；已验证模型 artifact 会复用，原有 Runtime deployment 仍有效时也会复用。

```powershell
# 仅以 fast-forward 方式更新当前 clone；它下载的是源码，不会下载模型或删除结果。
git pull --ff-only origin main

# 让 workspace 与锁文件保持一致。--locked 禁止改动锁定版本；--all-packages 包含全部 VIREA workspace 包；
# --extra dev 保留仓库所需的测试/开发工具。
uv sync --locked --all-packages --extra dev

# 再次进入交互式向导；选择原来的数据根、执行域和模型。
# VIREA 会复用已验证的本地 artifact，不需要你先删除或重新下载它们。
uv run virea
```

收集诊断：

```bash
# 从 clone 后一次配置的持久 home 输出本地支持摘要。
uv run virea support
# 只读查看状态数据库和迁移状态。
uv run virea state inspect
# 只读验证 flood-diffusion-tiny 的最新 READY 安装；诊断其他 manifest 时才替换它的 ID。
uv run virea model verify flood-diffusion-tiny
```

报告问题时附 model/result identity、执行域、doctor report ID、installation/job/result ID 与最小日志尾部，
不要上传 checkpoint、私有 Avatar、原始数据或整个状态数据库。
一次性数据根配置、复制路径和引号规则见[数据根路径与引号规则](../getting-started/persistent-data-root.zh-CN.md)。
