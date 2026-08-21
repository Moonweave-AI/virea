---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: 环境、权重、缓存、日志、job、结果和 QA 证据的仓库外位置与保留策略。
canonical: doc/operations/runtime-data-and-retention.zh-CN.md
related:
  - troubleshooting.zh-CN.md
  - ../getting-started/installation.zh-CN.md
supersedes: []
superseded_by: []
---

# Runtime 数据与保留策略

源码 checkout 只保存代码、轻量 manifest/registry、锁文件、测试和文档。以下内容一律写入外部
`VIREA_HOME` 或操作系统临时目录：

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

```text
virea model gc --dry-run --older-than-hours 168 --virea-home <external-home>
virea model gc --apply --older-than-hours 168 --virea-home <external-home>
virea state gc --dry-run --older-than-hours 168 --virea-home <external-home>
```

先 dry-run，确认不会删除 READY snapshot 或当前 evidence。失败安装的 staging 必须清理或转入 quarantine，
不能在 checkout 或 `VIREA_HOME/tmp` 无限累积。

## Checkout hygiene

CI 和文档检查应拒绝仓库内的 `.venv*`、模型权重、HF cache、Worker 日志、SQLite 状态、job/result、
pytest basetemp 和 fresh-install 工作区。源码开发通过外部 `UV_PROJECT_ENVIRONMENT` 使用同一规则。
`.gitignore` 只是误写后的最后防线，不表示这些目录可以在 checkout 内生成；`virea setup` 会拒绝把
`VIREA_HOME` 放进源码 checkout。
