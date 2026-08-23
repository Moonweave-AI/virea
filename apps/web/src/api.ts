import type {
  ExecutionDomainCandidates,
  ExecutionTargetSelection,
  JobRecord,
  ModelExecutionOptions,
  ModelManifest,
  ModelResult,
  SourceSkeletonPreview,
  VrmMotionResult,
  StateRevision,
} from "./contracts";
import {
  artifactBasename,
  artifactUrl,
  createGenerationPayload,
  createInstallPayload,
} from "./domain";
import { request } from "./http";
export type { JobRecord, ModelManifest } from "./contracts";
export { request } from "./http";

export interface HealthStatus {
  schema_version: "virea.health.v1.0.0";
  version: string;
  status: "ready";
  control_plane_ready: true;
}

const HEALTH_TIMEOUT_MS = 5_000;
const SYSTEM_DIAGNOSTIC_TIMEOUT_MS = 180_000;

function installTimeout(manifest: ModelManifest): number {
  const acceptanceTimeoutSeconds = Number(manifest.production_acceptance?.timeout_seconds);
  return Number.isFinite(acceptanceTimeoutSeconds) && acceptanceTimeoutSeconds > 0
    ? Math.ceil(acceptanceTimeoutSeconds * 1_000) + 120_000
    : SYSTEM_DIAGNOSTIC_TIMEOUT_MS;
}

export const api = {
  health: () => request<HealthStatus>("/health", {}, { timeoutMs: HEALTH_TIMEOUT_MS }),
  stateRevision: () => request<StateRevision>("/state", {}, { timeoutMs: HEALTH_TIMEOUT_MS }),
  system: (timeoutMs = SYSTEM_DIAGNOSTIC_TIMEOUT_MS) =>
    request<Record<string, unknown>>("/system", {}, { timeoutMs }),
  executionDomains: () =>
    request<ExecutionDomainCandidates>("/execution-domains", {}, { timeoutMs: 60_000 }),
  setupPlan: () => request<Record<string, unknown>>("/setup/plan", { method: "POST" }),
  setupApply: () => request<Record<string, unknown>>("/setup/apply", { method: "POST" }),
  models: () => request<ModelManifest[]>("/models"),
  executionOptions: (modelId: string) =>
    request<ModelExecutionOptions>(`/models/${encodeURIComponent(modelId)}/execution-options`, {}, { timeoutMs: 60_000 }),
  install: (manifest: ModelManifest, executionTarget: ExecutionTargetSelection) =>
    request<Record<string, unknown>>("/models/install", {
      method: "POST",
      body: JSON.stringify(createInstallPayload(manifest, executionTarget)),
    }, { timeoutMs: installTimeout(manifest) }),
  jobs: () => request<JobRecord[]>("/jobs"),
  job: (jobId: string) => request<JobRecord>(`/jobs/${encodeURIComponent(jobId)}`),
  generate: (
    manifest: ModelManifest,
    prompt: string,
    seconds: number,
    seed: number,
    executionTarget: ExecutionTargetSelection,
  ) =>
    request<JobRecord>("/jobs", {
      method: "POST",
      body: JSON.stringify(createGenerationPayload(manifest, prompt, seconds, seed, executionTarget)),
    }),
  result: (jobId: string) => request<VrmMotionResult>(`/jobs/${encodeURIComponent(jobId)}/result`),
  sourceSkeleton: (resultId: string) =>
    request<SourceSkeletonPreview>(
      `/results/${encodeURIComponent(resultId)}/source-skeleton`,
    ),
  modelResultArtifact: (resultId: string, locator: string) =>
    request<ModelResult>(
      `/results/${encodeURIComponent(resultId)}/artifacts/${encodeURIComponent(artifactBasename(locator))}`,
    ),
  artifactUrl,
  cancel: (jobId: string) =>
    request<JobRecord>(`/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" }),
  supportBundle: () =>
    request<Record<string, unknown>>("/support-bundles", { method: "POST" }),
};

export function stateEventsUrl(): string {
  const url = new URL("/api/v1/state/events", window.location.origin);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return url.href;
}
