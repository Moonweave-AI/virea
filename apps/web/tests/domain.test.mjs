import test from "node:test";
import assert from "node:assert/strict";

import {
  artifactBasename,
  artifactUrl,
  createGenerationPayload,
  createInstallPayload,
  firstVrmaExport,
  generationDefaults,
  isInstalledReady,
  modelMotionRoute,
  productionCatalogModels,
  realRunnableModels,
  resultMotionRoute,
} from "../src/domain.ts";

const windowsTarget = {
  schema_version: "virea.execution_target_selection.v1.0.0",
  execution_domain_id: "windows-native",
  runtime_variant_id: null,
  resource_profile_id: null,
};

function acceptanceRequestWithTarget(request) {
  return { ...request, execution_target: windowsTarget };
}

function productionAcceptance(modelId) {
  return {
    schema_version: "virea.production_e2e_acceptance.v1.0.0",
    kind: "production_e2e",
    request: {
      schema_version: "virea.job_request.v1.0.0",
      model_id: modelId,
      task: "text_to_motion",
      input: { prompt: "A person walks forward, turns left, and waves." },
      parameters: { seconds: 4, seed: 42, fps: 20 },
      avatar_id: null,
      idempotency_key: null,
      execution_target: null,
    },
    expected: {
      representation_id: "humanml3d.vector263.v1",
      skeleton_id: "humanml3d.body22.v1",
      min_frames: 40,
      artifacts: ["native_motion", "motion_ir", "retargeted_motion", "vrma"],
    },
    required_stages: [
      "environment_detection",
      "artifact_installation",
      "runtime_build",
      "model_load",
      "inference",
      "native_artifact_validation",
      "motion_ir_conversion",
      "retarget_validation",
      "vrma_export",
      "web_playback",
    ],
    timeout_seconds: 1800,
  };
}

function manifest({
  id,
  adapter = "humanml3d-motion263-body22",
  runtimes = [],
  availability = "declared",
  installState = null,
  acceptance,
}) {
  return {
    model: {
      id,
      display_name: id,
      status: "integrated_experimental",
      tasks: ["text_to_motion"],
      adapter_family: adapter,
    },
    output: {
      envelope: "virea.model_result.v1.0.0",
      representation_id: "humanml3d.vector263.v1",
      skeleton_id: "humanml3d.body22.v1",
      fps: 20,
      coordinate_system: "humanml3d.right_handed_y_up_z_forward",
      units: "meters",
      root_translation_semantics: "relative",
      root_rotation_semantics: "relative",
      face_representation_ids: [],
    },
    result_target: {
      representation_id: "virea.canonical211.v3",
      skeleton_id: "vrm1.humanoid52.v1",
    },
    runtime_variants: runtimes.map((runtimeId) => ({
      schema_version: "virea.runtime_spec.v1.0.0",
      id: runtimeId,
      backend: "uv-native",
      platforms: ["win32"],
      python: ">=3.11,<3.12",
      accelerator: { kind: "nvidia", abi: "cu128", min_vram_gib: 8 },
      lockfile: "uv.lock",
      entrypoint_argv: ["virea-real-worker"],
      environment_allowlist: [],
      working_directory: null,
      project_package: null,
      project_version: null,
      runtime_core_epoch: null,
      availability,
    })),
    resources: {},
    licenses: { commercial_allowed: true, requires_acceptance: false },
    production_acceptance: acceptance === undefined ? productionAcceptance(id) : acceptance,
    installation_state: installState,
  };
}

test("catalog excludes test-only identities and entries without a runtime", () => {
  const real = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  const noRuntime = manifest({ id: "catalog-only", runtimes: [] });
  const testOnly = manifest({ id: "fake-motion-v1", adapter: "fake-root-translation", runtimes: ["fake-runtime"] });
  assert.deepEqual(realRunnableModels([noRuntime, testOnly, real]), [real]);
});

test("production catalog keeps an official blocked model visible without making it runnable", () => {
  const blocked = manifest({ id: "prism-tp2m-1-4b", runtimes: [] });
  blocked.model.status = "blocked";
  blocked.resources = {
    integration_state: "upstream_incomplete",
    license_status: "license_blocked",
  };
  const testOnly = manifest({ id: "fake-motion-v1", adapter: "fake-root-translation", runtimes: [] });

  assert.deepEqual(productionCatalogModels([testOnly, blocked]), [blocked]);
  assert.deepEqual(realRunnableModels([blocked]), []);
});

test("explicit installation state takes precedence over runtime availability", () => {
  assert.equal(isInstalledReady(manifest({ id: "ready", runtimes: ["runtime"], installState: "READY" })), true);
  assert.equal(
    isInstalledReady(manifest({ id: "failed", runtimes: ["runtime"], availability: "available", installState: "FAILED" })),
    false,
  );
});

test("generation payload carries the selected model, prompt, seconds, and seed", () => {
  const selected = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  assert.deepEqual(createGenerationPayload(selected, "  Walk forward. ", 2.5, 17, windowsTarget), {
    schema_version: "virea.job_request.v1.0.0",
    model_id: "flood-diffusion-tiny",
    task: "text_to_motion",
    input: { prompt: "Walk forward." },
    parameters: { seconds: 2.5, seed: 17, fps: 20 },
    avatar_id: null,
    idempotency_key: null,
    execution_target: windowsTarget,
  });
});

test("generation payload preserves the selected manifest acceptance fps without hard-coding it", () => {
  const selected = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  selected.production_acceptance.request.parameters.fps = 29.97;

  assert.equal(createGenerationPayload(selected, "Walk.", 4, 42, windowsTarget).parameters.fps, 29.97);
});

test("matching Web inputs reproduce the manifest production acceptance JobRequest exactly", () => {
  const selected = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  const expected = selected.production_acceptance.request;

  assert.deepEqual(
    createGenerationPayload(
      selected,
      expected.input.prompt,
      expected.parameters.seconds,
      expected.parameters.seed,
      windowsTarget,
    ),
    acceptanceRequestWithTarget(expected),
  );
});

test("generation maps seconds to the manifest input motion length without adding fields", () => {
  const selected = manifest({ id: "momadiff-humanml3d", runtimes: ["momadiff-cu128"] });
  selected.production_acceptance.request.input.motion_length_frames = 80;
  delete selected.production_acceptance.request.parameters.seconds;

  assert.deepEqual(
    createGenerationPayload(
      selected,
      selected.production_acceptance.request.input.prompt,
      4,
      selected.production_acceptance.request.parameters.seed,
      windowsTarget,
    ),
    acceptanceRequestWithTarget(selected.production_acceptance.request),
  );
});

test("generation maps seconds to a manifest parameter motion length", () => {
  const selected = manifest({ id: "cmdm-humanml3d", runtimes: ["cmdm-cu128"] });
  selected.production_acceptance.request.parameters.motion_length_frames = 80;
  delete selected.production_acceptance.request.parameters.seconds;

  assert.equal(
    createGenerationPayload(selected, "Walk.", 4, 42, windowsTarget).parameters.motion_length_frames,
    80,
  );
});

test("PRISM generation preserves the manifest frame-based acceptance request exactly", () => {
  const selected = manifest({ id: "prism-tp2m-1-4b", runtimes: ["prism-component-split"] });
  selected.output.fps = 30;
  selected.production_acceptance.request.parameters = {
    num_frames: 129,
    inference_steps: 50,
    guidance_scale: 5,
    seed: 42,
    fps: 30,
  };
  const expected = selected.production_acceptance.request;
  const defaults = generationDefaults(selected);

  assert.deepEqual(defaults, {
    prompt: expected.input.prompt,
    seconds: 4.3,
    seed: 42,
  });
  assert.deepEqual(
    createGenerationPayload(selected, defaults.prompt, defaults.seconds, defaults.seed, windowsTarget),
    acceptanceRequestWithTarget(expected),
  );
});

test("generation fails closed when manifest acceptance fps is missing or not positive finite", () => {
  for (const fps of [undefined, null, 0, -1, Number.NaN, Number.POSITIVE_INFINITY, "20"]) {
    const selected = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
    selected.production_acceptance.request.parameters.fps = fps;
    assert.throws(
      () => createGenerationPayload(selected, "Walk.", 4, 42, windowsTarget),
      /fps 必须是正有限数/,
    );
  }
});

test("install delegates the exact manifest request and preserves only its timeout override", () => {
  const candidate = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  candidate.production_acceptance.request.input.prompt = "Exact manifest acceptance prompt.";
  candidate.production_acceptance.request.parameters.seconds = 6.5;
  candidate.production_acceptance.request.parameters.seed = 123456;
  candidate.production_acceptance.timeout_seconds = 3210;

  assert.deepEqual(createInstallPayload(candidate, windowsTarget), {
    model_id: "flood-diffusion-tiny",
    apply: true,
    validation_timeout: 3210,
    execution_target: windowsTarget,
  });
});

test("one global execution target is carried by both install and generation", () => {
  const selected = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  const wslTarget = {
    ...windowsTarget,
    execution_domain_id: "wsl:Ubuntu-24.04",
  };

  assert.deepEqual(createInstallPayload(selected, wslTarget).execution_target, wslTarget);
  assert.deepEqual(
    createGenerationPayload(selected, "Walk.", 4, 42, wslTarget).execution_target,
    wslTarget,
  );
});

test("install payload fails closed when production acceptance is absent or cannot be preserved", () => {
  const missing = manifest({
    id: "flood-diffusion-tiny",
    runtimes: ["flood-tiny-cu128"],
    acceptance: null,
  });
  assert.throws(() => createInstallPayload(missing, windowsTarget), /没有 production acceptance/);

  const mismatched = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  mismatched.production_acceptance.request.model_id = "different-model";
  assert.throws(() => createInstallPayload(mismatched, windowsTarget), /model_id 不一致/);

  const nonPrompt = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  nonPrompt.production_acceptance.request.input.prompt = 123;
  assert.throws(() => createInstallPayload(nonPrompt, windowsTarget), /prompt 必须/);
});

test("VRMA URL uses the result endpoint and locator basename", () => {
  assert.equal(artifactBasename("results\\01\\motion-actor.vrma"), "motion-actor.vrma");
  assert.equal(
    artifactUrl("result 01", "results/01/motion-actor.vrma"),
    "/api/v1/results/result%2001/artifacts/motion-actor.vrma",
  );
});

test("firstVrmaExport returns the first actual VRMA export and rejects absent output", () => {
  const base = {
    schema_version: "virea.vrm_motion_result.v1.0.0",
    result_id: "r1",
    job_id: "j1",
    source_motion_id: "motion",
    avatar_id: null,
    avatar_profile: "vrm1.humanoid52.v1",
    retarget_policy_id: "default",
    actor_ids: ["actor"],
    tracks: {},
    quality: {},
    loss_report: {},
  };
  const vrma = { format: "vrma", locator: "results/r1/motion.vrma", media_type: "model/gltf-binary", byte_length: 123 };
  assert.equal(firstVrmaExport({ ...base, exports: [{ format: "npz", locator: "motion.npz", media_type: "application/x-npz", byte_length: 1 }, vrma] }), vrma);
  assert.throws(() => firstVrmaExport({ ...base, exports: [] }), /没有 VRMA export/);
});

test("model and result motion routes keep source and target identities distinct", () => {
  const candidate = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-diffusion-tiny-cu128"] });
  candidate.output.representation_id = "humanml3d.vector263.v1";
  candidate.output.skeleton_id = "humanml3d.body22.v1";
  assert.equal(
    modelMotionRoute(candidate),
    "humanml3d.vector263.v1 / humanml3d.body22.v1 → virea.canonical211.v3 / vrm1.humanoid52.v1",
  );

  const result = {
    schema_version: "virea.vrm_motion_result.v1.0.0",
    result_id: "01RESULT",
    job_id: "01JOB",
    source_motion_id: "motion",
    avatar_id: null,
    avatar_profile: "vrm1.humanoid52.v1",
    retarget_policy_id: "default",
    actor_ids: ["actor-0"],
    tracks: {},
    exports: [],
    quality: {},
    loss_report: {},
    identity: {
      schema_version: "virea.result_identity.v1.0.0",
      model_id: "flood-diffusion-tiny",
      model_version: "0.1.0",
      runtime_variant_id: "flood-diffusion-tiny-cu128",
      checkpoint_revision: "pinned-revision",
      artifact_manifest_id: null,
      native_representation_id: "humanml3d.vector263.v1",
      native_skeleton_id: "humanml3d.body22.v1",
      target_representation_id: "virea.canonical211.v3",
      target_skeleton_id: "vrm1.humanoid52.v1",
      resource_profile_id: "cuda-full",
      memory_strategy: "cuda_full",
      device: "cuda:0",
    },
  };
  assert.equal(
    resultMotionRoute(result, null),
    "humanml3d.vector263.v1 / humanml3d.body22.v1 → virea.canonical211.v3 / vrm1.humanoid52.v1",
  );
});
