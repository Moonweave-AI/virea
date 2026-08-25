---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: English guide to selecting and operating VIREA execution domains on Windows, Linux, WSL2, and macOS.
canonical: doc/platforms/README.en.md
related:
  - README.zh-CN.md
  - ../getting-started.en.md
  - ../reference/cli.en.md
  - ../reference/status-semantics.en.md
  - support-matrix.generated.md
supersedes: []
superseded_by: []
---

# Platforms and execution domains

> [English](README.en.md) · [中文平台指南](README.zh-CN.md) · [CLI selection options](../reference/cli.en.md#model-install-and-model-repair)

VIREA does not label a model as a “Windows model” or “WSL model”. It shares an OS-neutral model asset snapshot and lets
the user choose the actual execution boundary. That boundary determines the Runtime environment, filesystem view,
resource observation, Worker process tree and accelerator backend.

## Detect first, then choose

```bash
# Record the machine's available execution domains and explain unavailable choices. This command is read-only except for the local report.
uv run virea doctor --json --record --explain --virea-home PATH

# Inspect the model's declared Runtimes and resource profiles before choosing an installation target.
uv run virea model info MODEL
```

| Domain ID | Process/resource boundary | Typical use |
|---|---|---|
| `windows-native` | Native Windows process, path and resource space. | Windows Python / CUDA or CPU Runtime. |
| `linux-native` | Native Linux process, path and resource space. | Linux Python / CUDA or CPU Runtime. |
| `macos-native` | Native macOS process, path and resource space. | macOS CPU Runtime where declared. |
| `wsl:<distribution>` | One named WSL Linux distribution. | Linux Runtime inside that specific WSL distribution. |

## Make an explicit selection

```bash
# Preview installation in one selected domain. DOMAIN must be exactly one ID emitted by doctor.
uv run virea model install MODEL --execution-domain DOMAIN --virea-home PATH

# Apply the reviewed installation. RUNTIME and PROFILE are optional exact overrides for advanced users.
uv run virea model install MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --apply --virea-home PATH

# Submit a job to the same selected domain and optional Runtime/profile override.
uv run virea generate --model MODEL --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --task text_to_motion --prompt "A person walks forward" --virea-home PATH
```

`--runtime` and `--resource-profile` must never be used without `--execution-domain`. If the chosen domain cannot build,
load, or reserve the requested profile, the command returns a domain-specific reason. It does not silently switch to the
host OS or a different accelerator.

## What is shared and what is per-domain

| Shared once per model asset revision | Isolated per selected execution domain |
|---|---|
| Official artifact identity and immutable asset snapshot | Locked Runtime environment and interpreter |
| Model/checkpoint files when the selected domain can access them | Framework ABI, device/backend and path mapping |
| Model manifest and native-result contract | Resource admission, lease, Worker process and acceptance job |

Changing domain therefore does not intentionally redownload the same model asset, but the target Runtime can still need
its own build and validation. An asset that is accessible on one domain can be unavailable on another because of path,
license, filesystem, driver or ABI constraints.

## Capability is not proof

The [generated support matrix](support-matrix.generated.md) separates:

1. **Declared Runtime capability** — a locked Runtime declares an ABI and profile for a platform.
2. **Known deployment blocker** — a structured model/domain/stage fact prevents a declared option from becoming ready.
3. **Observed evidence coverage** — a specific model/runtime/domain/device chain was recorded.

An empty blocker list and a declared CPU Runtime do not mean that every model has run inference on every OS. For the
current scope and evidence status, consult the [status semantics](../reference/status-semantics.en.md) and the
[production evidence contract](../quality/production-e2e.zh-CN.md).

All 14 non-test catalog models declare locked whole-model CPU Runtime variants for `win-64`, `linux-64`, `osx-arm64`
and `osx-64`, plus model-specific CUDA variants for `win-64` and `linux-64`. This removes the former six-integrated/eight-
upstream-only capability split, but it does not create real-device evidence. A target acceptance contract is required for
every model, and current real-checkpoint, platform, license and artifact facts remain separate gates. Intel macOS CPU
locks pair the compatible legacy `torch==2.2.2` path with `numpy==1.26.4`; they never resolve that ABI to NumPy 2.x.

## Operating-system notes

- **Windows:** use PowerShell examples from the [tutorial](../getting-started.en.md); keep both `UV_PROJECT_ENVIRONMENT`
  and `VIREA_HOME` outside the clone.
- **Linux:** use native `linux-native` when the detector reports it; use the selected Linux shell's own `VIREA_HOME`.
- **WSL2:** choose the exact `wsl:<distribution>` reported by `doctor`; do not assume a differently named distribution
  is interchangeable.
- **macOS:** choose `macos-native`; only declared CPU Runtimes appear. A declaration or lock baseline is not an Apple
  Silicon or Intel Mac inference claim.

For all commands and options, use the paired [English](../reference/cli.en.md) and [Chinese](../reference/cli.zh-CN.md)
CLI references.
