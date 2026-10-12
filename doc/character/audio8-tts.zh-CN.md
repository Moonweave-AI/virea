<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.zh-CN.md) · [文档](../README.zh-CN.md) · [部署](../getting-started/automatic-setup.zh-CN.md) · [演示](../demos/README.zh-CN.md)
<!-- END DOC NAV -->

# 🎙️ Audio8 语音与参考声线

在 **Set Up → 本地部署 → Audio8** 选择设备并部署。安装流程展示检测、环境、依赖、权重、服务启动与生成检验，不需要单独运行一组语音脚本。

| 设置 | 操作 |
|---|---|
| 计算设备 | 自动选择、CPU 或受支持的 NVIDIA CUDA |
| 模型 | 部署配方使用固定版本的 Audio8 ONNX 权重 |
| 参考声线 | 在角色设置中导入参考录音与逐字对应的文本 |
| 语音检验 | 生成波形、时长和 WAV 下载，按需试听 |
| 下次启动 | VIREA 按已保存的部署记录恢复服务 |

参考音频与文本保存在本地数据目录中，密钥与录音不进入 Git。参考声线编码使用 CPU，语音推理使用所选择的设备。部署完成后，在语音连接中选择已发现的模型和声线并激活。

重新部署前先检测已有模型和服务；匹配的本地资产会复用。历史 CUDA/SGLang 实验记录属于当时的实现，当前可点击部署的路径以 Set Up 中的配方和实测结果为准。

[从零部署](../getting-started/automatic-setup.zh-CN.md) · [Character Studio](README.zh-CN.md) · [部署 API](../reference/onboarding-api.md)

<!-- BEGIN DOC FOOTER -->
---

[📚 文档地图](../catalog.zh-CN.md) · [🛠️ 故障排查](../operations/troubleshooting.zh-CN.md) · [🤝 参与贡献](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-03
updated: 2026-10-12
last_reviewed: 2026-10-12
review_cycle_days: 30
summary: Audio8 deployment and voice cloning through the shared Set Up workflow.
canonical: doc/character/audio8-tts.zh-CN.md
related: [README.zh-CN.md, dots-tts.zh-CN.md]
supersedes: []
superseded_by: []
-->
