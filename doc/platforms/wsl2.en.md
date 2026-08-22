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

```bash
# Run inside the selected WSL distribution to inspect the available domain IDs; it does not download or run a model.
uv run virea doctor --json --explain --virea-home PATH

# Preview an installation in the exact WSL domain reported by doctor, such as wsl:Ubuntu-24.04.
uv run virea model install MODEL --execution-domain wsl:DISTRO --virea-home PATH
```

`DISTRO` is the exact reported distribution name. Do not hand a `\\wsl.localhost` path or WSL interpreter to Windows
`uv sync`. The domain mapper owns the host/guest path view and re-validates it in the target domain. Windows GPU totals
do not replace the WSL Runtime's available VRAM, RAM, swap and storage observation.

The browser can run on Windows while the Worker runs in WSL, but evidence must identify both facts; a Windows browser does
not make model inference Windows-native.
