---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: 原生 Linux 的外部环境、CUDA/ROCm/CPU Runtime 与 system lifecycle 要求。
canonical: doc/platforms/linux.zh-CN.md
related:
  - linux.en.md
  - README.zh-CN.md
  - wsl2.zh-CN.md
  - ../getting-started/installation.zh-CN.md
supersedes: []
superseded_by: []
---

# Linux

> [中文](linux.zh-CN.md) · [English](linux.en.md)

```bash
# 一次性读取已挂载数据盘的根路径。
# 提示处只粘贴目录本身，例如 /mnt/virea-data；外层单/双引号不是路径内容，不能输入。
printf '%s' "输入所选数据盘根路径: "
read -r virea_data_root
# 创建 VIREA 目录并安装 shell hook；之后新终端自动继承目录设置。
./scripts/configure-virea.sh --data-root "$virea_data_root"
# 在当前 shell 立即加载生成的设置；之后兼容 shell 将自动加载 hook。
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"
# 确认此 Linux 执行域能找到 Git；装在其他主机或其他 WSL 发行版内的 Git 不满足此检查。
git --version
# 按锁文件安装 Python workspace。
uv sync --locked --all-packages --extra dev
# 启动逐步交互向导：选择模型、Linux 执行域、Runtime/profile，确认安装、生成与播放。
uv run virea
```

原生 Linux 执行域内完成 `uv` 构建、framework probe、Worker、`/proc` 进程身份和浏览器服务。NVIDIA CUDA、
AMD ROCm 与 CPU 是不同 Runtime/profile，不能复用一个 CUDA lock 后仅修改设备字符串。

若本机没有满足模型要求的 GPU，解析器应尝试该模型真实实现的 CPU/offload profile；都不满足时在下载前停止，
列出缺少的 RAM、VRAM、swap 或磁盘，以及可选择的其他 Runtime。

CMDM 与 MoMADiff 声明了 `linux-64` CPU Runtime，但当前 build/import 证据只来自 Windows native 与
`wsl:Ubuntu-24.04`，不能继承为原生 Linux 实测；原生 Linux 的 CPU/CUDA model inference 与
doctor→browser 仍分别待验收。
