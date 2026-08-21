import "./styles.css";
import { api, type HealthStatus, type JobRecord, type ModelManifest } from "./api";
import type {
  ExecutionDomainCandidates,
  ExecutionTargetSelection,
  ModelExecutionOption,
  ModelResult,
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
  realRunnableModels,
  resultMotionRoute,
} from "./domain";
import { RealVrmViewer, type ViewerStatus } from "./viewer";

type View = "overview" | "catalog" | "playground" | "viewer" | "jobs" | "diagnostics";

const state: {
  view: View;
  models: ModelManifest[];
  jobs: JobRecord[];
  health: HealthStatus | null;
  system: Record<string, unknown> | null;
  systemLoading: boolean;
  executionDomains: ExecutionDomainCandidates | null;
  executionOptions: Record<string, ModelExecutionOption[]>;
  selectedExecutionDomainId: string;
  selectedModelId: string;
  installationStates: Record<string, string>;
  lastResult: VrmMotionResult | null;
  lastModelResult: ModelResult | null;
  lastVrmaUrl: string;
  lastGeneration: { modelId: string; seconds: number; seed: number } | null;
  error: string;
} = {
  view: "overview",
  models: [],
  jobs: [],
  health: null,
  system: null,
  systemLoading: false,
  executionDomains: null,
  executionOptions: {},
  selectedExecutionDomainId: "",
  selectedModelId: "",
  installationStates: {},
  lastResult: null,
  lastModelResult: null,
  lastVrmaUrl: "",
  lastGeneration: null,
  error: "",
};

const appNode = document.querySelector<HTMLDivElement>("#app");
if (!appNode) throw new Error("#app is missing");
const app: HTMLDivElement = appNode;
let viewerRuntime: RealVrmViewer | null = null;

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    registered: "仅登记",
    source_available: "源码可用",
    runnable_upstream: "上游可运行",
    integrated_experimental: "VIREA 实验接入",
    supported: "VIREA 支持",
    blocked: "阻塞",
  };
  return labels[status] ?? status;
}

function availableModels(): ModelManifest[] {
  return realRunnableModels(state.models);
}

function catalogModels(): ModelManifest[] {
  return productionCatalogModels(state.models);
}

function currentInstallationState(manifest: ModelManifest): string | null {
  return state.installationStates[manifest.model.id] ?? installationState(manifest);
}

function modelReady(manifest: ModelManifest): boolean {
  const current = currentInstallationState(manifest);
  return current != null ? current.toUpperCase() === "READY" : isInstalledReady(manifest);
}

function ensureSelectedModel(): void {
  const available = availableModels();
  if (!available.some((item) => item.model.id === state.selectedModelId)) {
    state.selectedModelId = available.find(modelReady)?.model.id ?? available[0]?.model.id ?? "";
  }
}

function ensureSelectedExecutionDomain(): void {
  const domains = state.executionDomains?.execution_domains ?? [];
  if (domains.some((domain) => domain.id === state.selectedExecutionDomainId)) return;
  state.selectedExecutionDomainId = domains.length === 1 ? domains[0]!.id : "";
}

function selectedExecutionTarget(): ExecutionTargetSelection {
  if (!state.selectedExecutionDomainId) {
    throw new Error("检测到多个运行环境，请先明确选择一个执行域");
  }
  return {
    schema_version: "virea.execution_target_selection.v1.0.0",
    execution_domain_id: state.selectedExecutionDomainId,
    runtime_variant_id: null,
    resource_profile_id: null,
  };
}

function executionDomainSelector(id: string): string {
  const domains = state.executionDomains?.execution_domains ?? [];
  const placeholder = domains.length > 1
    ? '<option value="">请选择运行环境</option>'
    : "";
  return `<label>运行环境<select id="${id}" ${domains.length ? "" : "disabled"}>${placeholder}${domains
    .map((domain) => {
      const label = domain.kind === "wsl"
        ? `WSL · ${domain.distribution ?? domain.id}`
        : `${domain.kind} · ${domain.platform}`;
      return `<option value="${escapeHtml(domain.id)}" ${domain.id === state.selectedExecutionDomainId ? "selected" : ""}>${escapeHtml(label)}</option>`;
    })
    .join("")}</select></label>`;
}

function selectedExecutionOption(modelId: string): ModelExecutionOption | null {
  return state.executionOptions[modelId]?.find(
    (option) => option.execution_domain.id === state.selectedExecutionDomainId,
  ) ?? null;
}

async function loadExecutionOptions(modelId: string): Promise<void> {
  if (!modelId || state.executionOptions[modelId]) return;
  const payload = await api.executionOptions(modelId);
  state.executionOptions[modelId] = payload.options;
}

function layout(content: string): string {
  const nav: Array<[View, string]> = [
    ["overview", "系统"],
    ["catalog", "模型目录"],
    ["playground", "Playground"],
    ["viewer", "Viewer"],
    ["jobs", "任务"],
    ["diagnostics", "诊断"],
  ];
  return `
    <div class="shell">
      <aside>
        <div class="brand"><span>V</span><div><strong>VIREA</strong><small>Motion Studio 0.4.0</small></div></div>
        <div class="global-runtime-selector">
          ${executionDomainSelector("global-execution-domain")}
          ${!state.selectedExecutionDomainId && (state.executionDomains?.execution_domains.length ?? 0) > 1 ? '<small class="environment-required">请选择运行环境后再安装或生成</small>' : ""}
        </div>
        <nav>${nav
          .map(
            ([id, label]) =>
              `<button data-view="${id}" class="${state.view === id ? "active" : ""}">${label}</button>`,
          )
          .join("")}</nav>
        <div class="legend"><i class="dot online"></i> Local control plane</div>
      </aside>
      <main>
        ${state.error ? `<div class="error">${escapeHtml(state.error)}</div>` : ""}
        ${content}
      </main>
    </div>`;
}

function overview(): string {
  const system = (state.system ?? state.health ?? {}) as Record<string, unknown>;
  const machine = (system.machine ?? {}) as Record<string, unknown>;
  return `
    <header><div><p class="eyebrow">LOCAL-FIRST MOTION INFRASTRUCTURE</p><h1>系统与能力</h1></div>
      <button class="primary" id="refresh" ${state.systemLoading ? "disabled" : ""}>${state.systemLoading ? "检测中…" : "重新检测"}</button></header>
    <section class="metric-grid">
      <article><small>版本</small><strong>${escapeHtml(system.version ?? "—")}</strong></article>
      <article><small>平台</small><strong>${escapeHtml(machine.platform ?? "—")}</strong></article>
      <article><small>真实运行时模型</small><strong>${availableModels().length}</strong></article>
      <article><small>活动 Worker</small><strong>${escapeHtml(system.active_workers ?? 0)}</strong></article>
    </section>
    <section class="panel"><h2>VIREA_HOME</h2><code>${escapeHtml(system.virea_home ?? "尚未读取")}</code>
      <div class="actions"><button id="setup-plan">查看设置计划</button><button id="setup-apply">初始化用户目录</button></div>
      <pre id="setup-output"></pre></section>`;
}

function catalog(): string {
  const models = catalogModels();
  return `
    <header><div><p class="eyebrow">VERIFIED MODEL CATALOG</p><h1>模型目录</h1></div></header>
    <div class="notice">目录同时展示可执行模型与已核实但仍被上游完整性、许可或运行时阻断的模型；只有具备真实 Worker 和 production acceptance 的条目才能安装。</div>
    <section class="cards">${
      models.length
        ? models
            .map((item) => {
              const installed = modelReady(item);
              const installState = currentInstallationState(item);
              const runnable = realRunnableModels([item]).length === 1;
              const installable = runnable && item.production_acceptance != null;
              const option = selectedExecutionOption(item.model.id);
              const boundary = [item.resources.integration_state, item.resources.license_status]
                .filter((value): value is string => typeof value === "string" && value.length > 0)
                .join(" · ");
              return `<article class="model-card">
                <div><span class="badge ${item.model.status}">${statusLabel(item.model.status)}</span>${
                  installState ? `<span class="badge install">${escapeHtml(installState)}</span>` : ""
                }</div>
                <h2>${escapeHtml(item.model.display_name)}</h2><code>${escapeHtml(item.model.id)}</code>
                <p>${item.model.tasks.map(escapeHtml).join(" · ")}</p>
                <small>Adapter: ${escapeHtml(item.model.adapter_family)}</small>
                <small>Runtime: ${item.runtime_variants.length ? item.runtime_variants.map((runtime) => escapeHtml(`${runtime.id}@${runtime.project_version ?? "unversioned"} [core ${runtime.runtime_core_epoch ?? "undeclared"}]`)).join(" · ") : "尚无可执行 runtime"}</small>
                <small>所选环境: ${option ? escapeHtml(`${option.status} · ${option.selected_runtime_id ?? "未实现"} · ${option.selected_resource_profile ?? "无可用 profile"}${option.reasons.length ? ` · ${option.reasons.join("; ")}` : ""}`) : "安装前将由服务核验"}</small>
                <small>Source → Target: ${escapeHtml(modelMotionRoute(item))}</small>
                ${boundary ? `<small>Boundary: ${escapeHtml(boundary)}</small>` : ""}
                <button data-install="${escapeHtml(item.model.id)}" ${installed || !installable || !state.selectedExecutionDomainId ? "disabled" : ""}>${
                  installed ? "已就绪" : installable ? "安装并执行真实验收" : "当前不可安装"
                }</button>
              </article>`;
            })
            .join("")
        : '<p class="empty">服务当前没有返回正式模型目录。请检查已安装资源。</p>'
    }</section>`;
}

function playground(): string {
  ensureSelectedModel();
  const models = availableModels();
  const selected = models.find((item) => item.model.id === state.selectedModelId) ?? null;
  let defaults = { prompt: "", seconds: 4, seed: 42 };
  if (selected) {
    try {
      defaults = generationDefaults(selected);
    } catch (error) {
      state.error = errorMessage(error);
    }
  }
  return `
    <header><div><p class="eyebrow">MODELRESULT → MOTION IR → VRMA</p><h1>Playground</h1></div></header>
    <section class="panel playground">
      <label>真实模型<select id="model-id" ${models.length ? "" : "disabled"}>${models
        .map(
          (item) =>
            `<option value="${escapeHtml(item.model.id)}" ${item.model.id === state.selectedModelId ? "selected" : ""}>${escapeHtml(item.model.display_name)} · ${modelReady(item) ? "READY" : "需安装"}</option>`,
        )
        .join("")}</select></label>
      <label>Prompt<textarea id="prompt">${escapeHtml(defaults.prompt)}</textarea></label>
      <div class="field-row">
        <label>时长（秒）<input id="seconds" type="number" min="1" max="90" step="0.01" value="${escapeHtml(defaults.seconds)}" /></label>
        <label>Seed<input id="seed" type="number" min="0" max="2147483647" step="1" value="${escapeHtml(defaults.seed)}" /></label>
      </div>
      <button class="primary" id="generate" ${models.length && state.selectedExecutionDomainId ? "" : "disabled"}>生成真实动作</button>
      <pre id="generation-output"></pre>
      <div id="result-actions" class="result-actions"></div>
    </section>`;
}

function viewerResultInfo(): string {
  const result = state.lastResult;
  if (!result) return "尚未从生成任务取得结果；也可以手动载入本地 VRMA。";
  const modelResult = state.lastModelResult;
  const identity = result.identity;
  const model = identity
    ? `${identity.model_id}@${identity.model_version}`
    : modelResult?.model.id ?? state.lastGeneration?.modelId ?? "—";
  const execution = identity
    ? `${identity.execution_domain_id ?? "legacy-domain"} · ${identity.runtime_variant_id} · ${identity.resource_profile_id}/${identity.memory_strategy} @ ${identity.device}`
    : "legacy result identity";
  return `模型 ${escapeHtml(model)} · ${escapeHtml(resultMotionRoute(result, modelResult))} · ${escapeHtml(execution)} · Actor ${escapeHtml(result.actor_ids.join(", "))} · 帧 ${escapeHtml(modelResult?.native.frame_count ?? "—")} · 结果 ${escapeHtml(result.result_id)}`;
}

function viewer(): string {
  return `
    <header><div><p class="eyebrow">VRM 1.0 AVATAR + VRMC_VRM_ANIMATION</p><h1>真实 VRMA Viewer</h1></div></header>
    <section class="viewer-toolbar panel">
      <label>本地 Avatar（.vrm / 含 VRM 扩展的 .glb）<input id="avatar-file" type="file" accept=".vrm,.glb,model/gltf-binary" /></label>
      <label>本地动作（可选 .vrma）<input id="vrma-file" type="file" accept=".vrma,model/gltf-binary" /></label>
      <button id="viewer-play">重新播放</button>
    </section>
    <section class="viewer-panel"><canvas id="vrm-canvas" aria-label="真实 VRM 动作播放器"></canvas></section>
    <section class="viewer-readout panel">
      <div id="viewer-status" class="viewer-status idle">等待载入 Avatar</div>
      <div>${viewerResultInfo()}</div>
      ${state.lastVrmaUrl ? `<a href="${escapeHtml(state.lastVrmaUrl)}" download>下载本次真实 VRMA</a>` : ""}
    </section>`;
}

function jobs(): string {
  return `
    <header><div><p class="eyebrow">APPEND-ONLY JOB EVENTS</p><h1>任务历史</h1></div><button id="refresh-jobs">刷新</button></header>
    <section class="panel table-wrap"><table><thead><tr><th>ID</th><th>模型</th><th>任务</th><th>状态</th><th>错误</th></tr></thead>
      <tbody>${state.jobs
        .map(
          (job) => `<tr><td><code>${escapeHtml(job.id)}</code></td><td>${escapeHtml(job.model_id)}</td><td>${escapeHtml(job.task)}</td><td><span class="job-state">${escapeHtml(job.state)}</span></td><td>${escapeHtml(job.error_code ?? "")}</td></tr>`,
        )
        .join("")}</tbody></table></section>`;
}

function diagnostics(): string {
  return `
    <header><div><p class="eyebrow">REDACTED LOCAL EVIDENCE</p><h1>诊断</h1></div></header>
    <section class="panel"><p>Support bundle 不收集 prompt、token、原始音频或模型权重。</p>
      <button id="support">生成本地 Support Bundle</button><pre id="support-output"></pre></section>`;
}

function render(): void {
  viewerRuntime?.dispose();
  viewerRuntime = null;
  const content = {
    overview: overview(),
    catalog: catalog(),
    playground: playground(),
    viewer: viewer(),
    jobs: jobs(),
    diagnostics: diagnostics(),
  }[state.view];
  app.innerHTML = layout(content);
  bind();
}

function output(id: string, value: unknown): void {
  const node = document.querySelector<HTMLElement>(`#${id}`);
  if (node) node.textContent = JSON.stringify(value, null, 2);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function bind(): void {
  document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view as View;
      state.error = "";
      render();
    });
  });
  document.querySelector("#refresh")?.addEventListener("click", () => void refreshSystem());
  document.querySelector("#setup-plan")?.addEventListener("click", async () => output("setup-output", await api.setupPlan()));
  document.querySelector("#setup-apply")?.addEventListener("click", async () => output("setup-output", await api.setupApply()));
  document.querySelectorAll<HTMLButtonElement>("[data-install]").forEach((button) => {
    button.addEventListener("click", () => void installModel(button));
  });
  document.querySelector<HTMLSelectElement>("#global-execution-domain")?.addEventListener("change", (event) => {
    state.selectedExecutionDomainId = (event.currentTarget as HTMLSelectElement).value;
    state.error = "";
    render();
  });
  document.querySelector("#generate")?.addEventListener("click", () => void generate());
  document.querySelector<HTMLSelectElement>("#model-id")?.addEventListener("change", (event) => {
    state.selectedModelId = (event.currentTarget as HTMLSelectElement).value;
    state.error = "";
    void loadExecutionOptions(state.selectedModelId)
      .catch((error: unknown) => {
        state.error = errorMessage(error);
      })
      .finally(render);
  });
  document.querySelector("#refresh-jobs")?.addEventListener("click", () => void refreshJobs());
  document.querySelector("#support")?.addEventListener("click", async () => output("support-output", await api.supportBundle()));
  if (state.view === "viewer") bindViewer();
}

function bindViewer(): void {
  const canvas = document.querySelector<HTMLCanvasElement>("#vrm-canvas");
  if (!canvas) return;
  const setStatus = (status: ViewerStatus): void => {
    const node = document.querySelector<HTMLElement>("#viewer-status");
    if (!node) return;
    node.className = `viewer-status ${status.kind}`;
    node.textContent = status.duration == null ? status.message : `${status.message} · ${status.duration.toFixed(2)} 秒`;
  };
  const handle = async (action: () => Promise<void> | void): Promise<void> => {
    try {
      await action();
    } catch (error) {
      setStatus({ kind: "error", message: errorMessage(error) });
    }
  };
  viewerRuntime = new RealVrmViewer(canvas, setStatus);
  document.querySelector<HTMLInputElement>("#avatar-file")?.addEventListener("change", (event) => {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (file) void handle(() => viewerRuntime?.loadAvatarFile(file));
  });
  document.querySelector<HTMLInputElement>("#vrma-file")?.addEventListener("change", (event) => {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (file) void handle(() => viewerRuntime?.loadAnimationFile(file));
  });
  document.querySelector("#viewer-play")?.addEventListener("click", () => void handle(() => viewerRuntime?.play()));
  if (state.lastVrmaUrl) void handle(() => viewerRuntime?.loadAnimation(state.lastVrmaUrl));
}

async function installModel(button: HTMLButtonElement): Promise<void> {
  const id = button.dataset.install;
  if (!id) return;
  button.disabled = true;
  button.textContent = "正在安装与真实验收…";
  try {
    const manifest = state.models.find((item) => item.model.id === id);
    if (!manifest) throw new Error(`模型目录中不存在 ${id}`);
    const target = selectedExecutionTarget();
    await loadExecutionOptions(id);
    const option = selectedExecutionOption(id);
    if (!option?.implemented || !option.can_build) {
      throw new Error(
        option?.reasons.join("; ") || `${id} 尚未在 ${target.execution_domain_id} 实现可部署 Runtime`,
      );
    }
    const result = await api.install(manifest, target);
    if (typeof result.state === "string") state.installationStates[id] = result.state;
    window.alert(JSON.stringify(result, null, 2));
    state.models = await api.models();
    state.error = "";
  } catch (error) {
    state.error = errorMessage(error);
  }
  render();
}

async function refreshSystem(): Promise<void> {
  state.systemLoading = true;
  state.error = "";
  state.executionOptions = {};
  render();
  const previousExecutionDomainId = state.selectedExecutionDomainId;
  const [systemResult, domainResult] = await Promise.allSettled([
    api.system(),
    api.executionDomains(),
  ]);
  if (systemResult.status === "fulfilled") {
    state.system = systemResult.value;
  }
  if (domainResult.status === "fulfilled") {
    state.executionDomains = domainResult.value;
    state.selectedExecutionDomainId = previousExecutionDomainId;
    ensureSelectedExecutionDomain();
  } else {
    state.executionDomains = null;
    state.selectedExecutionDomainId = "";
  }
  const firstFailure = [systemResult, domainResult].find((item) => item.status === "rejected");
  state.error = firstFailure?.status === "rejected" ? errorMessage(firstFailure.reason) : "";
  state.systemLoading = false;
  render();
}

async function refreshJobs(): Promise<void> {
  try {
    state.jobs = await api.jobs();
    state.error = "";
  } catch (error) {
    state.error = errorMessage(error);
  }
  render();
}

async function generate(): Promise<void> {
  const modelId = document.querySelector<HTMLSelectElement>("#model-id")?.value ?? "";
  const prompt = document.querySelector<HTMLTextAreaElement>("#prompt")?.value ?? "";
  const seconds = Number(document.querySelector<HTMLInputElement>("#seconds")?.value ?? 2);
  const seed = Number(document.querySelector<HTMLInputElement>("#seed")?.value ?? 42);
  const button = document.querySelector<HTMLButtonElement>("#generate");
  if (button) button.disabled = true;
  state.selectedModelId = modelId;
  try {
    const manifest = state.models.find((item) => item.model.id === modelId);
    if (!manifest) throw new Error(`模型目录中不存在 ${modelId}`);
    const target = selectedExecutionTarget();
    await loadExecutionOptions(modelId);
    const option = selectedExecutionOption(modelId);
    if (!option?.implemented || !option.can_build) {
      throw new Error(
        option?.reasons.join("; ") || `${modelId} 尚未在 ${target.execution_domain_id} 实现可运行 Runtime`,
      );
    }
    let job = await api.generate(manifest, prompt, seconds, seed, target);
    output("generation-output", job);
    while (!["SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT", "REJECTED"].includes(job.state)) {
      await new Promise((resolve) => window.setTimeout(resolve, 750));
      job = await api.job(job.id);
      output("generation-output", job);
    }
    if (job.state !== "SUCCEEDED") {
      throw new Error(`${job.state}: ${job.error_code ?? "GENERATION_FAILED"} ${job.error_message ?? ""}`.trim());
    }
    const result = await api.result(job.id);
    const vrma = firstVrmaExport(result);
    const modelResultLocator = result.tracks.model_result;
    if (!modelResultLocator) throw new Error("任务结果缺少 ModelResult track，无法核对真实帧数与模型来源");
    const modelResult = await api.modelResultArtifact(result.result_id, modelResultLocator);
    state.lastResult = result;
    state.lastModelResult = modelResult;
    state.lastVrmaUrl = artifactUrl(result.result_id, vrma.locator);
    state.lastGeneration = { modelId, seconds, seed };
    output("generation-output", { job, model_result: modelResult, result, vrma_url: state.lastVrmaUrl });
    const actions = document.querySelector<HTMLElement>("#result-actions");
    if (actions) {
      actions.innerHTML = `<a href="${escapeHtml(state.lastVrmaUrl)}" download>下载真实 VRMA</a><button id="open-viewer">在 Viewer 播放</button>`;
      document.querySelector("#open-viewer")?.addEventListener("click", () => {
        state.view = "viewer";
        render();
      });
    }
  } catch (error) {
    output("generation-output", { error: errorMessage(error) });
  } finally {
    if (button) button.disabled = false;
  }
}

async function loadPersistedSuccessfulJob(jobId: string): Promise<void> {
  const job = await api.job(jobId);
  if (job.state !== "SUCCEEDED") {
    throw new Error(`${jobId} 不是 SUCCEEDED，不能载入 Viewer`);
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
  state.selectedModelId = job.model_id;
  state.lastResult = result;
  state.lastModelResult = modelResult;
  state.lastVrmaUrl = artifactUrl(result.result_id, vrma.locator);
  state.lastGeneration = {
    modelId: job.model_id,
    seconds: modelResult.native.fps
      ? modelResult.native.frame_count / modelResult.native.fps
      : 0,
    seed: 0,
  };
  state.view = "viewer";
}

async function bootstrap(): Promise<void> {
  const [healthResult, domainResult, modelResult, jobResult] = await Promise.allSettled([
    api.health(),
    api.executionDomains(),
    api.models(),
    api.jobs(),
  ]);
  if (healthResult.status === "fulfilled") state.health = healthResult.value;
  if (domainResult.status === "fulfilled") state.executionDomains = domainResult.value;
  if (modelResult.status === "fulfilled") state.models = modelResult.value;
  if (jobResult.status === "fulfilled") state.jobs = jobResult.value;
  ensureSelectedExecutionDomain();
  ensureSelectedModel();
  const firstFailure = [healthResult, domainResult, modelResult, jobResult].find((item) => item.status === "rejected");
  if (firstFailure?.status === "rejected") state.error = String(firstFailure.reason);
  const persistedJobId = new URLSearchParams(window.location.search).get("job");
  if (persistedJobId) {
    try {
      await loadPersistedSuccessfulJob(persistedJobId);
      state.error = "";
    } catch (error) {
      state.error = errorMessage(error);
    }
  }
  render();
}

void bootstrap();

export { escapeHtml, statusLabel };
