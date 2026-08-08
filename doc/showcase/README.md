---
type: eval-report
status: Blocked
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-08
last_reviewed: 2026-08-08
review_cycle_days: 30
summary: 7 x 7 本地 Showcase、真实 VRM 审计、媒体隔离和公开发布门禁。
canonical: doc/showcase/README.md
related:
  - ../validation.zh-CN.md
  - ../dataset-audit.zh-CN.md
  - ../../README.md
supersedes: []
superseded_by: []
---

# Showcase：7 x 7 本地看板

## 当前结论

本目录历史上包含 49 个 GIF 与 49 个同名 WebM，但它们来自旧 v0.1 pipeline，
不是 v0.2 发布证据。旧选择还包含已经确认的错误路径：BABEL 未按真实 annotation
carrier 分层，Motion-X 曾使用错误的 322D slice，SuSu 曾使用错误的 rows/global
解释，HumanML3D 曾允许伪 fallback。因此旧媒体只能留作本地取证，不能用于证明
当前数学、标注、真实 VRM 对齐或动作质量。

机器可读的 [publication-policy.json](publication-policy.json) 当前决定为
`local-only`，所以本页不嵌入、不链接任何 legacy GIF/WebM。文档检查仍在本地核对
49 对文件、同名关系、非空内容与 legacy manifest 一致性；这只是完整性检查，不是
公开许可。

这些 98 个 legacy 文件已经存在于公开 `main` 的 Git 树和历史中，移除本页链接与新增
`.gitignore` 不能撤回 raw URL、clone、fork 或缓存。当前因此是 Stop-Ship：Owner/IP
reviewer 必须二选一并留下决定记录——提供每个 legacy 媒体独立的 `allowed` 证据，或
批准从当前树移除、重写历史、通知 fork/镜像并申请平台缓存撤回。完成前不得把新的
公开分支或 PR 当作发布交付。

## VRM 审计

用于本地验收的模型只记录脱敏信息：

| 字段 | 值 |
|---|---|
| SHA-256 | `f7c947ef380b9478db166db0366cec1dc3ceebaefe76a1b986fe104e793d998` |
| VRM generation | 0.x |
| Title | `VRM-Model-1` |
| Author | `Reira` |
| Humanoid coverage | 54 mappings；canonical core 21/21、hands 30/30 |
| Metadata license URL | 空 |
| Rights decision | `local-only` |

模型本体以及由它派生的媒体均不得公开提交、推送或内联。模型本机绝对路径不进入
仓库、日志、artifact 或验收报告。只有 Dataset/VRM/IP reviewer 将机器可读 decision
改为 `allowed`，并给出证据链接后，才可以恢复公开预览。

## v0.2 样本选择

`showcase-samples.json` 当前仍是 legacy manifest。重建时每个数据集固定选择七类样本：

1. 普通直立；
2. root locomotion；
3. 转身；
4. 上肢主导；
5. 下肢或地面接触；
6. 长文本或多标签；
7. 数据集特有多模态。

BABEL 必须使用真实 BABEL annotation record；GRAB 必须覆盖 object/contact；
Motion-X 必须包含 sub-source/basis 反例；SuSu 只允许已校准 profile。任何类别不适用时，
manifest 必须记录原因并选择另一条异常样本，不能临时挑选“看起来最好”的结果。

新 manifest 的每条记录必须包含：

- dataset、sample id、source file hash、source/effective FPS 与 frame count；
- resolved profile snapshot hash、canonical artifact hash、processing version 与 Git commit；
- VRM SHA-256、loader/version、viewport、DPR；
- GIF/WebM SHA-256、byte length、生成时间与命令；
- dataset license family、VRM rights、redistribution decision、reviewer 与证据链接；
- source、basis、canonical、FK、VRM、playback 各层结果。

缺少任何 rights decision 时默认为 `unknown` 并禁止公开发布。

## 本地录制

启动本地 Viewer 后执行；输出目录不得直接进入 Git：

```powershell
$env:VIREA_SHOWCASE_SERVER = "http://127.0.0.1:8000"
$env:VIREA_SHOWCASE_VRM = "<local-avatar.vrm>"
node scripts/render_showcase.mjs `
  --data-source demo `
  --manifest doc/showcase/showcase-samples.json `
  --out-dir "<local-output-directory>"
```

```bash
export VIREA_SHOWCASE_SERVER="http://127.0.0.1:8000"
export VIREA_SHOWCASE_VRM="<local-avatar.vrm>"
node scripts/render_showcase.mjs \
  --data-source demo \
  --manifest doc/showcase/showcase-samples.json \
  --out-dir "<local-output-directory>"
```

模型 path 只通过参数或环境变量传入。Recorder 必须确认 Viewer status 是 VRM humanoid，
而不是 static GLB fallback。

## 本地 GIF 转换

GitHub 对 WebM 内联支持不稳定；只有公开许可通过后，才可以选择 GIF/静态图内联并
链接完整视频。许可仍为 `local-only` 时，转换结果必须留在仓库外。

```powershell
Get-ChildItem "<local-video-directory>" -Filter *.webm | ForEach-Object {
  ffmpeg -y -i $_.FullName `
    -vf "fps=8,scale=160:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=64[p];[s1][p]paletteuse" `
    (Join-Path "<local-gif-directory>" ($_.BaseName + ".gif"))
}
```

```bash
for video in "<local-video-directory>"/*.webm; do
  base="$(basename "$video" .webm)"
  ffmpeg -y -i "$video" \
    -vf "fps=8,scale=160:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=64[p];[s1][p]paletteuse" \
    "<local-gif-directory>/${base}.gif"
done
```

## 发布门禁

当前状态是 Blocked / `local-only`。解除需要同时满足：

- v0.2 全量重建与固定七乘七 manifest；
- 七库真实 source/processed/VRM 视觉回归；
- body-part marker、真实时间播放与性能门禁；
- 所有 dataset、VRM 与衍生媒体 rights decision 均为 `allowed`；
- LICENSE/NOTICE 与第三方 attribution 完整；
- 已公开 legacy 媒体取得独立许可，或完成当前树、历史、fork/镜像与缓存处置；
- 干净 clone 的大小写、相对链接和远端 commit 一致性检查。

文件存在、hash 一致或本地视觉通过，都不能单独把该状态改成 Go。
