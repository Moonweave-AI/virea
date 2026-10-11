---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: 启动器与开发环境的数据位置，以及模型、表演制品和验证记录的保留策略。
canonical: doc/operations/runtime-data-and-retention.zh-CN.md
related:
  - runtime-data-and-retention.en.md
  - troubleshooting.zh-CN.md
  - ../getting-started/installation.zh-CN.md
supersedes: []
superseded_by: []
---

# Runtime 数据与保留策略

> [中文](runtime-data-and-retention.zh-CN.md) · [English](runtime-data-and-retention.en.md)

`VIREA_HOME` 保存模型、设置和生成结果。启动器默认将它设为项目的 `.virea-runtime/portable/home/`；VRChat 专用部署使用自己的 `home/`。开发者也可配置独立数据盘，具体步骤见[数据目录指南](../getting-started/persistent-data-root.zh-CN.md)。

代码、manifest、锁文件、测试和文档进入版本控制。下面这些运行数据保存在受管理的数据目录中：

- Python/uv Runtime 环境；
- checkpoint、Hugging Face cache 和上游源码快照；
- Worker stdout/stderr 与控制面日志；
- staging、job、ModelResult、Motion IR、Canonical211 与 VRMA；
- Playwright 浏览器证据和发布制品工作区。

## 目录责任

| 目录 | 内容 | 可否手工删除 |
|---|---|---|
| `machine/` | 不可覆盖的 doctor 报告与 latest 指针 | 仅按保留策略 |
| `state/` | SQLite 状态、事务、job/result 索引 | 不可直接删除 |
| `model-store/` | artifact blobs、manifest、READY snapshot 与 refs | 用 `model remove` / `model gc` |
| `runtimes/` | 隔离 Python/Worker 环境 | 用 repair/remove/GC |
| `cache/` | 可恢复下载缓存 | 可经 GC 清理 |
| `jobs/`、`results/` | 运行与不可变结果 | 先核对索引再清理 |
| `characters/<session-id>/` | 会话的临时 HTTP 音频与动作文件 | 播放确认或会话关闭后自动释放 |
| `characters/artifacts/` | 按 SHA-256 保存的原生动作、实测音频与可执行表演 | 停止会话后按需归档；普通模型/状态 GC 不回收这一目录 |
| `config/verification/` | 模型生成检验回执及 JSON/WAV/NPZ 结果 | 与对应连接配置一同保留 |
| `tmp/` | staging、quarantine、短期 QA | 可按年龄 GC |

## Production evidence 保留

通过当前 validator 的 production E2E bundle 属于发布事实，不是普通 `tmp/`。当前本地收集策略为：

| 字段 | 规则 |
|---|---|
| storage class | `local_evidence`，必须位于 checkout 外的受控 evidence root |
| owner | `VIREA maintainers` |
| retention | `until_superseded`；只有新版本同范围记录完成审查后才能替代 |
| GC | `excluded_from_gc: true`；普通 model/state retention GC 不得删除 |
| integrity | 当前路径不新增 SHA/checksum 门禁；完整性由版本化合同、不可变 job/result/artifact 索引和只读 validator 交叉核对 |

本地 evidence 只支持本机 QA 与技术结论。若未来用于公开发布，必须先迁移到团队可访问、带访问控制和
生命周期管理的共享 archive，并在 registry 中更新 locator/collection provenance；仅存在于某位维护者本机
不能建立公开 release 的可获取性或长期可追溯性。旧版或被替代的 bundle 可留在独立 historical/quarantine
区域，但不得继续标为当前 `passed`，也不能被普通 GC 静默删除。

## 清理

```bash
# 预览超过 168 小时且不再引用的模型数据；不会删除任何内容。
uv run virea model gc --dry-run --older-than-hours 168 --virea-home <external-home>
# 审核预览后才应用模型数据清理；会修改外部状态目录。
uv run virea model gc --apply --older-than-hours 168 --virea-home <external-home>
# 预览状态/日志保留策略；同样不删除数据。
uv run virea state gc --dry-run --older-than-hours 168 --virea-home <external-home>
```

先 dry-run，确认不会删除 READY snapshot 或当前 evidence。失败安装的 staging 必须清理或转入 quarantine，
不能在 checkout 或 `VIREA_HOME/tmp` 无限累积。

## 源码与运行目录

便携启动器会启用受管理的 `.virea-runtime/` 目录，并确认它在 Git 忽略规则中。手动运行 CLI 时默认采用源码之外的数据根；开发脚本同时设置 `UV_PROJECT_ENVIRONMENT`、下载缓存和模型目录。两种方式均将运行数据与发布源码分开管理。

表演制品保留原生输出和混合后的播放数据，读取时核对内容摘要。需要保留一次交互用于复核时，归档执行命令、回执及其引用的制品；正在使用的制品保持原位。模型/状态 GC 的范围见各命令的预览输出。
