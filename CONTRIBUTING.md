# Contributing to VIREA

感谢你帮助改进 VIREA。这里的“正确”不仅是代码能运行，还包括时间、坐标、旋转、来源、许可和 artifact replay 都有可复现证据。

## 开始之前

1. 阅读[模型状态](README.md#model-support)与[工程边界](doc/engineering-design.zh-CN.md)。
2. 确认改动属于 Adapter、Profile、Codec、Retarget、Hand Solver、Artifact、Reader 或 Viewer 中的哪一层。
3. 涉及公共 schema、坐标语义、处理版本或跨层责任时，先更新 RFC / ADR；不要用实现反向改写尚未批准的决策。
4. 检查数据、模型、截图或派生媒体的再分发权限。没有明确 `allowed` 决定时保持 local-only。

## 本地开发

```bash
export UV_PROJECT_ENVIRONMENT="${XDG_DATA_HOME:-$HOME/.local/share}/virea/dev-env"
export VIREA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/virea/home"
uv sync --extra dev
uv run python -m pytest -q
uv run python scripts/check_docs.py
```

Windows PowerShell 使用 `$env:LOCALAPPDATA\VIREA\...` 下的等价路径。只有修改 Web/Viewer 时才安装
Node 依赖并运行相应检查；`node_modules` 是开发缓存，不得进入发布候选或生产安装。所有临时测试、
截图、录屏和分析输出写入系统临时目录或外部 `VIREA_HOME/qa`，不能因为路径被 Git 忽略就写入仓库。
Raw dataset 与 VRM 可以只读引用，但不得复制到仓库或测试 fixture。

## 改动必须携带的证据

| 改动 | 最低证据 |
|---|---|
| Adapter / Codec | shape、FPS、unit、basis、rotation space、异常输入负测、真实样本 |
| Retarget / FK | identity、90°、非交换旋转、左右镜像、父子链、source/target 独立 oracle |
| Hand Solver | observation coverage、不可观测策略、连续段、postcondition、证书与篡改负测 |
| Artifact / Reader | schema、hash、replay、同尺寸/恢复 mtime 篡改、legacy fail-closed |
| Viewer | payload 契约、真实 VRM humanoid、零 pose mutation、无 console error |
| 文档 / Showcase | frontmatter、链接、alt text、current/legacy 分离、rights policy |

真实数据测试若因环境缺失而 `skipped`，请原样报告；不要把它计入通过数量。

## 数据与隐私

- 不提交 raw dataset、processed 大文件、`.vrm`、音频、人脸数据、凭据或机器绝对路径。
- NumPy object/pickle 默认视为不可信。只在已核验来源的离线进程中使用一次性 opt-in。
- 日志、metadata 与报告只记录 portable token、basename 或 hash。
- 不用公开 issue 粘贴私密样本、未授权媒体或漏洞利用细节；安全问题按 [SECURITY.md](SECURITY.md) 报告。

## 文档规则

- Tutorial、How-to、Reference、Explanation、Decision 与 Evidence 分开写。
- Volatile test count 只写入带日期的验证记录；其他页面链接事实源。
- 图片写有意义的替代文本，动画提供说明与可暂停的本地视频。
- 历史结果标记 `Historical` / `Superseded`，不得继续作为当前完成证据。

## 许可边界

仓库目前没有 VIREA 代码 `LICENSE`。公开可见不等于获得复制、再分发或商业使用授权。[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 只覆盖其中明确列出的第三方材料。贡献者不得自行替项目、数据集、VRM 或媒体选择许可。

## 提交前检查

- [ ] 改动范围与所属层清楚；没有顺手混入无关文件。
- [ ] 正例、反例与真实样本证据对应风险级别。
- [ ] schema、测试、文档和版本字段同步。
- [ ] `git diff --check` 无错误。
- [ ] 没有 raw、VRM、secret、绝对路径或受限媒体进入 diff。
- [ ] AI 辅助内容已经人工复核，并能追溯到代码或一手来源。

Owner：`@Joker-of-Gotham`。自动检查通过不等于合并或发布批准。


<!--
---
type: how-to
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-10
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 90
title: Contributing to VIREA
audience: Contributors and reviewers
visibility: Public
summary: VIREA 的贡献边界、证据要求、测试分层和受限资产规则。
canonical: CONTRIBUTING.md
related:
  - README.md
  - SECURITY.md
  - doc/engineering-design.zh-CN.md
  - doc/validation.zh-CN.md
supersedes: []
superseded_by: []
---
-->
