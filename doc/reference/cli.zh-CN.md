---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: VIREA CLI 的完整中文参考，逐项说明命令、位置参数、选项、副作用和安全示例。
canonical: doc/reference/cli.zh-CN.md
related:
  - cli.en.md
  - status-semantics.zh-CN.md
  - ../getting-started.zh-CN.md
  - ../../README.zh-CN.md
  - ../../apps/cli/src/virea_cli/main.py
supersedes: []
superseded_by: []
---

# VIREA CLI 参数参考

> [中文](cli.zh-CN.md) · [English CLI reference](cli.en.md) · [从 clone 到结果](../getting-started.zh-CN.md)

在 clean clone 中先执行 `uv sync --locked --all-packages --extra dev`。所有示例使用 `uv run`，确保调用的是锁定的
项目环境。自动化场景请把 `VIREA_HOME` 放在容量足够的数据盘且 checkout 外，并显式传入 `--virea-home PATH`。
会创建或访问持久状态的命令在未给出该路径时会拒绝执行，不会静默把模型数据写入 `LOCALAPPDATA` 或 `$HOME`。

一次性路径输入的精确规则（Windows 复制路径、外层引号、空格和后续新终端）见[选择并持久化 VIREA 数据根目录](../getting-started/persistent-data-root.zh-CN.md)。
完成后，下面普通交互命令刻意省略 `--virea-home`，因为它们会使用持久化的 `VIREA_HOME`。

## 推荐的交互式入口

```bash
# 启动完整逐步流程：确认数据根、初始化状态、选择模型/执行域/Runtime/profile、确认安装、生成，并可选启动本地播放。
uv run virea
```

这是面向人工操作的标准命令。它不是每次从零开始：向导从 `VIREA_HOME/config/wizard-preferences.json`
恢复上次模型、执行域、Runtime 和资源 profile，并从状态库恢复持久部署元数据与最近任务；完整字节复验会在
实际执行边界完成。保存项后标有
`[saved / 已保存]`，直接按 Enter 即可复用；输入其他序号会明确替换该选择，输入 `q` 可安全退出。

七个阶段会展示以下事实：

| 阶段 | 展示与行为 |
|---|---|
| 数据根 | 显示当前 `VIREA_HOME`，可复用，也可明确改到另一块数据盘。 |
| 设备与状态 | 真实检测当前设备/执行域，并展示上次模型、环境、READY 数量和最近任务。 |
| 模型 | 分组表格显示全部 14 个非测试 `integrated_experimental` 目录项。每个模型都会显示持久 `READY`（执行前复验）、可安装或需处理状态，以及人工资产、许可、资源和当前 evidence 条件。target-acceptance 合同使模型具备部署入口，但不代表当前真实 checkpoint 已通过。 |
| 执行环境 | 显示总/可用 RAM 与总 VRAM，再分别选择系统执行域、已实现 Runtime 和资源 profile；历史选择只是默认值，不会静默强制。 |
| 部署 | 匹配的持久 READY 快照默认复用且不重新下载；启动 Worker 前会完整复验字节。不同执行环境会建立独立部署并保留旧快照。 |
| 生成 | 依次显示提交、模型推理和结果制品收集；成功时只显示 job/result ID 摘要。 |
| 浏览器 | 可选启动同步显示源骨架与最终 VRM 的本地工作台。 |

部署门槛用总 RAM/VRAM 容量与 profile 比较；当前可用 RAM/VRAM 是实时观测，不代表硬件能力。平台不匹配的
Runtime 会作为不可用事实说明，但不会进入可按序号选择的列表。

顶部会保留一个紧凑的七步 rail 和已恢复 session 摘要，因此无需重复整块面板，也能持续看到当前阶段、保存的目标、
持久 READY 数量和最近状态。所有状态同时使用文字与符号，颜色只作辅助。已知传输总量使用真实 bytes，未知总量保持
indeterminate。

进度条只在真实完成一个阶段边界时前进。Hugging Face/Xet 传输期间，VIREA 会禁止依赖自己输出
`Downloading bytes`、`Reconstructing` 和 `Fetching files` 进度条，把下载/重建的字节数与速率接入 VIREA
的唯一动态行；若某个依赖版本不遵守自定义进度适配器，还会由只过滤已知进度帧、但保留普通警告/错误的
兼容边界收口。因此无论 Windows、Linux、WSL2、macOS 还是 IDE 终端，都不会再把回车刷新累积成几百行。
下载、Runtime 构建和模型推理无法预知
可信总量时，会显示活动指示器与已用时间，不伪造百分比。交互模式不会打印完整 RAW JSON；失败只显示
错误码、主要原因、下一步和证据目录，完整事务仍保存在 `VIREA_HOME/state` 与 `VIREA_HOME/logs`。下面的
显式子命令继续保持机器可读 JSON，供自动化和高级诊断使用，同时不会向 stderr 混入第三方原始进度条。

若安装到发布阶段仍未成为 `READY`，紧凑结果会把验收 `error_code`、`error_message`、失败阶段和重试动作放在
“制品下载成功”之前。重新打开 `uv run virea` 也会从失败 transaction 恢复这段摘要。已验证的稳定制品仍可
复用，因此用相同模型/环境重试不会重新下载。

颜色和动态进度只在交互式终端启用。重定向输出、`TERM=dumb` 或设置 `NO_COLOR` 时自动退化为逐行纯文本，
不会丢失阶段或结果。模型下载只记录第一次传输快照、每 15 秒至多一次的中间快照和最后一次完成快照，
因此 CI 日志和 PowerShell 捕获输出不会持续刷屏：

```powershell
# Windows：本次运行禁用颜色；$env:NO_COLOR 只影响当前 PowerShell 会话，命令仍进入完整交互流程。
$env:NO_COLOR = "1"
# 启动同一个完整向导；本次使用纯文本状态且不输出 ANSI 颜色序列。
uv run virea
```

```bash
# Linux、WSL2、macOS：只对这一条命令禁用颜色，退出后无需恢复变量。
NO_COLOR=1 uv run virea
```

下面的命令是非交互/自动化参考，仅在需要可重复脚本或高级修复时使用。

```bash
# 显示完整命令树和内建帮助；不会修改状态或访问网络。
uv run virea --help

# 显示已安装的 VIREA CLI 版本；提交诊断时可附带此信息。
uv run virea --version
```

## 约定与通用占位符

| 项目 | 含义 |
|---|---|
| `PATH` | 位于用户选定数据盘、checkout 外且可写的目录；保存状态、模型资产、Runtime、下载、日志和结果。 |
| `MODEL` | `virea model list` 返回的 manifest ID，例如 `flood-diffusion-tiny`。 |
| `DOMAIN` | `virea doctor --json` 返回的 canonical 执行域 ID：`windows-native`、`linux-native`、`macos-native` 或 `wsl:<distribution>`。 |
| `RUNTIME` | 对 `MODEL` 在 `DOMAIN` 中有效的可选 Runtime variant ID。 |
| `PROFILE` | 对 `RUNTIME` 有效的可选资源 profile，例如 `cuda-full` 或 `whole-model-cpu`。 |
| `JOB_ID` / `RESULT_ID` | `generate` 返回的持久化 ID，不是文件名。 |

`--execution-domain`、`--runtime` 与 `--resource-profile` 是同一个选择对象。提供 `--runtime` 或
`--resource-profile` 时必须提供 `--execution-domain`。显式选择无效时只会在该域内失败，不会悄悄改用其他
操作系统、加速器或 profile。

以下交互式示例使用持久化 home，因此无需传路径参数。自动化也应沿用已配置变量，避免再次手工复制路径：

```powershell
# Windows 自动化：$env:VIREA_HOME 已配置为一个参数，即使目录含空格也不会被拆分。
uv run virea state inspect --virea-home $env:VIREA_HOME
```

```bash
# Linux、WSL2 与 macOS 自动化：引号让已配置目录始终作为一个参数传入。
uv run virea state inspect --virea-home "$VIREA_HOME"
```

## 一次性数据根配置

clone 后、`uv sync` 前只运行一次对应脚本。它会在用户选择的数据根下创建 `home/`、`dev-venv/`、`uv-cache/`、
`npm-cache/` 与 `pnpm-store/`：`home/` 即 `VIREA_HOME`，承载模型数据及 `HF_HOME` 缓存；其余目录承载 Python/Node
开发环境与依赖缓存。
只有迁移到另一块数据盘时才需要重新运行。

不要把引号粘贴到 `Read-Host` 或 `read` 的回答中。例如选定 Windows 根显示为 `'X:\VIREA-DATA'` 时，输入
`X:\VIREA-DATA`；外层引号只是源码文本界定符。含空格路径的完整复制/粘贴案例见上面的数据根指南。

```powershell
# 提示处只粘贴目录本身，例如 X:\VIREA-DATA；外层单/双引号不是路径内容，不能输入。
$vireaDataVolume = Read-Host "输入所选数据盘的根路径"
# -DataRoot 是必填参数且必须位于 clone 外；以后 Windows 终端自动继承这些路径。
& .\scripts\configure-virea.ps1 -DataRoot $vireaDataVolume
```

```bash
# 提示处只粘贴目录本身，例如 /mnt/virea-data；外层单/双引号不是路径内容，不能输入。
printf '%s' "输入所选数据盘根路径: "
read -r virea_data_root
# --data-root 为必填参数；仅在探测到的 shell 启动文件不合适时才传可选 --shell-profile PATH。
./scripts/configure-virea.sh --data-root "$virea_data_root"
# 立即载入生成变量；以后兼容 shell 通过已安装的 hook 自动载入。
. "${XDG_CONFIG_HOME:-$HOME/.config}/virea/environment.sh"
```

## `setup`

```bash
# 在一次配置的持久 VIREA_HOME 下创建或迁移本地状态；不安装模型，也不修改系统软件。
uv run virea setup
```

| 选项 | 含义 |
|---|---|
| `--virea-home PATH` | 要初始化的状态根目录；仅在一次性配置已设置 `VIREA_HOME` 后才可省略，否则持久命令会拒绝请求。 |

## `doctor`

```bash
# 检查执行域、Python、驱动和资源，写入本地报告并附带不会自动执行的修复建议。
uv run virea doctor --json --record --explain --repair-plan
```

| 选项 | 含义 |
|---|---|
| `--virea-home PATH` | `--record` 写入报告时使用的状态根。 |
| `--json` | 输出机器可读 JSON，而不是只输出面向人的文本。 |
| `--record` | 将本次 doctor 报告持久化到本地，供后续安装/证据链绑定。 |
| `--explain` | 输出域、Runtime 和 profile 不可用的详细原因。 |
| `--repair-plan` | 输出建议修复动作，但绝不自动应用。 |

`doctor` 只检测事实：不下载模型资产，也不因发现 GPU 就声称该模型已完成推理。

## `model list`、`search`、`info` 与 `bundle`

```bash
# 用 JSON 列出整个模型目录；脚本可读取，且没有安装副作用。
uv run virea model list --json

# 用具体任务 text_to_motion 搜索目录；--json 让脚本可读取结果。
uv run virea model search text_to_motion --json

# 显示 flood-diffusion-tiny 的资产、许可门、Runtime、profile 和逐域阻断原因。
uv run virea model info flood-diffusion-tiny

# 列出所有声明的 release bundle；之后要查看某个 bundle 时再追加这里返回的精确 ID。
uv run virea model bundle
```

| 命令 / 参数 | 含义 |
|---|---|
| `model list --json` | `--json` 将目录输出切换为 JSON。 |
| `model search [QUERY] --json` | `QUERY` 是可选自由文本；`--json` 切换输出格式。 |
| `model info MODEL` | `MODEL` 必填，必须是目录中的 manifest ID。 |
| `model bundle [BUNDLE_ID]` | 不带 ID 列出 bundle；带 ID 查看对应 bundle。 |

<a id="model-install-and-model-repair"></a>

## `model install` 与 `model repair`

```bash
# Windows 示例：仅预览 flood-diffusion-tiny 的原生 Windows 域。Linux、WSL2、macOS 必须改用 doctor 输出的域。
uv run virea model install flood-diffusion-tiny --execution-domain windows-native

# Windows NVIDIA 示例：仅在 model info 与预览确认该精确 Runtime/profile 可用后才执行安装。
uv run virea model install flood-diffusion-tiny --execution-domain windows-native --runtime flood-diffusion-tiny-cu128 --resource-profile cuda-full --apply

# 预览最新 Windows 域安装的修复。确认计划后才添加 --apply。
uv run virea model repair flood-diffusion-tiny --execution-domain windows-native
```

`install` 可能获取或引用资产、构建隔离 Runtime、运行声明的验收合同或套件并发布 READY 安装。对于多任务模型，
它会按照 manifest 任务顺序，为每个声明任务执行一个不可变合同。每个任务都必须产生自己独立的 Job/result evidence
并通过；只通过主任务不能让包含失败或未执行任务的套件成为 READY。`repair` 在最新安装不健康时规划新事务；两个
命令都不会 fallback 到另一个执行域。

| 选项 | 含义 |
|---|---|
| `MODEL` | 必填模型 manifest ID。 |
| `--apply` | 明确授权本地安装/修复写入；省略时只输出计划。 |
| `--accepted-license` | 对要求确认的 manifest 记录本地确认，不授予任何权利。 |
| `--execution-domain DOMAIN` | 多域机器上必填；使用 Runtime/profile 覆盖时也必填。 |
| `--runtime RUNTIME` | 可选精确 Runtime 覆盖；必须属于该 `MODEL` 和 `DOMAIN`。 |
| `--resource-profile PROFILE` | 可选精确资源策略覆盖；必须属于所选 Runtime。 |
| `--artifact-root ID=PATH` | 不复制地复用一个明确外部资产目录；`ID` 必须是 manifest artifact ID。 |
| `--artifact-revision ID=REVISION` | 对该外部资产 ID 的 manifest 固定 revision 做确认；与 `--artifact-root` 配合使用。 |
| `--validation-prompt TEXT` | 兼容性断言：提供时必须等于不可变 manifest 验收 prompt；它不会改写合同。 |
| `--validation-seconds NUMBER` | 对不可变验收 `parameters.seconds` 的兼容性断言；不同值会被拒绝。 |
| `--validation-seed INTEGER` | 对不可变确定性验收 seed 的兼容性断言；不同值会被拒绝。 |
| `--validation-timeout SECONDS` | 对不可变验收 timeout 的兼容性断言；不同值会被拒绝。 |
| `--virea-home PATH` | 读取并修改的状态根目录。 |

对于验收套件，四个标量 `--validation-*` 选项只有在所给值与每个任务合同的对应值完全一致时才会被接受。若各任务
使用不同值或没有该值，请省略对应选项。这些参数不能选择单个任务、跳过其他任务或修改套件。

外部资产覆盖只适用于你有权使用、且能持续保留的资产。`--artifact-revision` 只记录你对 manifest 固定 revision
的确认，并不是内容证明。install/repair 期间，VIREA 会先要求全部 `expected_files` 哨兵存在，再完整读取该外部
制品根目录下的每个普通文件，记录相对路径、字节长度与 SHA-256，并把完整内容树绑定到安装的
`artifact_identity`。不要让 `--artifact-root` 指向即将被清理的缓存，也不要在 READY 安装背后增加、删除或修改文件。

内部符号链接或 Windows junction 只有在解析后仍指向同一制品根目录内的文件或目录时才允许。断裂链接、外部目标
与未知 reparse point 会 fail closed；不要用它们从设备其他位置拼装模型根目录。

## `model verify`、`remove` 与垃圾回收

```bash
# 读取 flood-diffusion-tiny 的最新安装，验证 READY 状态、资产和验收事实。
uv run virea model verify flood-diffusion-tiny

# 预览移除 MODEL 的最新安装；预览不会删除数据。
uv run virea model remove flood-diffusion-tiny

# 应用审核过的移除计划；会修改本地状态，但不会递归删除无关共享资产。
uv run virea model remove flood-diffusion-tiny --apply

# 预览回收超过 7 天（168 小时）、且不再引用的模型数据。
uv run virea model gc --dry-run --older-than-hours 168

# 应用审核过的模型数据保留策略。
uv run virea model gc --apply --older-than-hours 168
```

| 选项 | 含义 |
|---|---|
| `model verify MODEL` | `MODEL` 必填；命令只读。 |
| `model remove --apply` | `--apply` 才授权本地移除；默认是预览。 |
| `model gc --dry-run` | 明确的无写入保留计划。 |
| `model gc --apply` | 执行满足条件的清理；不要对未经审核的宽泛 home 路径使用。 |
| `--older-than-hours HOURS` | 不再引用数据的最小年龄阈值；省略时使用策略默认值。 |
| `--virea-home PATH` | 要检查或修改的状态根。 |

`model verify` 会重新计算 expected-file 内容哈希，并检查验收 evidence 是否仍指向精确的 `installation_id` 与
`artifact_identity`；它绝不会改写旧 evidence。若你有意替换或修改人工外部权重，请停止使用旧安装，先运行只读
复验，再创建新事务：

```bash
# 证明 MODEL 原有 READY/evidence 绑定已不能证明变更后的字节；把 MODEL 换成精确 manifest ID。
uv run virea model verify MODEL

# 重新哈希 expected-files 的完整内容并重跑每个任务验收；DOMAIN、ARTIFACT_ID、PATH、REVISION 均替换为 doctor/model info 给出的值。
uv run virea model repair MODEL --execution-domain DOMAIN --artifact-root ARTIFACT_ID=PATH --artifact-revision ARTIFACT_ID=REVISION --apply
```

新事务必须通过完整验收套件，并产生重新绑定的 `installation_id` 与 `artifact_identity`，才能成为 READY。如果恢复
的是之前验收过的精确字节，则完整复验可以确认原有内容身份。

## `generate`

```bash
# Windows 示例：向一个已 READY 的原生 Windows 安装提交受限 text-to-motion 任务。
uv run virea generate --model flood-diffusion-tiny --execution-domain windows-native --task text_to_motion --prompt "A person walks forward" --seconds 4 --fps 20 --seed 42 --timeout 1800
```

| 选项 | 含义 |
|---|---|
| `--model MODEL` | 模型 manifest ID；有意义的生成请求必须提供。 |
| `--task TASK` | 请求任务 ID，例如 `text_to_motion`；必须被所选模型支持。 |
| `--prompt TEXT` | 模型输入文本；分享支持包时把它当成本地 job 数据。 |
| `--seconds NUMBER` | 请求动作时长（秒）；manifest/Worker 可有独立边界。 |
| `--fps NUMBER` | 请求输出帧率；必须与模型/目标合同兼容。 |
| `--seed INTEGER` | 所选模型支持时的可复现随机 seed。 |
| `--denoise-steps INTEGER` | 可选、模型特定的采样步数覆盖；省略时使用 manifest/Worker 默认值。 |
| `--idempotency-key TEXT` | 可选客户端键，避免意外创建重复的等价 job。 |
| `--execution-domain DOMAIN` | 选择的执行域；多候选或使用覆盖时必填。 |
| `--runtime RUNTIME` | 可选精确 Runtime variant 覆盖。 |
| `--resource-profile PROFILE` | 可选精确资源 profile 覆盖。 |
| `--timeout SECONDS` | 端到端等待和 Worker 推理超时；最大 `7200`。 |
| `--virea-home PATH` | 包含 READY 安装和结果数据库的状态根。 |

命令返回持久化 ID。它不构成公开发布声明，成功结果也不能复制到另一个执行域来伪造那里运行过的证据。

<a id="serve"></a>

## `serve`

```bash
# 在回环地址提供本地 API 与唯一的新版浏览器 UI；浏览器打开规范根地址 http://127.0.0.1:8000/。
uv run virea serve --host 127.0.0.1 --port 8000
```

| 选项 | 含义 |
|---|---|
| `--host ADDRESS` | 绑定地址。本地使用优先 `127.0.0.1`；对外暴露控制面需要单独安全审查。 |
| `--port NUMBER` | API 与 Web UI 的 TCP 端口；选择未占用的本地端口。 |
| `--reload` | 开发期自动重载；不要将其当作生产进程管理器。 |
| `--virea-home PATH` | 该控制面服务的状态根。 |
| `--data-source {full,demo}` | legacy Preview 路由的废弃兼容选项；优先 `VIREA_DATA_SOURCE` 或每请求 `data_source`，正常 0.4 生成无需使用。 |

根地址会跳转到 `/app/`；后者只是挂载路径，并不是第二套 UI。同一 `VIREA_HOME` 下的 CLI 变更会通过本地状态流
自动显示，无法建立状态流时自动降级轮询。

## `state` 与 `support`

```bash
# 只读查看当前本地数据库/状态摘要。
uv run virea state inspect

# 应用已知本地 schema migration；设计为可重复执行。
uv run virea state migrate

# 预览状态/日志清理；只在审核完路径后使用 --apply。
uv run virea state gc --dry-run --older-than-hours 168

# 输出简洁本地诊断摘要，最多包含 20 条近期 job。
uv run virea support --jobs 20
```

| 选项 | 含义 |
|---|---|
| `state inspect` | 只读的当前状态摘要。 |
| `state migrate` | 应用本地 schema migration。 |
| `state gc --dry-run` / `--apply` | 预览 / 应用状态保留策略。 |
| `--older-than-hours HOURS` | 可清理状态数据的年龄阈值。 |
| `support --jobs COUNT` | 要包含的近期 job 摘要数量。 |
| `--virea-home PATH` | 要检查或修改的状态根。 |

## 证据校验器

```bash
# 校验一条持久化真实安装/生成链。将 job_123 换成 generate 返回的精确 job_id；--job-id 与 --result-id 二选一。
uv run virea validate-real-e2e --job-id job_123 --expect success

# 将独立采集的浏览器 observation 文件与后端持久化事实绑定；--output 指定要写入的已校验 JSON。
uv run virea validate-production-e2e-evidence --observation browser-observation.json --output validated-browser-evidence.json
```

| 选项 | 含义 |
|---|---|
| `validate-real-e2e --job-id JOB_ID` | 按 job ID 校验；与 `--result-id` 互斥。 |
| `validate-real-e2e --result-id RESULT_ID` | 按 result ID 校验；与 `--job-id` 互斥。 |
| `--expect {success,cancelled,recovered}` | 期望终态；省略时使用命令正常成功预期。 |
| `--plugin-root PATH` | 在隔离/fresh-install 校验器环境中可选指定 plugin 根。 |
| `validate-production-e2e-evidence --observation FILE` | 必填的浏览器 observation JSON；必须来自独立浏览器证据流程。 |
| `--output FILE` | 验证后 evidence 的可选输出路径；省略时使用命令默认位置。 |
| `--virea-home PATH` | 两个校验器都必需的状态根。 |

这些命令校验本地不可变事实，不能替代上游许可证、公开发布审批或逐模型浏览器证据流程。
