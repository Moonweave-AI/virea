<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md) · [English](installation.en.md)
<!-- END DOC NAV -->

# 🛠️ 开发安装清单

日常使用请运行[自动启动器](automatic-setup.zh-CN.md)。本页用于修改源码和运行测试。

准备 Python 3.12、uv、Node.js 24 和 pnpm 10.33.0，然后在仓库根目录执行：

```sh
uv sync --locked --all-packages --extra dev
pnpm install --frozen-lockfile
pnpm --filter @virea/web build
# 初始化与启动器共用的项目内数据目录。
uv run virea setup --virea-home .virea-runtime/portable/home
# 用同一 API 提供 Set Up 和三个工作区。
uv run virea serve --virea-home .virea-runtime/portable/home
```

Windows 用户可在 `uv sync` 中追加 `--extra vrchat` 安装 VRChat 接入依赖。通过 CLI 在项目内安装模型运行环境时，设置 `VIREA_ALLOW_CHECKOUT_RUNTIME=1`；自动启动器会自行设置。

服务启动后打印四个页面地址。`python -m virea serve` 也进入同一应用。源码更新后，服务会先检查四个 HTML 入口及其资源，构建过期前端。

## 验证修改

```sh
uv run ruff check .
uv run python -m pytest tests/onboarding tests/refactor/test_api_cli_integration.py -q
pnpm --filter @virea/web test
pnpm --filter @virea/web build
uv run python scripts/check_docs.py
```

需要前端热更新时，保持 API 在 8000 端口运行，再执行 `pnpm --filter @virea/web dev`。Vite 打印开发地址，并将 `/api` 转发给 API；正式启动器直接提供构建后的页面。

配置、模型安装和结果位于选定的 `VIREA_HOME`。参阅[存储](persistent-data-root.zh-CN.md)和 [CLI](../reference/cli.zh-CN.md)。

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: tutorial
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: Source development using the same application and web workspace.
canonical: doc/getting-started/installation.zh-CN.md
related:
  - installation.en.md
  - ../getting-started.zh-CN.md
  - first-generation.zh-CN.md
  - ../platforms/README.zh-CN.md
  - ../operations/runtime-data-and-retention.zh-CN.md
supersedes: []
superseded_by: []
-->
