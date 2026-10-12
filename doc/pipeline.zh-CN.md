<!-- BEGIN DOC NAV -->
[✦ VIREA](../README.zh-CN.md) · [文档](README.zh-CN.md) · [部署](getting-started/automatic-setup.zh-CN.md) · [演示](demos/README.zh-CN.md)
<!-- END DOC NAV -->

# 数据处理与动作预览

数据管线把原始动作、标注与坐标约定转成可检查的骨架和 VRMA。生成模型在 [Motion Lab](http://127.0.0.1:8000/app/) 中运行；离线数据集使用下列命令。两者共用重定向数学与数据契约。

## 🚀 准备环境

普通使用从 [Set Up](getting-started/automatic-setup.zh-CN.md) 开始。处理本地数据集时，先按[开发环境安装](getting-started/installation.zh-CN.md)准备 `uv`，然后在项目目录执行：

```sh
# 安装仓库锁定的开发依赖。
uv sync --locked --all-packages --extra dev
```

## 📁 数据与输出位置

| 配置 | 用途 |
|---|---|
| `VIREA_RAW_ROOT` | 原始数据集目录 |
| `VIREA_DATA_ROOT` | 未指定 raw root 时，从它的 `raw/` 目录寻找数据 |
| `VIREA_PROCESSED_ROOT` | 处理产物保存目录 |
| `VIREA_DATA_SOURCE` | `demo` 或 `full` |
| `VIREA_ALLOW_TRUSTED_RAW_PICKLE` | 核验过来源的旧 GRAB/SuSu 对象容器可显式设为 `1` |

项目默认值在 `configs/project.yaml`，本机路径由环境变量覆盖。模型、原始数据和批量输出放在本机数据目录，不提交到 Git。

<details>
<summary>设置数据目录</summary>

Windows PowerShell：

```powershell
$env:VIREA_RAW_ROOT = "X:\VIREA-DATA\raw"
$env:VIREA_PROCESSED_ROOT = "X:\VIREA-DATA\processed"
```

macOS / Linux：

```sh
export VIREA_RAW_ROOT="/mnt/motion/raw"
export VIREA_PROCESSED_ROOT="/mnt/motion/processed"
```

</details>

## 🦴 处理一组样本

```sh
# 先处理 AMASS 中的两个样本，检查坐标和产物。
uv run virea process --data-source full --datasets amass --limit-per-dataset 2
# 检查无误后处理该数据集；默认复用已经完成的产物。
uv run virea process --data-source full --datasets amass
# 从完整数据制作供开发使用的 demo 子集。
uv run virea build-demo --samples-per-dataset 100
```

`--query` 筛选样本 ID，`--max-frames` 限制处理帧数，`--workers` 指定并发量，`--force` 重新处理已有样本。运行结果包含逐样本与逐骨骼质量指标。

## 🔎 读取与检查

启动器运行后，数据接口与工作区共用一个服务；默认地址为 `http://127.0.0.1:8000`。具体请求字段可直接在 `/docs` 查阅。

| API | 内容 |
|---|---|
| `GET /api/datasets` | 数据集与数据根状态 |
| `GET /api/samples?dataset=amass&limit=10` | 样本列表 |
| `GET /api/preview/source` | 原始骨架、标注和通道 |
| `GET /api/preview/processed` | 重定向后的骨架与同一组语义标注 |
| `GET /api/preview/motion` | 动作结果 |
| `GET /api/preview/quality` | 数值质量报告 |
| `POST /api/process` | 处理选定样本 |
| `POST /api/batch` | 提交批处理 |

预览请求传入 `dataset`、`sample_id` 和可选 `data_source`。API 中保留完整语义元数据；当前 Motion Lab 展示生成任务的源骨架与 VRM 对照，并支持导入本地 VRMA 播放。

## 📚 继续阅读

[七数据集语义](dataset-audit.zh-CN.md) · [标注契约](annotation-viewer.zh-CN.md) · [重定向数学](math-retarget/README.zh-CN.md) · [浏览器验收](quality/production-browser-evidence.zh-CN.md)

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](catalog.zh-CN.md) · [🛠️ 故障排查](operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 60
summary: Current dataset processing commands and shared API preview workflow.
canonical: doc/pipeline.zh-CN.md
related:
  - ../README.md
  - engineering-design.zh-CN.md
  - validation.zh-CN.md
  - rfcs/0002-constraint-aware-hand-retarget-v1.zh-CN.md
  - adrs/0002-canonical-v3-constrained-hand-retarget.zh-CN.md
supersedes: []
superseded_by: []
-->
