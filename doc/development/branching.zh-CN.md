<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](branching.en.md)
<!-- END DOC NAV -->

# 🌿 分支与发布规范

**公开的 `Moonweave-AI/virea` 仓库只保留 `main`。** 日常开发使用短期本地分支；团队需要共享私密评审时，使用独立的私有仓库。完成评审后，将准备公开的改动纳入 `main`。

GitHub 的公开/私有设置针对整个仓库，不能单独隐藏某个分支。公开仓库里的 `private/*` 仍是公开分支；删除分支名，也不会让已公开的提交、fork 或 PR 历史变成私密内容。

## 分支名表达工作内容

统一使用 **`<类型>/<简短主题>`**：小写英文字母和数字，单词之间用连字符，仅一层斜杠，总长度不超过 64 个字符。名称描述要解决的问题或完成的结果。有助于定位时可加入 issue 编号，例如 `fix/42-worker-recovery`。

| 前缀 | 用途 | 示例 |
|:--|:--|:--|
| `feat/` | 用户可见的新能力 | `feat/provider-discovery` |
| `fix/` | 修复行为 | `fix/wrist-retargeting` |
| `refactor/` | 内部结构调整 | `refactor/body-ownership` |
| `docs/` | 文档 | `docs/setup-guide` |
| `test/` | 测试覆盖 | `test/avatar-rest-pose` |
| `perf/` | 有测量依据的性能优化 | `perf/worker-startup` |
| `build/` 或 `ci/` | 打包、自动化 | `ci/windows-first-run` |
| `chore/` | 维护与清理 | `chore/retire-old-assets` |
| `codex/` | 自动化本地工作 | `codex/motion-optimization-baseline` |

对应规则为 `^(feat|fix|refactor|docs|test|perf|build|ci|chore|codex)/[a-z0-9]+(-[a-z0-9]+)*$`，另加 64 字符长度限制。`main` 是唯一长期分支；发布版本使用标签，不建立长期 release 分支。

去掉 `detail-technical-method` 这类重复后缀、多层目录、人名、无明确用途的日期和 `final-final`。名称还需符合 Git 本身的语法：

```sh
git check-ref-format --branch fix/wrist-retargeting
```

这个命令只检查 Git 语法；上面的表格和表达式定义 VIREA 更严格的命名约定。

## 开发与发布改动

从干净、最新的 `main` 开始：

```sh
git switch main
git pull --ff-only origin main
git switch -c fix/wrist-retargeting
```

完成聚焦的改动、相关检查与 diff 评审。按 [AGENTS.md](../../AGENTS.md) 在修改前执行 GitNexus 影响分析，在提交前执行变更分析。用户可见的变化写入[更新日志](../../CHANGELOG.zh-CN.md)，并同步英文版。

公开远端拒绝创建或更新 `main` 之外的分支。不要使用 `git push --all` 或 `git push --mirror`。如需私密协作，使用**独立的私有仓库**，确认访问名单，并将其远端命名为 `private` 等明确名称。公开 fork 可用于公开贡献，不能用于隐藏开发工作。

完成评审和本地检查后，维护者可在本地合入：

```sh
git switch main
git pull --ff-only origin main
git merge --ff-only fix/wrist-retargeting
git push origin main
```

如果 `main` 已推进，先在开发分支处理差异，再执行受影响的检查。推送后查看该提交对应的 GitHub Actions；验证完成后，用 `git branch -d fix/wrist-retargeting` 删除已合并的本地分支。外部贡献仍可通过公开 fork 发起 PR，私密评审留在独立私有仓库中。

## 公开仓库规则

| 规则 | 效果 |
|:--|:--|
| **Public branches: main only** | 拒绝创建或更新 `main` 之外的所有分支，未配置绕过角色 |
| **Main: preserve history** | 拒绝删除或非快进更新 `main`，未配置绕过角色 |
| 合并后自动删除分支 | 将来若调整为允许公开开发分支，合并后自动清理 |

这些规则在服务器端执行。它们不把旧提交变为私密；管理员仍能主动修改仓库设置。改变工作流时，应同时检查[当前规则](https://github.com/Moonweave-AI/virea/rules)。

## 准备软件发布

1. 将重要变化写入“尚未发布”，按新增、变更、弃用、移除、修复、安全分类，说明新的使用行为和迁移步骤。
2. 按[语义化版本](https://semver.org/lang/zh-CN/)选择版本号，使包、CLI/API 与文档版本一致。当前 `0.x` 阶段也要明确说明兼容性变化。
3. 对准确的源码提交完成发布验证并等待 CI 通过。只有实际发布软件时，才创建不可变的 `v主版本.次版本.修订号` 附注标签。
4. 把本次条目移入对应版本及日期，添加版本比较链接、GitHub Release 说明和已验证的发布产物。
5. `launch-film-2026-10` 等素材标签与软件版本分别管理；补历史记录时不倒造标签或发布日期。

[当前主线说明](../releases/current.zh-CN.md)解释现有源码版本。历史 `0.4.0` 验收文档记录的是当时基线，并不自动代表后续全部变更的发布结论。

## 恢复已整理的分支

2026-10-13 清理时已核对远端端点，将完整 Git bundle 保存到本地 `.git/branch-archive/2026-10-13/heads.bundle`，旁边保留引用清单和 SHA-256 记录。备份不进入版本控制。移除的 8 条远端分支和 11 条本地分支已包含在 `main` 中；另有两次独有提交，保存在本地 `codex/motion-optimization-baseline`。

用 `git log main..codex/motion-optimization-baseline` 查看保留工作。恢复其他端点时，先运行 `git bundle list-heads .git/branch-archive/2026-10-13/heads.bundle`，再将需要的归档引用 fetch 为命名规范的**本地**分支。备份位于本次维护的电脑，新的 clone 中不会自动存在。

## 规范依据

- [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow)：简短、有描述性的分支，聚焦改动和评审。
- [Git 引用语法](https://git-scm.com/docs/git-check-ref-format)：合法的分支名。
- [仓库可见性](https://docs.github.com/en/repositories/creating-and-managing-repositories/about-repositories)：公开/私有访问以仓库为单位。
- [Ruleset 控制](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)：创建、更新、删除和强推限制。
- [合并后自动删除](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-the-automatic-deletion-of-branches)：分支生命周期管理。
- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 与 [Semantic Versioning](https://semver.org/)：可读的变更记录和清晰的版本含义。

VIREA 根据私密开发、主线公开的需求采用上述实践；前缀列表是本项目约定。

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-13
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 90
summary: 简洁分支命名、本地或私有开发、仅 main 的公开远端，以及可追溯的发布记录。
canonical: doc/development/branching.zh-CN.md
related:
  - doc/development/branching.en.md
  - CONTRIBUTING.md
  - CHANGELOG.zh-CN.md
  - doc/releases/current.zh-CN.md
supersedes: []
superseded_by: []
-->
