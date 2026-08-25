---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: 模型集成、技术可用性、发行许可、平台声明和真实验收状态的正交语义。
canonical: doc/reference/status-semantics.zh-CN.md
related:
  - status-semantics.en.md
  - cli.zh-CN.md
  - ../models/README.zh-CN.md
  - ../platforms/README.zh-CN.md
  - ../quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# 状态语义

> [中文](status-semantics.zh-CN.md) · [English](status-semantics.en.md)

VIREA 不用一个 `supported` 字段同时表达代码、权重、平台、许可证和实测证据。

## 模型集成状态

| 状态 | 精确定义 |
|---|---|
| `registered` | 仅登记身份与研究目标；不声明上游或 VIREA 可运行 |
| `runnable_upstream` | 固定上游有可执行路径，但 VIREA 尚未完成并登记该模型要求的 production E2E；可以已有部分 adapter、Worker 或 managed Runtime，不能据此提前晋级 |
| `integrated_experimental` | VIREA Worker、隔离 Runtime、适配器和逐模型 target-acceptance 合同已经实现；这不声明当前真实 checkpoint 已通过，实际结果必须单独读取当前 policy 接受的 evidence |
| `supported` | 在声明的平台/资源范围内持续通过发布门禁，并有明确发行许可和维护责任 |
| `blocked` | 当前存在明确且可引用的技术/资产条件；必须另写阻断维度，不能只给一个 `blocked` 标签 |

## 正交状态

| 维度 | 示例 |
|---|---|
| `technical_availability` | `installable`、`upstream_incomplete` |
| `distribution_status` | `redistributable`、`external_assets_only`、`license_review_required` |
| `runtime_platforms` | `win-64`、`linux-64`、`osx-arm64`、`osx-64` |
| `execution_domains` | `windows-native`、`wsl:Ubuntu-24.04`、`linux-native`、`macos-native` |
| `resource_profiles` | `cuda_full`、`cuda_component_split`、`cpu`、经实现验证的 offload |
| `validated_platforms` | 带 OS、设备、驱动和 evidence ID 的实际记录 |
| `production_e2e_registry` | 由当前 validator 接受的 doctor→browser 同链记录；不能从 manifest 状态、历史结果或浏览器 observation 推导 |

平台是产品目标不等于已经实测；尚未实测也不等于产品主动拒绝。解析器只应因实际执行域、模型依赖或资源
条件不满足而停止，并返回可用的 CPU、WSL、MPS、ROCm 或其他已实现路径。

## 验收套件与内容绑定

旧版单任务 manifest 可以声明一个 `production_acceptance` 合同。集成后的多任务 manifest 声明
`production_acceptance_suite`：它按照 `model.tasks` 的相同顺序，为每个任务提供且仅提供一个不可变合同。
`model install` 和 `model repair` 会执行套件中的每个合同。每个任务必须产生自己独立的验收 Job 和 result，
不能复用另一个任务的 evidence。只有全部任务合同都通过各自要求的无头验收阶段，安装验收才算成功。浏览器
播放仍是独立的发布 evidence，安装过程不能自行证明该阶段。

验收 evidence 绑定的是内容，而不只是模型名称或目录路径：

- 套件 evidence 会记录精确的 `installation_id`、完整套件合同、每个任务的验收结果和一个
  `artifact_identity`；每个任务验收都必须反向绑定到同一安装与制品身份。
- 新安装事务会持久化 `artifact_content_binding=complete-tree-sha256-v2`，数据库还会把同一策略存入独立的不可变列。
  删除 JSON evidence、标记或摘要字段都不能让该安装降级为旧版“只看元数据”语义；复验必须 fail closed。
- `artifact_identity.sha256` 覆盖规范化后的安装 manifest 与包含内容绑定的制品引用 manifest。对于人工提供的
  外部制品根目录，VIREA 会要求全部 `expected_files` 哨兵存在，并对 Worker 可见完整内容树中的每个普通文件
  记录相对路径、字节长度与完整 SHA-256。只有 revision 字符串、文件名、文件大小或路径都不能证明内容。
- 完整树哈希遇到目录扫描错误会 fail closed；在宿主支持时以不跟随链接的方式打开普通文件，逐文件在读取前后
  比对路径与句柄身份，并在哈希完成后重新枚举成员。并发新增、删除、替换或引用变化都会使扫描失效，而不会
  生成遗漏内容的身份摘要。
- 每个验收任务都会在自己的 Job 线程中、Worker 启动前重新执行完整 staging 制品验证，并比对精确安装 ID、
  制品身份和解析后的根路径。结果制品行会记录不可变 SHA-256；对新安装，发布、READY 复验与只读 real-E2E
  validator 都会拒绝缺失或已变化的字节。
- 根目录内部的符号链接或 Windows junction 只有在解析后的目标仍位于同一根目录内时才允许；v2 identity 会记录
  链接类型、相对路径与目标。越界、断裂或未知 reparse point 会在验收前失败。
- 只要任一文件被增加、删除、替换或修改，原 `artifact_identity` 及其验收 evidence 就不再证明当前字节。
  显式完整复验必须重新计算内容身份；若内容是有意变更，必须创建新的 install/repair 事务，重新执行全部
  任务合同，并产生重新绑定的 `installation_id` 和 `artifact_identity`；严禁给旧 evidence 改标签或直接沿用。

仅元数据对账不会完成上述内容复验。它可以报告“持久 READY · 执行前复验”，但 Worker 使用该安装之前仍必须
通过完整字节完整性边界。

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

- Manifest 声明能力；RuntimeSpec 声明构建路径；target-acceptance 声明晋级前必须通过的验收合同；Evidence
  才证明一次具体真实执行。四者不能互相代替。
- 模型状态记录已实现的集成合同；当前树是否已有可用于发布的 fresh evidence，仍只读取
  `registries/evidence/production-e2e.v1.yaml` 中被当前 schema/validator policy 接受的 `records`。文件非空
  不等于有效；validated evidence / validator v1.0 在 v1.1 policy 下按 0 条当前 evidence 处理。合同状态与
  实际 evidence 是两个正交维度。
- 浏览器客户端提交的布尔值不能自行把模型提升为 production E2E 完成。
- 许可审查失败可以阻止发行，但不能反向伪造为模型“技术不可部署”。
- 单台机器通过只证明该执行域与配置，不自动外推到其他平台或最低配置。
