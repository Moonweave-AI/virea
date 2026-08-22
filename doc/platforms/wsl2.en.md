---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: English guide to treating a named WSL2 distribution as an independent VIREA execution domain.
canonical: doc/platforms/wsl2.en.md
related:
  - wsl2.zh-CN.md
  - README.en.md
  - windows.en.md
  - linux.en.md
supersedes: []
superseded_by: []
---

# WSL2

> [English](wsl2.en.md) · [中文](wsl2.zh-CN.md)

WSL2 is an independent Linux execution domain, not an accelerator label attached to Windows Python. Its detector, `uv`,
cache, isolated environment, Worker and resource observation must run in the same named distribution.

First follow the [Linux data-root setup](linux.en.md) **inside the selected distribution**. At its path prompt, paste
only the Linux directory (for example `/mnt/virea-data`), without outer single or double quotation marks.

```bash
# Run inside the selected WSL distribution. The wizard detects the exact WSL domain and asks you to choose its model, Runtime and profile before installation.
uv run virea
```

For automation, `DISTRO` is the exact reported distribution name. Do not hand a `\\wsl.localhost` path or WSL interpreter
to Windows `uv sync`. The domain mapper owns the host/guest path view and re-validates it in the target domain. Windows
GPU totals do not replace the WSL Runtime's available VRAM, RAM, swap and storage observation.

The browser can run on Windows while the Worker runs in WSL, but evidence must identify both facts; a Windows browser does
not make model inference Windows-native.
