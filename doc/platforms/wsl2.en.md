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
# Run inside the selected WSL distribution, not in Windows PowerShell. This confirms that the domain itself can resolve Git.
git --version

# Run inside the selected WSL distribution. The wizard detects the exact WSL domain and asks you to choose its model, Runtime and profile before installation.
uv run virea
```

For automation, `DISTRO` is the exact reported distribution name. Do not hand a `\\wsl.localhost` path or WSL interpreter
to Windows `uv sync`. The domain mapper owns the host/guest path view and re-validates it in the target domain. Windows
GPU totals do not replace the WSL Runtime's available VRAM, RAM, swap and storage observation.

## WSL2 RAM quota versus physical host RAM

WSL2 RAM total is the virtual-machine limit visible inside the distribution. It is not the Windows host's installed RAM.
When a 64 GiB host exposes only about 20 GiB to WSL, VIREA reports `configuration-required` instead of claiming the
physical machine is incapable. PRISM needs 28 GiB total RAM in that domain; the guided recommendation is 32 GiB so the
profile is not placed exactly on its boundary.

From Windows PowerShell, preserve unrelated settings and update the global WSL2 file:

```powershell
# Open %UserProfile%\.wslconfig for the current Windows user. Do not create this file inside the Linux distribution.
notepad "$env:USERPROFILE\.wslconfig"
```

```ini
; Keep other settings. Add or update this key under the one [wsl2] section; 32GB is the WSL VM limit.
[wsl2]
memory=32GB
```

```powershell
# Stop all WSL distributions so the global VM setting is reloaded. Save active WSL work before running this command.
wsl --shutdown

# Start the clone's guided flow again. Existing model files and READY installations remain in the configured data root.
uv run virea
```

Installed-capacity admission and live load safety are separate. Total RAM/VRAM decides whether a device can deploy the
profile; the Worker can still stop before loading if current available memory is below its measured safe working-set
headroom. PRISM's CUDA Worker currently requires 15 GiB available before load and 2 GiB remaining afterward.

The browser can run on Windows while the Worker runs in WSL, but evidence must identify both facts; a Windows browser does
not make model inference Windows-native.
