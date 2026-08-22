---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: Windows native 执行域的外部环境、资源探测、CUDA/CPU 路径和故障恢复。
canonical: doc/platforms/windows.zh-CN.md
related:
  - windows.en.md
  - README.zh-CN.md
  - wsl2.zh-CN.md
  - ../getting-started/installation.zh-CN.md
supersedes: []
superseded_by: []
---

# Windows

> [中文](windows.zh-CN.md) · [English](windows.en.md)

## 推荐目录

选择有足够容量的数据盘作为生产状态目录；不要把模型写到 C 盘用户目录。`LOCALAPPDATA` 仅是小型只读探测的
兼容回退，持久命令必须显式给出 `VIREA_HOME` 或 `--virea-home`：

```powershell
# 列出文件系统卷和可用空间，再选择实际数据盘。
Get-PSDrive -PSProvider FileSystem
# 一次性读取所选数据盘根路径；脚本会在其下创建开发环境和持久数据目录。
# 提示处只粘贴目录本身，例如 X:\VIREA-DATA；外层单/双引号不是路径内容，不能输入。
$vireaDataVolume = Read-Host "输入所选数据盘的根路径"
# 持久写入 VIREA_HOME、UV_PROJECT_ENVIRONMENT、UV_CACHE_DIR、HF_HOME；以后 Windows 终端自动继承。
& .\scripts\configure-virea.ps1 -DataRoot $vireaDataVolume
# 按锁文件安装 Python workspace。
uv sync --locked --all-packages --extra dev
# 启动逐步交互向导：选择模型、Windows 执行域、Runtime/profile，确认安装、生成与播放。
uv run virea
```

不要在仓库根目录创建 `.venv`、权重缓存、日志或 job。模型安装器会在下载前分别检查可用显存、物理内存、
pagefile 和磁盘。

## CUDA 与 CPU

- NVIDIA Runtime 只在目标隔离 Python 的 Torch/ABI/compute capability 复验成功后标记 ready。
- 支持 `cpu` 的模型可以在 CUDA profile 资源不足时选择 whole-model CPU；没有实现 CPU/offload 的模型不会
  把 RAM 假装成 VRAM。
- CMDM 与 MoMADiff 的独立 CPU locks 已在 Windows 完成构建和隔离 Worker import；这只证明 Runtime 可构建，
  不等于 CPU checkpoint inference 或 doctor→browser 已通过。
- Windows 宿主需要运行 Linux Runtime 时使用 [WSL2 执行域](wsl2.zh-CN.md)，不得把 WSL Python 路径交给
  Windows `uv`。

## 恢复

`virea support` 输出诊断摘要；`virea state inspect` 查看状态；`virea model verify <model-id>` 重新验证
READY snapshot。强制终止后，控制面会按进程创建身份、可执行文件和完整参数核验孤儿 Worker，身份不匹配时
绝不误杀。
