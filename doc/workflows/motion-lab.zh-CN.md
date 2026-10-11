---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Use the motion-lab workspace.
canonical: doc/workflows/motion-lab.zh-CN.md
related: []
supersedes: []
superseded_by: []
---

# Motion Lab：生成与检查动作

[English](motion-lab.en.md) · [先完成部署](../getting-started/automatic-setup.zh-CN.md)

想单独生成、比较和导出动作时，使用 Motion Lab。

1. 打开 `/app/` 主工作台。
2. 选择动作模型；按页面提示安装并进行真实生成检验。
3. 选择检测到的运行环境，输入简洁英文动作，如 `A person waves with one hand.`。
4. 设置时长和随机种子，提交任务。查看加载、生成、标准化、重定向、校验和导出的进度。
5. 在原始骨架与目标角色之间对照，拖动时间轴检查手腕、脚部、朝向和位移。
6. 下载动画和结果元数据。

Motion Lab 使用原生模型适配器、Motion IR v2 和公共重定向流程，无需语言模型、声线或角色会话。

继续阅读[模型目录](../models/README.zh-CN.md)、[首次生成](../getting-started/first-generation.zh-CN.md)及[重定向数学](../math-retarget/README.zh-CN.md)。
