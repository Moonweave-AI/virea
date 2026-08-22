---
type: reference
status: Active
owner: VIREA maintainers
created: 2026-08-21
updated: 2026-08-23
last_reviewed: 2026-08-23
review_cycle_days: 14
summary: 真模型从环境检测到浏览器播放的单链验收、证据结构和晋级门槛。
canonical: doc/quality/production-e2e.zh-CN.md
related:
  - production-e2e.en.md
  - ../models/README.zh-CN.md
  - ../platforms/README.zh-CN.md
  - ../operations/troubleshooting.zh-CN.md
supersedes: []
superseded_by: []
---

# Production E2E

> [中文](production-e2e.zh-CN.md) · [English](production-e2e.en.md)

完整流程必须由同一个 run/evidence identity 关联：

```text
doctor report
  → artifact installation transaction
  → isolated runtime build and probe
  → model READY
  → exact real-checkpoint inference
  → native ModelResult
  → Motion IR
  → target/canonical motion
  → validated VRMA
  → real browser + real VRM playback
```

## 必需证据

| 阶段 | 必须保存 |
|---|---|
| 环境 | execution domain、OS/arch、Python、driver、device、free VRAM/RAM/swap/storage |
| 安装 | model/runtime/artifact revisions、transaction 和 READY snapshot |
| 推理 | exact manifest request、Worker identity、device/profile、native shape/FPS/finite/variance |
| 转换 | native→Motion IR→target skeleton/representation identity 与 frame count |
| VRMA | glTF/VRMC 扩展、rest hips、52 rotation + root translation 或模型声明的精确轨道 |
| 浏览器 | Playwright JSON、截图、WebGL renderer、Avatar 可见、动画时间推进、duration、console 零错误 |
| 生命周期 | Worker/child process 退出、端口关闭、GPU/内存释放、取消与重启无孤儿 |

## 不构成证据

- 合成 tensor、fixture、只加载 checkpoint 或只下载文件；
- 不属于同一 installation/job/result 的拼接截图；
- 客户端自报的 `played=true`、`errors=0` 等布尔字段；
- Viewer 中用相机或修正矩阵掩盖错误 VRMA；
- 其他 OS、GPU 或资源配置的外推。

`virea validate-real-e2e` 验证持久化安装、生成和制品；真实浏览器 runner 生成独立、不可由普通客户端自证的
播放证据。两者都通过后，当前 `virea.production_e2e_evidence_validator.v1.1.0` 还会绑定 acceptance 与
fresh generation 的 Runtime project/version/core epoch、已安装核心包 identity，以及当前 Web 0.4.0 的唯一
hashed JavaScript HTTP body；最终只有 `virea.production_e2e_evidence.v1.1.0` 能登记为 validated。完整版本
策略见 [Production browser evidence](production-browser-evidence.zh-CN.md)。

## 当前六模型 v1.1 重采集（2026-08-21）

`registries/evidence/production-e2e.v1.yaml` 是模型级事实入口，但其中原有六条 validated evidence / validator
`v1.0.0` 已被当前 `v1.1.0` 合同判定为失效。在六条新链实际完成并写入前，当前策略下有效 `passed` 数量为
0；本文不会预分配 evidence/job/result ID，也不会把历史 result replay 当作迁移。待重采集范围为：

| 模型 | Execution domain | 当前 v1.1 record |
|---|---|---|
| `mardm-humanml3d` | Windows native | 待本轮生成并从 registry 读取 |
| `acmdm-humanml3d` | Windows native | 待本轮生成并从 registry 读取 |
| `cmdm-humanml3d` | Windows native | 待本轮生成并从 registry 读取 |
| `flood-diffusion-tiny` | Windows native | 待本轮生成并从 registry 读取 |
| `momadiff-humanml3d` | Windows native | 待本轮生成并从 registry 读取 |
| `prism-tp2m-1-4b` | `wsl:Ubuntu-24.04` | 待本轮生成并从 registry 读取 |

预期范围本身不能代替证据。即使新六条全部通过，前五条也只覆盖其实际 Windows native 机器，PRISM 只
覆盖其实际 `wsl:Ubuntu-24.04` component-split 路径；不得外推 Windows native PRISM、原生 Linux、macOS、
其他 NVIDIA、ROCm、MPS、多 GPU 或 CPU inference profile。

历史 PRISM v1.0 bundle 的 RAM 观察仍可作为已标注来源的诊断事实：加载前 available 32,463,986,688 bytes；加载后 available
20,110,942,208 bytes、RSS 12,612,476,928 bytes；推理后 available 19,152,322,560 bytes、RSS
13,683,249,152 bytes；VmHWM 31,703,216,128 bytes。该旧轮次 `allocation_peak_recorded: false`，所以没有
可声明的 GPU peak，不能用 GPU 总量或 RAM VmHWM 代替，也不能把这些数字冒充新 v1.1 运行的资源观测。

同一历史 PRISM observation 记录 fully visible、AnimationMixer 0.1167→0.8334、43 frames、
WebGL2/SwiftShader 和 0 console/page/request errors。根任务又在独立应用内 Browser 打开同一 result，确认
fully visible、mixer 推进、硬件 WebGL2 RTX renderer 和 0 errors。这是第二份视觉复核，不覆盖 registry
runner 的 renderer 原始事实；两者都不是当前 v1.1 晋级记录。

## Evidence collection 与发布边界

新 v1.1 record 必须自行记录本轮 collection provenance；旧 v1.0 的
`dirty_workspace_source_checkout`、`source_revision: null`、`release_artifact_verified: false` 不能被复制成新
运行的既成事实。若本轮仍来自 dirty/unfrozen tree，其 qualification 最多只能解释为本机技术验证 / 非商业
研究候选。现有 164633 fresh-wheel 运行发生在 Web 0.4 品牌修复与当前 evidence policy 之前，只能作为
packaging 机制回归；冻结树的最终 sdist/wheel、installed Web 版本一致性和完整 suite 均待重跑。

因此当前状态是：六模型 manifest 状态保留此前有界 `integrated_experimental`，但当前树的 v1.1 证据重采集
尚未关闭；`supported = 0`，公开 GA 为 No-Go。除当前 evidence、未冻结源码和最终制品外，阻断还包括项目
代码 `LICENSE` 缺失、PRISM 许可、SentiAvatar MTA63 CC BY-NC、Showcase 页已全部内联的 16 个指定 GIF
使用权限未核实、CMDM 模型卡许可链接缺文件、托管 CI 与生产 SLO/部署后验证缺失。任何一条都不能由本地
E2E 或用户 `--accepted-license` 自动消除。
