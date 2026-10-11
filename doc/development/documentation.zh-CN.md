<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](documentation.en.md)
<!-- END DOC NAV -->

# 📚 文档设计与写作

好的文档帮助读者完成下一步。README 讲清项目并展示效果；任务指南写操作顺序；协议、数学与实验证据各有自己的参考页面。

## 页面分工

| 页面 | 目的 | 结构 |
|:--|:--|:--|
| README | 几分钟内理解 VIREA | Banner → 2+3 导航卡片 → 功能 → 对比 → 启动 → 五段视频 → 架构 → 贡献、安全与许可 |
| 文档首页 | 选择任务 | 三个入口卡片、工作区表格、按目标查阅 |
| 教程／操作指南 | 完成一个工作流 | 目标、准备、操作步骤、预期结果、恢复方法、下一步 |
| 参考／解释 | 查字段或理解原理 | 简介、结构图或 schema、准确的定义、例子 |
| 决策／证据 | 理解选择与测量结果 | 日期、背景、来源、方法、结果与解释 |

## 视觉语言

以提供的 banner 为配色基准：**炭黑、灰紫、月光银，以及少量暖粉高光**。生图导航卡片采用同一轮廓与图标样式，架构图沿用克制的配色。截图与录像保留真实画面。

- 用 icon 识别章节，用表格表达对比和映射。
- 为图片写有意义的 alt 文本；关键信息也保留可选择的文字。
- 使用短段落与具体动词，在影响选择或下一步时解释限制。
- 用 `> [!TIP]` 放小提示，用 `<details>` 收起较长的可选内容。
- 修改标题时保留已有锚点，必要时添加 `<a id="…"></a>`。
- 视频保持暂停、静音起播；README 用 GitHub 附件播放器，仓库保存源文件与来源记录。

图表配色通过 [Mermaid 主题变量](https://mermaid.js.org/config/theming.html)设置，节点、分组与连线共享 banner 的灰紫色系。完整演示集的附件地址与源文件哈希记录在 [`github-videos.json`](../assets/unified-motion-demos/github-videos.json)，重新录制后更新记录再发布。

## 双语与导航

面向用户的现行指南成对提供 `.en.md` 和 `.zh-CN.md`，页面可以直接回到文档、部署与演示。研究、ADR 与证据记录保留原语言和日期，通过双语[文档地图](../catalog.zh-CN.md)找到。

`scripts/doc_layout.py` 统一页头、页尾，并将元数据放入隐藏的 HTML 注释。正文、公式、表格与锚点保持原样，多次运行产生相同结果。

## 事实与命令

| 内容 | 来源 |
|:--|:--|
| 模型与原始表示 | `plugins/models/*/manifest.yaml` |
| 环境与平台配置 | `registries/runtimes/` · `registries/platforms/` |
| API 契约 | `packages/contracts/` · 服务的 `/docs` |
| 自动生成矩阵 | `scripts/generate_docs.py` |
| 检验记录 | `registries/evidence/` · 带日期的质量文档 |

命令应能从干净的仓库副本运行。写清 shell、前提和占位符，再说明预期结果。`virea` CLI 命令前加一句用途注释；详细选项链接到 [CLI 参考](../reference/cli.zh-CN.md)。

## 发布前检查

安装开发环境后，在仓库根目录运行：

```sh
# 更新模型、平台矩阵和页面导航。
python scripts/generate_docs.py
python scripts/doc_layout.py

# 检查自动生成结果、页面结构、链接与媒体来源。
python scripts/generate_docs.py --check
python scripts/doc_layout.py --check
python scripts/check_docs.py

# 验证文档工具。
uv run python -m pytest tests/test_docs.py tests/test_generated_documentation.py tests/test_doc_layout.py tests/test_gallery_publication.py -q
```

保留元数据字段 `type`、`status`、`owner`、`created`、`updated`、`last_reviewed`、`review_cycle_days`、`summary`、`canonical`、`related`、`supersedes` 与 `superseded_by`。视觉升级不会改写历史实验的日期和结论。

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Bilingual documentation structure, banner-matched visual design and publishing workflow.
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
-->
