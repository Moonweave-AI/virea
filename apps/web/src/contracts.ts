export const schemaVersions = {
  jobRequest: "virea.job_request.v1.0.0",
  modelDefinition: "virea.model_definition.v1.0.0",
  runtimeSpec: "virea.runtime_spec.v1.0.0",
  modelResult: "virea.model_result.v1.0.0",
  vrmMotionResult: "virea.vrm_motion_result.v1.0.0",
  resultIdentity: "virea.result_identity.v1.0.0",
  actorExportIdentity: "virea.actor_export_identity.v1.0.0",
  sourceSkeletonPreview: "virea.source_skeleton_preview.v1.0.0",
  workerProtocol: "virea.worker_protocol.v1.0.0",
  motionIr: "virea.motion_ir.v2.0.0",
  productionE2eAcceptance: "virea.production_e2e_acceptance.v1.0.0",
  productionE2eAcceptanceSuite: "virea.production_e2e_acceptance_suite.v1.0.0",
} as const;

export type ExecutionDomainKind = "windows-native" | "linux-native" | "macos-native" | "wsl";

export interface ExecutionTargetSelection {
  schema_version: "virea.execution_target_selection.v1.0.0";
  execution_domain_id: string;
  runtime_variant_id: string | null;
  resource_profile_id: string | null;
}

export interface ResolvedExecutionTarget {
  execution_domain: ExecutionDomainReport;
  runtime_variant_id: string;
  resource_profile_id: string;
  memory_strategy: MemoryStrategy;
  selected_accelerator: {
    kind: "cpu" | "nvidia" | "rocm" | "mps";
    name: string | null;
    physical_device_id: string;
    memory_free_bytes: number | null;
  } | null;
}

export interface ExecutionDomainReport {
  schema_version: "virea.execution_domain_report.v1.0.0";
  id: string;
  kind: ExecutionDomainKind;
  platform: string;
  architecture: string;
  is_host: boolean;
  distribution: string | null;
  warnings: string[];
}

export interface ExecutionDomainCandidates {
  schema_version: "virea.execution_domain_candidates.v1.0.0";
  report_id: string;
  recorded_at: string;
  host_execution_domain: string | null;
  execution_domains: ExecutionDomainReport[];
}

export interface StateRevision {
  schema_version: "virea.state_revision.v1.0.0";
  observed_at: string;
  events_url: string;
  virea_home: string;
  revision: {
    jobs: string;
    results: string;
    installations: string;
    models: string;
    workers: string;
  };
}

export interface ModelExecutionOption {
  execution_domain: ExecutionDomainReport;
  implemented: boolean;
  selected_runtime_id: string | null;
  status: string;
  can_build: boolean;
  reasons: string[];
  remediation: string[];
  selected_resource_profile: string | null;
  selected_memory_strategy: MemoryStrategy | null;
}

export interface ModelExecutionOptions {
  schema_version: "virea.model_execution_options.v1.0.0";
  model_id: string;
  report_id: string;
  options: ModelExecutionOption[];
}

export type ModelStatus =
  | "registered"
  | "source_available"
  | "runnable_upstream"
  | "integrated_experimental"
  | "supported"
  | "blocked";

export interface JobRequest {
  schema_version: typeof schemaVersions.jobRequest;
  model_id: string;
  task: string;
  input: Record<string, unknown>;
  parameters: Record<string, unknown>;
  avatar_id: string | null;
  idempotency_key: string | null;
  execution_target: ExecutionTargetSelection | null;
}

export interface WebGenerationJobRequest extends JobRequest {
  input: Record<string, unknown>;
  parameters: Record<string, unknown>;
  avatar_id: null;
  idempotency_key: string;
}

export interface ManifestInputField {
  type?: string;
  required?: boolean;
  default?: unknown;
  enum?: unknown[];
  description?: string;
  representation_id?: string;
  minimum?: number;
  maximum?: number;
  exclusive_minimum?: number;
  multiple_of?: number;
  maximum_length?: number;
  sample_rate_hz?: number;
  [key: string]: unknown;
}

export interface ManifestInputSchema {
  schema_version: typeof schemaVersions.jobRequest;
  task: string;
  fields: Record<string, ManifestInputField>;
}

export interface ProductionE2EAcceptance {
  schema_version: typeof schemaVersions.productionE2eAcceptance;
  kind: "production_e2e";
  request: JobRequest;
  expected: {
    representation_id: string;
    skeleton_id: string;
    min_frames: number;
    artifacts: string[];
  };
  required_stages: string[];
  timeout_seconds: number;
}

export interface ProductionE2EAcceptanceSuite {
  schema_version: typeof schemaVersions.productionE2eAcceptanceSuite;
  kind: "production_e2e_suite";
  contracts: ProductionE2EAcceptance[];
}

export interface ModelInstallPayload {
  model_id: string;
  apply: true;
  validation_prompt?: string;
  validation_seconds?: number;
  validation_seed?: number;
  validation_timeout?: number;
  execution_target: ExecutionTargetSelection;
}

export type MemoryStrategy =
  | "cuda_full"
  | "cuda_component_split"
  | "cuda_cpu_offload"
  | "cuda_sequential_cpu_offload"
  | "rocm_full"
  | "mps_full"
  | "cpu";

export interface RuntimeSpec {
  schema_version: typeof schemaVersions.runtimeSpec;
  id: string;
  backend: "uv-native" | "pixi-native" | "oci";
  platforms: string[];
  python: string;
  accelerator: {
    kind: "cpu" | "nvidia" | "rocm" | "mps";
    abi: string | null;
    min_vram_gib: number | null;
  };
  lockfile: string;
  min_storage_gib: number | null;
  resource_profiles: Array<{
    id: string;
    strategy: MemoryStrategy;
    min_free_vram_gib: number | null;
    min_free_ram_gib: number;
    min_free_swap_gib: number;
  }>;
  entrypoint_argv: string[];
  environment_allowlist: string[];
  working_directory: string | null;
  project_package: string | null;
  project_version: string | null;
  runtime_core_epoch: string | null;
  availability: string;
}

export interface ArtifactRef {
  name: string;
  media_type: string;
  uri: string;
  byte_length: number | null;
  dtype: string | null;
  shape: number[] | null;
}

export interface ModelResult {
  schema_version: typeof schemaVersions.modelResult;
  job_id: string;
  model: {
    id: string;
    plugin_version: string;
    upstream_repository: string;
    upstream_revision: string;
    runtime_id: string;
    artifact_manifest_id: string | null;
  };
  task: string;
  request_id: string | null;
  native: {
    representation_id: string;
    skeleton_id: string;
    fps: number | null;
    timebase: [number, number] | null;
    frame_count: number;
    coordinate_system: string;
    units: string;
    root_translation_semantics: string;
    root_rotation_semantics: string;
    artifacts: ArtifactRef[];
  };
  segments: Array<{ start_frame: number; end_frame: number; valid: boolean }>;
  warnings: string[];
  provenance: Record<string, unknown>;
}

export interface ModelManifest {
  model: {
    id: string;
    display_name: string;
    status: ModelStatus;
    tasks: string[];
    adapter_family: string;
  };
  inputs: ManifestInputSchema[];
  output: {
    envelope: typeof schemaVersions.modelResult;
    representation_id: string;
    skeleton_id: string;
    fps: number | null;
    coordinate_system: string;
    units: string;
    root_translation_semantics: string;
    root_rotation_semantics: string;
    face_representation_ids: string[];
  };
  result_target: {
    representation_id: string;
    skeleton_id: string;
  };
  runtime_variants: RuntimeSpec[];
  resources: Record<string, unknown>;
  licenses: {
    commercial_allowed: boolean | null;
    requires_acceptance: boolean;
  };
  production_acceptance: ProductionE2EAcceptance | null;
  production_acceptance_suite?: ProductionE2EAcceptanceSuite | null;
  production_acceptance_primary_task?: string | null;
  capability?: {
    cataloged: boolean;
    upstream_runnable: boolean;
    virea_integrated: boolean;
    installable: boolean;
    reasons: string[];
  };
  installation_state?: string | null;
  installation?: {
    installation_id?: string | null;
    state?: string | null;
    installed?: boolean;
    ready?: boolean;
    /** Scope performed by this catalog response, not historical acceptance. */
    verification_scope?: "metadata" | "full_integrity" | string;
    /** True only when this response performed a complete asset-integrity pass. */
    integrity_verified?: boolean;
    execution_target?: {
      requested: ExecutionTargetSelection;
      resolved: ResolvedExecutionTarget;
    } | null;
    latest_attempt?: {
      installation_id?: string | null;
      state?: string | null;
      failure?: {
        task?: string | null;
        job_id?: string | null;
        job_state?: string | null;
        error_code?: string | null;
        error_message?: string | null;
        failed_stages?: string[];
        publication_failure?: string | null;
        downloads_reusable?: boolean;
      } | null;
    } | null;
  } | null;
  test_only?: boolean;
}

export interface JobRecord {
  id: string;
  state: string;
  model_id: string;
  task: string;
  error_code?: string | null;
  error_message?: string | null;
  result_id?: string;
  created_at?: string;
  updated_at?: string;
  idempotency_key?: string | null;
  events?: Array<{
    sequence: number;
    state: string;
    event_type: string;
    created_at: string;
  }>;
}

export interface ExportRecord {
  format: string;
  locator: string;
  media_type: string;
  byte_length: number | null;
  identity?: ActorExportIdentity | null;
}

export interface ResultIdentity {
  schema_version: typeof schemaVersions.resultIdentity;
  model_id: string;
  model_version: string;
  runtime_variant_id: string;
  execution_domain_id?: string | null;
  checkpoint_revision: string;
  artifact_manifest_id: string | null;
  native_representation_id: string;
  native_skeleton_id: string;
  target_representation_id: string;
  target_skeleton_id: string;
  resource_profile_id: string;
  memory_strategy: MemoryStrategy;
  device: string;
}

export interface ActorExportIdentity {
  schema_version: typeof schemaVersions.actorExportIdentity;
  actor_id: string;
  representation_id: string;
  skeleton_id: string;
}

export interface SourceSkeletonActor {
  actor_id: string;
  joint_names: string[];
  edges: [number, number][];
  positions_xyz: number[];
}

export interface SourceSkeletonPreview {
  schema_version: typeof schemaVersions.sourceSkeletonPreview;
  result_id: string;
  job_id: string;
  stage: "model_output_pre_retarget";
  representation_id: string;
  skeleton_id: string;
  coordinate_system: string;
  fps: number;
  frame_count: number;
  duration_seconds: number;
  actors: SourceSkeletonActor[];
  display_transform: {
    coordinates_normalized_for_preview: true;
    vrm_retarget_applied: false;
  };
  metadata: Record<string, unknown>;
}

export interface VrmMotionResult {
  schema_version: typeof schemaVersions.vrmMotionResult;
  result_id: string;
  job_id: string;
  identity?: ResultIdentity | null;
  source_motion_id: string;
  avatar_id: string | null;
  avatar_profile: string;
  retarget_policy_id: string;
  actor_ids: string[];
  tracks: Record<string, string | null>;
  exports: ExportRecord[];
  quality: Record<string, unknown>;
  loss_report: Record<string, unknown>;
}
