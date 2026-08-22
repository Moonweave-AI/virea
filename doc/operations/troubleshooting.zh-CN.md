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
| 安装前 `RUNTIME_NOT_BUILDABLE` | doctor 的执行域与每个 resource profile 诊断 | 释放资源或选择真实实现的 CPU/WSL/MPS/ROCm profile |
| 下载失败 | artifact revision、许可接受、网络与磁盘 | 重试 repair；失败不得产生 READY |
| Runtime build 失败 | 目标执行域的 uv/Python、lock 和 stdout/stderr tail | 修复执行域，不在 checkout 手装依赖 |
| Worker readiness 超时 | startup timeout、离线资产、模型加载日志 | `model verify` 后 repair；确认进程树已回收 |
| 推理超时/取消 | job state、Worker instance、PID/child tree | 等待有界取消；不得发布 result |
| VRMA 校验失败 | rest hips、root translation、track 数、finite | 修 exporter/adapter，不在 Viewer 中掩盖 |
| 浏览器角色消失或裁切 | VRM rest pose、VRMA absolute hips、console | 使用真实产物重跑 Viewer QA |

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
