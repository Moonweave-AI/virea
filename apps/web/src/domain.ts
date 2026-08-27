import type {
  ExportRecord,
  JobRecord,
  ManifestInputField,
  ManifestInputSchema,
  ModelInstallPayload,
  ModelManifest,
  ModelResult,
  ProductionE2EAcceptance,
  ExecutionTargetSelection,
  VrmMotionResult,
  WebGenerationJobRequest,
} from "./contracts";

const TEST_ONLY_PATTERN = /(?:^|[-_.])(fake|mock|synthetic)(?:$|[-_.])/i;

export function isProductionCatalogModel(manifest: ModelManifest): boolean {
  if (manifest.test_only === true) return false;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function assertProductionAcceptanceContract(
  manifest: ModelManifest,
  contract: ProductionE2EAcceptance,
  task: string,
): void {
  const modelId = manifest.model.id;
  if (
    contract?.schema_version !== "virea.production_e2e_acceptance.v1.0.0"
    || contract.kind !== "production_e2e"
  ) {
    throw new Error(`${modelId} 的 production acceptance 契约版本无效`);
  }
  const request = contract.request;
  if (!request || request.schema_version !== "virea.job_request.v1.0.0") {
    throw new Error(`${modelId} 的验收 JobRequest 版本无效`);
  }
  if (request.model_id !== modelId) {
    throw new Error(`${modelId} 的验收请求 model_id 不一致`);
  }
  if (request.task !== task) {
    throw new Error(`${modelId} 的验收 task ${request.task} 与声明顺序 ${task} 不一致`);
  }
  if (!isRecord(request.input) || !isRecord(request.parameters)) {
    throw new Error(`${modelId} 的验收 JobRequest input/parameters 必须是对象`);
  }
  if (request.avatar_id !== null || request.idempotency_key !== null) {
    throw new Error(`${modelId} 的验收 JobRequest 必须使用空 avatar_id 和 idempotency_key`);
  }
  if (
    typeof contract.timeout_seconds !== "number"
    || !Number.isFinite(contract.timeout_seconds)
    || contract.timeout_seconds <= 0
    || contract.timeout_seconds > 7_200
  ) {
    throw new Error(`${modelId} 的验收 timeout 必须大于 0 且不超过 7200 秒`);
  }
}

/**
 * Return the immutable task contracts in manifest task order. API catalog
 * responses expose the first suite item in the legacy field as a compatibility
 * projection, so the suite must take precedence whenever it is present.
 */
export function productionAcceptanceContracts(
  manifest: ModelManifest,
): readonly ProductionE2EAcceptance[] {
  const suite = manifest.production_acceptance_suite;
  let contracts: readonly ProductionE2EAcceptance[];
  if (suite != null) {
    if (
      suite.schema_version !== "virea.production_e2e_acceptance_suite.v1.0.0"
      || suite.kind !== "production_e2e_suite"
      || !Array.isArray(suite.contracts)
      || suite.contracts.length === 0
    ) {
      throw new Error(`${manifest.model.id} 的 production acceptance suite 契约无效`);
    }
    contracts = suite.contracts;
  } else {
    contracts = manifest.production_acceptance ? [manifest.production_acceptance] : [];
  }
  if (!contracts.length) return contracts;
  if (contracts.length !== manifest.model.tasks.length) {
    throw new Error(`${manifest.model.id} 必须为每个声明任务提供且仅提供一个 production acceptance`);
  }
  contracts.forEach((contract, index) => {
    assertProductionAcceptanceContract(manifest, contract, manifest.model.tasks[index]!);
  });
  return contracts;
}

export function productionAcceptanceForTask(
  manifest: ModelManifest,
  task: string,
): ProductionE2EAcceptance | null {
  return productionAcceptanceContracts(manifest).find(
    (contract) => contract.request.task === task,
  ) ?? null;
}

export function productionAcceptanceTimeoutSeconds(manifest: ModelManifest): number {
  return productionAcceptanceContracts(manifest).reduce(
    (total, contract) => total + contract.timeout_seconds,
    0,
  );
}

function safeProductionAcceptanceContracts(
  manifest: ModelManifest,
): readonly ProductionE2EAcceptance[] {
  try {
    return productionAcceptanceContracts(manifest);
  } catch {
    return [];
  }
}

/** A catalog entry is integrated only when VIREA owns a Runtime and real acceptance contract. */
export function isVireaIntegratedModel(manifest: ModelManifest): boolean {
  const hasRunnableContract = isRealRunnableModel(manifest)
    && safeProductionAcceptanceContracts(manifest).length > 0;
  if (typeof manifest.capability?.virea_integrated === "boolean") {
    return manifest.capability.virea_integrated && hasRunnableContract;
  }
  return hasRunnableContract;
}

export function vireaIntegratedModels(manifests: ModelManifest[]): ModelManifest[] {
  return manifests.filter(isVireaIntegratedModel);
}

export function modelCapabilityLabel(manifest: ModelManifest): string {
  return isVireaIntegratedModel(manifest)
    ? "VIREA integrated / 已接入"
    : "Upstream only / 仅上游登记";
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

/**
 * The catalog intentionally reconciles READY metadata without hashing large
 * snapshots. Execution remains fail-closed and performs the full verification.
 */
export function isInstallationIntegrityDeferred(manifest: ModelManifest): boolean {
  return isInstalledReady(manifest)
    && manifest.installation?.verification_scope === "metadata"
    && manifest.installation.integrity_verified !== true;
}

export function installationReadinessLabel(manifest: ModelManifest): string {
  if (!isInstalledReady(manifest)) return "Not READY / 未就绪";
  if (isInstallationIntegrityDeferred(manifest)) {
    return "Persisted READY · reverify on execution / 持久 READY · 执行前复验";
  }
  if (manifest.installation?.integrity_verified === true) {
    return "READY · integrity verified / READY · 已完整复验";
  }
  return "READY · verification scope undeclared / READY · 校验范围未声明";
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
  const contracts = productionAcceptanceContracts(manifest);
  if (!contracts.length) {
    throw new Error(`${manifest.model.id} 没有 production acceptance，不能执行真实安装验收`);
  }
  const legacyTimeout = manifest.production_acceptance_suite == null
    ? contracts[0]!.timeout_seconds
    : null;
  return {
    model_id: manifest.model.id,
    apply: true,
    ...(legacyTimeout == null ? {} : { validation_timeout: legacyTimeout }),
    execution_target: executionTarget,
  };
}

export interface GenerationFormDraft {
  task: string;
  values: Record<string, unknown>;
}

const FILE_FIELD_TYPES = new Set(["audio", "mono_pcm_audio", "mono_pcm_audio_stream"]);
const STRUCTURED_FIELD_TYPES = new Set([
  "mono_pcm_audio_stream",
  "normalized_half_open_interval",
  "remomask_part_motion_database",
  "text_segments",
  "text_stream",
  "world_space_constraints",
]);
const CONTENT_FIELD_NAMES = new Set([
  "action_and_expression_tags",
  "audio",
  "audio_chunks",
  "conditioning_actor_motion",
  "dialogue_text",
  "dialogue_turns",
  "edit_interval",
  "initial_motion",
  "prompt",
  "retrieval_database",
  "source_motion",
  "text_timeline",
  "transcript",
  "waypoints",
]);

function compatibilityInputSchema(
  contract: ProductionE2EAcceptance,
): ManifestInputSchema {
  const request = contract.request;
  return {
    schema_version: "virea.job_request.v1.0.0",
    task: request.task,
    fields: {
      ...(Object.hasOwn(request.input, "prompt")
        ? { prompt: { type: "string", required: true, maximum_length: 8_000 } }
        : {}),
      ...(Object.hasOwn(request.parameters, "seconds")
        || Object.hasOwn(request.input, "motion_length_frames")
        || Object.hasOwn(request.parameters, "motion_length_frames")
        || Object.hasOwn(request.parameters, "num_frames")
        ? { seconds: { type: "number", required: true, minimum: 1, maximum: 90 } }
        : {}),
      ...(Object.hasOwn(request.parameters, "seed")
        ? { seed: { type: "integer", required: true, minimum: 0, maximum: 2_147_483_647 } }
        : {}),
    },
  };
}

export function generationTaskSchemas(manifest: ModelManifest): ManifestInputSchema[] {
  const declared = Array.isArray(manifest.inputs)
    ? manifest.inputs.filter((schema) => (
      schema
      && schema.schema_version === "virea.job_request.v1.0.0"
      && typeof schema.task === "string"
      && schema.task.length > 0
      && manifest.model.tasks.includes(schema.task)
      && schema.fields
      && typeof schema.fields === "object"
    ))
    : [];
  const contracts = safeProductionAcceptanceContracts(manifest);
  if (!contracts.length) return declared;
  return contracts.map((contract) => (
    declared.find((schema) => schema.task === contract.request.task)
      ?? compatibilityInputSchema(contract)
  ));
}

function taskSchema(manifest: ModelManifest, task: string): ManifestInputSchema {
  const schema = generationTaskSchemas(manifest).find((candidate) => candidate.task === task);
  if (!schema) throw new Error(`${manifest.model.id} 未声明任务 ${task} 的 manifest.inputs schema`);
  return schema;
}

export function generationInputFields(
  manifest: ModelManifest,
  task: string,
): Array<[string, ManifestInputField]> {
  const fields = Object.entries(taskSchema(manifest, task).fields);
  // seconds is the user-facing alternative declared by these manifests. Showing
  // it together with motion_length_frames would submit a mutually exclusive pair.
  return fields.filter(([name]) => !(name === "motion_length_frames" && Object.hasOwn(
    taskSchema(manifest, task).fields,
    "seconds",
  )));
}

export function generationVisibleTaskSchemas(
  manifest: ModelManifest,
): ManifestInputSchema[] {
  return generationTaskSchemas(manifest).filter((schema) => schema.presentation?.hidden !== true);
}

export function generationVisibleInputFields(
  manifest: ModelManifest,
  task: string,
): Array<[string, ManifestInputField]> {
  return generationInputFields(manifest, task).filter(([, field]) => field.ui?.hidden !== true);
}

function matchingAcceptanceRequest(manifest: ModelManifest, task: string) {
  return productionAcceptanceForTask(manifest, task)?.request ?? null;
}

function requestDurationSeconds(manifest: ModelManifest, task: string): number | undefined {
  const request = matchingAcceptanceRequest(manifest, task);
  if (!request) return undefined;
  const direct = request.parameters.seconds;
  if (typeof direct === "number" && Number.isFinite(direct) && direct > 0) return direct;
  const fps = request.parameters.fps;
  if (typeof fps !== "number" || !Number.isFinite(fps) || fps <= 0) return undefined;
  const frames = request.input.motion_length_frames
    ?? request.parameters.motion_length_frames
    ?? request.parameters.num_frames;
  return typeof frames === "number" && Number.isFinite(frames) && frames > 0
    ? frames / fps
    : undefined;
}

function fieldDefault(
  manifest: ModelManifest,
  task: string,
  name: string,
  field: ManifestInputField,
): unknown {
  const request = matchingAcceptanceRequest(manifest, task);
  if (request && Object.hasOwn(request.input, name)) return structuredClone(request.input[name]);
  if (request && Object.hasOwn(request.parameters, name)) {
    return structuredClone(request.parameters[name]);
  }
  if (name === "seconds") return requestDurationSeconds(manifest, task) ?? "";
  if (Object.hasOwn(field, "default")) return structuredClone(field.default);
  if (field.type === "boolean") return false;
  return "";
}

export function generationFormDefaults(
  manifest: ModelManifest,
  requestedTask?: string,
): GenerationFormDraft {
  const schemas = generationTaskSchemas(manifest);
  if (!schemas.length) {
    throw new Error(`${manifest.model.id} 没有可呈现的 manifest.inputs schema`);
  }
  const acceptanceTask = safeProductionAcceptanceContracts(manifest)[0]?.request.task;
  const task = requestedTask
    ?? schemas.find((candidate) => candidate.task === acceptanceTask)?.task
    ?? schemas[0]!.task;
  if (!schemas.some((candidate) => candidate.task === task)) {
    throw new Error(`${manifest.model.id} 未声明任务 ${task} 的 manifest.inputs schema`);
  }
  const values = Object.fromEntries(
    generationInputFields(manifest, task).map(([name, field]) => [
      name,
      fieldDefault(manifest, task, name, field),
    ]),
  );
  return { task, values };
}

const OMIT_FIELD = Symbol("omit-field");

function fieldIsEmpty(value: unknown): boolean {
  return value == null || (typeof value === "string" && !value.trim());
}

function validateNumericField(
  value: number,
  name: string,
  field: ManifestInputField,
): void {
  if (typeof field.minimum === "number" && value < field.minimum) {
    throw new Error(`${name} 必须大于等于 ${field.minimum}`);
  }
  if (typeof field.maximum === "number" && value > field.maximum) {
    throw new Error(`${name} 必须小于等于 ${field.maximum}`);
  }
  if (typeof field.exclusive_minimum === "number" && value <= field.exclusive_minimum) {
    throw new Error(`${name} 必须大于 ${field.exclusive_minimum}`);
  }
  if (typeof field.multiple_of === "number" && field.multiple_of > 0) {
    const quotient = value / field.multiple_of;
    if (Math.abs(quotient - Math.round(quotient)) > 1e-7) {
      throw new Error(`${name} 必须是 ${field.multiple_of} 的倍数`);
    }
  }
}

function normalizedFieldValue(
  name: string,
  field: ManifestInputField,
  raw: unknown,
): unknown | typeof OMIT_FIELD {
  if (fieldIsEmpty(raw)) {
    if (field.required === true) throw new Error(`${name} 为必填项 / ${name} is required`);
    return OMIT_FIELD;
  }
  const fieldType = field.type ?? "structured";
  if (fieldType === "integer" || fieldType === "number") {
    const value = typeof raw === "number" ? raw : Number(raw);
    if (!Number.isFinite(value) || (fieldType === "integer" && !Number.isSafeInteger(value))) {
      throw new Error(`${name} 必须是${fieldType === "integer" ? "整数" : "有限数"}`);
    }
    validateNumericField(value, name, field);
    return value;
  }
  if (fieldType === "boolean") {
    if (typeof raw === "boolean") return raw;
    if (typeof raw === "string" && ["true", "1", "yes", "y"].includes(raw.toLowerCase())) {
      return true;
    }
    if (typeof raw === "string" && ["false", "0", "no", "n"].includes(raw.toLowerCase())) {
      return false;
    }
    throw new Error(`${name} 必须是布尔值 / must be boolean`);
  }
  if (
    STRUCTURED_FIELD_TYPES.has(fieldType)
    || field.representation_id
  ) {
    if (typeof raw !== "string") return raw;
    const value = raw.trim();
    if (value.startsWith("{") || value.startsWith("[")) {
      try {
        const parsed = JSON.parse(value) as unknown;
        if (!parsed || typeof parsed !== "object") throw new Error("not structured");
        return parsed;
      } catch {
        throw new Error(`${name} 必须是有效 JSON，或服务端可访问的本地路径`);
      }
    }
    if (["\"", "'"].includes(value.at(0) ?? "") || ["\"", "'"].includes(value.at(-1) ?? "")) {
      throw new Error(`${name} 的本地路径不要包含首尾引号 / remove outer path quotes`);
    }
    return value;
  }
  const value = typeof raw === "string" ? raw.trim() : String(raw);
  if (
    FILE_FIELD_TYPES.has(fieldType)
    && (["\"", "'"].includes(value.at(0) ?? "") || ["\"", "'"].includes(value.at(-1) ?? ""))
  ) {
    throw new Error(`${name} 的本地路径不要包含首尾引号 / remove outer path quotes`);
  }
  if (typeof field.maximum_length === "number" && value.length > field.maximum_length) {
    throw new Error(`${name} 最多允许 ${field.maximum_length} 个字符`);
  }
  if (Array.isArray(field.enum) && !field.enum.includes(value)) {
    throw new Error(`${name} 必须选择 ${field.enum.map(String).join("、")}`);
  }
  return value;
}

function fieldDestination(
  name: string,
  field: ManifestInputField,
  originalInputNames: Set<string>,
  originalParameterNames: Set<string>,
): "input" | "parameters" {
  if (originalInputNames.has(name)) return "input";
  if (originalParameterNames.has(name)) return "parameters";
  const fieldType = field.type ?? "structured";
  return CONTENT_FIELD_NAMES.has(name)
    || FILE_FIELD_TYPES.has(fieldType)
    || STRUCTURED_FIELD_TYPES.has(fieldType)
    || Boolean(field.representation_id)
    ? "input"
    : "parameters";
}

function setManifestDuration(
  request: WebGenerationJobRequest,
  seconds: number,
  originalInputNames: Set<string>,
  originalParameterNames: Set<string>,
  modelId: string,
): void {
  if (originalParameterNames.has("seconds")) {
    request.parameters.seconds = seconds;
    return;
  }
  const fps = request.parameters.fps;
  if (
    originalInputNames.has("motion_length_frames")
    || originalParameterNames.has("motion_length_frames")
    || originalParameterNames.has("num_frames")
  ) {
    if (typeof fps !== "number" || !Number.isFinite(fps) || fps <= 0) {
      throw new Error(`${modelId} 的 duration 映射需要正有限数 fps`);
    }
    const framesFloat = seconds * fps;
    const frames = Math.round(framesFloat);
    if (Math.abs(framesFloat - frames) > 1e-6) {
      throw new Error(`${modelId} 的时长与 fps 不能形成整数帧`);
    }
    if (originalInputNames.has("motion_length_frames")) {
      request.input.motion_length_frames = frames;
    } else if (originalParameterNames.has("motion_length_frames")) {
      request.parameters.motion_length_frames = frames;
    } else {
      request.parameters.num_frames = frames;
    }
    return;
  }
  request.parameters.seconds = seconds;
}

export function createManifestGenerationPayload(
  manifest: ModelManifest,
  draft: GenerationFormDraft,
  executionTarget: ExecutionTargetSelection,
  idempotencyKey: string,
): WebGenerationJobRequest {
  const modelId = manifest.model.id;
  if (!modelId) throw new Error("请选择真实可运行模型");
  if (!isVireaIntegratedModel(manifest)) {
    throw new Error(`${modelId} 尚无 VIREA runtime/Worker，不能伪装为可生成状态`);
  }
  if (!manifest.model.tasks.includes(draft.task)) {
    throw new Error(`${modelId} 的 runtime 未声明任务 ${draft.task}`);
  }
  if (!idempotencyKey.trim() || idempotencyKey.length > 128) {
    throw new Error("生成请求缺少有效的幂等键");
  }
  const schema = taskSchema(manifest, draft.task);
  const template = matchingAcceptanceRequest(manifest, draft.task);
  if (!template) {
    throw new Error(`${modelId} 的任务 ${draft.task} 没有 immutable production acceptance request`);
  }
  const request = structuredClone(template) as WebGenerationJobRequest;
  const originalInputNames = new Set(Object.keys(request.input));
  const originalParameterNames = new Set(Object.keys(request.parameters));
  for (const name of Object.keys(schema.fields)) {
    delete request.input[name];
    delete request.parameters[name];
  }
  request.idempotency_key = idempotencyKey;
  request.execution_target = executionTarget;
  request.task = draft.task;
  for (const [name, field] of generationInputFields(manifest, draft.task)) {
    const value = normalizedFieldValue(name, field, draft.values[name]);
    if (value === OMIT_FIELD) continue;
    if (name === "seconds") {
      setManifestDuration(
        request,
        value as number,
        originalInputNames,
        originalParameterNames,
        modelId,
      );
      continue;
    }
    const destination = fieldDestination(
      name,
      field,
      originalInputNames,
      originalParameterNames,
    );
    request[destination][name] = value;
  }
  return request;
}
