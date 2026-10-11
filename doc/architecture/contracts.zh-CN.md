---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Unified runtime contracts.
canonical: doc/architecture/contracts.zh-CN.md
related: []
supersedes: []
superseded_by: []
---

# 能力与执行契约

[English](contracts.en.md) · [架构总览](overview.zh-CN.md)

契约位于 `virea_contracts.performance`，采用可独立安装的 Pydantic 数据结构。原生数组、动作窗口和音频保存在制品文件中，控制消息携带引用与 SHA-256 摘要。

| 契约 | 含义 |
|---|---|
| `InteractionRequestV1` | 工作流、用户输入，以及可选的会话或直接动作任务 |
| `ResponsePlanV1` | 话语、简洁动作阶段、工具意图与时间关系 |
| `MotionRequestV1` | 所选模型、时间条件与可选原生历史 |
| `NativeMotionArtifactV1` | 原生样本、源表示、模型版本和时间轴 |
| `AudioArtifactV1` | 实测采样率和采样数；两者相除得到时长 |
| `ExecutablePerformanceV1` | 校验后的动作、混合音频与话语区间 |
| `ExecutionCommandV1` | 会话、轮次、版本、目标、有效期和幂等键 |
| `ExecutionReceiptV1` | 完成状态与明确的证据级别 |
| `SessionSnapshotV1` | 当前版本、状态、身体控制者和最近回执 |

源表示与目标骨架分别记录。原生旋转观测和从位置推定的扭转也分别记录。画面观测及语义完成回执需要证据引用；设备确认单独记录。

## HTTP 接口

`GET /api/v1/workflows` 返回三个工作台。`POST /api/v1/interactions` 路由 `InteractionRequestV1`：Motion Lab 接受已有 `JobRequest` 格式的 `motion_job`，无需创建角色会话；另外两个工作台使用已有会话 ID。提供目标 ID 时，服务会核对所属会话。结果包含请求 ID、工作流和原有任务或会话响应。

```json
{
  "schema_version": "virea.interaction_request.v1",
  "request_id": "hello-character",
  "workflow": "character_studio",
  "session_id": "从创建会话响应取得的 ID",
  "text": "向观众挥手，再介绍今天的展览。"
}
```

直接动作任务中的输入与参数遵循所选模型的 manifest schema。原有 `/jobs`、`/characters`、`/vrchat` 以及模型部署 API 继续提供服务；运行中的 `/docs` 页面展示完整接口。

`LanguagePort`、`AudioPort`、`MotionPort`、`MotionAdapterPort`、`EmbodimentPort` 定义 Python 集成边界。各模型继续使用自己的流式接口与原生窗口协议。`ToolDispatcher` 仅调用已登记能力，并检查参数、授权范围和副作用。

时间轴计划的旧导入 `PerformancePlan` 指向 `virea_contracts.timeline`，新代码可使用 `TimedPerformancePlan`。语义规划器导出 `IntentPlan`，两个概念在文档和新接口中使用不同名称。

九类消息的版本化 JSON Schema 位于 `packages/contracts/schemas/v1/`。使用 `python -m virea_contracts.schema_export` 更新，追加 `--check` 可检查是否与代码一致。当前对话规划器生成语音与动作；新增工具能力通过 `ToolDispatcher` 登记。
