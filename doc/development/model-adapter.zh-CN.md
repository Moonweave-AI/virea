---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: 将新 motion generation 模型接入独立 Runtime、ModelResult、Motion IR、骨骼表示和真实验收的步骤。
canonical: doc/development/model-adapter.zh-CN.md
related:
  - documentation.zh-CN.md
  - ../models/README.zh-CN.md
  - ../quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# 接入新模型

一个模型的接入单位不是单个 Python 函数，而是可追溯的 manifest、隔离 Runtime、Worker、原生表示、适配器
和真实验收。

## 1. 固定上游

记录官方代码、checkpoint、文本编码器、statistics、人体模型及其完整 revision。区分技术可下载、用户自行
取得、允许再分发和允许商业使用；许可不清晰不等于技术不可运行。

## 2. 定义原生身份

先登记真实 tensor/结构：dtype、shape、FPS、单位、坐标系、root 语义、rotation layout、skeleton joint map。
只有语义完全相同才复用已有 representation；不能因维度相同创建别名或强行复用。

## 3. 创建隔离 Runtime

Runtime 位于 `plugins/models/<model-id>/runtime/`，只包含源码、`pyproject.toml`、`uv.lock` 与法律通知。
环境、上游源码、checkpoint、缓存和日志写入外部 `VIREA_HOME`。Worker 离线加载显式 artifact roots，不搜索
当前工作目录，也不在缺件时生成替代结果。

## 4. 声明资源 profile

分别声明可用 VRAM、RAM、swap/pagefile 和 storage。只登记 Worker 真正实现的 placement，例如
`cuda_full`、`cpu` 或 `cuda_component_split`；不得把 RAM 与 VRAM 相加，也不得把未实现的 offload 写进
manifest。

## 5. 输出 ModelResult

Worker 输出原生 artifact 与完整 provenance。Control plane 校验 ArtifactRef 的路径边界、byte length、dtype、
shape、FPS 和有限值，再调用单一 adapter 转为 Motion IR。适配器保留模型无法映射到 Canonical211 的原生
通道，不能静默丢弃。

## 6. 建立 production acceptance

Manifest 给出一个固定、真实的 request、期望原生 skeleton/representation、最少帧数、必需制品和 timeout。
晋级前完成 [Production E2E](../quality/production-e2e.zh-CN.md)，包括真实浏览器加载真实 VRM/VRMA。

## 7. 测试层

- schema/registry 交叉引用和唯一性；
- 原生格式、单位、rotation 与非有限值负例；
- Worker 协议、取消、超时、孤儿恢复；
- 正式 checkpoint 的真实推理与 adapter 数值；
- Motion IR、retarget、VRMA 和浏览器播放；
- sdist/wheel/fresh install 中 Runtime 资源完整且无环境、权重或测试 fixture。

在真实证据完成前保持 `runnable_upstream`；完成单一受限平台路径后可标
`integrated_experimental`；更广泛的 `supported` 需要目标平台、最低配置、许可和持续回归共同满足。
