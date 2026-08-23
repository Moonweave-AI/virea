import "./styles.css";
import {
  api,
  stateEventsUrl,
  type HealthStatus,
  type JobRecord,
  type ModelManifest,
} from "./api";
import type {
  ExecutionDomainCandidates,
  ExecutionTargetSelection,
  ModelExecutionOption,
  ModelResult,
  SourceSkeletonPreview,
  StateRevision,
  VrmMotionResult,
} from "./contracts";
import {
  artifactUrl,
  firstVrmaExport,
  generationDefaults,
  installationState,
  isInstalledReady,
  modelMotionRoute,
  productionCatalogModels,
  productionCatalogJobs,
  realRunnableModels,
  resultMotionRoute,
} from "./domain";
import { RealVrmViewer, type ViewerStatus } from "./viewer";
import { SourceSkeletonViewer, type SourceViewerStatus } from "./source-viewer";

type View = "playground" | "catalog" | "overview";
type SyncStatus = "connecting" | "live" | "polling" | "offline";
type Draft = { prompt: string; seconds: number; seed: number };

const TERMINAL_JOB_STATES = new Set([
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "TIMED_OUT",
  "REJECTED",
]);
const STATE_POLL_INTERVAL_MS = 4_000;

const state: {
  view: View;
  models: ModelManifest[];
  jobs: JobRecord[];
  health: HealthStatus | null;
  vireaHome: string;
  system: Record<string, unknown> | null;
  systemLoading: boolean;
  executionDomains: ExecutionDomainCandidates | null;
  executionOptions: Record<string, ModelExecutionOption[]>;
  selectedExecutionDomainId: string;
  executionDomainTouched: boolean;
  selectedModelId: string;
  drafts: Record<string, Draft>;
  installationStates: Record<string, string>;
  installingModelId: string;
  activeJob: JobRecord | null;
  lastResult: VrmMotionResult | null;
  lastModelResult: ModelResult | null;
  lastSourcePreview: SourceSkeletonPreview | null;
  lastVrmaUrl: string;
  lastGeneration: { modelId: string; seconds: number; seed: number } | null;
  generationEvidence: string;
  viewerStatus: ViewerStatus;
  sourceViewerStatus: SourceViewerStatus;
  syncStatus: SyncStatus;
  lastSyncedAt: string;
  notice: string;
  error: string;
} = {
  view: "playground",
  models: [],
  jobs: [],
  health: null,
  vireaHome: "",
  system: null,
  systemLoading: false,
  executionDomains: null,
  executionOptions: {},
  selectedExecutionDomainId: "",
  executionDomainTouched: false,
  selectedModelId: "",
  drafts: {},
  installationStates: {},
  installingModelId: "",
  activeJob: null,
  lastResult: null,
  lastModelResult: null,
  lastSourcePreview: null,
  lastVrmaUrl: "",
  lastGeneration: null,
  generationEvidence: "",
  viewerStatus: { kind: "idle", message: "载入 Avatar 后即可预览生成动作" },
  sourceViewerStatus: { kind: "idle", message: "生成完成后显示重定向前骨架" },
  syncStatus: "connecting",
  lastSyncedAt: "",
  notice: "",
  error: "",
};

const appNode = document.querySelector<HTMLDivElement>("#app");
if (!appNode) throw new Error("#app is missing");
const app: HTMLDivElement = appNode;

let viewerRuntime: RealVrmViewer | null = null;
let viewerCanvas: HTMLCanvasElement | null = null;
let viewerLoadedVrmaUrl = "";
let sourceViewerRuntime: SourceSkeletonViewer | null = null;
let sourceViewerCanvas: HTMLCanvasElement | null = null;
let sourceViewerLoadedResultId = "";
let sourcePreviewAttemptedResultId = "";
let stateSocket: WebSocket | null = null;
let stateStreamRetryAt = 0;
let stateRevisionKey = "";
let syncInFlight: Promise<void> | null = null;
let syncQueued = false;

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    registered: "仅登记",
    source_available: "源码可用",
    runnable_upstream: "上游可运行",
    integrated_experimental: "实验接入",
    supported: "正式支持",
    blocked: "阻塞",
  };
  return labels[status] ?? status;
}

function installationLabel(status: string | null): string {
  const labels: Record<string, string> = {
    READY: "已就绪",
    DOWNLOADING: "正在下载",
    VERIFYING: "正在校验",
    BUILDING_RUNTIME: "正在部署",
    ACCEPTANCE_TESTING: "正在验收",
    FAILED: "失败",
    CANCELLED: "已取消",
    REMOVING: "正在移除",
  };
  return status ? labels[status.toUpperCase()] ?? status : "未部署";
}

function jobLabel(status: string): string {
  const labels: Record<string, string> = {
    QUEUED: "排队中",
    ADMITTED: "资源已准入",
    STARTING_WORKER: "启动 Worker",
    LOADING_MODEL: "加载模型",
    RUNNING: "生成动作",
    DECODING: "解码输出",
    NORMALIZING: "转换 Motion IR",
    RETARGETING: "重定向骨骼",
    VALIDATING: "校验动作",
    EXPORTING: "导出 VRMA",
    SUCCEEDED: "已完成",
    FAILED: "失败",
    CANCELLED: "已取消",
    TIMED_OUT: "超时",
    REJECTED: "已拒绝",
  };
  return labels[status] ?? status;
}

function availableModels(): ModelManifest[] {
  return realRunnableModels(state.models);
}

function catalogModels(): ModelManifest[] {
  return productionCatalogModels(state.models);
}

function visibleJobs(): JobRecord[] {
  return productionCatalogJobs(state.jobs, state.models);
}

function selectedManifest(): ModelManifest | null {
  return state.models.find((item) => item.model.id === state.selectedModelId) ?? null;
}

function currentInstallationState(manifest: ModelManifest): string | null {
  return state.installationStates[manifest.model.id] ?? installationState(manifest);
}

function modelReady(manifest: ModelManifest): boolean {
  const current = currentInstallationState(manifest);
  if (current != null) return current.toUpperCase() === "READY";
  return isInstalledReady(manifest);
}

function ensureSelectedModel(): void {
  const available = availableModels();
  if (!available.some((item) => item.model.id === state.selectedModelId)) {
    state.selectedModelId = available.find(modelReady)?.model.id ?? available[0]?.model.id ?? "";
  }
  const manifest = selectedManifest();
  if (manifest && !state.drafts[manifest.model.id]) {
    try {
      state.drafts[manifest.model.id] = generationDefaults(manifest);
    } catch {
      state.drafts[manifest.model.id] = { prompt: "", seconds: 4, seed: 42 };
    }
  }
}

function installedExecutionTarget(manifest: ModelManifest | null): ExecutionTargetSelection | null {
  const resolved = manifest?.installation?.execution_target?.resolved;
  if (!resolved) return null;
  return {
    schema_version: "virea.execution_target_selection.v1.0.0",
    execution_domain_id: resolved.execution_domain.id,
    runtime_variant_id: resolved.runtime_variant_id,
    resource_profile_id: resolved.resource_profile_id,
  };
}

function ensureSelectedExecutionDomain(): void {
  const domains = state.executionDomains?.execution_domains ?? [];
  if (domains.some((domain) => domain.id === state.selectedExecutionDomainId)) return;
  const installed = installedExecutionTarget(selectedManifest());
  if (
    !state.executionDomainTouched
    && installed
    && domains.some((domain) => domain.id === installed.execution_domain_id)
  ) {
    state.selectedExecutionDomainId = installed.execution_domain_id;
    return;
  }
  state.selectedExecutionDomainId = domains.length === 1 ? domains[0]!.id : "";
}

function selectedExecutionTarget(): ExecutionTargetSelection {
  if (!state.selectedExecutionDomainId) {
    throw new Error("检测到多个运行环境，请先明确选择一个执行域");
  }
  const installed = installedExecutionTarget(selectedManifest());
  if (installed?.execution_domain_id === state.selectedExecutionDomainId) return installed;
  return {
    schema_version: "virea.execution_target_selection.v1.0.0",
    execution_domain_id: state.selectedExecutionDomainId,
    runtime_variant_id: null,
    resource_profile_id: null,
  };
}

function selectedExecutionOption(modelId: string): ModelExecutionOption | null {
  return state.executionOptions[modelId]?.find(
    (option) => option.execution_domain.id === state.selectedExecutionDomainId,
  ) ?? null;
}

async function loadExecutionOptions(modelId: string, force = false): Promise<void> {
  if (!modelId || (!force && state.executionOptions[modelId])) return;
  const payload = await api.executionOptions(modelId);
  state.executionOptions[modelId] = payload.options;
}

function executionDomainSelector(): string {
  const domains = state.executionDomains?.execution_domains ?? [];
  const placeholder = domains.length > 1 ? '<option value="">选择运行环境</option>' : "";
  return `<label class="domain-control"><span>运行环境</span><select id="global-execution-domain" ${domains.length ? "" : "disabled"}>${placeholder}${domains
    .map((domain) => {
      const label = domain.kind === "wsl"
        ? `WSL · ${domain.distribution ?? domain.id}`
        : `${domain.kind.replace("-native", "")} · ${domain.platform}`;
      return `<option value="${escapeHtml(domain.id)}" ${domain.id === state.selectedExecutionDomainId ? "selected" : ""}>${escapeHtml(label)}</option>`;
    })
    .join("")}</select></label>`;
}

function syncLabel(): string {
  const labels: Record<SyncStatus, string> = {
    connecting: "正在连接",
    live: "实时同步",
    polling: "自动刷新",
    offline: "连接中断",
  };
  return labels[state.syncStatus];
}

function layout(content: string): string {
  const nav: Array<[View, string, string]> = [
    ["playground", "工作台", "生成与预览"],
    ["catalog", "模型", "部署与能力"],
    ["overview", "系统", "环境与诊断"],
  ];
  return `
    <div class="app-shell">
      <header class="topbar">
        <button class="brand" id="brand-home" aria-label="打开 VIREA 工作台">
          <span class="brand-mark"><i></i><i></i><i></i></span>
          <span><strong>VIREA</strong><small>Motion Studio 0.4.0</small></span>
        </button>
        <nav aria-label="主要导航">${nav.map(([id, label, description]) => `
          <button data-view="${id}" class="nav-item ${state.view === id ? "active" : ""}">
            <strong>${label}</strong><small>${description}</small>
          </button>`).join("")}</nav>
        <div class="topbar-tools">
          ${executionDomainSelector()}
          <div class="data-root-pill" id="data-root-indicator" title="${escapeHtml(state.vireaHome ? `当前服务 VIREA_HOME：${state.vireaHome}` : "正在读取当前服务的 VIREA_HOME")}">
            <span>VIREA_HOME</span><code>${escapeHtml(state.vireaHome || "读取中…")}</code>
          </div>
          <div class="sync-pill ${state.syncStatus}" id="sync-status" title="CLI 与 Web 使用同一持久状态">
            <i></i><span>${syncLabel()}</span>
          </div>
        </div>
      </header>
      <main class="page-frame">
        ${state.error ? `<div class="message error" role="alert"><strong>需要处理</strong><span>${escapeHtml(state.error)}</span><button id="dismiss-error" aria-label="关闭错误">关闭</button></div>` : ""}
        ${state.notice ? `<div class="message success" role="status"><strong>已完成</strong><span>${escapeHtml(state.notice)}</span><button id="dismiss-notice" aria-label="关闭提示">关闭</button></div>` : ""}
        ${content}
      </main>
    </div>`;
}

function modelSelectOptions(): string {
  return availableModels().map((item) => {
    const ready = modelReady(item);
    return `<option value="${escapeHtml(item.model.id)}" ${item.model.id === state.selectedModelId ? "selected" : ""}>${escapeHtml(item.model.display_name)} · ${ready ? "READY" : installationLabel(currentInstallationState(item))}</option>`;
  }).join("");
}

function resultFacts(): string {
  const result = state.lastResult;
  if (!result) {
    return `<div class="empty-result"><span>还没有可预览的结果</span><p>完成一次生成后，动作会直接进入右侧舞台，不再跳转页面。</p></div>`;
  }
  const modelResult = state.lastModelResult;
  const identity = result.identity;
  const model = identity?.model_id ?? modelResult?.model.id ?? state.lastGeneration?.modelId ?? "—";
  const frames = modelResult?.native.frame_count ?? "—";
  const duration = modelResult?.native.fps
    ? `${(modelResult.native.frame_count / modelResult.native.fps).toFixed(2)} 秒`
    : "—";
  return `<div class="result-facts">
    <div><small>模型</small><strong>${escapeHtml(model)}</strong></div>
    <div><small>帧数 / 时长</small><strong>${escapeHtml(frames)} / ${escapeHtml(duration)}</strong></div>
    <div><small>动作路径</small><strong>${escapeHtml(resultMotionRoute(result, modelResult))}</strong></div>
    <div><small>重定向前诊断</small><strong>${state.lastSourcePreview ? `${escapeHtml(state.lastSourcePreview.skeleton_id)} · ${state.lastSourcePreview.frame_count} 帧` : "源骨架不可用"}</strong></div>
    <div><small>结果 ID</small><code>${escapeHtml(result.result_id)}</code></div>
  </div>`;
}

function recentActivity(limit = 6): string {
  const jobs = visibleJobs().slice(0, limit);
  if (!jobs.length) return '<p class="quiet-empty">暂无任务。首次生成或模型验收会自动出现在这里。</p>';
  return `<div class="activity-list">${jobs.map((job) => {
    const current = state.activeJob?.id === job.id ? state.activeJob : job;
    const terminal = TERMINAL_JOB_STATES.has(current.state);
    return `<button class="activity-row ${current.state.toLowerCase()}" data-open-job="${escapeHtml(current.id)}" ${current.state === "SUCCEEDED" ? "" : "disabled"}>
      <span class="state-icon"><i></i></span>
      <span class="activity-copy"><strong>${escapeHtml(current.model_id)}</strong><small>${escapeHtml(jobLabel(current.state))}${current.error_message ? ` · ${escapeHtml(current.error_message)}` : ""}</small></span>
      <code>${escapeHtml(current.id.slice(-8))}</code>
      ${terminal ? "" : '<span class="activity-pulse"></span>'}
    </button>`;
  }).join("")}</div>`;
}

function playground(): string {
  ensureSelectedModel();
  const manifest = selectedManifest();
  const draft = manifest ? state.drafts[manifest.model.id]! : { prompt: "", seconds: 4, seed: 42 };
  const ready = manifest ? modelReady(manifest) : false;
  const installState = manifest ? currentInstallationState(manifest) : null;
  const active = state.activeJob && !TERMINAL_JOB_STATES.has(state.activeJob.state)
    ? state.activeJob
    : null;
  const busy = Boolean(active || state.installingModelId);
  const canGenerate = Boolean(manifest && ready && state.selectedExecutionDomainId && !busy);
  return `
    <section class="page-heading compact">
      <div><p class="eyebrow">MOTION CREATION WORKSPACE</p><h1>从文字到可播放动作，在同一个工作台完成</h1>
        <p>模型选择、任务进度、重定向前源骨架与最终 VRM 对照保持在一条连续工作流中。</p></div>
    </section>
    <section class="studio-grid">
      <article class="composer-card surface">
        <div class="section-title"><span>01</span><div><h2>动作生成</h2><p>使用已部署模型创建可追溯结果</p></div></div>
        <label class="field"><span>模型</span><select id="model-id" ${availableModels().length ? "" : "disabled"}>${modelSelectOptions()}</select></label>
        <div class="model-readiness ${ready ? "ready" : "pending"}">
          <div><i></i><span>${manifest ? escapeHtml(manifest.model.display_name) : "没有可执行模型"}</span></div>
          <strong>${ready ? "READY" : installationLabel(installState)}</strong>
        </div>
        ${manifest && !ready ? `<button class="secondary wide" data-install="${escapeHtml(manifest.model.id)}" ${state.installingModelId ? "disabled" : ""}>${state.installingModelId === manifest.model.id ? "正在部署并验收…" : "部署这个模型"}</button>` : ""}
        <label class="field prompt-field"><span>动作描述</span><textarea id="prompt" maxlength="8000" placeholder="例如：A person walks forward, turns left, and waves.">${escapeHtml(draft.prompt)}</textarea><small>写清人物、方向、节奏和动作结束方式。</small></label>
        <div class="parameter-grid">
          <label class="field"><span>时长（秒）</span><input id="seconds" type="number" min="1" max="90" step="0.01" value="${escapeHtml(draft.seconds)}" /></label>
          <label class="field"><span>随机种子</span><input id="seed" type="number" min="0" max="2147483647" step="1" value="${escapeHtml(draft.seed)}" /></label>
        </div>
        <button class="primary generate-button" id="generate" ${canGenerate ? "" : "disabled"}>
          <span>${active ? jobLabel(active.state) : ready ? "生成动作" : "请先完成模型部署"}</span><i>→</i>
        </button>
        ${active ? `<div class="job-progress"><div><span style="--progress:${Math.max(12, Math.min(94, ((active.events?.length ?? 1) / 10) * 100))}%"></span></div><p><strong>${escapeHtml(jobLabel(active.state))}</strong><code>${escapeHtml(active.id)}</code></p></div>` : ""}
        <pre id="generation-output" class="machine-evidence" aria-hidden="true">${escapeHtml(state.generationEvidence)}</pre>
      </article>

      <article class="stage-card">
        <div class="stage-toolbar">
          <div><p class="eyebrow">PRE / POST RETARGET DIAGNOSTICS</p><h2>${state.lastResult ? "最新结果双阶段对照" : "模型骨架与最终 VRM"}</h2></div>
          <div class="stage-actions">
            <label class="file-action"><input id="avatar-file" type="file" accept=".vrm,.glb,model/gltf-binary" /><span>载入 Avatar</span></label>
            <label class="file-action"><input id="vrma-file" type="file" accept=".vrma,model/gltf-binary" /><span>载入 VRMA</span></label>
            <button id="comparison-replay" class="icon-action" title="同时从头播放两个阶段">同步重播</button>
          </div>
        </div>
        <div class="motion-comparison" id="viewer-stage">
          <section class="comparison-panel source-panel">
            <header><span>A</span><div><strong>重定向前 · 模型骨架</strong><small>${escapeHtml(state.lastSourcePreview?.skeleton_id ?? "等待模型原生输出")}</small></div></header>
            <div class="viewer-panel"><canvas id="source-skeleton-canvas" aria-label="模型生成的重定向前骨架动画"></canvas>
              <div class="stage-grid" aria-hidden="true"></div>
              <div class="stage-watermark source"><span>SOURCE</span><small>NO VRM RETARGET</small></div>
              ${state.lastSourcePreview ? "" : '<div class="viewer-empty-state" data-source-empty="true"><strong>没有可播放的源骨架</strong><span>完成一次真实模型生成后，这里才会开始播放；空状态不会创建虚拟动画。</span></div>'}
            </div>
            <div id="source-viewer-status" class="viewer-status ${state.sourceViewerStatus.kind}"><i></i><span>${escapeHtml(state.sourceViewerStatus.message)}${state.sourceViewerStatus.duration == null ? "" : ` · ${state.sourceViewerStatus.duration.toFixed(2)} 秒`}</span></div>
          </section>
          <section class="comparison-panel target-panel">
            <header><span>B</span><div><strong>重定向后 · 最终 VRM</strong><small>${escapeHtml(state.lastResult?.avatar_profile ?? "VRM 1.0 / VRMA")}</small></div></header>
            <div class="viewer-panel"><canvas id="vrm-canvas" aria-label="重定向后的真实 VRM 动画播放器"></canvas>
              <div class="stage-grid" aria-hidden="true"></div>
              <div class="stage-watermark"><span>VIREA</span><small>VRM 1.0 / VRMA</small></div>
            </div>
            <div id="viewer-status" class="viewer-status ${state.viewerStatus.kind}"><i></i><span>${escapeHtml(state.viewerStatus.message)}${state.viewerStatus.duration == null ? "" : ` · ${state.viewerStatus.duration.toFixed(2)} 秒`}</span></div>
          </section>
        </div>
        <div class="viewer-readout">
          <p>左侧只做坐标归一化用于显示，不进入 VRM 骨骼重定向；右侧是同一结果的最终 VRMA，可直接判断问题发生在哪一阶段。</p>
          <div class="result-actions">
            ${state.lastResult ? `<code>${escapeHtml(state.lastResult.result_id)}</code>` : ""}
            ${state.lastVrmaUrl ? `<a href="${escapeHtml(state.lastVrmaUrl)}" download>下载 VRMA</a><button id="open-viewer">定位到预览</button>` : ""}
          </div>
        </div>
      </article>
    </section>
    <section class="studio-bottom-grid">
      <article class="surface result-summary"><div class="section-title small"><span>02</span><div><h2>结果信息</h2><p>始终显示最近一次成功产物</p></div></div>${resultFacts()}</article>
      <article class="surface activity-card"><div class="section-title small"><span>03</span><div><h2>实时活动</h2><p>CLI、安装验收和 Web 任务共用同一状态</p></div></div>${recentActivity()}</article>
    </section>`;
}

function catalog(): string {
  const models = catalogModels();
  return `
    <section class="page-heading">
      <div><p class="eyebrow">MODEL LIBRARY</p><h1>模型能力与部署</h1><p>一个模型可在多个系统执行；这里展示的是当前数据根中的真实部署状态。</p></div>
      <div class="heading-metric"><strong>${models.filter(modelReady).length}</strong><span>READY / ${models.length}</span></div>
    </section>
    <section class="model-library surface">
      <div class="library-header"><span>模型</span><span>转换路径</span><span>当前状态</span><span>操作</span></div>
      ${models.length ? models.map((item) => {
        const ready = modelReady(item);
        const installState = currentInstallationState(item);
        const installable = realRunnableModels([item]).length === 1 && item.production_acceptance != null;
        const option = selectedExecutionOption(item.model.id);
        const runtime = item.runtime_variants.find((candidate) => candidate.id === option?.selected_runtime_id);
        const latestAttempt = item.installation?.latest_attempt?.state;
        return `<article class="model-row">
          <div class="model-identity"><span class="model-monogram">${escapeHtml(item.model.display_name.slice(0, 1))}</span><div><h2>${escapeHtml(item.model.display_name)}</h2><code>${escapeHtml(item.model.id)}</code><p>${escapeHtml(item.model.adapter_family)}</p></div></div>
          <div class="model-route"><strong>${escapeHtml(item.output.skeleton_id)}</strong><i>→</i><strong>${escapeHtml(item.result_target.skeleton_id)}</strong><small>${escapeHtml(item.model.tasks.join(" · "))}</small></div>
          <div class="model-state"><span class="state-badge ${ready ? "ready" : (installState ?? "idle").toLowerCase()}"><i></i>${ready ? "READY" : installationLabel(installState)}</span><small>${latestAttempt && latestAttempt !== installState ? `最近尝试：${installationLabel(latestAttempt)}` : statusLabel(item.model.status)}</small><small>${option ? `${option.selected_runtime_id ?? "未实现"} · ${option.selected_resource_profile ?? "无 profile"}${runtime?.runtime_core_epoch ? ` · ${runtime.runtime_core_epoch}` : ""}` : "选择环境后自动核验 Runtime"}</small></div>
          <div class="model-action">${ready ? `<button data-use-model="${escapeHtml(item.model.id)}">在工作台使用</button>` : `<button data-install="${escapeHtml(item.model.id)}" ${!installable || !state.selectedExecutionDomainId || state.installingModelId ? "disabled" : ""}>${state.installingModelId === item.model.id ? "部署中…" : installable ? "部署并验收" : "暂不可部署"}</button>`}</div>
        </article>`;
      }).join("") : '<p class="quiet-empty padded">服务没有返回模型目录，请检查项目资源。</p>'}
    </section>`;
}

function systemFacts(): { system: Record<string, unknown>; machine: Record<string, unknown> } {
  const system = (state.system ?? state.health ?? {}) as Record<string, unknown>;
  const machine = (system.machine ?? {}) as Record<string, unknown>;
  return { system, machine };
}

function overview(): string {
  const { system, machine } = systemFacts();
  const domains = state.executionDomains?.execution_domains ?? [];
  return `
    <section class="page-heading">
      <div><p class="eyebrow">LOCAL CONTROL PLANE</p><h1>系统、数据与诊断</h1><p>快速状态保持轻量；完整硬件检测只在你明确点击时运行。</p></div>
      <button class="primary compact-button" id="refresh" ${state.systemLoading ? "disabled" : ""}>${state.systemLoading ? "正在检测…" : "运行完整检测"}</button>
    </section>
    <section class="system-metrics">
      <article class="surface"><small>控制面</small><strong>${state.health?.status === "ready" ? "在线" : "连接中"}</strong><span>${escapeHtml(state.health?.version ?? "—")}</span></article>
      <article class="surface"><small>可用执行域</small><strong>${domains.length}</strong><span>${escapeHtml(domains.map((item) => item.kind).join(" · ") || "尚未检测")}</span></article>
      <article class="surface"><small>READY 模型</small><strong>${availableModels().filter(modelReady).length}</strong><span>共 ${availableModels().length} 个可执行模型</span></article>
      <article class="surface"><small>活动 Worker</small><strong>${escapeHtml(system.active_workers ?? 0)}</strong><span>${escapeHtml(machine.platform ?? "等待完整检测")}</span></article>
    </section>
    <section class="system-grid">
      <article class="surface data-root-card"><div class="section-title small"><span>A</span><div><h2>持久数据根</h2><p>模型、Runtime、任务与结果都以这里为根</p></div></div><code class="path-display">${escapeHtml(state.vireaHome || system.virea_home || "正在读取当前 VIREA_HOME")}</code>
        <div class="button-row"><button id="setup-plan">查看初始化计划</button><button id="setup-apply">核验目录结构</button></div><pre id="setup-output" class="diagnostic-output"></pre></article>
      <article class="surface domain-card"><div class="section-title small"><span>B</span><div><h2>执行域</h2><p>Web 与 CLI 共享选择和部署身份</p></div></div><div class="domain-list">${domains.map((domain) => `<div class="domain-row ${domain.id === state.selectedExecutionDomainId ? "selected" : ""}"><i></i><div><strong>${escapeHtml(domain.kind === "wsl" ? `WSL · ${domain.distribution}` : domain.kind)}</strong><small>${escapeHtml(domain.platform)} · ${escapeHtml(domain.architecture)}</small></div><span>${domain.id === state.selectedExecutionDomainId ? "当前" : domain.is_host ? "宿主" : "可用"}</span></div>`).join("") || '<p class="quiet-empty">尚未取得执行域报告。</p>'}</div></article>
      <article class="surface diagnostics-card"><div class="section-title small"><span>C</span><div><h2>安全诊断</h2><p>生成脱敏的本地支持包</p></div></div><p>支持包不会收集 prompt、token、原始音频、Avatar 或模型权重。</p><button id="support">生成 Support Bundle</button><pre id="support-output" class="diagnostic-output"></pre></article>
      <article class="surface all-activity"><div class="section-title small"><span>D</span><div><h2>最近任务</h2><p>持久数据库中的最新活动</p></div></div>${recentActivity(8)}</article>
    </section>`;
}

interface FocusSnapshot {
  id: string;
  start: number | null;
  end: number | null;
}

function focusedControl(): FocusSnapshot | null {
  const node = document.activeElement;
  if (!(node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement || node instanceof HTMLSelectElement)) {
    return null;
  }
  return {
    id: node.id,
    start: "selectionStart" in node ? node.selectionStart : null,
    end: "selectionEnd" in node ? node.selectionEnd : null,
  };
}

function restoreFocus(snapshot: FocusSnapshot | null): void {
  if (!snapshot) return;
  const node = document.getElementById(snapshot.id);
  if (!(node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement || node instanceof HTMLSelectElement)) return;
  node.focus({ preventScroll: true });
  if (
    (node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement)
    && snapshot.start != null
    && snapshot.end != null
  ) {
    node.setSelectionRange(snapshot.start, snapshot.end);
  }
}

function render(): void {
  const focus = focusedControl();
  if (viewerCanvas?.isConnected) viewerCanvas.remove();
  if (sourceViewerCanvas?.isConnected) sourceViewerCanvas.remove();
  const content = {
    playground: playground(),
    catalog: catalog(),
    overview: overview(),
  }[state.view];
  app.innerHTML = layout(content);
  bind();
  viewerRuntime?.setActive(state.view === "playground");
  sourceViewerRuntime?.setActive(state.view === "playground");
  restoreFocus(focus);
}

function output(id: string, value: unknown): void {
  const node = document.querySelector<HTMLElement>(`#${id}`);
  if (node) node.textContent = JSON.stringify(value, null, 2);
}

function setView(view: View): void {
  state.view = view;
  state.error = "";
  state.notice = "";
  render();
}

function bindDraftInputs(): void {
  const manifest = selectedManifest();
  if (!manifest) return;
  const draft = state.drafts[manifest.model.id]!;
  document.querySelector<HTMLTextAreaElement>("#prompt")?.addEventListener("input", (event) => {
    draft.prompt = (event.currentTarget as HTMLTextAreaElement).value;
  });
  document.querySelector<HTMLInputElement>("#seconds")?.addEventListener("input", (event) => {
    draft.seconds = Number((event.currentTarget as HTMLInputElement).value);
  });
  document.querySelector<HTMLInputElement>("#seed")?.addEventListener("input", (event) => {
    draft.seed = Number((event.currentTarget as HTMLInputElement).value);
  });
}

function bind(): void {
  document.querySelector("#brand-home")?.addEventListener("click", () => setView("playground"));
  document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view as View));
  });
  document.querySelector("#dismiss-error")?.addEventListener("click", () => {
    state.error = "";
    render();
  });
  document.querySelector("#dismiss-notice")?.addEventListener("click", () => {
    state.notice = "";
    render();
  });
  document.querySelector<HTMLSelectElement>("#global-execution-domain")?.addEventListener("change", (event) => {
    state.selectedExecutionDomainId = (event.currentTarget as HTMLSelectElement).value;
    state.executionDomainTouched = true;
    state.executionOptions = {};
    state.error = "";
    render();
  });
  document.querySelector<HTMLSelectElement>("#model-id")?.addEventListener("change", (event) => {
    state.selectedModelId = (event.currentTarget as HTMLSelectElement).value;
    ensureSelectedModel();
    ensureSelectedExecutionDomain();
    state.error = "";
    void loadExecutionOptions(state.selectedModelId).catch((error: unknown) => {
      state.error = errorMessage(error);
      render();
    });
    render();
  });
  bindDraftInputs();
  document.querySelectorAll<HTMLButtonElement>("[data-install]").forEach((button) => {
    button.addEventListener("click", () => void installModel(button));
  });
  document.querySelectorAll<HTMLButtonElement>("[data-use-model]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedModelId = button.dataset.useModel ?? state.selectedModelId;
      ensureSelectedModel();
      ensureSelectedExecutionDomain();
      setView("playground");
    });
  });
  document.querySelectorAll<HTMLButtonElement>("[data-open-job]").forEach((button) => {
    button.addEventListener("click", () => void openJob(button.dataset.openJob ?? ""));
  });
  document.querySelector("#generate")?.addEventListener("click", () => void generate());
  document.querySelector("#refresh")?.addEventListener("click", () => void refreshSystem());
  document.querySelector("#setup-plan")?.addEventListener("click", () => void runOutput("setup-output", api.setupPlan));
  document.querySelector("#setup-apply")?.addEventListener("click", () => void runOutput("setup-output", api.setupApply));
  document.querySelector("#support")?.addEventListener("click", () => void runOutput("support-output", api.supportBundle));
  document.querySelector("#open-viewer")?.addEventListener("click", () => {
    document.querySelector("#viewer-stage")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  if (state.view === "playground") {
    bindSourceViewer();
    bindViewer();
  }
}

async function runOutput(id: string, action: () => Promise<unknown>): Promise<void> {
  try {
    output(id, await action());
  } catch (error) {
    state.error = errorMessage(error);
    render();
  }
}

function publishViewerStatus(status: ViewerStatus): void {
  state.viewerStatus = status;
  const node = document.querySelector<HTMLElement>("#viewer-status");
  if (!node) return;
  node.className = `viewer-status ${status.kind}`;
  const message = node.querySelector("span");
  if (message) {
    message.textContent = status.duration == null
      ? status.message
      : `${status.message} · ${status.duration.toFixed(2)} 秒`;
  }
}

function publishSourceViewerStatus(status: SourceViewerStatus): void {
  state.sourceViewerStatus = status;
  const node = document.querySelector<HTMLElement>("#source-viewer-status");
  if (!node) return;
  node.className = `viewer-status ${status.kind}`;
  const message = node.querySelector("span");
  if (message) {
    message.textContent = status.duration == null
      ? status.message
      : `${status.message} · ${status.duration.toFixed(2)} 秒`;
  }
}

function bindSourceViewer(): void {
  const placeholder = document.querySelector<HTMLCanvasElement>("#source-skeleton-canvas");
  if (!placeholder) return;
  if (sourceViewerCanvas) {
    placeholder.replaceWith(sourceViewerCanvas);
  } else if (state.lastSourcePreview) {
    sourceViewerCanvas = placeholder;
    sourceViewerRuntime = new SourceSkeletonViewer(
      sourceViewerCanvas,
      publishSourceViewerStatus,
    );
  } else {
    placeholder.dataset.viewerState = "idle";
    placeholder.dataset.sourceFrame = "0";
    return;
  }
  sourceViewerRuntime?.setActive(true);
  if (!state.lastSourcePreview && sourceViewerLoadedResultId) {
    sourceViewerRuntime?.clear("当前数据根没有可播放的生产源骨架");
    sourceViewerLoadedResultId = "";
  }
  if (
    state.lastSourcePreview
    && sourceViewerLoadedResultId !== state.lastSourcePreview.result_id
  ) {
    try {
      sourceViewerRuntime?.load(state.lastSourcePreview);
      sourceViewerLoadedResultId = state.lastSourcePreview.result_id;
    } catch (error) {
      publishSourceViewerStatus({ kind: "error", message: errorMessage(error) });
    }
  }
}

function bindViewer(): void {
  const placeholder = document.querySelector<HTMLCanvasElement>("#vrm-canvas");
  if (!placeholder) return;
  if (viewerCanvas) {
    placeholder.replaceWith(viewerCanvas);
  } else {
    viewerCanvas = placeholder;
    viewerRuntime = new RealVrmViewer(viewerCanvas, publishViewerStatus);
  }
  viewerRuntime?.setActive(true);
  const handle = async (action: () => Promise<void> | void): Promise<void> => {
    try {
      await action();
    } catch (error) {
      publishViewerStatus({ kind: "error", message: errorMessage(error) });
    }
  };
  document.querySelector<HTMLInputElement>("#avatar-file")?.addEventListener("change", (event) => {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (file) void handle(() => viewerRuntime?.loadAvatarFile(file));
  });
  document.querySelector<HTMLInputElement>("#vrma-file")?.addEventListener("change", (event) => {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (file) void handle(() => viewerRuntime?.loadAnimationFile(file));
  });
  document.querySelector("#comparison-replay")?.addEventListener("click", () => {
    if (state.lastSourcePreview) {
      try {
        sourceViewerRuntime?.replay();
      } catch (error) {
        publishSourceViewerStatus({ kind: "error", message: errorMessage(error) });
      }
    }
    if (state.lastVrmaUrl) void handle(() => viewerRuntime?.play());
  });
  if (state.lastVrmaUrl && viewerLoadedVrmaUrl !== state.lastVrmaUrl) {
    const requestedUrl = state.lastVrmaUrl;
    void handle(async () => {
      await viewerRuntime?.loadAnimation(requestedUrl);
      viewerLoadedVrmaUrl = requestedUrl;
    });
  }
}

async function installModel(button: HTMLButtonElement): Promise<void> {
  const id = button.dataset.install;
  if (!id || state.installingModelId) return;
  state.installingModelId = id;
  state.selectedModelId = id;
  state.error = "";
  state.notice = "";
  render();
  try {
    const manifest = state.models.find((item) => item.model.id === id);
    if (!manifest) throw new Error(`模型目录中不存在 ${id}`);
    const target = selectedExecutionTarget();
    await loadExecutionOptions(id, true);
    const option = selectedExecutionOption(id);
    if (!option?.implemented || !option.can_build) {
      throw new Error(option?.reasons.join("; ") || `${id} 尚未在 ${target.execution_domain_id} 实现可部署 Runtime`);
    }
    const result = await api.install(manifest, target);
    if (typeof result.state === "string") state.installationStates[id] = result.state;
    state.notice = result.state === "READY"
      ? `${manifest.model.display_name} 已完成部署与真实验收。`
      : `${manifest.model.display_name} 返回状态 ${String(result.state ?? "UNKNOWN")}。`;
    await synchronizePersistentState();
  } catch (error) {
    state.error = errorMessage(error);
  } finally {
    state.installingModelId = "";
    render();
  }
}

async function refreshSystem(): Promise<void> {
  state.systemLoading = true;
  state.error = "";
  state.executionOptions = {};
  render();
  const previousExecutionDomainId = state.selectedExecutionDomainId;
  const [systemResult, domainResult] = await Promise.allSettled([api.system(), api.executionDomains()]);
  if (systemResult.status === "fulfilled") state.system = systemResult.value;
  if (domainResult.status === "fulfilled") {
    state.executionDomains = domainResult.value;
    state.selectedExecutionDomainId = previousExecutionDomainId;
    ensureSelectedExecutionDomain();
  } else {
    state.executionDomains = null;
    state.selectedExecutionDomainId = "";
  }
  const failure = [systemResult, domainResult].find((item) => item.status === "rejected");
  state.error = failure?.status === "rejected" ? errorMessage(failure.reason) : "";
  state.systemLoading = false;
  render();
}

function upsertJob(job: JobRecord): void {
  state.jobs = [job, ...state.jobs.filter((item) => item.id !== job.id)];
  state.activeJob = job;
}

async function generate(): Promise<void> {
  const manifest = selectedManifest();
  if (!manifest) return;
  const draft = state.drafts[manifest.model.id]!;
  state.error = "";
  state.notice = "";
  try {
    const target = selectedExecutionTarget();
    await loadExecutionOptions(manifest.model.id);
    const option = selectedExecutionOption(manifest.model.id);
    if (!option?.implemented || !option.can_build) {
      throw new Error(option?.reasons.join("; ") || `${manifest.model.id} 尚未在 ${target.execution_domain_id} 实现可运行 Runtime`);
    }
    let job = await api.generate(manifest, draft.prompt, draft.seconds, draft.seed, target);
    upsertJob(job);
    render();
    while (!TERMINAL_JOB_STATES.has(job.state)) {
      await new Promise((resolve) => window.setTimeout(resolve, 750));
      job = await api.job(job.id);
      upsertJob(job);
      render();
    }
    if (job.state !== "SUCCEEDED") {
      throw new Error(`${job.state}: ${job.error_code ?? "GENERATION_FAILED"} ${job.error_message ?? ""}`.trim());
    }
    await loadPersistedSuccessfulJob(job.id);
    state.lastGeneration = { modelId: manifest.model.id, seconds: draft.seconds, seed: draft.seed };
    state.notice = "动作已经生成，并载入重定向前 / 重定向后的双阶段 Viewer。";
    state.generationEvidence = JSON.stringify({
      job,
      model_result: state.lastModelResult,
      result: state.lastResult,
      source_skeleton: state.lastSourcePreview ? {
        stage: state.lastSourcePreview.stage,
        representation_id: state.lastSourcePreview.representation_id,
        skeleton_id: state.lastSourcePreview.skeleton_id,
        frame_count: state.lastSourcePreview.frame_count,
      } : null,
      vrma_url: state.lastVrmaUrl,
    }, null, 2);
  } catch (error) {
    state.error = errorMessage(error);
    state.generationEvidence = JSON.stringify({ error: state.error }, null, 2);
  } finally {
    render();
  }
}

async function loadPersistedSuccessfulJob(jobId: string): Promise<void> {
  const job = await api.job(jobId);
  if (job.state !== "SUCCEEDED") throw new Error(`${jobId} 不是 SUCCEEDED，不能载入结果`);
  if (!catalogModels().some((manifest) => manifest.model.id === job.model_id)) {
    throw new Error(`${jobId} 不属于当前生产模型目录，已拒绝载入测试或未知结果`);
  }
  const result = await api.result(jobId);
  if (result.job_id !== jobId) throw new Error("持久化结果与 Job ID 不一致");
  const vrma = firstVrmaExport(result);
  const modelResultLocator = result.tracks.model_result;
  if (!modelResultLocator) throw new Error("持久化结果缺少 ModelResult track");
  const modelResult = await api.modelResultArtifact(result.result_id, modelResultLocator);
  if (modelResult.job_id !== jobId || modelResult.model.id !== job.model_id) {
    throw new Error("持久化 ModelResult 与 Job 绑定不一致");
  }
  let sourcePreview: SourceSkeletonPreview | null = null;
  sourcePreviewAttemptedResultId = result.result_id;
  try {
    sourcePreview = await api.sourceSkeleton(result.result_id);
    if (
      sourcePreview.result_id !== result.result_id
      || sourcePreview.job_id !== jobId
      || sourcePreview.stage !== "model_output_pre_retarget"
      || sourcePreview.display_transform.vrm_retarget_applied !== false
    ) {
      throw new Error("重定向前骨架与当前结果绑定不一致");
    }
  } catch (error) {
    sourceViewerRuntime?.clear();
    sourceViewerLoadedResultId = result.result_id;
    state.sourceViewerStatus = {
      kind: "error",
      message: `无法载入重定向前骨架：${errorMessage(error)}`,
    };
  }
  state.selectedModelId = job.model_id;
  ensureSelectedModel();
  state.lastResult = result;
  state.lastModelResult = modelResult;
  state.lastSourcePreview = sourcePreview;
  if (sourcePreview) sourceViewerLoadedResultId = "";
  state.lastVrmaUrl = artifactUrl(result.result_id, vrma.locator);
  state.lastGeneration = {
    modelId: job.model_id,
    seconds: modelResult.native.fps ? modelResult.native.frame_count / modelResult.native.fps : 0,
    seed: 0,
  };
  upsertJob(job);
  state.view = "playground";
}

async function openJob(jobId: string): Promise<void> {
  if (!jobId) return;
  try {
    await loadPersistedSuccessfulJob(jobId);
    state.error = "";
    render();
  } catch (error) {
    state.error = errorMessage(error);
    render();
  }
}

async function hydrateLatestSuccessfulResult(): Promise<void> {
  const latest = visibleJobs().find((job) => job.state === "SUCCEEDED");
  if (!latest) {
    if (state.lastResult) clearPersistedResult("当前数据根没有可播放的生产源骨架");
    return;
  }
  if (
    (
      state.lastResult?.job_id === latest.id
      && sourcePreviewAttemptedResultId === state.lastResult.result_id
    )
  ) return;
  try {
    await loadPersistedSuccessfulJob(latest.id);
  } catch {
    // A terminal job row and its immutable result commit can be observed on
    // adjacent refreshes. The next revision/poll retries without a false alert.
  }
}

function clearPersistedResult(sourceMessage: string): void {
  state.lastResult = null;
  state.lastModelResult = null;
  state.lastSourcePreview = null;
  state.lastVrmaUrl = "";
  state.lastGeneration = null;
  state.generationEvidence = "";
  sourcePreviewAttemptedResultId = "";
  sourceViewerLoadedResultId = "";
  viewerLoadedVrmaUrl = "";
  sourceViewerRuntime?.clear(sourceMessage);
  viewerRuntime?.clearAnimation();
  state.sourceViewerStatus = { kind: "idle", message: sourceMessage };
  state.viewerStatus = { kind: "idle", message: "载入 Avatar 后即可预览生成动作" };
}

function applyStateRevision(payload: StateRevision): void {
  const nextHome = payload.virea_home;
  if (state.vireaHome && nextHome && state.vireaHome !== nextHome) {
    clearPersistedResult("数据根已经切换；等待当前数据根中的真实生成结果");
  }
  state.vireaHome = nextHome;
  state.lastSyncedAt = payload.observed_at;
}

function revisionKey(payload: StateRevision): string {
  return JSON.stringify({ virea_home: payload.virea_home, revision: payload.revision });
}

function updateSyncBadge(): void {
  const node = document.querySelector<HTMLElement>("#sync-status");
  if (!node) return;
  node.className = `sync-pill ${state.syncStatus}`;
  const label = node.querySelector("span");
  if (label) label.textContent = syncLabel();
  node.title = state.lastSyncedAt
    ? `CLI 与 Web 使用 ${state.vireaHome || "当前"} 的同一持久状态 · 最近同步 ${new Date(state.lastSyncedAt).toLocaleTimeString()}`
    : "CLI 与 Web 使用同一持久状态";
}

async function synchronizePersistentState(): Promise<void> {
  if (syncInFlight) {
    syncQueued = true;
    return syncInFlight;
  }
  syncInFlight = (async () => {
    const [modelsResult, jobsResult] = await Promise.allSettled([api.models(), api.jobs()]);
    if (modelsResult.status === "fulfilled") state.models = modelsResult.value;
    if (jobsResult.status === "fulfilled") state.jobs = jobsResult.value;
    if (state.activeJob) {
      const refreshed = visibleJobs().find((job) => job.id === state.activeJob?.id);
      if (refreshed) state.activeJob = refreshed;
    }
    ensureSelectedModel();
    ensureSelectedExecutionDomain();
    await hydrateLatestSuccessfulResult();
    state.lastSyncedAt = new Date().toISOString();
    render();
  })().finally(() => {
    syncInFlight = null;
    if (syncQueued) {
      syncQueued = false;
      void synchronizePersistentState();
    }
  });
  return syncInFlight;
}

function connectStateStream(): void {
  if (
    stateSocket
    && (stateSocket.readyState === WebSocket.CONNECTING || stateSocket.readyState === WebSocket.OPEN)
  ) return;
  state.syncStatus = "connecting";
  updateSyncBadge();
  const socket = new WebSocket(stateEventsUrl());
  stateSocket = socket;
  socket.addEventListener("open", () => {
    if (stateSocket !== socket) return;
    stateStreamRetryAt = 0;
    state.syncStatus = "live";
    updateSyncBadge();
  });
  socket.addEventListener("message", (event) => {
    try {
      const payload = JSON.parse(String(event.data)) as StateRevision;
      const key = revisionKey(payload);
      applyStateRevision(payload);
      if (key !== stateRevisionKey) {
        stateRevisionKey = key;
        void synchronizePersistentState();
      } else {
        updateSyncBadge();
      }
    } catch {
      socket.close();
    }
  });
  socket.addEventListener("close", () => {
    if (stateSocket !== socket) return;
    stateSocket = null;
    stateStreamRetryAt = Date.now() + 30_000;
    state.syncStatus = "polling";
    updateSyncBadge();
  });
  socket.addEventListener("error", () => socket.close());
}

async function pollStateRevision(): Promise<void> {
  if (stateSocket?.readyState === WebSocket.OPEN) {
    updateSyncBadge();
    return;
  }
  try {
    const payload = await api.stateRevision();
    const key = revisionKey(payload);
    applyStateRevision(payload);
    if (key !== stateRevisionKey) {
      stateRevisionKey = key;
      await synchronizePersistentState();
    }
    if (!stateSocket && payload.events_url && Date.now() >= stateStreamRetryAt) connectStateStream();
    else updateSyncBadge();
  } catch {
    state.syncStatus = "offline";
    updateSyncBadge();
  }
}

async function bootstrap(): Promise<void> {
  const [healthResult, stateResult, domainResult, modelResult, jobResult] = await Promise.allSettled([
    api.health(),
    api.stateRevision(),
    api.executionDomains(),
    api.models(),
    api.jobs(),
  ]);
  if (healthResult.status === "fulfilled") state.health = healthResult.value;
  if (stateResult.status === "fulfilled") {
    applyStateRevision(stateResult.value);
    stateRevisionKey = revisionKey(stateResult.value);
  }
  if (domainResult.status === "fulfilled") state.executionDomains = domainResult.value;
  if (modelResult.status === "fulfilled") state.models = modelResult.value;
  if (jobResult.status === "fulfilled") state.jobs = jobResult.value;
  ensureSelectedModel();
  ensureSelectedExecutionDomain();
  const failure = [healthResult, stateResult, domainResult, modelResult, jobResult].find((item) => item.status === "rejected");
  if (failure?.status === "rejected") state.error = errorMessage(failure.reason);
  const persistedJobId = new URLSearchParams(window.location.search).get("job");
  if (persistedJobId) {
    try {
      await loadPersistedSuccessfulJob(persistedJobId);
      state.error = "";
    } catch (error) {
      state.error = errorMessage(error);
    }
  } else {
    await hydrateLatestSuccessfulResult();
  }
  render();
  void pollStateRevision();
}

window.setInterval(() => void pollStateRevision(), STATE_POLL_INTERVAL_MS);
window.addEventListener("focus", () => void pollStateRevision());
window.addEventListener("online", () => void pollStateRevision());
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") void pollStateRevision();
});
window.addEventListener("pagehide", () => {
  stateSocket?.close();
  stateSocket = null;
  sourceViewerRuntime?.dispose();
  sourceViewerRuntime = null;
  viewerRuntime?.dispose();
  viewerRuntime = null;
});
void bootstrap();

export { escapeHtml, statusLabel };
