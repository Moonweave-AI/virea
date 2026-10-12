<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](persistent-data-root.en.md)
<!-- END DOC NAV -->

# 📁 存储、端口与已有安装

自动启动器默认将运行文件放在 `.virea-runtime/portable/`。该目录由 Git 忽略。

| 目录 | 内容 |
|---|---|
| `tools/` | Python、Node 和包管理器 |
| `environment/` | 应用 Python 环境 |
| `cache/` | 安装包下载缓存 |
| `home/config/` | 服务配置、模型选择和客户端设置 |
| `home/model-store/` | 已安装的动作模型及校验制品 |
| `home/setup/` | 本地服务部署记录 |
| `home/jobs/`、`home/results/` | 任务和生成结果 |

## 选择磁盘与端口

Windows PowerShell：

```powershell
./scripts/start-virea.ps1 -DataRoot 'X:\VIREA-DATA' -Port 8000
```

Linux 或 macOS：

```sh
VIREA_DATA_ROOT='/path/with space/virea-runtime' sh start-virea.sh --port 8000
```

这里指定的是运行目录，其 `home/` 子目录成为 `VIREA_HOME`。引号是命令语法，不是路径的一部分。下次使用相同参数即可复用。终端会打印包含实际端口的 Set Up 和工作区链接。

## 接续已有数据目录

已经配置过 `VIREA_HOME` 时，在[开发环境](installation.zh-CN.md)中启动同一应用并指定原目录：

```sh
# 将路径替换为已有 config 和 model-store 的数据目录。
uv run virea serve --virea-home '/existing/virea/home' --port 8000
```

通过 Set Up 的本地检测接入已有模型，部署前确认检测出的路径。匹配的权重可以复用；选择空目录则会建立另一套安装状态。

## 更新或迁移

先用 Ctrl+C 停止启动器，更新源码，再以相同数据目录重新启动。复用运行服务前，启动器会核对应用版本指纹、数据目录身份和四个页面。端口被旧版或其他服务占用时，会明确说明。

更换磁盘时，先停止服务，再复制完整运行目录，用新的 `DataRoot` 启动。检测和真实生成检验通过后再处理原目录。清理缓存和结果前可参阅[数据保留](../operations/runtime-data-and-retention.zh-CN.md)。

高级命令行自动化可以用 `scripts/configure-virea.ps1` 或 `scripts/configure-virea.sh` 持久化环境变量。这些工具管理 CLI 存储；自动启动器会自行传入环境，无需修改终端配置文件。

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: Project-local runtime layout, custom ports and preservation of existing data.
canonical: doc/getting-started/persistent-data-root.zh-CN.md
related:
  - persistent-data-root.en.md
  - ../getting-started.zh-CN.md
  - ../reference/cli.zh-CN.md
  - ../../scripts/configure-virea.ps1
  - ../../scripts/configure-virea.sh
supersedes: []
superseded_by: []
-->
