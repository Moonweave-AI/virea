---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: 环境探测、资源准入、安装、Worker、结果和浏览器播放的分层排错入口。
canonical: doc/operations/troubleshooting.zh-CN.md
related:
  - runtime-data-and-retention.zh-CN.md
  - ../platforms/README.zh-CN.md
  - ../quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# 排错

按失败发生的层级处理，不要通过关闭验证或修改结果文件绕过。

| 症状 | 首个检查 | 恢复动作 |
|---|---|---|
| 安装前 `RUNTIME_NOT_BUILDABLE` | doctor 的执行域与每个 resource profile 诊断 | 释放资源或选择真实实现的 CPU/WSL/MPS/ROCm profile |
| 下载失败 | artifact revision、许可接受、网络与磁盘 | 重试 repair；失败不得产生 READY |
| Runtime build 失败 | 目标执行域的 uv/Python、lock 和 stdout/stderr tail | 修复执行域，不在 checkout 手装依赖 |
| Worker readiness 超时 | startup timeout、离线资产、模型加载日志 | `model verify` 后 repair；确认进程树已回收 |
| 推理超时/取消 | job state、Worker instance、PID/child tree | 等待有界取消；不得发布 result |
| VRMA 校验失败 | rest hips、root translation、track 数、finite | 修 exporter/adapter，不在 Viewer 中掩盖 |
| 浏览器角色消失或裁切 | VRM rest pose、VRMA absolute hips、console | 使用真实产物重跑 Viewer QA |

收集诊断：

```text
virea support --virea-home <external-home>
virea state inspect --virea-home <external-home>
virea model verify <model-id> --virea-home <external-home>
```

报告问题时附 model/result identity、执行域、doctor report ID、installation/job/result ID 与最小日志尾部，
不要上传 checkpoint、私有 Avatar、原始数据或整个状态数据库。
