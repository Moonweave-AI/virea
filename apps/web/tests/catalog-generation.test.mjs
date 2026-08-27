import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { parse } from "yaml";

import {
  createManifestGenerationPayload,
  generationFormDefaults,
  generationInputFields,
  generationVisibleInputFields,
  generationVisibleTaskSchemas,
  isVireaIntegratedModel,
  productionAcceptanceContracts,
  productionAcceptanceForTask,
} from "../src/domain.ts";

const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
const pluginRoot = path.join(repositoryRoot, "plugins", "models");
const models = fs.readdirSync(pluginRoot, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => path.join(pluginRoot, entry.name, "manifest.yaml"))
  .filter((manifestPath) => fs.existsSync(manifestPath))
  .sort()
  .map((manifestPath) => parse(fs.readFileSync(manifestPath, "utf8")))
  .filter((manifest) => ["integrated_experimental", "supported"].includes(manifest.model.status));
const executionTarget = {
  schema_version: "virea.execution_target_selection.v1.0.0",
  execution_domain_id: "windows-native",
  runtime_variant_id: null,
  resource_profile_id: null,
};
const idempotencyKey = "real-catalog-web-contract";

test("every integrated model task produces an executable manifest-driven Web JobRequest", () => {
  assert.equal(models.length, 14);
  let validatedTasks = 0;

  for (const manifest of models) {
    const modelId = manifest.model.id;
    assert.equal(isVireaIntegratedModel(manifest), true, modelId);
    const contracts = productionAcceptanceContracts(manifest);
    assert.deepEqual(
      contracts.map((contract) => contract.request.task),
      manifest.model.tasks,
      `${modelId} acceptance order`,
    );

    for (const task of manifest.model.tasks) {
      const acceptance = productionAcceptanceForTask(manifest, task);
      assert.ok(acceptance, `${modelId}/${task} acceptance`);
      const draft = generationFormDefaults(manifest, task);
      const payload = createManifestGenerationPayload(
        manifest,
        draft,
        executionTarget,
        idempotencyKey,
      );

      assert.equal(payload.schema_version, "virea.job_request.v1.0.0", `${modelId}/${task}`);
      assert.equal(payload.model_id, modelId, `${modelId}/${task}`);
      assert.equal(payload.task, task, `${modelId}/${task}`);
      assert.equal(payload.avatar_id, null, `${modelId}/${task}`);
      assert.equal(payload.idempotency_key, idempotencyKey, `${modelId}/${task}`);
      assert.deepEqual(payload.execution_target, executionTarget, `${modelId}/${task}`);

      for (const [name, expected] of Object.entries(acceptance.request.input)) {
        assert.deepEqual(payload.input[name], expected, `${modelId}/${task} input.${name}`);
      }
      for (const [name, expected] of Object.entries(acceptance.request.parameters)) {
        assert.deepEqual(payload.parameters[name], expected, `${modelId}/${task} parameters.${name}`);
      }
      for (const [name, field] of generationInputFields(manifest, task)) {
        const locations = Number(Object.hasOwn(payload.input, name))
          + Number(Object.hasOwn(payload.parameters, name));
        if (field.required === true) {
          assert.equal(locations, 1, `${modelId}/${task} required field ${name}`);
        } else {
          assert.ok(locations <= 1, `${modelId}/${task} optional field ${name}`);
        }
      }
      validatedTasks += 1;
    }
  }
  assert.equal(validatedTasks, 19);
});

test("SentiAvatar audio and streaming acceptances require no text-to-motion assumptions", () => {
  const manifest = models.find(({ model }) => model.id === "sentiavatar-susu");
  assert.ok(manifest);
  assert.deepEqual(manifest.model.tasks, [
    "audio_text_to_avatar_motion",
    "streaming_dialogue_avatar_motion",
  ]);
  for (const task of manifest.model.tasks) {
    const payload = createManifestGenerationPayload(
      manifest,
      generationFormDefaults(manifest, task),
      executionTarget,
      idempotencyKey,
    );
    assert.equal(Object.hasOwn(payload.input, "prompt"), false);
    assert.equal(Object.hasOwn(payload.parameters, "seconds"), false);
    assert.equal(Object.hasOwn(payload.parameters, "fps"), false);
  }
});

test("SentiAvatar guided Web mode asks only for an action while preserving verified defaults", () => {
  const manifest = models.find(({ model }) => model.id === "sentiavatar-susu");
  assert.ok(manifest);
  assert.deepEqual(
    generationVisibleTaskSchemas(manifest).map(({ task }) => task),
    ["audio_text_to_avatar_motion"],
  );
  assert.deepEqual(
    generationVisibleInputFields(manifest, "audio_text_to_avatar_motion").map(([name]) => name),
    ["action_and_expression_tags"],
  );

  const acceptance = productionAcceptanceForTask(manifest, "audio_text_to_avatar_motion");
  assert.ok(acceptance);
  const draft = generationFormDefaults(manifest);
  draft.values.action_and_expression_tags = "动作：向前走两步，右手挥动，最后微笑点头";
  const payload = createManifestGenerationPayload(
    manifest,
    draft,
    executionTarget,
    idempotencyKey,
  );

  assert.equal(payload.input.action_and_expression_tags, draft.values.action_and_expression_tags);
  assert.equal(payload.input.audio, acceptance.request.input.audio);
  assert.equal(payload.input.dialogue_text, acceptance.request.input.dialogue_text);
  assert.deepEqual(payload.parameters, acceptance.request.parameters);
});
