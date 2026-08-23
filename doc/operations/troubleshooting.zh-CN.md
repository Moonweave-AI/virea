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
例如 16 GiB 显卡即使桌面占用了一部分，也满足 16 GiB profile；但 64 GiB 内存的机器仍不满足 PRISM CPU 的
96 GiB profile。WSL 使用该发行版内部实际可见的总内存上限。

向导也会从编号菜单移除平台不匹配的 Runtime。PRISM 的 CUDA Runtime 只实现 Linux，因此应在 Linux/WSL 选择，
不能在 `windows-native` 选择；Windows 会显示已实现的 CPU variant 及其 96 GiB 总 RAM 要求。更新源码后不需要删除
已有模型资产或成功的隔离 Runtime。

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
