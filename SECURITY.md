# Security Policy

VIREA 处理来自外部数据集、模型与多模态文件的输入。即使只做本地预览，也必须把这些内容视为不可信或受限资产。

## 受支持状态

VIREA 当前是研究预览，没有正式 release 或稳定支持分支。安全修复以最新 `main` 为目标；pre-v3 artifact 仅保留受限兼容读取，不获得当前 Avatar motion 支持。

## 私密报告

请优先使用 GitHub 仓库的 private vulnerability reporting / Security Advisory（如果仓库已启用）。如果该入口不可用，请通过 Moonweave-AI 组织已经建立的私密渠道联系仓库 Owner；不要为此公开原始样本、凭据、个人数据、未授权媒体或可直接执行的利用代码。

报告尽量包含：

- 受影响 commit、入口和数据类型；
- 最小、无隐私数据的复现步骤；
- 实际影响与预期 fail-closed 行为；
- 是否涉及 pickle/object array、路径泄漏、浏览器内容、artifact 篡改或媒体权限；
- 可安全共享的日志与哈希。

Owner 收到报告后应确认范围、保留证据、制定修复与回归，并在不扩大暴露的前提下协调披露。当前没有承诺固定响应 SLA。

## 关键威胁边界

### NumPy object / pickle

GRAB 与部分 SuSuInterActs 容器可能需要 pickle。默认加载路径必须拒绝；一次性 opt-in 只允许用于来源和摘要已经核验的离线会话。公开或远程服务不得启用。

### 路径与隐私

API、日志、metadata、截图和 JSON 报告不得返回 raw root、processed root、用户目录或 VRM 绝对路径。使用 portable token、basename 与 SHA-256。

### Artifact 与 Viewer

Canonical v3 的 manifest、数组、quality、solver report 与证书必须一起验证。Reader 不使用仅基于 path/size/mtime 的可信缓存；Viewer 只接受 replay-verified payload，并对实际 hand quaternion 切片重算摘要。验证失败不得回退到未验证 Avatar motion。

### 浏览器与外部内容

未知字符串不自动变成可点击 URL。Viewer 只从本地文件选择器读取 VRM；不得把 dataset text、模型 metadata 或 annotation 当作 HTML 执行。

### 媒体与知识产权

未经明确 `allowed` 决定的数据集、VRM 与派生媒体保持 local-only。权限错误、无意公开、raw URL 暴露或历史 Git 对象残留都属于需要 Owner/IP reviewer 处理的安全与治理事件。

## 不应进入公开 issue 的内容

- credentials、private URL、个人目录与访问 token；
- raw dataset、对话、音频、人脸或可识别个人的信息；
- 未授权 VRM、截图、GIF、视频或模型元数据；
- 可直接触发恶意 pickle 的 payload；
- 尚未协调披露的漏洞细节。

一般 bug、文档错误和不含敏感信息的姿态回归可以使用普通 issue，并按 [CONTRIBUTING.md](CONTRIBUTING.md) 提供最小证据。


<!--
---
type: policy
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-10
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 90
title: VIREA Security Policy
audience: Users, contributors, and security reporters
visibility: Public
summary: VIREA 的漏洞报告、受支持状态、raw/pickle/路径隐私和媒体资产安全边界。
canonical: SECURITY.md
related:
  - README.md
  - CONTRIBUTING.md
  - doc/validation.zh-CN.md
supersedes: []
superseded_by: []
---
-->
