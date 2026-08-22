---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: 从模型选择、资源准入、真实安装到生成和持久化验证的第一条完整命令路径。
canonical: doc/getting-started/first-generation.zh-CN.md
related:
  - first-generation.en.md
  - ../getting-started.zh-CN.md
  - installation.zh-CN.md
  - browser-playback.zh-CN.md
  - ../models/README.zh-CN.md
supersedes: []
superseded_by: []
---

# 第一次真实生成

> [中文](first-generation.zh-CN.md) · [English](first-generation.en.md) · [完整教程](../getting-started.zh-CN.md)

以下示例使用模型 manifest 的 production acceptance 参数。先从
[模型矩阵](../models/support-matrix.generated.md) 选择适合任务、原生骨骼和资源的模型。

```bash
# 查看模型在每个检测到的执行域中的 Runtime、资源 profile 与阻断原因。
uv run virea model info flood-diffusion-tiny
# 仅预览所选域的安装计划；DOMAIN 必须来自 doctor --json。
uv run virea model install flood-diffusion-tiny --execution-domain DOMAIN --virea-home <external-home>
# 审核后才执行安装；RUNTIME/PROFILE 是可选高级覆盖项，提供时必须保持同一 DOMAIN。
uv run virea model install flood-diffusion-tiny --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --apply --virea-home <external-home>
# 只读验证最新安装仍为 READY。
uv run virea model verify flood-diffusion-tiny --virea-home <external-home>
# 向同一执行域提交文本动作任务；--timeout 的单位是秒，最大为 7200。
uv run virea generate --model flood-diffusion-tiny --execution-domain DOMAIN --runtime RUNTIME --resource-profile PROFILE --task text_to_motion --prompt "A person walks forward, turns left, and waves with the right hand." --seconds 4 --fps 20 --seed 42 --timeout 1800 --virea-home <external-home>
```

安装前 resolver 会分别检查执行域、VRAM、RAM、swap/pagefile 与磁盘；不满足时不会下载权重或创建安装
事务。安装成功后记录输出中的 installation、job 与 result ID：

```bash
# 对返回的 job ID 执行只读真实链校验；success 是期望的终态。
uv run virea validate-real-e2e --virea-home <external-home> --job-id <job-id>
```

该验证覆盖真实安装、结果和 VRMA；浏览器播放是下一步独立证据，不能由 CLI 伪造完成。
