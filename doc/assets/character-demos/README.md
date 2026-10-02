---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-03
updated: 2026-10-03
last_reviewed: 2026-10-03
review_cycle_days: 90
summary: Recorded character performances, exact public media inventory and provenance.
canonical: doc/assets/character-demos/README.md
related: [doc/character/showcase.en.md, doc/character/showcase.zh-CN.md]
supersedes: []
superseded_by: []
---

# Motion Studio recording inventory / 录制清单

Recorded locally on 2026-10-02–03 at the repository owner's explicit request to publish eight demos in the README. These are actual model-generated performances, captured from browser playback with original sound. The source VRM and model weights are not distributed.

角色使用用户提供的 `miku.vrm`。内嵌 VRM 元数据的 title、author、contactInformation 和 reference 均为空；因此此处不猜测作者或宣称已经核实上游发布授权。元数据包含 [VRoid 使用条件链接](https://hub.vroid.com/license?allowed_to_use_user=everyone&characterization_allowed_user=everyone&corporate_commercial_use=allow&credit=necessary&modification=disallow&personal_commercial_use=profit&redistribution=disallow&sexual_expression=allow&version=1&violent_expression=allow)。本次媒体按仓库所有者明确展示指令登记；这与独立核实权利是两件事。

Model and tooling credits: [SentiAvatar / SentiPulse](https://github.com/SentiAvatar/SentiAvatar), [ARDY / NVIDIA](https://github.com/nv-tlabs/ardy), [Qwen](https://github.com/QwenLM), [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), [Three.js](https://threejs.org/) and [three-vrm / pixiv](https://github.com/pixiv/three-vrm). VIREA integrates their outputs, retargets motion to the provided VRM and records the result. Their individual license conditions remain with the respective projects.

详细任务、实测和失败尝试见 [中文报告](../../character/showcase.zh-CN.md) / [English report](../../character/showcase.en.md)。[可播放画廊](index.html) · [时序与校验和](manifest.json)。

| Task / 任务 | Complete video | Five-second preview | Poster |
| --- | --- | --- | --- |
| 主持入场 / Stage host | [MP4](01-host.mp4) | [GIF](01-host.gif) | [JPG](01-host.jpg) |
| 热身教练 / Warm-up coach | [MP4](02-warmup.mp4) | [GIF](02-warmup.gif) | [JPG](02-warmup.jpg) |
| 故事表演 / Acted story | [MP4](03-story.mp4) | [GIF](03-story.gif) | [JPG](03-story.jpg) |
| 舞步教学 / Dance lesson | [MP4](04-dance.mp4) | [GIF](04-dance.gif) | [JPG](04-dance.jpg) |
| 服装展示 / Fashion presentation | [MP4](05-fashion.mp4) | [GIF](05-fashion.gif) | [JPG](05-fashion.jpg) |
| 情绪转折 / From doubt to joy | [MP4](06-celebration.mp4) | [GIF](06-celebration.gif) | [JPG](06-celebration.jpg) |
| 行走导览 / Walking guide | [MP4](07-tour.mp4) | [GIF](07-tour.gif) | [JPG](07-tour.jpg) |
| 拳击练习 / Boxing practice | [MP4](08-boxing.mp4) | [GIF](08-boxing.gif) | [JPG](08-boxing.jpg) |
