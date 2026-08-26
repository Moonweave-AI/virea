---
type: runtime-guide
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: FloodDiffusionTiny 隔离 Worker 的固定制品、离线加载与原生输出契约。
canonical: plugins/models/flood-diffusion-tiny/runtime/README.md
related:
  - ../manifest.yaml
  - RESEARCH_SELECTION.md
supersedes: []
superseded_by: []
---

# FloodDiffusionTiny managed runtime

This directory is the isolated Worker source owned by the
`flood-diffusion-tiny` VIREA model plugin. It is deliberately nested with the
model manifest so that a checkout contains no root-level runtime project.

Only source, dependency declarations, the lock file, and legal notices belong
here. Virtual environments, Hugging Face snapshots, logs, jobs, and generated
motion are created below `VIREA_HOME` by the control plane; they must never be
written into this directory.

The production entry point is shown below. VIREA invokes it automatically;
users do not need to run it themselves. / 生产启动入口如下。VIREA 会自动调用，
用户无需手动执行：

```shell
# Start the shared diagnostic wrapper, then load the Flood Worker module.
# 启动共享诊断包装器，然后加载 Flood Worker 模块。
python -m virea_model_sdk.worker_entrypoint virea_flood.worker
```

`python -m` runs an installed Python module; `virea_model_sdk.worker_entrypoint`
is the shared startup wrapper that records a bounded structured failure when a
Worker cannot become ready; `virea_flood.worker` is the positional module name
loaded by that wrapper. / `python -m` 用于运行已安装的 Python 模块；
`virea_model_sdk.worker_entrypoint` 是共享启动包装器，会在 Worker 无法就绪时
记录有界的结构化失败证据；`virea_flood.worker` 是由包装器加载的位置参数模块名。

Users should not install or invoke this project directly. The supported flow is
`virea doctor` → `virea model install flood-diffusion-tiny --apply` →
`virea generate ...`. The model plugin supplies the pinned FloodDiffusionTiny
and UMT5 revisions, installation roots, offline settings, memory strategy, and
the versioned HumanML3D 263D/body-22 output contract.

The Worker does not download weights, search the current working directory, or
fall back to a generated fixture. Missing official artifacts, an unsupported
memory strategy, or an unusable CUDA runtime fails closed before inference.

See the parent [manifest](../manifest.yaml) for the authoritative model,
skeleton, representation, runtime, artifact, and production-acceptance
contracts. Third-party terms are summarized in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
