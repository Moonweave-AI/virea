# VIREA 0.4.0 重构发布验收

验收日期：2026-08-21

Owner / DRI：`@Joker-of-Gotham`

风险 / 质量级别：S3 / QA-L4

决策依据：RFC-0003、ADR-0003、ADR-0004、ADR-0005、`EXECUTION_COMPATIBILITY.yaml`、
`registries/evidence/production-e2e.v1.yaml`

WP00-WP15 的实现与未完成出口见 [实现映射](WP00_WP15_IMPLEMENTATION_MAP.md)。本页只裁决当前事实，
不修改作为历史决策记录保留的 0.3 RFC/ADR。

## 最终裁决

| 范围 | 裁决 | 依据 |
|---|---|---|
| 六模型 manifest 状态 | 保留此前有界 `integrated_experimental` | 历史本机技术链存在；状态与当前 release evidence 是不同时间维度 |
| 六模型当前 v1.1 技术链 | Pending / No-Go | 旧 validated evidence / validator v1.0 已失效；新 v1.1 有效 `passed = 0` |
| 真实模型 `supported` | No-Go，数量为 0 | 多机况、质量、许可、生命周期与 SLO 未关闭 |
| 最终 0.4.0 artifact | Pending / No-Go | 树未冻结；最终 full suite 与 fresh artifact 尚未重跑 |
| 公开包、开源或商业 GA | No-Go | 项目/第三方许可、媒体权限、CI、SLO 与 release provenance 阻断 |

历史“六模型通过”只表示当时的本机技术验证，并在许可允许的范围内作为非商业研究候选；它不具备生产
候选资格，也不能替代当前 v1.1 重采集。
SentiAvatar MTA63 的 CC BY-NC 限制不因进入根 wheel 而消失，商业组织内部生产也不
自动获准；PRISM prompt-encoding adaptation 的上游条款缺失，技术成功不等于使用、复制或分发授权。

## 六条 current-0.4 v1.1 production evidence

`registries/evidence/production-e2e.v1.yaml` 中原有六条 validated evidence / validator `v1.0.0` 已被当前
合同判定失效。`virea.production_e2e_evidence.v1.1.0` 还要求 acceptance 与 fresh generation 的 Runtime
project package/version/core epoch、已安装 `virea-contracts`/`virea-model-sdk` identity 完全一致，并绑定
当前 Web 0.4.0 的唯一 hashed JavaScript HTTP body。新六条实际落盘前，有效 `passed = 0`。

| 模型 | Execution domain | 当前 v1.1 record |
|---|---|---|
| MARDM | Windows native | 待实际生成后从 registry 读取 |
| ACMDM | Windows native | 待实际生成后从 registry 读取 |
| CMDM | Windows native | 待实际生成后从 registry 读取 |
| FloodDiffusionTiny | Windows native | 待实际生成后从 registry 读取 |
| MoMADiff | Windows native | 待实际生成后从 registry 读取 |
| PRISM TP2M 1.4B | `wsl:Ubuntu-24.04` | 待实际生成后从 registry 读取 |

### ACMDM 资源校准（不是 v1.1 browser evidence）

ACMDM Runtime `0.1.3` / core epoch `virea-runtime-core-20260821.2` 已在 Win64 / RTX 5090 Laptop GPU 对
80 帧 production acceptance 与 196 帧 manifest maximum 各执行一次真实推理。跨请求 maxima 为
2,552,532,992 B process RSS、1,540,747,264 B system available RAM drop、673,024,512 B CUDA allocated、
687,865,856 B CUDA reserved、759,169,024 B CUDA free drop。按 `max(observed) + max(2 GiB, 20%)` 推导为
5 GiB RAM / 3 GiB VRAM；manifest 保留更保守的 8 GiB / 6 GiB，未下调且不外推其他 GPU/平台。这两次 job
没有 fresh browser observation，不能填入上表或计入 `passed`。

上述是待验证范围，不是预先成立的结果。即使六条新 record 全部通过，前五条也只证明其实际 Windows
native 机器，PRISM 只证明其实际 `wsl:Ubuntu-24.04` component-split 路径；不得外推原生 Linux、macOS、
其他 NVIDIA、ROCm、MPS、多 GPU 或 CPU inference profile。Windows/WSL 的 CPU build/import 也不等于
doctor→browser。

### PRISM 历史 v1.0 资源与浏览器记录

以下 ID 与测量只用于追溯旧轮次，不是当前 `passed`。历史 PRISM evidence
`e2e-browser-prism-tp2m-1-4b-20260821085331248-39264` 绑定 doctor
`01M0HR90CBFEXYGP0X5H0RJC5K`、installation `01M0HRA3NWZ1CHC8F0PBM8FD9F`、fresh job
`01M0HRD5QP3WRHD4W1NEXGGNX1` 与上述 result。RAM 观测为：

| 时点 | Available RAM | Process RSS |
|---|---:|---:|
| 加载前 | 32,463,986,688 B | — |
| 加载后 | 20,110,942,208 B | 12,612,476,928 B |
| 推理后 | 19,152,322,560 B | 13,683,249,152 B |

进程 VmHWM 是 31,703,216,128 B。本次 `allocation_peak_recorded: false`；VmHWM 是 RAM 高水位，不能被
写成 GPU peak，也不能用 GPU 总量代替未记录的 allocation peak。

Registry runner 记录 Avatar fully visible、AnimationMixer 0.1167→0.8334、43 个 render frames、
WebGL2/SwiftShader 和 0 console/page/request errors。根任务随后用独立应用内 Browser 打开同一 result，确认
fully visible、mixer 推进、硬件 WebGL2 RTX renderer 与 0 errors。独立复核补充了人工可见性与硬件渲染
观察，但不会覆盖 registry runner 的 renderer 字段。

## Evidence provenance

历史六条 v1.0 记录的 collection provenance 是：

```yaml
control_plane_version: 0.4.0
control_plane_source_kind: dirty_workspace_source_checkout
source_revision: null
release_artifact_verified: false
qualification: technical_source_candidate
```

这里的历史 registry qualification 只能解释为本机技术验证 / 非商业研究候选，不能复制成新 v1.1 记录的
既成 provenance。新记录必须写入本轮实际观测；工作树未冻结且没有 source revision 时，仍不能建立源码、
制品和证据之间的不可变追溯，也不能称 release candidate。

新 bundle 使用 checkout 外 `local_evidence` storage class，owner 为 `VIREA maintainers`，保留到被同范围
新记录替代，且 `excluded_from_gc: true`。本地 evidence 只支持 QA；公开发布前必须迁移到团队可访问的共享
archive。当前不新增 SHA/checksum 门禁。

## 当前测试与制品状态

| 门禁 | 当前事实 | 发布解释 |
|---|---|---|
| Web suite | 34 passed | 当前 Web 单元/合同切片通过；不是最终 full suite |
| Web production build | passed | 构建通过；不是部署或 GA 批准 |
| Python / Viewer / legacy / Ruff 完整 suite | pending frozen-tree run | 不复用任何历史通过数 |
| 文档门禁 | 本轮收口结束时运行 `check_docs.py`、`generate_docs.py --check`、`git diff --check` | 只证明文档一致性 |
| 最终 root sdist/wheel + offline fresh install | pending frozen-tree run | 必须在全部 evidence/docs/registry 稳定后重跑 |

外部 QA root `fresh-wheel-040-20260821-164633` 的 2026-08-21 运行已通过仓库外
sdist→sdist-built wheel→离线 fresh install 机制，并验证 bundled resources。但该 wheel 早于 Web 0.4 品牌
修复与最终 evidence registry，installed bundled JS 仍含已被取代的 `Motion Studio 0.3`；所以它只能作为
机制回归，不能作为最终 artifact。fresh test 已增加 installed bundled JS 版本/品牌一致性断言；最终运行
必须验证根版本、CLI、API、source Web、sdist、wheel 与 installed Web 都是 0.4.0，并拒绝旧品牌。

## 公开 / 商业 GA 阻断

以下任一项都足以保持 No-Go：

1. workspace dirty/unfrozen，`source_revision: null`；最终 full suite 与 release artifact 未在冻结树重跑。
2. 仓库没有项目代码 `LICENSE`，不能从第三方许可证、README 或公开可见性推导项目授权。
3. PRISM 正式源码/权重没有可由 VIREA 代授的许可；prompt-encoding adaptation 的上游条款缺失，
   `--accepted-license` 只记录本地操作者选择。
4. 根 wheel 的 `virea/motion/codecs.py` 含改编自 SentiAvatar MTA63 的 geometry constants，来源为 CC BY-NC；
   非商业限制同样约束商业组织内部生产，不授予项目整体 MIT 权利。
5. 用户指定的 AMASS/BABEL/GRAB/HumanML3D 各 4 个、共 16 个 GIF 已全部内联在 Showcase 页（该页总计
   28 个 GIF 引用），但这 16 项权限尚未逐项核实；文件存在、docs checker 通过或用户要求保留都不等于授权。
6. CMDM checkpoint 模型卡写 Apache-2.0，但其许可证链接目标缺失；发布前仍需权利链复核。
7. 托管 GitHub Actions 没有已观察记录；生产部署、SLO、告警和回滚演练也没有证据。

以上阻断与 v1.1 重采集门同时明确阻断公开包、开源 GA、商业 GA 和 `supported`；历史有界技术运行不能
解除其中任何一项。

## 发布与回滚

只有在树冻结后，才能按以下顺序重新裁决：

1. 记录 immutable source revision；
2. 串行运行最终完整 suite；
3. 从该 revision 构建 root sdist 和 sdist-built wheel；
4. 在 checkout 外离线安装，并验证全部 bundled resources、0.4.0 品牌/版本一致性；
5. 生成并确认六条 v1.1 模型证据与该 artifact 的对应关系；
6. 单独解决项目/PRISM/SentiAvatar/CMDM/GIF 权利和托管 CI/SLO 阻断。

回滚时保留 canonical211 v3、旧 Preview/Viewer 兼容层和历史 artifact；单模型异常只禁用对应
adapter/runtime。安装按 transaction/event 处理，remove 先移到可恢复位置；Motion IR descriptor 最后原子
发布。RFC-0003 的历史 0.3 无新增 SHA/安全码裁决继续保留，不用额外门禁替代真实测试和许可审查。

<!--
type: release-acceptance
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-21
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 14
summary: VIREA 0.4.0 六模型 v1.1 evidence 重采集、历史 dirty provenance、最终制品 pending 和公开/商业 GA No-Go 裁决。
canonical: doc/refactor/RELEASE_ACCEPTANCE_0.4.0.md
related:
  - doc/refactor/QA_PLAN.md
  - doc/refactor/WP00_WP15_IMPLEMENTATION_MAP.md
  - doc/rfcs/0003-virea-0.3-multi-model-refactor.zh-CN.md
  - doc/adrs/0003-multi-package-isolated-model-runtimes.zh-CN.md
supersedes: []
superseded_by: []
-->
