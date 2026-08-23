import type {
  ExportRecord,
  JobRecord,
  ModelInstallPayload,
  ModelManifest,
  ModelResult,
  ExecutionTargetSelection,
  VrmMotionResult,
  WebGenerationJobRequest,
} from "./contracts";

const TEST_ONLY_PATTERN = /(?:^|[-_.])(fake|mock|synthetic)(?:$|[-_.])/i;

export function isProductionCatalogModel(manifest: ModelManifest): boolean {
  const identity = `${manifest.model.id} ${manifest.model.adapter_family}`;
  return !TEST_ONLY_PATTERN.test(identity);
}

export function productionCatalogModels(manifests: ModelManifest[]): ModelManifest[] {
  return manifests.filter(isProductionCatalogModel);
}

export function productionCatalogJobs(
  jobs: JobRecord[],
  manifests: ModelManifest[],
): JobRecord[] {
  const modelIds = new Set(productionCatalogModels(manifests).map((manifest) => manifest.model.id));
  return jobs.filter((job) => modelIds.has(job.model_id));
}

export function isRealRunnableModel(manifest: ModelManifest): boolean {
  if (!isProductionCatalogModel(manifest)) return false;
  return manifest.runtime_variants.some((runtime) => {
    const runtimeIdentity = `${runtime.id} ${runtime.entrypoint_argv.join(" ")}`;
    return !TEST_ONLY_PATTERN.test(runtimeIdentity);
  });
}

export function realRunnableModels(manifests: ModelManifest[]): ModelManifest[] {
  return manifests.filter(isRealRunnableModel);
}

export function installationState(manifest: ModelManifest): string | null {
  return manifest.installation?.state ?? manifest.installation_state ?? null;
}

export function isInstalledReady(manifest: ModelManifest): boolean {
  if (typeof manifest.installation?.ready === "boolean") {
    return manifest.installation.ready;
  }
  const installState = installationState(manifest)?.toUpperCase();
  if (installState != null) return installState === "READY";
  return manifest.runtime_variants.some((runtime) =>
    ["READY", "AVAILABLE", "DETECTED"].includes(runtime.availability.toUpperCase()),
  );
}

export function artifactBasename(locator: string): string {
  const normalized = locator.replaceAll("\\", "/");
  const name = normalized.slice(normalized.lastIndexOf("/") + 1);
  if (!name) throw new Error("制品 locator 不包含文件名");
  return name;
}

export function artifactUrl(resultId: string, locator: string): string {
  return `/api/v1/results/${encodeURIComponent(resultId)}/artifacts/${encodeURIComponent(artifactBasename(locator))}`;
}

export function firstVrmaExport(result: VrmMotionResult): ExportRecord {
  const record = result.exports.find(
    (item) => item.format.toLowerCase() === "vrma" || item.locator.toLowerCase().endsWith(".vrma"),
  );
  if (!record) throw new Error("任务结果没有 VRMA export，无法播放");
  return record;
}

export function modelMotionRoute(manifest: ModelManifest): string {
  return `${manifest.output.representation_id} / ${manifest.output.skeleton_id} → ${manifest.result_target.representation_id} / ${manifest.result_target.skeleton_id}`;
}

export function resultMotionRoute(
  result: VrmMotionResult,
  modelResult: ModelResult | null,
): string {
  const identity = result.identity;
  if (identity) {
    return `${identity.native_representation_id} / ${identity.native_skeleton_id} → ${identity.target_representation_id} / ${identity.target_skeleton_id}`;
  }
  if (modelResult) {
    return `${modelResult.native.representation_id} / ${modelResult.native.skeleton_id} → legacy target / ${result.avatar_profile}`;
  }
  return `legacy source → legacy target / ${result.avatar_profile}`;
}

export function createInstallPayload(
  manifest: ModelManifest,
  executionTarget: ExecutionTargetSelection,
): ModelInstallPayload {
  const acceptance = manifest.production_acceptance;
  if (!acceptance) {
    throw new Error(`${manifest.model.id} 没有 production acceptance，不能执行真实安装验收`);
  }
  if (
    acceptance.schema_version !== "virea.production_e2e_acceptance.v1.0.0" ||
    acceptance.kind !== "production_e2e"
  ) {
    throw new Error(`${manifest.model.id} 的 production acceptance 契约版本无效`);
  }
  const request = acceptance.request;
  if (request.schema_version !== "virea.job_request.v1.0.0") {
    throw new Error(`${manifest.model.id} 的验收 JobRequest 版本无效`);
  }
  if (request.model_id !== manifest.model.id) {
    throw new Error(`${manifest.model.id} 的验收请求 model_id 不一致`);
  }
  if (request.task !== manifest.model.tasks[0]) {
    throw new Error(`${manifest.model.id} 的验收 task 必须是该 runtime 的首个声明任务`);
  }
  if (request.avatar_id !== null || request.idempotency_key !== null) {
    throw new Error(`${manifest.model.id} 的安装验收当前只支持空 avatar_id 和 idempotency_key`);
  }
  const prompt = request.input.prompt;
  if (typeof prompt !== "string" || !prompt.trim() || prompt.length > 8_000) {
    throw new Error(`${manifest.model.id} 的验收 prompt 必须是 1 到 8000 字符的非空字符串`);
  }
  const timeout = acceptance.timeout_seconds;
  if (typeof timeout !== "number" || !Number.isFinite(timeout) || timeout <= 0 || timeout > 7_200) {
    throw new Error(`${manifest.model.id} 的验收 timeout 必须大于 0 且不超过 7200 秒`);
  }
  return {
    model_id: request.model_id,
    apply: true,
    validation_timeout: timeout,
    execution_target: executionTarget,
  };
}

export interface GenerationDefaults {
  prompt: string;
  seconds: number;
  seed: number;
}

export function generationDefaults(manifest: ModelManifest): GenerationDefaults {
  const acceptance = manifest.production_acceptance;
  if (!acceptance || acceptance.request.model_id !== manifest.model.id) {
    throw new Error(`${manifest.model.id} 没有可执行的 production acceptance`);
  }
  const { input, parameters } = acceptance.request;
  const prompt = input.prompt;
  const fps = parameters.fps;
  const seed = parameters.seed;
  if (typeof prompt !== "string" || !prompt.trim()) {
    throw new Error(`${manifest.model.id} 的 production acceptance prompt 无效`);
  }
  if (typeof fps !== "number" || !Number.isFinite(fps) || fps <= 0) {
    throw new Error(`${manifest.model.id} 的 production acceptance fps 必须是正有限数`);
  }
  if (typeof seed !== "number" || !Number.isSafeInteger(seed) || seed < 0) {
    throw new Error(`${manifest.model.id} 的 production acceptance seed 无效`);
  }
  let seconds: unknown = parameters.seconds;
  if (seconds == null && typeof input.motion_length_frames === "number") {
    seconds = input.motion_length_frames / fps;
  }
  if (seconds == null && typeof parameters.motion_length_frames === "number") {
    seconds = parameters.motion_length_frames / fps;
  }
  if (seconds == null && typeof parameters.num_frames === "number") {
    seconds = parameters.num_frames / fps;
  }
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) {
    throw new Error(`${manifest.model.id} 的 production acceptance 缺少可映射的时长`);
  }
  return { prompt: prompt.trim(), seconds, seed };
}

function setDuration(
  request: WebGenerationJobRequest,
  seconds: number,
  fps: number,
  modelId: string,
): void {
  if (Object.hasOwn(request.parameters, "seconds")) {
    request.parameters.seconds = seconds;
    return;
  }
  const framesFloat = seconds * fps;
  const frames = Math.round(framesFloat);
  if (Math.abs(framesFloat - frames) > 1e-6) {
    throw new Error(`${modelId} 的时长与 fps 不能形成整数帧`);
  }
  if (Object.hasOwn(request.input, "motion_length_frames")) {
    request.input.motion_length_frames = frames;
    return;
  }
  if (Object.hasOwn(request.parameters, "motion_length_frames")) {
    request.parameters.motion_length_frames = frames;
    return;
  }
  if (Object.hasOwn(request.parameters, "num_frames")) {
    request.parameters.num_frames = frames;
    return;
  }
  throw new Error(`${modelId} 的 production acceptance 没有可映射的时长字段`);
}

export function createGenerationPayload(
  manifest: ModelManifest,
  prompt: string,
  seconds: number,
  seed: number,
  executionTarget: ExecutionTargetSelection,
): WebGenerationJobRequest {
  const modelId = manifest.model.id;
  if (!modelId) throw new Error("请选择真实可运行模型");
  if (!prompt.trim()) throw new Error("Prompt 不能为空");
  if (!Number.isFinite(seconds) || seconds < 1 || seconds > 90) {
    throw new Error("时长必须在 1 到 90 秒之间");
  }
  if (!Number.isSafeInteger(seed) || seed < 0 || seed > 2_147_483_647) {
    throw new Error("Seed 必须是 0 到 2147483647 的整数");
  }
  const acceptance = manifest.production_acceptance;
  if (!acceptance || acceptance.request.model_id !== modelId) {
    throw new Error(`${modelId} 没有与模型一致的 production acceptance，不能生成可追溯请求`);
  }
  const template = acceptance.request;
  if (
    template.schema_version !== "virea.job_request.v1.0.0" ||
    template.task !== "text_to_motion" ||
    template.avatar_id !== null ||
    template.idempotency_key !== null
  ) {
    throw new Error(`${modelId} 的 production acceptance 不是可执行的 Web JobRequest`);
  }
  const fps = template.parameters.fps;
  if (typeof fps !== "number" || !Number.isFinite(fps) || fps <= 0) {
    throw new Error(`${modelId} 的 production acceptance fps 必须是正有限数`);
  }
  const request: WebGenerationJobRequest = structuredClone(template) as WebGenerationJobRequest;
  request.input.prompt = prompt.trim();
  if (!Object.hasOwn(request.parameters, "seed")) {
    throw new Error(`${modelId} 的 production acceptance 缺少 parameters.seed`);
  }
  request.parameters.seed = seed;
  request.execution_target = executionTarget;
  setDuration(request, seconds, fps, modelId);
  return request;
}
