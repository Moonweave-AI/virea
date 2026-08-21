---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: 模型集成、技术可用性、发行许可、平台声明和真实验收状态的正交语义。
canonical: doc/reference/status-semantics.zh-CN.md
related:
  - ../models/README.zh-CN.md
  - ../platforms/README.zh-CN.md
  - ../quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# 状态语义

VIREA 不用一个 `supported` 字段同时表达代码、权重、平台、许可证和实测证据。

## 模型集成状态

| 状态 | 精确定义 |
|---|---|
| `registered` | 仅登记身份与研究目标；不声明上游或 VIREA 可运行 |
| `runnable_upstream` | 固定上游有可执行路径，但 VIREA 尚未完成并登记该模型要求的 production E2E；可以已有部分 adapter、Worker 或 managed Runtime，不能据此提前晋级 |
| `integrated_experimental` | VIREA Worker、Runtime、适配器和至少一条真实 checkpoint 验收路径存在，但平台、许可、质量或持续回归覆盖仍有限 |
| `supported` | 在声明的平台/资源范围内持续通过发布门禁，并有明确发行许可和维护责任 |
| `blocked` | 当前存在明确且可引用的技术/资产条件；必须另写阻断维度，不能只给一个 `blocked` 标签 |

## 正交状态

| 维度 | 示例 |
|---|---|
| `technical_availability` | `installable`、`upstream_incomplete` |
| `distribution_status` | `redistributable`、`external_assets_only`、`license_review_required` |
| `runtime_platforms` | `win-64`、`linux-64`、`osx-arm64` |
| `execution_domains` | `windows-native`、`wsl:Ubuntu-24.04`、`linux-native`、`macos-native` |
| `resource_profiles` | `cuda_full`、`cuda_component_split`、`cpu`、经实现验证的 offload |
| `validated_platforms` | 带 OS、设备、驱动和 evidence ID 的实际记录 |
| `production_e2e_registry` | 由当前 validator 接受的 doctor→browser 同链记录；不能从 manifest 状态、历史结果或浏览器 observation 推导 |

平台是产品目标不等于已经实测；尚未实测也不等于产品主动拒绝。解析器只应因实际执行域、模型依赖或资源
条件不满足而停止，并返回可用的 CPU、WSL、MPS、ROCm 或其他已实现路径。

## 结果身份

每个结果必须能够区分：

```text
model + model version + runtime + checkpoint
native skeleton + native representation
target skeleton + target representation
execution domain + resource profile + device
```

数据库主键和文件名不能代替这些字段。不同骨骼或表示产生的结果不可只靠展示名称区分。

## 声明规则

- Manifest 声明能力；RuntimeSpec 声明构建路径；Evidence 证明一次实际执行。
- 模型状态可以保留此前有界验收的晋级结果；当前树是否已有可用于发布的 fresh evidence，仍只读取
  `registries/evidence/production-e2e.v1.yaml` 中被当前 schema/validator policy 接受的 `records`。文件非空
  不等于有效；validated evidence / validator v1.0 在 v1.1 policy 下按 0 条当前 evidence 处理。两者不是
  同一个时间维度。
- 浏览器客户端提交的布尔值不能自行把模型提升为 production E2E 完成。
- 许可审查失败可以阻止发行，但不能反向伪造为模型“技术不可部署”。
- 单台机器通过只证明该执行域与配置，不自动外推到其他平台或最低配置。
