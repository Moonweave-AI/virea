---
type: reference
status: Generated
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-22
last_reviewed: 2026-08-22
review_cycle_days: 14
summary: 从执行目标 registry 与 RuntimeSpec 生成的平台实现、资源策略和真实设备 evidence 边界。
canonical: doc/platforms/support-matrix.generated.md
related:
  - README.zh-CN.md
  - ../models/support-matrix.generated.md
  - ../quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# 平台支持矩阵

> 此文件由 `python scripts/generate_docs.py` 生成。不要直接编辑。

| Selectable execution domain | Declared Runtime capability | Declared resource profiles | Known deployment blockers (model/domain-scoped) | Observed evidence coverage (model-scoped) |
|---|---|---|---|---|
| Windows native | detector=implemented, resolver=implemented, builder=implemented, worker=implemented<br>matching models: `acmdm-humanml3d`, `cmdm-humanml3d`, `flood-diffusion-tiny`, `mardm-humanml3d`, `momadiff-humanml3d`, `prism-tp2m-1-4b` | cpu (RAM 12 GiB); cpu (RAM 16 GiB); cpu (RAM 24 GiB); cpu (RAM 96 GiB); cuda_component_split (VRAM 12 GiB, RAM 28 GiB); cuda_full (VRAM 12 GiB, RAM 16 GiB); cuda_full (VRAM 16 GiB, RAM 16 GiB); cuda_full (VRAM 6 GiB, RAM 8 GiB) | No structured blocker recorded | No model-scoped observation recorded |
| WSL2 (Linux runtime) | detector=implemented, resolver=implemented, builder=implemented, worker=implemented<br>matching models: `acmdm-humanml3d`, `cmdm-humanml3d`, `flood-diffusion-tiny`, `mardm-humanml3d`, `momadiff-humanml3d`, `prism-tp2m-1-4b` | cpu (RAM 12 GiB); cpu (RAM 16 GiB); cpu (RAM 24 GiB); cpu (RAM 96 GiB); cuda_component_split (VRAM 12 GiB, RAM 28 GiB); cuda_full (VRAM 12 GiB, RAM 16 GiB); cuda_full (VRAM 16 GiB, RAM 16 GiB); cuda_full (VRAM 6 GiB, RAM 8 GiB) | No structured blocker recorded | No model-scoped observation recorded |
| Linux native | detector=implemented, resolver=implemented, builder=implemented, worker=implemented<br>matching models: `acmdm-humanml3d`, `cmdm-humanml3d`, `flood-diffusion-tiny`, `mardm-humanml3d`, `momadiff-humanml3d`, `prism-tp2m-1-4b` | cpu (RAM 12 GiB); cpu (RAM 16 GiB); cpu (RAM 24 GiB); cpu (RAM 96 GiB); cuda_component_split (VRAM 12 GiB, RAM 28 GiB); cuda_full (VRAM 12 GiB, RAM 16 GiB); cuda_full (VRAM 16 GiB, RAM 16 GiB); cuda_full (VRAM 6 GiB, RAM 8 GiB) | No structured blocker recorded | No model-scoped observation recorded |
| macOS native | detector=implemented, resolver=implemented, builder=implemented, worker=implemented<br>matching models: `acmdm-humanml3d`, `cmdm-humanml3d`, `flood-diffusion-tiny`, `mardm-humanml3d`, `momadiff-humanml3d`, `prism-tp2m-1-4b` | cpu (RAM 12 GiB); cpu (RAM 16 GiB); cpu (RAM 24 GiB); cpu (RAM 96 GiB) | No structured blocker recorded | No model-scoped observation recorded |

启动时，控制面先检测可选 execution domains，用户再为同一模型/checkpoint 资产选择 domain；该选择解析并
按需懒构建或复用对应 Runtime、域内路径、构建器与 Worker，不重复安装或下载模型资产。Windows 宿主编排
WSL 使用独立 `wsl:<distro>` domain，不等于 `win-64` 或 `linux-64` 字符串本身。

“Declared Runtime capability”只来自 RuntimeSpec 平台 ABI、已实现资源 profile 和执行域实现声明；manifest
中的 `availability` 字符串不会被当作能力或支持结论。“Known deployment blockers”只读取结构化
model/platform blocker；没有已登记 blocker 也不等于推理通过。“Observed evidence coverage”只展示明确
点名模型的 target-local 观测，不从 target status 扩散到整行模型，也不参与执行域选择或排序。record 的
当前有效性与 promotion 仍以 production evidence registry 为准；缺少观测只表示待实测，不表示 OS 不受支持。
