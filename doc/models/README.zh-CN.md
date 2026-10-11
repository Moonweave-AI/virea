<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](README.en.md)
<!-- END DOC NAV -->

# 🔌 模型目录

按工作流连接需要的能力。Motion Lab 可以独立生成动作；Character Studio 与 VRChat Studio 将语言、语音和动作组合起来。

| 能力 | 云端连接 | 本地选择 | 第一次检验 |
|:--|:--|:--|:--|
| 💬 语言 | OpenAI、DeepSeek、Anthropic、阿里百炼、Gemini 及兼容服务 | Ollama、LM Studio、llama.cpp 与 VIREA 服务 | 生成结构化回复 |
| 🎙️ 语音 | OpenAI Speech、百炼、ElevenLabs、Azure 及已支持端点 | Kokoro、Audio8 与本地服务 | 生成波形并查看实际时长 |
| 🦴 动作 | 动作能力服务端点 | MotionCraft、SynTalker、SentiAvatar + ARDY，以及 Motion Lab 目录中的模型 | 生成动作帧并预览原始骨架 |

<a id="choose-in-this-order"></a>
## 怎样选择

1. 打开**配置向导**，选择服务商或本地安装配方。
2. 自动检测模型与声线，从返回的列表中选择。
3. 使用本地模型时，查看检测到的设备、内存要求与下载计划，再开始部署。
4. 点击**生成检验**，检查服务实际返回的文字、波形或动作。
5. 启用连接，进入工作区。

[完整配置步骤](../getting-started/automatic-setup.zh-CN.md) · [平台选择](../platforms/README.zh-CN.md)

## 保留动作的原始身份

| 阶段 | 保留什么 |
|:--|:--|
| 原始结果 | 模型输出的表示、骨架、单位和时间信息 |
| 源适配器 | 转换到 Motion IR 的明确映射，以及观测量与推算量 |
| 重定向 | 源与目标的静止坐标系、关节层级、正向运动学与目标骨骼动作 |
| 执行 | 带时间安排的表演及目标端投递 |

[自动生成的模型矩阵](support-matrix.generated.md)列出了全部模型、原始骨架、运行环境和资源配置。[MotionCraft 与 SynTalker](../character/unified-motion.zh-CN.md)有专门的交互说明；新增输出格式见[模型接入指南](../development/model-adapter.zh-CN.md)。

<a id="read-the-matrix-correctly"></a>
## 怎样读模型矩阵

从 **Runtime** 列选环境，从**资源**列查看内存要求，从**观测记录**找到生成实测。配置页面会分别显示环境是否安装完成，以及连接是否已生成有效结果。

自动化接口提供两种安装视图：`full_integrity` 检查当前文件字节，`metadata` 快速读取已保存状态。执行前会进行完整性校验；多任务模型按每项任务保存验收记录，绑定安装与资产身份。详细字段见[状态语义](../reference/status-semantics.zh-CN.md)。

<details>
<summary>⌨️ 使用命令行选择模型</summary>

在开发环境的仓库根目录运行：

```sh
# 列出脚本可使用的模型标识。
uv run virea model list --json

# 查看模型要求与原始表示。
uv run virea model info MODEL

# 预览指定执行环境的安装计划。
uv run virea model install MODEL --execution-domain DOMAIN --virea-home PATH
```

`MODEL` 来自模型列表，`DOMAIN` 来自 `doctor --json`，`PATH` 是 VIREA 数据目录。应用安装计划的选项见 [CLI 参考](../reference/cli.zh-CN.md)。

</details>

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 14
summary: 模型选择、状态语义、原生骨骼/表示和逐模型文档入口。
canonical: doc/models/README.zh-CN.md
related:
  - README.en.md
  - support-matrix.generated.md
  - prism.zh-CN.md
  - ../reference/cli.zh-CN.md
  - ../reference/status-semantics.zh-CN.md
  - ../model-catalog/first-wave-2026-08-20.zh-CN.md
supersedes: []
superseded_by: []
-->
