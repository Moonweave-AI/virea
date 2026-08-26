import test from "node:test";
import assert from "node:assert/strict";

import {
  artifactBasename,
  artifactUrl,
  createManifestGenerationPayload,
  createInstallPayload,
  firstVrmaExport,
  generationFormDefaults,
  generationInputFields,
  generationTaskSchemas,
  isInstalledReady,
  isInstallationIntegrityDeferred,
  isVireaIntegratedModel,
  installationReadinessLabel,
  modelCapabilityLabel,
  modelMotionRoute,
  productionAcceptanceContracts,
  productionAcceptanceForTask,
  productionAcceptanceTimeoutSeconds,
  productionCatalogJobs,
  productionCatalogModels,
  realRunnableModels,
  resultMotionRoute,
  vireaIntegratedModels,
} from "../src/domain.ts";

const IDEMPOTENCY_KEY = "web-test-generation-01";

const windowsTarget = {
  schema_version: "virea.execution_target_selection.v1.0.0",
  execution_domain_id: "windows-native",
  runtime_variant_id: null,
  resource_profile_id: null,
};

function acceptanceRequestWithTarget(request) {
  return { ...request, idempotency_key: IDEMPOTENCY_KEY, execution_target: windowsTarget };
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
    inputs: [],
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

function acceptanceContract(modelId, task, input, parameters, timeoutSeconds) {
  const contract = productionAcceptance(modelId);
  contract.request.task = task;
  contract.request.input = structuredClone(input);
  contract.request.parameters = structuredClone(parameters);
  contract.timeout_seconds = timeoutSeconds;
  return contract;
}

function suiteManifest(modelId, taskSpecs) {
  const selected = manifest({ id: modelId, runtimes: [`${modelId}-cpu`], acceptance: null });
  selected.model.tasks = taskSpecs.map(({ task }) => task);
  selected.inputs = taskSpecs.map(({ task, fields }) => ({
    schema_version: "virea.job_request.v1.0.0",
    task,
    fields: structuredClone(fields),
  }));
  const contracts = taskSpecs.map(({ task, input, parameters, timeout }) => (
    acceptanceContract(modelId, task, input, parameters, timeout)
  ));
  selected.production_acceptance_suite = {
    schema_version: "virea.production_e2e_acceptance_suite.v1.0.0",
    kind: "production_e2e_suite",
    contracts,
  };
  // `/models` retains this first-contract projection for old clients. New Web
  // code must still treat the complete suite above as canonical.
  selected.production_acceptance = structuredClone(contracts[0]);
  return selected;
}

const MULTI_TASK_MODELS = [
  {
    modelId: "motioncraft-smplx",
    tasks: [
      {
        task: "text_to_motion",
        input: { prompt: "A dancer crosses the stage.", motion_length_frames: 60 },
        parameters: { seed: 11 },
        timeout: 7_200,
        fields: {
          prompt: { type: "string", required: true },
          motion_length_frames: { type: "integer", required: true },
          seed: { type: "integer", required: true },
        },
      },
      {
        task: "speech_to_gesture",
        input: { audio: "data:audio/wav;base64,UklGRg==", transcript: "Welcome." },
        parameters: { seed: 12 },
        timeout: 7_100,
        fields: {
          audio: { type: "audio", required: true },
          transcript: { type: "string", required: false },
          seed: { type: "integer", required: true },
        },
      },
      {
        task: "music_to_dance",
        input: { audio: "data:audio/wav;base64,UklGRg==", style_prompt: "jazz" },
        parameters: { seed: 13 },
        timeout: 7_000,
        fields: {
          audio: { type: "audio", required: true },
          style_prompt: { type: "string", required: false },
          seed: { type: "integer", required: true },
        },
      },
    ],
  },
  {
    modelId: "intermask-interhuman",
    tasks: [
      {
        task: "text_to_two_person_interaction",
        input: { prompt: "Two people shake hands.", duration_seconds: 2 },
        parameters: { seed: 21, sampling_steps: 20 },
        timeout: 3_600,
        fields: {
          prompt: { type: "string", required: true },
          duration_seconds: { type: "number", required: true },
          seed: { type: "integer", required: true },
          sampling_steps: { type: "integer", required: true },
        },
      },
      {
        task: "interaction_reaction_generation",
        input: {
          prompt: "The second person steps back.",
          conditioning_actor_motion: "D:/motion/actor-a.npy",
        },
        parameters: { seed: 22, sampling_steps: 24 },
        timeout: 3_500,
        fields: {
          prompt: { type: "string", required: true },
          conditioning_actor_motion: {
            type: "array_or_npy_path",
            representation_id: "interhuman.motion262.single_actor.v1",
            required: true,
          },
          seed: { type: "integer", required: true },
          sampling_steps: { type: "integer", required: true },
        },
      },
    ],
  },
  {
    modelId: "remomask-humanml3d",
    tasks: [
      {
        task: "text_to_motion",
        input: { prompt: "Walk in a circle." },
        parameters: { motion_length_frames: 80, seed: 31, retrieval_top_k: 1, fps: 20 },
        timeout: 5_400,
        fields: {
          prompt: { type: "string", required: true },
          seconds: { type: "number", required: true },
          seed: { type: "integer", required: true },
          retrieval_top_k: { type: "integer", required: true },
        },
      },
      {
        task: "retrieval_augmented_text_to_motion",
        input: { prompt: "Retrieve a jumping motion." },
        parameters: { motion_length_frames: 80, seed: 32, retrieval_top_k: 4, fps: 20 },
        timeout: 5_300,
        fields: {
          prompt: { type: "string", required: true },
          seconds: { type: "number", required: true },
          seed: { type: "integer", required: true },
          retrieval_top_k: { type: "integer", required: true },
        },
      },
    ],
  },
  {
    modelId: "sentiavatar-susu",
    tasks: [
      {
        task: "audio_text_to_avatar_motion",
        input: {
          audio: "data:audio/wav;base64,UklGRg==",
          dialogue_text: "Hello.",
          action_and_expression_tags: ["wave"],
        },
        parameters: { seed: 41 },
        timeout: 7_200,
        fields: {
          audio: { type: "audio", required: true },
          dialogue_text: { type: "string", required: true },
          action_and_expression_tags: {
            type: "text_segments",
            required: true,
            default: ["schema default must not override the acceptance request"],
          },
          seed: { type: "integer", required: true },
        },
      },
      {
        task: "streaming_dialogue_avatar_motion",
        input: {
          audio_chunks: ["data:audio/wav;base64,UklGRg=="],
          dialogue_turns: ["Goodbye."],
        },
        parameters: { seed: 42 },
        timeout: 7_100,
        fields: {
          audio_chunks: { type: "mono_pcm_audio_stream", required: true },
          dialogue_turns: { type: "text_stream", required: true },
          seed: { type: "integer", required: true },
        },
      },
    ],
  },
];

for (const { modelId, tasks } of MULTI_TASK_MODELS) {
  test(`${modelId} resolves every task from its immutable acceptance suite`, () => {
    const selected = suiteManifest(modelId, tasks);
    const suiteBefore = structuredClone(selected.production_acceptance_suite);
    const legacyBefore = structuredClone(selected.production_acceptance);
    const contracts = productionAcceptanceContracts(selected);

    assert.equal(isVireaIntegratedModel(selected), true);
    assert.deepEqual(contracts.map(({ request }) => request.task), tasks.map(({ task }) => task));
    assert.equal(
      productionAcceptanceTimeoutSeconds(selected),
      tasks.reduce((total, task) => total + task.timeout, 0),
    );
    assert.strictEqual(contracts[0], selected.production_acceptance_suite.contracts[0]);
    assert.deepEqual(generationTaskSchemas(selected).map(({ task }) => task), tasks.map(({ task }) => task));

    for (const taskSpec of tasks) {
      const contract = productionAcceptanceForTask(selected, taskSpec.task);
      assert.ok(contract);
      assert.equal(contract.timeout_seconds, taskSpec.timeout);
      const draft = generationFormDefaults(selected, taskSpec.task);
      const payload = createManifestGenerationPayload(
        selected,
        draft,
        windowsTarget,
        IDEMPOTENCY_KEY,
      );
      assert.deepEqual(payload, {
        ...contract.request,
        input: structuredClone(contract.request.input),
        parameters: structuredClone(contract.request.parameters),
        idempotency_key: IDEMPOTENCY_KEY,
        execution_target: windowsTarget,
      });
    }

    assert.deepEqual(selected.production_acceptance_suite, suiteBefore);
    assert.deepEqual(selected.production_acceptance, legacyBefore);
    const installPayload = createInstallPayload(selected, windowsTarget);
    assert.equal(Object.hasOwn(installPayload, "validation_timeout"), false);
  });
}

test("an API integration claim fails closed when suite task order drifts", () => {
  const { modelId, tasks } = MULTI_TASK_MODELS[1];
  const selected = suiteManifest(modelId, tasks);
  selected.capability = { virea_integrated: true };
  selected.production_acceptance_suite.contracts.reverse();

  assert.equal(isVireaIntegratedModel(selected), false);
  assert.throws(
    () => productionAcceptanceContracts(selected),
    /验收 task .* 与声明顺序/,
  );
});

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

test("catalog capability keeps upstream-only entries visible without claiming integration", () => {
  const integrated = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  const upstreamOnly = manifest({ id: "hy-motion-1", runtimes: [], acceptance: null });
  upstreamOnly.model.status = "runnable_upstream";

  assert.equal(isVireaIntegratedModel(integrated), true);
  assert.equal(isVireaIntegratedModel(upstreamOnly), false);
  assert.deepEqual(vireaIntegratedModels([upstreamOnly, integrated]), [integrated]);
  assert.match(modelCapabilityLabel(upstreamOnly), /Upstream only/);

  integrated.capability = {
    cataloged: true,
    upstream_runnable: true,
    virea_integrated: false,
    installable: false,
    reasons: ["VIREA_ADAPTER_NOT_INTEGRATED"],
  };
  assert.equal(isVireaIntegratedModel(integrated), false, "API capability is authoritative");
});

test("production activity excludes fake and unknown jobs even when they succeeded", () => {
  const real = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  const fake = manifest({ id: "fake-motion-v1", adapter: "fake-root-translation", runtimes: ["fake-runtime"] });
  const jobs = [
    { id: "fake-job", model_id: "fake-motion-v1", task: "text_to_motion", state: "SUCCEEDED" },
    { id: "unknown-job", model_id: "external-cli-sync-probe", task: "text_to_motion", state: "SUCCEEDED" },
    { id: "real-job", model_id: "flood-diffusion-tiny", task: "text_to_motion", state: "SUCCEEDED" },
  ];

  assert.deepEqual(productionCatalogJobs(jobs, [fake, real]), [jobs[2]]);
});

test("explicit installation state takes precedence over runtime availability", () => {
  assert.equal(isInstalledReady(manifest({ id: "ready", runtimes: ["runtime"], installState: "READY" })), true);
  assert.equal(
    isInstalledReady(manifest({ id: "failed", runtimes: ["runtime"], availability: "available", installState: "FAILED" })),
    false,
  );
});

test("metadata-only READY is labeled as persisted state, not fresh integrity proof", () => {
  const ready = manifest({ id: "ready", runtimes: ["runtime"], installState: "READY" });
  ready.installation = {
    state: "READY",
    ready: true,
    verification_scope: "metadata",
    integrity_verified: false,
  };

  assert.equal(isInstalledReady(ready), true);
  assert.equal(isInstallationIntegrityDeferred(ready), true);
  assert.match(installationReadinessLabel(ready), /Persisted READY/);

  ready.installation.integrity_verified = true;
  assert.equal(isInstallationIntegrityDeferred(ready), false);
  assert.match(installationReadinessLabel(ready), /integrity verified/);
});

test("generation payload carries the selected model, prompt, seconds, and seed", () => {
  const selected = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  const draft = generationFormDefaults(selected);
  draft.values.prompt = "  Walk forward. ";
  draft.values.seconds = 2.5;
  draft.values.seed = 17;
  assert.deepEqual(createManifestGenerationPayload(
    selected,
    draft,
    windowsTarget,
    IDEMPOTENCY_KEY,
  ), {
    schema_version: "virea.job_request.v1.0.0",
    model_id: "flood-diffusion-tiny",
    task: "text_to_motion",
    input: { prompt: "Walk forward." },
    parameters: { seconds: 2.5, seed: 17, fps: 20 },
    avatar_id: null,
    idempotency_key: IDEMPOTENCY_KEY,
    execution_target: windowsTarget,
  });
});

test("manifest inputs drive non-text task defaults and the generic JobRequest", () => {
  const selected = manifest({ id: "motioncraft-smplx", runtimes: ["motioncraft-cu128"] });
  selected.model.tasks = ["speech_to_gesture"];
  selected.inputs = [{
    schema_version: "virea.job_request.v1.0.0",
    task: "speech_to_gesture",
    fields: {
      audio: { type: "audio", required: true },
      transcript: { type: "string", required: false },
      seed: { type: "integer", default: 7, minimum: 0 },
    },
  }];
  selected.production_acceptance.request.task = "speech_to_gesture";
  selected.production_acceptance.request.input = {
    audio: "D:/media/acceptance.wav",
    transcript: "Please wave.",
  };
  selected.production_acceptance.request.parameters = { seed: 11 };

  const defaults = generationFormDefaults(selected);
  assert.equal(defaults.task, "speech_to_gesture");
  assert.deepEqual(generationTaskSchemas(selected).map((schema) => schema.task), ["speech_to_gesture"]);
  assert.deepEqual(generationInputFields(selected, defaults.task).map(([name]) => name), [
    "audio",
    "transcript",
    "seed",
  ]);
  defaults.values.audio = "data:audio/wav;base64,UklGRg==";
  defaults.values.transcript = "Wave twice.";

  assert.deepEqual(
    createManifestGenerationPayload(selected, defaults, windowsTarget, IDEMPOTENCY_KEY),
    {
      ...selected.production_acceptance.request,
      input: {
        audio: "data:audio/wav;base64,UklGRg==",
        transcript: "Wave twice.",
      },
      parameters: { seed: 11 },
      idempotency_key: IDEMPOTENCY_KEY,
      execution_target: windowsTarget,
    },
  );
});

test("streaming audio fields preserve ordered browser chunks as a JSON array", () => {
  const selected = manifest({ id: "sentiavatar-susu", runtimes: ["sentiavatar-susu-cu128"] });
  selected.model.tasks = ["streaming_dialogue_avatar_motion"];
  selected.inputs = [{
    schema_version: "virea.job_request.v1.0.0",
    task: "streaming_dialogue_avatar_motion",
    fields: {
      audio_chunks: { type: "mono_pcm_audio_stream", required: true, maximum_items: 64 },
      dialogue_turns: { type: "text_stream", required: true, maximum_items: 64 },
    },
  }];
  selected.production_acceptance.request.task = "streaming_dialogue_avatar_motion";
  selected.production_acceptance.request.input = { audio_chunks: [], dialogue_turns: [] };
  selected.production_acceptance.request.parameters = {};

  const draft = generationFormDefaults(selected);
  draft.values.audio_chunks = '["data:audio/wav;base64,UklGRg==","D:/media/turn-2.wav"]';
  draft.values.dialogue_turns = '["你好","再见"]';

  assert.deepEqual(
    createManifestGenerationPayload(selected, draft, windowsTarget, IDEMPOTENCY_KEY).input,
    {
      audio_chunks: ["data:audio/wav;base64,UklGRg==", "D:/media/turn-2.wav"],
      dialogue_turns: ["你好", "再见"],
    },
  );
});

test("structured manifest fields parse inline JSON while upstream-only models stay non-runnable", () => {
  const schema = {
    schema_version: "virea.job_request.v1.0.0",
    task: "waypoint_controlled_motion",
    fields: {
      text_timeline: { type: "text_segments", required: true },
      waypoints: { type: "world_space_constraints", required: true },
    },
  };
  const integrated = manifest({ id: "schema-runtime-probe", runtimes: ["schema-runtime"] });
  integrated.model.tasks = ["waypoint_controlled_motion"];
  integrated.inputs = [schema];
  integrated.production_acceptance.request.task = "waypoint_controlled_motion";
  integrated.production_acceptance.request.input = {
    text_timeline: [{ start_seconds: 0, end_seconds: 2, text: "walk" }],
    waypoints: [{ time_seconds: 1, position: [0, 0, 1] }],
  };
  integrated.production_acceptance.request.parameters = {};
  integrated.capability = { virea_integrated: true };
  const draft = generationFormDefaults(integrated);
  draft.values.text_timeline = '[{"start_seconds":0,"end_seconds":2,"text":"walk"}]';
  draft.values.waypoints = '[{"time_seconds":1,"position":[0,0,1]}]';
  const payload = createManifestGenerationPayload(
    integrated,
    draft,
    windowsTarget,
    IDEMPOTENCY_KEY,
  );
  assert.deepEqual(payload.input, {
    text_timeline: [{ start_seconds: 0, end_seconds: 2, text: "walk" }],
    waypoints: [{ time_seconds: 1, position: [0, 0, 1] }],
  });
  draft.values.waypoints = '"D:/inputs/waypoints.json"';
  assert.throws(
    () => createManifestGenerationPayload(integrated, draft, windowsTarget, IDEMPOTENCY_KEY),
    /不要包含首尾引号/,
  );

  const upstreamOnly = manifest({ id: "dart-smplx", runtimes: [], acceptance: null });
  upstreamOnly.model.status = "runnable_upstream";
  upstreamOnly.model.tasks = ["waypoint_controlled_motion"];
  upstreamOnly.inputs = [schema];

  assert.throws(
    () => createManifestGenerationPayload(upstreamOnly, draft, windowsTarget, IDEMPOTENCY_KEY),
    /尚无 VIREA runtime\/Worker/,
  );
});

test("generation payload preserves the selected manifest acceptance fps without hard-coding it", () => {
  const selected = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  selected.production_acceptance.request.parameters.fps = 29.97;

  assert.equal(createManifestGenerationPayload(
    selected,
    generationFormDefaults(selected),
    windowsTarget,
    IDEMPOTENCY_KEY,
  ).parameters.fps, 29.97);
});

test("matching Web inputs reproduce the manifest production acceptance JobRequest exactly", () => {
  const selected = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  const expected = selected.production_acceptance.request;

  assert.deepEqual(
    createManifestGenerationPayload(
      selected,
      generationFormDefaults(selected),
      windowsTarget,
      IDEMPOTENCY_KEY,
    ),
    acceptanceRequestWithTarget(expected),
  );
});

test("generation maps seconds to the manifest input motion length without adding fields", () => {
  const selected = manifest({ id: "momadiff-humanml3d", runtimes: ["momadiff-cu128"] });
  selected.production_acceptance.request.input.motion_length_frames = 80;
  delete selected.production_acceptance.request.parameters.seconds;

  assert.deepEqual(
    createManifestGenerationPayload(
      selected,
      generationFormDefaults(selected),
      windowsTarget,
      IDEMPOTENCY_KEY,
    ),
    acceptanceRequestWithTarget(selected.production_acceptance.request),
  );
});

test("generation maps seconds to a manifest parameter motion length", () => {
  const selected = manifest({ id: "cmdm-humanml3d", runtimes: ["cmdm-cu128"] });
  selected.production_acceptance.request.parameters.motion_length_frames = 80;
  delete selected.production_acceptance.request.parameters.seconds;

  assert.equal(createManifestGenerationPayload(
    selected,
    generationFormDefaults(selected),
    windowsTarget,
    IDEMPOTENCY_KEY,
  ).parameters.motion_length_frames, 80);
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
  const defaults = generationFormDefaults(selected);

  assert.deepEqual(defaults, {
    task: "text_to_motion",
    values: {
      prompt: expected.input.prompt,
      seconds: 4.3,
      seed: 42,
    },
  });
  assert.deepEqual(
    createManifestGenerationPayload(
      selected,
      defaults,
      windowsTarget,
      IDEMPOTENCY_KEY,
    ),
    acceptanceRequestWithTarget(expected),
  );
});

test("install delegates the exact manifest request and preserves only its timeout override", () => {
  const candidate = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  candidate.production_acceptance.request.input.prompt = "Exact manifest acceptance prompt.";
  candidate.production_acceptance.request.parameters.seconds = 6.5;
  candidate.production_acceptance.request.parameters.seed = 123456;
  candidate.production_acceptance.timeout_seconds = 3210;

  assert.equal(productionAcceptanceTimeoutSeconds(candidate), 3210);
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
    createManifestGenerationPayload(
      selected,
      generationFormDefaults(selected),
      wslTarget,
      IDEMPOTENCY_KEY,
    ).execution_target,
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

  const mutableIdentity = manifest({ id: "flood-diffusion-tiny", runtimes: ["flood-tiny-cu128"] });
  mutableIdentity.production_acceptance.request.idempotency_key = "manifest-must-not-pin-this";
  assert.throws(() => createInstallPayload(mutableIdentity, windowsTarget), /空 avatar_id 和 idempotency_key/);
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
