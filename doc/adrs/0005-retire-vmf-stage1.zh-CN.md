---
type: adr
status: Accepted
owner: "@Joker-of-Gotham"
decision_owner: "@Joker-of-Gotham"
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 180
summary: 退役已失去产品用途的 VMF Stage 1 训练支线，同时保留 VIREA 共享动作数学、运行时与发布契约。
canonical: doc/adrs/0005-retire-vmf-stage1.zh-CN.md
related:
  - 0003-multi-package-isolated-model-runtimes.zh-CN.md
  - ../rfcs/0003-virea-0.3-multi-model-refactor.zh-CN.md
  - ../refactor/RELEASE_ACCEPTANCE_0.4.0.md
supersedes: []
superseded_by: []
---

# ADR-0005：退役 VMF Stage 1 训练支线

## 决策

2026-08-21，Decision Owner 明确确认 VMF 是此前模型训练的遗留产物，并批准完整退役。VIREA 删除
VMF 专属源码、测试、配置、文档、演示、训练数据派生物与 checkpoint；它不再是安装、CI、打包或
发布矩阵的一部分。

本决策只退役 VMF 专属支线。以下共享能力继续保留并由当前真实模型链使用：

- `virea.motion`、`virea.data`、Motion IR、兼容 adapter、retarget、VRMA Exporter 与 Viewer；
- canonical211 v3 的坐标、旋转、FK 与骨骼语义；
- 模型隔离运行时、环境检测、资源准入、结果身份和生产验收契约。

## 实施边界

- 删除 `src/vmf`、`tests/vmf_stage1`、`configs/vmf`、`doc/vmf` 与 `demo/vmf-demo`。
- Python 打包显式排除 `vmf` 与 `vmf.*`；sdist、wheel 和 fresh install 必须证明没有 VMF 模块。
- CI 不再安装 VMF 的训练依赖，也不再运行或跳过 VMF suite。
- 仓库外 VMF 数据和 checkpoint 先移动到已核验的隔离区；总门禁通过后永久删除。
- 不把 VMF 的测试数字、环境名称或路径继续写入当前发布声明。

## 验收

退役成立需要同时满足：

1. 仓库中没有 VMF 专属实现和可执行入口；
2. sdist、由 sdist 构建的 wheel、直接 wheel 与 fresh install 均不包含 `vmf`；
3. 非 VMF legacy、refactor、Web、Viewer、模型插件与真实 E2E 不因退役回归；
4. 共享动作数学不因删除发生公式或表示变更；
5. 隔离区只在最终总门禁通过后按精确路径永久删除。

## 后果

VIREA 的生产表面不再携带训练支线和约 63 GiB 遗留数据。历史训练 checkpoint 不再可由本仓库恢复，
这是经 Decision Owner 明确批准的不可逆后果。需要未来训练功能时，应以新的模型插件、独立 runtime
和可复现数据契约重新提案，而不是恢复 VMF 命名空间。
