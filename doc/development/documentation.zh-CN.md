---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 30
summary: VIREA README、文档信息架构、机器事实源、元数据和持续验证规范。
canonical: doc/development/documentation.zh-CN.md
related:
  - ../../README.md
  - documentation.en.md
  - ../reference/cli.zh-CN.md
  - ../README.zh-CN.md
  - ../reference/status-semantics.zh-CN.md
  - ../quality/production-e2e.zh-CN.md
supersedes: []
superseded_by: []
---

# 文档设计与维护规范

> [中文](documentation.zh-CN.md) · [English policy](documentation.en.md)

VIREA 的文档不是发布后的说明附件，而是模型身份、平台能力、资源边界和真实验收证据的可审查入口。
文档可以解释机器事实，但不能覆盖或创造机器事实。

## 双语与命令合同

所有**当前用户工作流**都必须成对提供 English（`.en.md`）与简体中文（`.zh-CN.md`）入口，并在标题下直接互链。
新教程、How-to、CLI/API 使用说明不得只新增一种语言；翻译未完成时保持 `InReview`，不能伪装成已发布的 Active
用户路径。历史 ADR、RFC、研究记录和第三方 notice 保留原始证据语言，但中英文文档中心必须给出双语标题、用途、
状态和导航，不能把读者直接丢给没有上下文的原文。

每条面向用户的命令必须同时写清：

1. 从 clean clone 开始的前提、Shell 与仓库外状态目录；
2. 命令前的有效 Shell 注释，说明它要做什么；
3. 所有位置占位符（如 `MODEL`、`DOMAIN`、`PATH`）的来源；
4. 每个参数的意义、取值/冲突/默认限制和读写副作用；
5. 预期输出、状态变化与下一步，不把未实测的模型能力写成保证。

完整语法和选项只以[中文 CLI 参数参考](../reference/cli.zh-CN.md)与
[English CLI reference](../reference/cli.en.md)为准；教程只保留最短命令并链接回参考页，禁止在多处复制一份
未维护的参数表。

## 设计原则

1. **先让读者选择路径。** 首页首先区分第一次生成、选择模型、部署平台、接入模型和审查证据。
2. **少即是多。** README 只保留价值、能力矩阵、最短真实流程和导航；数据集画廊、长表和实现细节下沉。
3. **三个稳定心智层。** Model 定义生成能力，Execution Domain 定义实际运行位置，Result 绑定原生骨骼到目标骨骼。
4. **目标、声明和证据分开。** 产品目标支持 Windows、Linux、WSL2 与 macOS；Runtime 声明可执行平台；Evidence 只记录实际跑过的机器。
5. **单一事实源。** 同一个模型状态、平台或测试数字不能在多份 Markdown 中手工复制。
6. **失败要可行动。** 文档给出原因、恢复动作和数据位置，不以“其他系统不支持”结束问题。

这些原则吸收了几个成熟项目的项目级做法：

- [LobeHub](https://github.com/lobehub/lobehub) 把产品叙事、文档入口、生态与独立设计规范分层；
- [Cua](https://github.com/trycua/cua) 用 “Choose Your Path” 和显式 OS 表帮助不同用户快速进入正确子系统；
- [iii](https://github.com/iii-hq/iii) 用少量稳定原语解释复杂系统，并直接给出 monorepo 结构与责任；
- [Kaneo](https://github.com/usekaneo/kaneo) 把“只保留解决真实问题的内容”落实为一条可运行的快速部署路径；
- [Ollama](https://github.com/ollama/ollama)、[Transformers](https://github.com/huggingface/transformers)、
  [Kubernetes](https://github.com/kubernetes/kubernetes) 与 [uv](https://github.com/astral-sh/uv)
  分别提供 OS-first 安装、模型矩阵、用户/开发者分流和平台政策的优秀范式。

借鉴只限于信息设计；VIREA 的能力、状态和示例必须来自本仓库事实。

## 文档层级

| 层级 | 作用 | 允许的事实来源 |
|---|---|---|
| 根 README | 价值、当前能力、最短真实路径、总导航 | 生成的模型/平台摘要与稳定命令 |
| Tutorial | 从零完成一个结果 | 当前 CLI、真实可安装模型 |
| How-to | 完成明确任务或恢复失败 | 实际命令与状态机 |
| Reference | 精确字段、状态、骨骼和协议 | Schema、manifest、registry |
| Explanation | 数学、架构与设计理由 | 代码、RFC、ADR、论文 |
| Evidence | 带机器、时间和结果身份的实测事实 | 版本化 evidence manifest 与产物 |
| Archive | 已被取代但需要追溯的快照 | 原文加 Superseded 指针 |

## 机器事实源

| 事实 | 唯一来源 |
|---|---|
| 模型身份、任务、输入、原生表示与状态 | `plugins/models/*/manifest.yaml` |
| Runtime、平台、资源策略和入口 | `registries/runtimes/*.yaml` |
| 随发行包携带的模型/Runtime | `registries/bundles/release-assets.v1.json` |
| 骨骼与表示定义 | `registries/skeletons/`、`registries/representations/` |
| 当前真实 E2E | 版本化 production evidence registry 中被当前 schema/validator policy 接受的 records；旧版物理存在不等于有效 |
| README 与模型/平台表 | `scripts/generate_docs.py` 的确定性输出 |

生成段必须带 `BEGIN GENERATED` / `END GENERATED` 标记。修改生成段的正确方式是更新事实源后重新生成，
不是直接编辑表格。

## 元数据

新建的 `doc/**/*.md`、模型卡、Runtime README 与研究/证据文档使用文件头 YAML frontmatter。历史页面
若仍采用文件尾 HTML comment 包裹的同一份 YAML，检查器会完整解析、验证并保持兼容；页面发生结构性修改时
应把元数据迁移到文件头。两种形式的字段合同完全相同，不能用尾注绕过类型、日期、链接或 canonical 检查。
核心字段为：

```yaml
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 30
summary: 一句话说明权威范围。
canonical: doc/example.zh-CN.md
related: []
supersedes: []
superseded_by: []
```

根 README、CHANGELOG、SECURITY、CONTRIBUTING 和第三方许可通知遵守 GitHub/法律文件惯例；若不用可见
frontmatter，必须由文档检查器中的显式、带理由例外记录覆盖，不能因为未被枚举而漏检。

## 写作规则

- 先写用户得到的结果，再写机制；命令必须能复制执行。
- 每个模型同时写 `model_id`、原生 skeleton/representation 和目标 skeleton/representation。
- `integrated_experimental`、`supported`、`validated_platforms` 与许可状态不得合并为一个含糊的“支持”。
- 多 Runtime 模型必须把每个 `runtime_id` 与自己的 platform、resource profile 和 availability 成对展示；
  禁止先按模型合并后把 CUDA profile 错投到 macOS/CPU 行。
- “未在该平台实测”不能写成“该平台不支持”；真正缺少实现时写明模型级或 Runtime 级原因。
- 示例不得在 checkout 中创建 `.venv`、模型缓存、日志、job 或结果。
- 合成数据只能作为数学/协议回归，不能写入 production acceptance。
- 外部来源优先官方论文、官方仓库和官方文档；工程证据同时记录固定 revision。

## 本地与 CI 验证

```text
python scripts/generate_docs.py --check
python scripts/check_docs.py
```

文档 CI 应发现仓库内全部 Markdown，验证元数据、canonical 唯一性、内部链接、图片 alt、生成段、
命令中的 checkout hygiene，以及模型/Runtime/evidence 交叉引用。外链检查放在带重试的定时任务，避免网络
波动阻断普通变更。
