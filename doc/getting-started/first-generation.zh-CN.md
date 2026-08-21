---
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 14
summary: 从模型选择、资源准入、真实安装到生成和持久化验证的第一条完整命令路径。
canonical: doc/getting-started/first-generation.zh-CN.md
related:
  - installation.zh-CN.md
  - browser-playback.zh-CN.md
  - ../models/README.zh-CN.md
supersedes: []
superseded_by: []
---

# 第一次真实生成

以下示例使用模型 manifest 的 production acceptance 参数。先从
[模型矩阵](../models/support-matrix.generated.md) 选择适合任务、原生骨骼和资源的模型。

```text
uv run virea model info flood-diffusion-tiny
uv run virea model install flood-diffusion-tiny --apply --virea-home <external-home>
uv run virea model verify flood-diffusion-tiny --virea-home <external-home>
uv run virea generate --model flood-diffusion-tiny --task text_to_motion --prompt "A person walks forward, turns left, and waves with the right hand." --seconds 4 --fps 20 --seed 42 --timeout 1800 --virea-home <external-home>
```

安装前 resolver 会分别检查执行域、VRAM、RAM、swap/pagefile 与磁盘；不满足时不会下载权重或创建安装
事务。安装成功后记录输出中的 installation、job 与 result ID：

```text
uv run virea validate-real-e2e --virea-home <external-home> --job-id <job-id>
```

该验证覆盖真实安装、结果和 VRMA；浏览器播放是下一步独立证据，不能由 CLI 伪造完成。
