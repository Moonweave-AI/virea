import "./styles.css";
import {
  api,
  jobEventsUrl,
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
  isInstallationIntegrityDeferred,
  isVireaIntegratedModel,
  modelCapabilityLabel,
  modelMotionRoute,
  productionCatalogModels,
  productionCatalogJobs,
  resultMotionRoute,
  vireaIntegratedModels,
} from "./domain";
import { RealVrmViewer, type ViewerStatus } from "./viewer";
import { SourceSkeletonViewer, type SourceViewerStatus } from "./source-viewer";
import {
  retainOrCreateSubmissionAttempt,
  submissionAttemptWasPersisted,
  submissionFingerprint,
  type PendingSubmissionAttempt,
} from "./submission";

type View = "playground" | "catalog" | "overview";
type SyncStatus = "connecting" | "live" | "polling" | "degraded" | "offline";
type GenerationPhase = "idle" | "validating" | "submitting" | "tracking" | "loading_result";
type Draft = { prompt: string; seconds: number; seed: number };
type JobEvent = NonNullable<JobRecord["events"]>[number];

const TERMINAL_JOB_STATES = new Set([
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "TIMED_OUT",
  "REJECTED",
]);
const STATE_POLL_INTERVAL_MS = 4_000;
const JOB_STREAM_STALL_MS = 10_000;
const PENDING_SUBMISSION_STORAGE_KEY = "virea.pending-generation.v1";

const state: {
  view: View;
  models: ModelManifest[];
  jobs: JobRecord[];
  health: HealthStatus | null;
  vireaHome: string;
  vireaHomeAuthorityFresh: boolean;
  system: Record<string, unknown> | null;
  systemLoading: boolean;
  executionDomains: ExecutionDomainCandidates | null;
  executionOptions: Record<string, ModelExecutionOption[]>;
  selectedExecutionDomainId: string;
  executionDomainTouched: boolean;
  selectedModelId: string;
  drafts: Record<string, Draft>;
  installingModelId: string;
  activeJob: JobRecord | null;
  lastResult: VrmMotionResult | null;
  lastModelResult: ModelResult | null;
  lastSourcePreview: SourceSkeletonPreview | null;
  lastVrmaUrl: string;
  lastGeneration: { modelId: string; seconds: number; seed: number } | null;
  generationEvidence: string;
  generationPhase: GenerationPhase;
  generationMessage: string;
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
  vireaHomeAuthorityFresh: false,
  system: null,
  systemLoading: false,
  executionDomains: null,
  executionOptions: {},
  selectedExecutionDomainId: "",
  executionDomainTouched: false,
  selectedModelId: "",
  drafts: {},
  installingModelId: "",
  activeJob: null,
  lastResult: null,
  lastModelResult: null,
  lastSourcePreview: null,
  lastVrmaUrl: "",
  lastGeneration: null,
  generationEvidence: "",
  generationPhase: "idle",
  generationMessage: "",
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
let sourcePreviewRetryResultId = "";
let sourcePreviewRetryCount = 0;
let sourcePreviewRetryTimer: number | null = null;
let resultLoadEpoch = 0;
let resultLoadJobId = "";
let resultLoadPromise: Promise<void> | null = null;
let stateSocket: WebSocket | null = null;
let jobSocket: WebSocket | null = null;
let stateStreamRetryAt = 0;
let stateRevisionKey = "";
let syncInFlight: Promise<void> | null = null;
let lastRevision: StateRevision["revision"] | null = null;
let pendingRevisionPayload: PendingRevisionObservation | null = null;
let syncRetryTimer: number | null = null;
let syncFailureCount = 0;
let syncRetryDelayMs = 0;
let syncFailureMessage = "";
let resumedJobId = "";
let pendingSubmissionAttempt = loadPendingSubmissionAttempt();
let stateAuthorityRequestEpoch = 0;
let stateAuthorityReconciliationHome = "";
let stateAuthorityReconciliationEpoch = 0;
let stateAuthorityLastSuccessfulEpoch = 0;
let stateAuthorityLastFailureEpoch = 0;

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

function hasFreshVireaHomeAuthority(): boolean {
  return state.vireaHomeAuthorityFresh && Boolean(state.vireaHome.trim());
}

function invalidateVireaHomeAuthority(): void {
  state.vireaHomeAuthorityFresh = false;
  renderLiveRegions();
}

function loadPendingSubmissionAttempt(): PendingSubmissionAttempt | null {
  try {
    const payload = JSON.parse(
      window.localStorage.getItem(PENDING_SUBMISSION_STORAGE_KEY) ?? "null",
    ) as Partial<PendingSubmissionAttempt> | null;
    if (
      payload
      && typeof payload.fingerprint === "string"
      && typeof payload.idempotencyKey === "string"
      && typeof payload.createdAt === "string"
    ) {
      return payload as PendingSubmissionAttempt;
    }
  } catch {
    // Storage can be disabled or contain a value from an interrupted upgrade.
  }
  return null;
}

function persistPendingSubmissionAttempt(attempt: PendingSubmissionAttempt | null): void {
  pendingSubmissionAttempt = attempt;
  try {
    if (attempt) {
      window.localStorage.setItem(PENDING_SUBMISSION_STORAGE_KEY, JSON.stringify(attempt));
    } else {
      window.localStorage.removeItem(PENDING_SUBMISSION_STORAGE_KEY);
    }
  } catch {
    // The in-memory identity still protects retries in this page session.
  }
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

function capabilityReason(manifest: ModelManifest): string {
  const labels: Record<string, string> = {
    UPSTREAM_BLOCKED: "上游状态阻塞 / Upstream blocked",
    UPSTREAM_NOT_RUNNABLE: "上游尚不可运行 / Upstream not runnable",
    VIREA_ADAPTER_NOT_INTEGRATED: "缺少 VIREA adapter / Adapter not integrated",
    VIREA_RUNTIME_NOT_INTEGRATED: "缺少 VIREA Runtime / Runtime not integrated",
    VIREA_ACCEPTANCE_NOT_DECLARED: "缺少生产验收合同 / Production acceptance missing",
  };
  const reasons = manifest.capability?.reasons ?? [];
  return reasons.map((reason) => labels[reason] ?? reason).join(" · ")
    || "缺少 VIREA Runtime、Worker 或真实端到端验收 / Integration incomplete";
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
  return catalogModels();
}

function integratedModels(): ModelManifest[] {
  return vireaIntegratedModels(state.models);
}

function catalogModels(): ModelManifest[] {
  return productionCatalogModels(state.models);
}

function visibleJobs(): JobRecord[] {
  return productionCatalogJobs(state.jobs, state.models);
}

function reconcileActiveJob(): JobRecord | null {
  const currentId = state.activeJob?.id;
  const current = currentId ? visibleJobs().find((job) => job.id === currentId) : null;
  const active = current && !TERMINAL_JOB_STATES.has(current.state)
    ? current
    : visibleJobs().find((job) => !TERMINAL_JOB_STATES.has(job.state)) ?? null;
  if (active) state.activeJob = active;
  else if (current) state.activeJob = current;
  else state.activeJob = null;
  return active;
}

function selectedManifest(): ModelManifest | null {
  return state.models.find((item) => item.model.id === state.selectedModelId) ?? null;
}

function currentInstallationState(manifest: ModelManifest): string | null {
  return installationState(manifest);
}

function modelReady(manifest: ModelManifest): boolean {
  const current = currentInstallationState(manifest);
  if (current != null) return current.toUpperCase() === "READY";
  return isInstalledReady(manifest);
}

function modelReadyBadge(manifest: ModelManifest): string {
  if (!modelReady(manifest)) return installationLabel(currentInstallationState(manifest));
  return isInstallationIntegrityDeferred(manifest) ? "PERSISTED READY" : "READY";
}

function modelIntegrityNote(manifest: ModelManifest): string {
  if (isInstallationIntegrityDeferred(manifest)) {
    return "持久状态与当前目录匹配；启动 Worker 前会完整复验模型字节。 / Metadata matched; bytes are fully reverified before execution.";
  }
  if (manifest.installation?.integrity_verified === true) {
    return "本次响应完成了完整字节复验。 / This response completed full byte-integrity verification.";
  }
  return "旧版状态未声明校验范围；执行仍会完整复验。 / Legacy state has no declared scope; execution still re-verifies.";
}

function ensureSelectedModel(): void {
  const available = availableModels();
  if (!available.some((item) => item.model.id === state.selectedModelId)) {
    const integrated = integratedModels();
    state.selectedModelId = integrated.find(modelReady)?.model.id
      ?? integrated[0]?.model.id
      ?? available[0]?.model.id
      ?? "";
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
    degraded: syncRetryDelayMs
      ? `同步异常 · ${Math.ceil(syncRetryDelayMs / 1_000)}s 重试`
      : "同步异常",
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
          <div class="data-root-pill ${hasFreshVireaHomeAuthority() ? "" : "stale"}" id="data-root-indicator" title="${escapeHtml(hasFreshVireaHomeAuthority() ? `当前服务 VIREA_HOME：${state.vireaHome}` : state.vireaHome ? `上次确认的 VIREA_HOME：${state.vireaHome}；正在等待服务重新确认` : "正在读取当前服务的 VIREA_HOME")}">
            <span>${hasFreshVireaHomeAuthority() ? "VIREA_HOME" : "VIREA_HOME · 待确认"}</span><code>${escapeHtml(state.vireaHome || "读取中…")}</code>
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
    const integrated = isVireaIntegratedModel(item);
    const stateLabel = integrated
      ? ready ? modelReadyBadge(item) : installationLabel(currentInstallationState(item))
      : "仅上游登记";
    return `<option value="${escapeHtml(item.model.id)}" ${item.model.id === state.selectedModelId ? "selected" : ""}>${escapeHtml(item.model.display_name)} · ${stateLabel}</option>`;
  }).join("");
}

const JOB_PROGRESS: Record<string, number> = {
  QUEUED: 8,
  ADMITTED: 16,
  STARTING_WORKER: 25,
  LOADING_MODEL: 36,
  RUNNING: 52,
  DECODING: 66,
  NORMALIZING: 73,
  RETARGETING: 80,
  VALIDATING: 87,
  EXPORTING: 94,
  SUCCEEDED: 100,
};

function generationPresentation(): { label: string; progress: number | null; busy: boolean } {
  const active = state.activeJob && !TERMINAL_JOB_STATES.has(state.activeJob.state)
    ? state.activeJob
    : null;
  if (active) {
    return {
      label: `${jobLabel(active.state)} / ${active.state}`,
      progress: JOB_PROGRESS[active.state] ?? null,
      busy: true,
    };
  }
  if (state.generationPhase !== "idle") {
    const labels: Record<Exclude<GenerationPhase, "idle">, string> = {
      validating: "核验执行目标 / Checking target",
      submitting: "提交持久任务 / Submitting durable job",
      tracking: "连接任务事件 / Connecting live events",
      loading_result: "载入动作结果 / Loading result",
    };
    return { label: state.generationMessage || labels[state.generationPhase], progress: null, busy: true };
  }
  return { label: "等待生成 / Ready", progress: 0, busy: false };
}

function generationStatusMarkup(): string {
  const presentation = generationPresentation();
  const jobId = state.activeJob?.id;
  const value = presentation.progress;
  return `<div class="job-progress ${presentation.busy ? "active" : "idle"}" id="generation-status" role="status" aria-live="polite">
    <div class="progress-track" role="progressbar" aria-label="生成进度" aria-valuemin="0" aria-valuemax="100" ${value == null ? "" : `aria-valuenow="${value}"`}>
      <span class="${value == null ? "indeterminate" : ""}" style="--progress:${value ?? 35}%"></span>
    </div>
    <p><strong data-generation-label>${escapeHtml(presentation.label)}</strong><code data-generation-job>${escapeHtml(jobId ?? "尚未提交")}</code></p>
  </div>`;
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
  const integrated = manifest ? isVireaIntegratedModel(manifest) : false;
  const installState = manifest ? currentInstallationState(manifest) : null;
  const active = state.activeJob && !TERMINAL_JOB_STATES.has(state.activeJob.state)
    ? state.activeJob
    : null;
  const busy = Boolean(active || state.installingModelId || state.generationPhase !== "idle");
  const canGenerate = Boolean(
    manifest
    && integrated
    && ready
    && hasFreshVireaHomeAuthority()
    && state.selectedExecutionDomainId
    && !busy,
  );
  return `
    <section class="page-heading compact">
      <div><p class="eyebrow">MOTION CREATION WORKSPACE</p><h1>从文字到可播放动作，在同一个工作台完成</h1>
        <p>模型选择、任务进度、重定向前源骨架与最终 VRM 对照保持在一条连续工作流中。</p></div>
    </section>
    <section class="studio-grid">
      <article class="composer-card surface">
        <div class="section-title"><span>01</span><div><h2>动作生成</h2><p>使用已部署模型创建可追溯结果</p></div></div>
        <label class="field"><span>模型</span><select id="model-id" ${availableModels().length ? "" : "disabled"}>${modelSelectOptions()}</select></label>
        <div class="model-readiness ${ready && integrated ? "ready" : integrated ? "pending" : "unsupported"}">
          <div><i></i><span>${manifest ? escapeHtml(manifest.model.display_name) : "没有可执行模型"}</span></div>
          <strong>${manifest ? escapeHtml(integrated ? ready ? modelReadyBadge(manifest) : installationLabel(installState) : "UPSTREAM ONLY") : "UNAVAILABLE"}</strong>
        </div>
        ${manifest && ready && integrated ? `<p class="readiness-evidence">${escapeHtml(modelIntegrityNote(manifest))}</p>` : ""}
        ${manifest && !integrated ? `<div class="capability-note" role="note"><strong>仅上游登记，尚未接入 VIREA</strong><p>${escapeHtml(capabilityReason(manifest))}。此模型仍可浏览，但不会伪装成可部署。</p></div>` : ""}
        ${manifest && integrated && !ready ? `<button class="secondary wide" data-install="${escapeHtml(manifest.model.id)}" ${state.installingModelId ? "disabled" : ""}>${state.installingModelId === manifest.model.id ? "正在部署并验收…" : "部署这个模型"}</button>` : ""}
        <label class="field prompt-field"><span>动作描述</span><textarea id="prompt" maxlength="8000" placeholder="例如：A person walks forward, turns left, and waves." ${integrated ? "" : "disabled"}>${escapeHtml(draft.prompt)}</textarea><small>写清人物、方向、节奏和动作结束方式。</small></label>
        <div class="parameter-grid">
          <label class="field"><span>时长（秒）</span><input id="seconds" type="number" min="1" max="90" step="0.01" value="${escapeHtml(draft.seconds)}" ${integrated ? "" : "disabled"} /></label>
          <label class="field"><span>随机种子</span><input id="seed" type="number" min="0" max="2147483647" step="1" value="${escapeHtml(draft.seed)}" ${integrated ? "" : "disabled"} /></label>
        </div>
        <button class="primary generate-button" id="generate" ${canGenerate ? "" : "disabled"}>
          <span data-generate-button-label>${active ? jobLabel(active.state) : !hasFreshVireaHomeAuthority() ? "等待数据根同步" : !integrated ? "该模型尚未接入" : ready ? "生成动作" : "请先完成模型部署"}</span><i>→</i>
        </button>
        ${generationStatusMarkup()}
        <pre id="generation-output" class="machine-evidence" aria-hidden="true">${escapeHtml(state.generationEvidence)}</pre>
      </article>

      <article class="stage-card">
        <div class="stage-toolbar">
          <div><p class="eyebrow">PRE / POST RETARGET DIAGNOSTICS</p><h2>${state.lastResult ? "最新结果双阶段对照" : "模型骨架与最终 VRM"}</h2></div>
          <div class="stage-actions">
            <label class="file-action"><input id="avatar-file" type="file" accept=".vrm,.glb,model/gltf-binary" /><span>载入 Avatar</span></label>
            <label class="file-action"><input id="vrma-file" type="file" accept=".vrma,model/gltf-binary" /><span>载入 VRMA</span></label>
            <button id="source-camera-reset" class="icon-action" title="重置源骨架视角">重置 A 视角</button>
            <button id="target-camera-reset" class="icon-action" title="重置 VRM 视角">重置 B 视角</button>
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
          <p>左侧只做坐标归一化用于显示，不进入 VRM 骨骼重定向；右侧是同一结果的最终 VRMA。拖动旋转、右键平移、滚轮或双指缩放；生成期间 Viewer 自动暂停绘制以降低前端 GPU 开销，完成后原位恢复。</p>
          <div class="result-actions">
            ${state.lastResult ? `<code>${escapeHtml(state.lastResult.result_id)}</code>` : ""}
            ${state.lastVrmaUrl ? `<a href="${escapeHtml(state.lastVrmaUrl)}" download>下载 VRMA</a><button id="open-viewer">定位到预览</button>` : ""}
          </div>
        </div>
      </article>
    </section>
    <section class="studio-bottom-grid">
      <article class="surface result-summary"><div class="section-title small"><span>02</span><div><h2>结果信息</h2><p>始终显示最近一次成功产物</p></div></div>${resultFacts()}</article>
      <article class="surface activity-card"><div class="section-title small"><span>03</span><div><h2>实时活动</h2><p>CLI、安装验收和 Web 任务共用同一状态</p></div></div><div data-activity-host>${recentActivity()}</div></article>
    </section>`;
}

function catalog(): string {
  const models = catalogModels();
  return `
    <section class="page-heading">
      <div><p class="eyebrow">MODEL LIBRARY</p><h1>模型能力与部署</h1><p>一个模型可在多个系统执行；这里展示的是当前数据根中的真实部署状态。</p></div>
      <div class="heading-metric"><strong>${models.filter((model) => isVireaIntegratedModel(model) && modelReady(model)).length}</strong><span>PERSISTED READY / ${integratedModels().length} INTEGRATED · ${models.length} CATALOGED</span></div>
    </section>
    <section class="model-library surface">
      <div class="library-header"><span>模型</span><span>转换路径</span><span>当前状态</span><span>操作</span></div>
      ${models.length ? models.map((item) => {
        const ready = modelReady(item);
        const integrated = isVireaIntegratedModel(item);
        const installState = currentInstallationState(item);
        const installable = integrated;
        const option = selectedExecutionOption(item.model.id);
        const runtime = item.runtime_variants.find((candidate) => candidate.id === option?.selected_runtime_id);
        const latestAttempt = item.installation?.latest_attempt?.state;
        return `<article class="model-row">
          <div class="model-identity"><span class="model-monogram">${escapeHtml(item.model.display_name.slice(0, 1))}</span><div><h2>${escapeHtml(item.model.display_name)}</h2><code>${escapeHtml(item.model.id)}</code><p>${escapeHtml(item.model.adapter_family)}</p></div></div>
          <div class="model-route"><strong>${escapeHtml(item.output.skeleton_id)}</strong><i>→</i><strong>${escapeHtml(item.result_target.skeleton_id)}</strong><small>${escapeHtml(item.model.tasks.join(" · "))}</small></div>
          <div class="model-state"><span class="state-badge ${ready && integrated ? "ready" : integrated ? (installState ?? "idle").toLowerCase() : "upstream"}"><i></i>${integrated ? ready ? modelReadyBadge(item) : installationLabel(installState) : "UPSTREAM ONLY"}</span><small>${escapeHtml(modelCapabilityLabel(item))}</small><small>${ready && integrated ? escapeHtml(modelIntegrityNote(item)) : latestAttempt && latestAttempt !== installState ? `最近尝试：${installationLabel(latestAttempt)}` : statusLabel(item.model.status)}</small><small>${integrated ? option ? `${option.selected_runtime_id ?? "未实现"} · ${option.selected_resource_profile ?? "无 profile"}${runtime?.runtime_core_epoch ? ` · ${runtime.runtime_core_epoch}` : ""}` : "选择环境后自动核验 Runtime" : escapeHtml(capabilityReason(item))}</small></div>
          <div class="model-action">${ready && integrated ? `<button data-use-model="${escapeHtml(item.model.id)}">在工作台使用</button>` : `<button data-install="${escapeHtml(item.model.id)}" ${!installable || !state.selectedExecutionDomainId || state.installingModelId ? "disabled" : ""}>${state.installingModelId === item.model.id ? "部署中…" : installable ? "部署并验收" : "浏览详情"}</button>`}</div>
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
  const activeWorkerJobs = visibleJobs().filter((job) => [
    "STARTING_WORKER", "LOADING_MODEL", "RUNNING", "DECODING", "NORMALIZING",
    "RETARGETING", "VALIDATING", "EXPORTING",
  ].includes(job.state)).length;
  return `
    <section class="page-heading">
      <div><p class="eyebrow">LOCAL CONTROL PLANE</p><h1>系统、数据与诊断</h1><p>快速状态保持轻量；完整硬件检测只在你明确点击时运行。</p></div>
      <button class="primary compact-button" id="refresh" ${state.systemLoading ? "disabled" : ""}>${state.systemLoading ? "正在检测…" : "运行完整检测"}</button>
    </section>
    <section class="system-metrics">
      <article class="surface"><small>控制面</small><strong>${state.health?.status === "ready" ? "在线" : "连接中"}</strong><span>${escapeHtml(state.health?.version ?? "—")}</span></article>
      <article class="surface"><small>可用执行域</small><strong>${domains.length}</strong><span>${escapeHtml(domains.map((item) => item.kind).join(" · ") || "尚未检测")}</span></article>
      <article class="surface"><small>模型目录</small><strong>${catalogModels().length}</strong><span>${integratedModels().length} 个 VIREA 已接入 · ${integratedModels().filter(modelReady).length} 持久 READY（执行前复验）</span></article>
      <article class="surface"><small>活动 Worker 任务</small><strong>${activeWorkerJobs}</strong><span>${escapeHtml(machine.platform ?? "按持久 Job 状态实时计算")}</span></article>
    </section>
    <section class="system-grid">
      <article class="surface data-root-card"><div class="section-title small"><span>A</span><div><h2>持久数据根</h2><p>模型、Runtime、任务与结果都以这里为根</p></div></div><code class="path-display">${escapeHtml(state.vireaHome || system.virea_home || "正在读取当前 VIREA_HOME")}</code>
        <div class="button-row"><button id="setup-plan">查看初始化计划</button><button id="setup-apply">核验目录结构</button></div><pre id="setup-output" class="diagnostic-output"></pre></article>
      <article class="surface domain-card"><div class="section-title small"><span>B</span><div><h2>执行域</h2><p>Web 与 CLI 共享选择和部署身份</p></div></div><div class="domain-list">${domains.map((domain) => `<div class="domain-row ${domain.id === state.selectedExecutionDomainId ? "selected" : ""}"><i></i><div><strong>${escapeHtml(domain.kind === "wsl" ? `WSL · ${domain.distribution}` : domain.kind)}</strong><small>${escapeHtml(domain.platform)} · ${escapeHtml(domain.architecture)}</small></div><span>${domain.id === state.selectedExecutionDomainId ? "当前" : domain.is_host ? "宿主" : "可用"}</span></div>`).join("") || '<p class="quiet-empty">尚未取得执行域报告。</p>'}</div></article>
      <article class="surface diagnostics-card"><div class="section-title small"><span>C</span><div><h2>安全诊断</h2><p>生成脱敏的本地支持包</p></div></div><p>支持包不会收集 prompt、token、原始音频、Avatar 或模型权重。</p><button id="support">生成 Support Bundle</button><pre id="support-output" class="diagnostic-output"></pre></article>
      <article class="surface all-activity"><div class="section-title small"><span>D</span><div><h2>最近任务</h2><p>持久数据库中的最新活动</p></div></div><div data-activity-host data-activity-limit="8">${recentActivity(8)}</div></article>
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
  setViewerActivity();
  restoreFocus(focus);
}

function setViewerActivity(): void {
  const generating = state.generationPhase !== "idle"
    || Boolean(state.activeJob && !TERMINAL_JOB_STATES.has(state.activeJob.state));
  const active = state.view === "playground" && !generating && document.visibilityState !== "hidden";
  viewerRuntime?.setActive(active);
  sourceViewerRuntime?.setActive(active);
}

function renderLiveRegions(): void {
  updateVireaHomeIndicator();
  const manifest = selectedManifest();
  const presentation = generationPresentation();
  const domainSelector = document.querySelector<HTMLSelectElement>("#global-execution-domain");
  if (domainSelector) domainSelector.disabled = presentation.busy;
  const modelSelector = document.querySelector<HTMLSelectElement>("#model-id");
  if (modelSelector) modelSelector.disabled = presentation.busy || !availableModels().length;
  const button = document.querySelector<HTMLButtonElement>("#generate");
  if (button) {
    button.disabled = !manifest
      || !isVireaIntegratedModel(manifest)
      || !modelReady(manifest)
      || !hasFreshVireaHomeAuthority()
      || !state.selectedExecutionDomainId
      || presentation.busy
      || Boolean(state.installingModelId);
    const label = button.querySelector<HTMLElement>("[data-generate-button-label]");
    if (label) {
      label.textContent = presentation.busy
        ? presentation.label
        : hasFreshVireaHomeAuthority() ? "生成动作" : "等待数据根同步";
    }
  }
  const status = document.querySelector<HTMLElement>("#generation-status");
  if (status) status.outerHTML = generationStatusMarkup();
  document.querySelectorAll<HTMLElement>("[data-activity-host]").forEach((host) => {
    host.innerHTML = recentActivity(host.dataset.activityLimit === "8" ? 8 : 6);
  });
  setViewerActivity();
}

function nextPaint(): Promise<void> {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
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
  setViewerActivity();
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
    if (isVireaIntegratedModel(selectedManifest()!)) {
      void loadExecutionOptions(state.selectedModelId).catch((error: unknown) => {
        state.error = errorMessage(error);
        render();
      });
    }
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
  document.querySelector("#source-camera-reset")?.addEventListener("click", () => {
    sourceViewerRuntime?.resetView();
  });
  document.querySelector("#target-camera-reset")?.addEventListener("click", () => {
    viewerRuntime?.resetView();
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

function mergeJobEvent(job: JobRecord, event: JobEvent): JobRecord {
  const events = [...(job.events ?? [])];
  if (!events.some((item) => item.sequence === event.sequence)) events.push(event);
  events.sort((left, right) => left.sequence - right.sequence);
  return { ...job, state: event.state, updated_at: event.created_at, events };
}

async function pollJobUntilTerminal(initial: JobRecord): Promise<JobRecord> {
  let current = initial;
  while (!TERMINAL_JOB_STATES.has(current.state)) {
    await new Promise((resolve) => window.setTimeout(resolve, 1_500));
    current = await api.job(current.id);
    upsertJob(current);
    renderLiveRegions();
  }
  return current;
}

async function waitForTerminalJob(initial: JobRecord): Promise<JobRecord> {
  if (TERMINAL_JOB_STATES.has(initial.state)) return initial;
  if (typeof WebSocket === "undefined") return pollJobUntilTerminal(initial);
  return new Promise<JobRecord>((resolve, reject) => {
    let current = initial;
    let settled = false;
    let fallbackStarted = false;
    const socket = new WebSocket(jobEventsUrl(initial.id));
    let watchdog = window.setTimeout(() => socket.close(), JOB_STREAM_STALL_MS);
    jobSocket?.close();
    jobSocket = socket;

    const armWatchdog = (): void => {
      window.clearTimeout(watchdog);
      watchdog = window.setTimeout(() => socket.close(), JOB_STREAM_STALL_MS);
    };

    const finishFromServer = async (): Promise<void> => {
      if (settled || fallbackStarted) return;
      try {
        const latest = await api.job(initial.id);
        current = latest;
        upsertJob(latest);
        renderLiveRegions();
        if (TERMINAL_JOB_STATES.has(latest.state)) {
          settled = true;
          resolve(latest);
          return;
        }
        fallbackStarted = true;
        resolve(await pollJobUntilTerminal(latest));
      } catch (error) {
        settled = true;
        reject(error);
      }
    };

    socket.addEventListener("message", (message) => {
      try {
        armWatchdog();
        const event = JSON.parse(String(message.data)) as NonNullable<JobRecord["events"]>[number];
        current = mergeJobEvent(current, event);
        upsertJob(current);
        renderLiveRegions();
        if (TERMINAL_JOB_STATES.has(current.state)) socket.close(1000);
      } catch {
        socket.close();
      }
    });
    socket.addEventListener("close", () => {
      window.clearTimeout(watchdog);
      if (jobSocket === socket) jobSocket = null;
      void finishFromServer();
    });
    socket.addEventListener("error", () => socket.close());
  });
}

async function resumePersistedActiveJob(job: JobRecord): Promise<void> {
  if (
    resumedJobId === job.id
    || state.generationPhase !== "idle"
    || TERMINAL_JOB_STATES.has(job.state)
  ) return;
  resumedJobId = job.id;
  state.generationPhase = "tracking";
  state.generationMessage = "正在恢复持久任务事件 / Resuming durable job events";
  renderLiveRegions();
  try {
    const terminal = await waitForTerminalJob(job);
    if (terminal.state === "SUCCEEDED") {
      state.generationPhase = "loading_result";
      state.generationMessage = "任务已完成，正在恢复结果 / Restoring completed result";
      renderLiveRegions();
      await loadPersistedSuccessfulJob(terminal.id);
      state.notice = "已恢复进行中的任务，并载入最新双阶段结果。";
    } else {
      state.error = `${terminal.state}: ${terminal.error_code ?? "GENERATION_FAILED"} ${terminal.error_message ?? ""}`.trim();
    }
  } catch (error) {
    state.error = `恢复任务 ${job.id} 失败：${errorMessage(error)}`;
  } finally {
    if (resumedJobId === job.id) resumedJobId = "";
    state.generationPhase = "idle";
    state.generationMessage = "";
    render();
  }
}

async function submitGeneration(
  manifest: ModelManifest,
  draft: Draft,
  target: ExecutionTargetSelection,
  idempotencyKey: string,
): Promise<JobRecord> {
  try {
    return await api.generate(
      manifest,
      draft.prompt,
      draft.seconds,
      draft.seed,
      target,
      idempotencyKey,
    );
  } catch (submissionError) {
    // A browser abort cannot cancel a server thread. Reconcile the durable
    // idempotency identity before allowing a retry to create another Job.
    try {
      const jobs = await api.jobs();
      const existing = jobs.find((job) => job.idempotency_key === idempotencyKey);
      if (existing) return existing;
    } catch {
      // Preserve the original, more useful submission error.
    }
    throw submissionError;
  }
}

async function generationRequestFingerprint(
  manifest: ModelManifest,
  draft: Draft,
  target: ExecutionTargetSelection,
  vireaHome: string,
): Promise<string> {
  return submissionFingerprint({
    vireaHome,
    modelId: manifest.model.id,
    task: manifest.production_acceptance?.request.task ?? manifest.model.tasks[0] ?? "",
    prompt: draft.prompt,
    seconds: draft.seconds,
    seed: draft.seed,
    executionTarget: target,
  });
}

async function submissionAttemptFor(
  manifest: ModelManifest,
  draft: Draft,
  target: ExecutionTargetSelection,
  vireaHome: string,
): Promise<PendingSubmissionAttempt> {
  const fingerprint = await generationRequestFingerprint(manifest, draft, target, vireaHome);
  const attempt = retainOrCreateSubmissionAttempt(
    pendingSubmissionAttempt,
    fingerprint,
    () => crypto.randomUUID(),
    () => new Date().toISOString(),
  );
  persistPendingSubmissionAttempt(attempt);
  return attempt;
}

function reconcilePendingSubmission(jobs: readonly JobRecord[]): void {
  if (submissionAttemptWasPersisted(pendingSubmissionAttempt, jobs)) {
    persistPendingSubmissionAttempt(null);
  }
}

async function generate(): Promise<void> {
  const manifest = selectedManifest();
  if (!manifest || state.generationPhase !== "idle") return;
  const authoritativeVireaHome = state.vireaHome.trim();
  if (!hasFreshVireaHomeAuthority()) {
    state.notice = "";
    state.error = "正在等待服务确认持久数据根；同步完成前不会创建任务 / Waiting for authoritative VIREA_HOME";
    render();
    return;
  }
  const draft = state.drafts[manifest.model.id]!;
  state.error = "";
  state.notice = "";
  state.generationPhase = "validating";
  state.generationMessage = "核验所选系统、Runtime 与资源配置 / Checking execution target";
  renderLiveRegions();
  try {
    if (!isVireaIntegratedModel(manifest)) {
      throw new Error(`${manifest.model.id} 仅在目录中登记；尚无 VIREA Runtime、Worker 与端到端验收`);
    }
    await nextPaint();
    const selectedModelId = manifest.model.id;
    const selectedDomainId = state.selectedExecutionDomainId;
    await loadExecutionOptions(selectedModelId, true);
    if (
      state.selectedModelId !== selectedModelId
      || state.selectedExecutionDomainId !== selectedDomainId
      || !hasFreshVireaHomeAuthority()
      || state.vireaHome.trim() !== authoritativeVireaHome
    ) {
      throw new Error("核验期间模型、执行环境或持久数据根发生变化；请确认当前选择后重新生成");
    }
    const target = selectedExecutionTarget();
    const option = selectedExecutionOption(manifest.model.id);
    if (!option) {
      throw new Error(`${manifest.model.id} 没有返回 ${target.execution_domain_id} 的执行选项；不会创建无效任务`);
    }
    if (!option.implemented || !option.can_build) {
      throw new Error(option.reasons.join("; ") || `${manifest.model.id} 尚未在 ${target.execution_domain_id} 实现可运行 Runtime`);
    }
    state.generationPhase = "submitting";
    state.generationMessage = "正在提交并创建可恢复的持久任务 / Submitting durable job";
    renderLiveRegions();
    await nextPaint();
    if (!hasFreshVireaHomeAuthority() || state.vireaHome.trim() !== authoritativeVireaHome) {
      throw new Error("提交前持久数据根发生变化；不会在不确定的数据根中创建任务");
    }
    const attempt = await submissionAttemptFor(
      manifest,
      draft,
      target,
      authoritativeVireaHome,
    );
    let authorityObservation: StateAuthorityObservation;
    try {
      authorityObservation = await requestAuthoritativeStateRevision();
    } catch (error) {
      throw new Error(
        `提交前无法重新确认持久数据根；不会创建任务：${errorMessage(error)}`,
      );
    }
    const observedVireaHome = authorityObservation.payload?.virea_home.trim() ?? "";
    if (
      !authorityObservation.current
      || authorityObservation.epoch !== stateAuthorityRequestEpoch
      || !hasFreshVireaHomeAuthority()
      || observedVireaHome !== authoritativeVireaHome
      || state.vireaHome.trim() !== authoritativeVireaHome
    ) {
      throw new Error(
        `持久数据根已从 ${authoritativeVireaHome} 变更为 ${observedVireaHome || "未知"}；已应用最新状态，请确认后重试`,
      );
    }
    let job = await submitGeneration(
      manifest,
      draft,
      target,
      attempt.idempotencyKey,
    );
    if (pendingSubmissionAttempt?.idempotencyKey === attempt.idempotencyKey) {
      persistPendingSubmissionAttempt(null);
    }
    upsertJob(job);
    state.generationPhase = "tracking";
    state.generationMessage = "已连接任务事件 / Live job events connected";
    renderLiveRegions();
    job = await waitForTerminalJob(job);
    if (job.state !== "SUCCEEDED") {
      throw new Error(`${job.state}: ${job.error_code ?? "GENERATION_FAILED"} ${job.error_message ?? ""}`.trim());
    }
    state.generationPhase = "loading_result";
    state.generationMessage = "正在载入源骨架与最终 VRMA / Loading both motion stages";
    renderLiveRegions();
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
    state.generationPhase = "idle";
    state.generationMessage = "";
    render();
    setViewerActivity();
  }
}

async function loadPersistedSuccessfulJob(jobId: string): Promise<void> {
  if (resultLoadJobId === jobId && resultLoadPromise) return resultLoadPromise;
  const epoch = ++resultLoadEpoch;
  resultLoadJobId = jobId;
  let pending: Promise<void>;
  pending = performLoadPersistedSuccessfulJob(jobId, epoch).finally(() => {
    if (resultLoadPromise === pending) {
      resultLoadPromise = null;
      resultLoadJobId = "";
    }
  });
  resultLoadPromise = pending;
  return pending;
}

function scheduleSourcePreviewRetry(jobId: string, resultId: string): void {
  if (sourcePreviewRetryResultId !== resultId) {
    sourcePreviewRetryResultId = resultId;
    sourcePreviewRetryCount = 0;
  }
  if (sourcePreviewRetryCount >= 3 || sourcePreviewRetryTimer != null) return;
  sourcePreviewRetryCount += 1;
  sourcePreviewRetryTimer = window.setTimeout(() => {
    sourcePreviewRetryTimer = null;
    if (state.lastResult?.result_id !== resultId) return;
    void loadPersistedSuccessfulJob(jobId)
      .then(() => render())
      .catch(() => scheduleSourcePreviewRetry(jobId, resultId));
  }, sourcePreviewRetryCount * 1_500);
}

async function performLoadPersistedSuccessfulJob(jobId: string, epoch: number): Promise<void> {
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
  let sourceError = "";
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
    sourceError = errorMessage(error);
  }
  if (epoch !== resultLoadEpoch) return;
  if (sourceError) {
    sourceViewerRuntime?.clear();
    sourceViewerLoadedResultId = "";
    state.sourceViewerStatus = {
      kind: "error",
      message: `无法载入重定向前骨架：${sourceError}`,
    };
    scheduleSourcePreviewRetry(jobId, result.result_id);
  } else {
    sourcePreviewAttemptedResultId = result.result_id;
    sourcePreviewRetryResultId = result.result_id;
    sourcePreviewRetryCount = 0;
    if (sourcePreviewRetryTimer != null) window.clearTimeout(sourcePreviewRetryTimer);
    sourcePreviewRetryTimer = null;
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

async function hydrateLatestSuccessfulResult(): Promise<boolean> {
  const latest = visibleJobs().find((job) => job.state === "SUCCEEDED");
  if (!latest) {
    if (state.lastResult) clearPersistedResult("当前数据根没有可播放的生产源骨架");
    return true;
  }
  if (
    (
      state.lastResult?.job_id === latest.id
      && sourcePreviewAttemptedResultId === state.lastResult.result_id
    )
  ) return true;
  try {
    await loadPersistedSuccessfulJob(latest.id);
    return true;
  } catch {
    // A terminal job row and its immutable result commit can be observed on
    // adjacent refreshes. The next revision/poll retries without a false alert.
    return false;
  }
}

function clearPersistedResult(sourceMessage: string): void {
  resultLoadEpoch += 1;
  resultLoadJobId = "";
  resultLoadPromise = null;
  state.lastResult = null;
  state.lastModelResult = null;
  state.lastSourcePreview = null;
  state.lastVrmaUrl = "";
  state.lastGeneration = null;
  state.generationEvidence = "";
  sourcePreviewAttemptedResultId = "";
  sourcePreviewRetryResultId = "";
  sourcePreviewRetryCount = 0;
  if (sourcePreviewRetryTimer != null) window.clearTimeout(sourcePreviewRetryTimer);
  sourcePreviewRetryTimer = null;
  sourceViewerLoadedResultId = "";
  viewerLoadedVrmaUrl = "";
  sourceViewerRuntime?.clear(sourceMessage);
  viewerRuntime?.clearAnimation();
  state.sourceViewerStatus = { kind: "idle", message: sourceMessage };
  state.viewerStatus = { kind: "idle", message: "载入 Avatar 后即可预览生成动作" };
}

function applyStateRevision(payload: StateRevision, authorityEpoch: number): void {
  const authorityWasFresh = state.vireaHomeAuthorityFresh;
  const nextHome = payload.virea_home;
  const normalizedNextHome = nextHome.trim();
  const homeChanged = state.vireaHome.trim() !== normalizedNextHome;
  if (state.vireaHome && nextHome && state.vireaHome !== nextHome) {
    clearPersistedResult("数据根已经切换；等待当前数据根中的真实生成结果");
    persistPendingSubmissionAttempt(null);
    lastRevision = null;
    stateRevisionKey = "";
  }
  if (homeChanged) {
    stateAuthorityReconciliationHome = normalizedNextHome;
    stateAuthorityReconciliationEpoch = authorityEpoch;
  } else if (stateAuthorityReconciliationHome === normalizedNextHome) {
    stateAuthorityReconciliationEpoch = authorityEpoch;
  }
  if (!normalizedNextHome) {
    stateAuthorityReconciliationHome = "";
    stateAuthorityReconciliationEpoch = 0;
  }
  state.vireaHome = nextHome;
  state.vireaHomeAuthorityFresh = Boolean(normalizedNextHome)
    && !stateAuthorityReconciliationHome;
  state.lastSyncedAt = payload.observed_at;
  if (authorityWasFresh !== state.vireaHomeAuthorityFresh) renderLiveRegions();
  else updateVireaHomeIndicator();
}

interface StateAuthorityObservation {
  payload: StateRevision | null;
  current: boolean;
  epoch: number;
}

interface PendingRevisionObservation {
  payload: StateRevision;
  authorityEpoch: number;
}

async function requestAuthoritativeStateRevision(): Promise<StateAuthorityObservation> {
  const requestEpoch = ++stateAuthorityRequestEpoch;
  try {
    const payload = await api.stateRevision();
    const current = requestEpoch === stateAuthorityRequestEpoch;
    if (current) {
      stateAuthorityLastSuccessfulEpoch = requestEpoch;
      applyStateRevision(payload, requestEpoch);
    }
    return { payload, current, epoch: requestEpoch };
  } catch (error) {
    if (requestEpoch !== stateAuthorityRequestEpoch) {
      // A newer stream/HTTP observation already superseded this request. Its
      // late failure cannot invalidate the newer authority or mark it offline.
      return { payload: null, current: false, epoch: requestEpoch };
    }
    stateAuthorityLastFailureEpoch = requestEpoch;
    invalidateVireaHomeAuthority();
    throw error;
  }
}

function revisionKey(payload: StateRevision): string {
  return JSON.stringify({ virea_home: payload.virea_home, revision: payload.revision });
}

function updateVireaHomeIndicator(): void {
  const indicator = document.querySelector<HTMLElement>("#data-root-indicator");
  if (!indicator) return;
  const fresh = hasFreshVireaHomeAuthority();
  indicator.classList.toggle("stale", !fresh);
  indicator.title = fresh
    ? `当前服务 VIREA_HOME：${state.vireaHome}`
    : state.vireaHome
      ? `上次确认的 VIREA_HOME：${state.vireaHome}；正在等待服务重新确认`
      : "正在读取当前服务的 VIREA_HOME";
  const label = indicator.querySelector("span");
  if (label) label.textContent = fresh ? "VIREA_HOME" : "VIREA_HOME · 待确认";
  const path = indicator.querySelector("code");
  if (path) path.textContent = state.vireaHome || "读取中…";
}

function changedRevisionKeys(
  previous: StateRevision["revision"] | null,
  next: StateRevision["revision"],
): Set<keyof StateRevision["revision"]> {
  const keys = new Set<keyof StateRevision["revision"]>();
  for (const key of Object.keys(next) as Array<keyof StateRevision["revision"]>) {
    if (previous == null || previous[key] !== next[key]) keys.add(key);
  }
  return keys;
}

function updateSyncBadge(): void {
  const node = document.querySelector<HTMLElement>("#sync-status");
  if (!node) return;
  node.className = `sync-pill ${state.syncStatus}`;
  const label = node.querySelector("span");
  if (label) label.textContent = syncLabel();
  const healthyTitle = state.lastSyncedAt
    ? `CLI 与 Web 使用 ${state.vireaHome || "当前"} 的同一持久状态 · 最近同步 ${new Date(state.lastSyncedAt).toLocaleTimeString()}`
    : "CLI 与 Web 使用同一持久状态";
  node.title = syncFailureMessage
    ? `${syncFailureMessage}；保留未应用的状态版本并自动退避重试。可检查服务日志或刷新页面。`
    : healthyTitle;
}

function markSynchronizationHealthy(): void {
  if (syncRetryTimer != null) window.clearTimeout(syncRetryTimer);
  syncRetryTimer = null;
  syncFailureCount = 0;
  syncRetryDelayMs = 0;
  syncFailureMessage = "";
  state.syncStatus = stateSocket?.readyState === WebSocket.OPEN ? "live" : "polling";
  updateSyncBadge();
}

async function synchronizePersistentState(
  requestedKeys: ReadonlySet<keyof StateRevision["revision"]> | null = null,
): Promise<void> {
  const keys = requestedKeys ?? new Set<keyof StateRevision["revision"]>([
    "models", "installations", "jobs", "results", "workers",
  ]);
  const reloadModels = keys.has("models") || keys.has("installations");
  const reloadJobs = keys.has("jobs");
  const previousResultId = state.lastResult?.result_id ?? "";
  const [models, jobs] = await Promise.all([
    reloadModels ? api.models() : Promise.resolve(null),
    reloadJobs ? api.jobs() : Promise.resolve(null),
  ]);
  if (models) state.models = models;
  if (jobs) {
    state.jobs = jobs;
    reconcilePendingSubmission(jobs);
  }
  ensureSelectedModel();
  ensureSelectedExecutionDomain();
  const active = reconcileActiveJob();
  if (keys.has("results") && !(await hydrateLatestSuccessfulResult())) {
    throw new Error("最新结果尚未完成不可变发布，等待下一次状态核对");
  }
  reconcileActiveJob();
  state.lastSyncedAt = new Date().toISOString();
  const resultChanged = previousResultId !== (state.lastResult?.result_id ?? "");
  if (reloadModels || resultChanged) render();
  else renderLiveRegions();
  if (active) void resumePersistedActiveJob(active);
}

function synchronizeRevision(payload: StateRevision, authorityEpoch: number): Promise<void> {
  pendingRevisionPayload = { payload, authorityEpoch };
  if (syncInFlight) return syncInFlight;
  if (syncRetryTimer != null) window.clearTimeout(syncRetryTimer);
  syncRetryTimer = null;
  let failedTarget: PendingRevisionObservation | null = null;
  syncInFlight = (async () => {
    while (pendingRevisionPayload) {
      const targetObservation = pendingRevisionPayload;
      pendingRevisionPayload = null;
      const target = targetObservation.payload;
      const targetRequiresRootReconciliation = Boolean(
        stateAuthorityReconciliationHome
        && stateAuthorityReconciliationHome === target.virea_home.trim(),
      );
      const changed = targetRequiresRootReconciliation
        ? new Set<keyof StateRevision["revision"]>([
          "models", "installations", "jobs", "results", "workers",
        ])
        : changedRevisionKeys(lastRevision, target.revision);
      if (!changed.size) {
        stateRevisionKey = revisionKey(target);
        continue;
      }
      try {
        await synchronizePersistentState(changed);
      } catch (error) {
        failedTarget = targetObservation;
        throw error;
      }
      const applied = lastRevision ? { ...lastRevision } : { ...target.revision };
      changed.forEach((key) => { applied[key] = target.revision[key]; });
      lastRevision = applied;
      stateRevisionKey = revisionKey(target);
      if (
        stateAuthorityReconciliationHome
        && stateAuthorityReconciliationHome === target.virea_home.trim()
        && state.vireaHome.trim() === target.virea_home.trim()
      ) {
        const reconciliationIsCurrent = stateAuthorityReconciliationEpoch
          === targetObservation.authorityEpoch
          && targetObservation.authorityEpoch === stateAuthorityRequestEpoch
          && targetObservation.authorityEpoch === stateAuthorityLastSuccessfulEpoch
          && stateAuthorityLastFailureEpoch < targetObservation.authorityEpoch;
        if (reconciliationIsCurrent) {
          stateAuthorityReconciliationHome = "";
          stateAuthorityReconciliationEpoch = 0;
          state.vireaHomeAuthorityFresh = true;
          renderLiveRegions();
        }
      }
    }
    // An older collection refresh can finish after a newer /state failure.
    // It must not overwrite that authority failure with a healthy sync badge.
    if (hasFreshVireaHomeAuthority()) markSynchronizationHealthy();
    else updateSyncBadge();
  })().catch((error) => {
    if (!pendingRevisionPayload && failedTarget) pendingRevisionPayload = failedTarget;
    syncFailureCount += 1;
    syncRetryDelayMs = Math.min(1_000 * (2 ** Math.min(syncFailureCount - 1, 5)), 30_000);
    syncFailureMessage = `持久状态同步失败：${errorMessage(error)}`;
    state.syncStatus = "degraded";
    updateSyncBadge();
    syncRetryTimer = window.setTimeout(() => {
      syncRetryTimer = null;
      const retry = pendingRevisionPayload;
      if (retry && !syncInFlight) {
        void synchronizeRevision(retry.payload, retry.authorityEpoch);
      }
    }, syncRetryDelayMs);
  }).finally(() => {
    syncInFlight = null;
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
    state.syncStatus = syncFailureMessage ? "degraded" : "live";
    updateSyncBadge();
  });
  socket.addEventListener("message", (event) => {
    try {
      const payload = JSON.parse(String(event.data)) as StateRevision;
      const key = revisionKey(payload);
      const authorityEpoch = ++stateAuthorityRequestEpoch;
      stateAuthorityLastSuccessfulEpoch = authorityEpoch;
      applyStateRevision(payload, authorityEpoch);
      if (key !== stateRevisionKey || stateAuthorityReconciliationHome) {
        void synchronizeRevision(payload, authorityEpoch);
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
    state.syncStatus = syncFailureMessage ? "degraded" : "polling";
    updateSyncBadge();
  });
  socket.addEventListener("error", () => socket.close());
}

async function pollStateRevision(): Promise<void> {
  try {
    const observation = await requestAuthoritativeStateRevision();
    if (!observation.current || !observation.payload) return;
    const payload = observation.payload;
    const key = revisionKey(payload);
    if (key !== stateRevisionKey || stateAuthorityReconciliationHome) {
      await synchronizeRevision(payload, observation.epoch);
    } else if (!pendingRevisionPayload && !syncInFlight) {
      markSynchronizationHealthy();
    }
    if (!stateSocket && payload.events_url && Date.now() >= stateStreamRetryAt) connectStateStream();
    else updateSyncBadge();
  } catch {
    syncFailureMessage = "无法读取服务状态；正在等待 API 恢复";
    state.syncStatus = "offline";
    updateSyncBadge();
  }
}

async function bootstrap(): Promise<void> {
  const [healthResult, stateResult, domainResult, modelResult, jobResult] = await Promise.allSettled([
    api.health(),
    requestAuthoritativeStateRevision(),
    api.executionDomains(),
    api.models(),
    api.jobs(),
  ]);
  if (healthResult.status === "fulfilled") state.health = healthResult.value;
  if (domainResult.status === "fulfilled") state.executionDomains = domainResult.value;
  if (modelResult.status === "fulfilled") state.models = modelResult.value;
  if (jobResult.status === "fulfilled") {
    state.jobs = jobResult.value;
    reconcilePendingSubmission(jobResult.value);
  }
  ensureSelectedModel();
  ensureSelectedExecutionDomain();
  reconcileActiveJob();
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
  const active = reconcileActiveJob();
  // Parallel bootstrap payloads are only an immediate visual snapshot. Never
  // mark the independently fetched /state revision as applied: /models or
  // /jobs may have been read just before that revision. The post-render state
  // poll observes a checkpoint and, with lastRevision=null, reconciles every
  // collection from requests that begin after the checkpoint.
  lastRevision = null;
  stateRevisionKey = "";
  render();
  if (active) void resumePersistedActiveJob(active);
  void pollStateRevision();
}

window.setInterval(() => void pollStateRevision(), STATE_POLL_INTERVAL_MS);
window.addEventListener("focus", () => void pollStateRevision());
window.addEventListener("online", () => void pollStateRevision());
document.addEventListener("visibilitychange", () => {
  setViewerActivity();
  if (document.visibilityState === "visible") void pollStateRevision();
});
window.addEventListener("pagehide", (event: PageTransitionEvent) => {
  stateSocket?.close();
  stateSocket = null;
  jobSocket?.close();
  jobSocket = null;
  if (event.persisted) {
    viewerRuntime?.setActive(false);
    sourceViewerRuntime?.setActive(false);
    return;
  }
  sourceViewerRuntime?.dispose();
  sourceViewerRuntime = null;
  sourceViewerCanvas = null;
  viewerRuntime?.dispose();
  viewerRuntime = null;
  viewerCanvas = null;
});
window.addEventListener("pageshow", (event: PageTransitionEvent) => {
  if (!event.persisted) return;
  setViewerActivity();
  void pollStateRevision();
});
void bootstrap();

export { escapeHtml, statusLabel };
