<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md)
<!-- END DOC NAV -->

# 启动入口与工作区统一

## 目标

从桌面启动器、CLI 或 Python 模块启动时，访问同一组页面、同一个控制面与同一个数据根。配置和模型部署集中在 Set Up，三个工作区各自负责生成、角色对话与 VRChat 执行。

## 启动契约

| 入口 | 行为 |
|---|---|
| `Start-VIREA.cmd` / `start-virea.sh` | 准备工具链、依赖和前端，启动 API，打开 Set Up |
| `virea serve` | 使用指定数据根，检查前端构建，启动统一 API |
| `python -m virea` / `python -m virea.cli` | 转发到同一个 CLI；保留数据处理子命令 |
| `GET /api/v1/workspaces` | 返回四个工作区路径、运行代码指纹和数据根身份 |

共享入口定义在 `src/virea/workspaces.py`。构建检查覆盖四个 HTML 入口、共享源码和锁文件；自定义前端目录也必须提供四个入口。运行版本识别包含插件、注册表、配置、运行环境锁文件与协议资源，排除模型数据和已安装环境。启动器复用服务前，核对运行代码、数据根、Set Up 接口和全部页面，避免旧服务健康但新版功能返回 404。

独立 wheel 的基础包保留数据命令；`virea[studio]` 通过显式依赖安装同一套 CLI 和 API。缺少该扩展时，模块帮助和数据命令仍可运行，工作区命令会给出安装方式。

## 清理范围

移除旧 `apps/viewer-web`、其依赖和专用录制脚本；移除 Character/VRChat 独立进程栈启动器。保留数据集处理和预览 API，仍供批处理、标注与质量检查使用。Motion Lab 清除已迁移的系统页、模型部署事件及重复主题状态；浏览器验收使用当前 HeroUI 模型选择器。

模型权重、用户配置、原始数据、实验测量和发布视频保持可追溯。历史实验文档标记归档，并链接当时的代码修订；当前操作文档统一指向启动器和 Set Up。

## 验证与风险

风险 S2 / QA-L2。主要影响 CLI 分派、API 资源发现、前端构建、发布包和浏览器生成流程。回归覆盖入口分派、四页 HTTP 响应、旧路径移除、服务身份验证、源码变更后重建、全新 wheel 资源、模型选择、状态恢复与文档链接。

升级时退出原启动器，再运行同一个入口。代码可通过 Git 回退；本次修改不迁移或删除用户数据根。

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: explanation
status: Active
owner: VIREA maintainers
created: 2026-10-12
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 60
summary: Shared launch contract, retired UI cleanup, and verification of all four current workspaces.
canonical: doc/engineering-briefs/unified-entrypoints.zh-CN.md
related:
  - ../getting-started/automatic-setup.zh-CN.md
supersedes: []
superseded_by: []
-->
