---
type: explanation
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: 首次启动、多供应商接入及本地运行环境自动部署的工程边界与验收。
canonical: doc/engineering-briefs/portable-onboarding.zh-CN.md
related: []
supersedes: []
superseded_by: []
---

# 可移植首次配置与模型接入

用户授权在当前功能分支实施。维护者负责合并审查；本文不代表独立审查已完成。

## 领域与状态

- Connection：语言或语音供应商、协议、地址、模型、声线及独立保存的凭证；公开查询仅返回凭证是否存在。
- Active connection：每类一个当前连接；保存不等于启用，测试成功后可启用，后续推理读取当前配置。
- Deployment：本机一个安装任务，状态 queued/running/succeeded/failed/cancelled/interrupted；持久化步骤、进度、错误与可重试结果。
- Managed service：由 VIREA 启动的进程；复用通过健康检查的现有端点，不杀死用户已有的服务。
- Capability：操作系统、CPU/GPU、磁盘、已发现服务和已安装模型的事实；不能把“下载完成”视为“推理正常”。

## 不变量与接口

现有 CharacterConfig 地址仍兼容；新增接入配置是可选的。语言规划和流式回复共享协议转换；语音输出统一为经过验证的 PCM16 WAV。云端连接必须使用 HTTPS，本机 HTTP 限 loopback。API Key 不进入 URL、浏览器持久存储、任务日志或诊断响应。

新增 `/api/v1/onboarding` 接口提供供应商目录、连接 CRUD/测试/启用、本机发现、部署任务提交/查询/取消。具有写入或联网副作用的接口要求同源及专用请求头。请求不接受任意 shell 命令，安装配方为代码内白名单。现有模型安装和运行时清单继续负责模型兼容性与检查点契约。

网页向导和脚本共用该控制面。Windows、Linux、macOS 启动器补齐用户目录中的 uv/Python/Node/pnpm 并按锁文件安装；项目资产和运行数据各有固定目录。安装过程不更改系统音量、不执行音频播放。

## 实施与验收

1. OpenAI 兼容、Anthropic Messages、Ollama 原生语言适配；OpenAI 兼容、DashScope 和本机 VIREA 语音适配；供应商能力显式展示。
2. 局部端点探测、已有配置复用、本地 LLM 下载进度、本地语音及 MotionCraft/SynTalker 安装启动。
3. 可恢复任务、进度条、步骤数、失败说明；从零启动入口与中文/英文操作指南。
4. 协议契约、凭证隔离、错误与取消、平台命令规划、真实浏览器流程、现有角色/VRChat 回归；CI 覆盖三种操作系统。

## 失败、资源与回退

网络断开保留已下载缓存；失败不激活连接；进程重启把未完成任务标记 interrupted。模型条款和受限资源不自动伪造接受；不兼容硬件提前给出说明。CPU 兼容不等于实时速度。游戏客户端及虚拟 VR 驱动仍有平台限制，与通用模型配置分开显示。

依赖优先采用现有 httpx、Pydantic、uv 与锁文件；供应商协议使用独立模块，替换不影响会话/动作契约。回滚方式是取消启用新连接并回到原 CharacterConfig；不自动清除用户模型、密钥或缓存。

## 风险与审查

风险 S2 / QA-L2：本地软件安装、外部 API 数据发送及凭证持久化。新增接口需要维护者在 PR 进行契约与安全审查。GitNexus 对 CharacterConfig 为 HIGH、语言规划入口为 CRITICAL；当前索引存在过期和错误关联，须结合实际调用与回归证据，不能将空图结果当成无影响。
