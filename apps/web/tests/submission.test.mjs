import test from "node:test";
import assert from "node:assert/strict";

import {
  retainOrCreateSubmissionAttempt,
  submissionAttemptWasPersisted,
  submissionFingerprint,
} from "../src/submission.ts";

const identity = {
  vireaHome: "E:\\VIREA-DATA\\home",
  modelId: "flood-diffusion-tiny",
  task: "text_to_motion",
  prompt: "walk forward",
  seconds: 4,
  seed: 7,
  executionTarget: {
    execution_domain_id: "windows-native",
    runtime_variant_id: "flood-diffusion-tiny-cpu",
    resource_profile_id: "whole-model-cpu",
  },
};

test("an unresolved retry retains the exact idempotency key for the same request", async () => {
  const fingerprint = await submissionFingerprint(identity);
  let keyCalls = 0;
  const first = retainOrCreateSubmissionAttempt(
    null,
    fingerprint,
    () => `key-${++keyCalls}`,
    () => "2026-08-25T00:00:00Z",
  );
  const retry = retainOrCreateSubmissionAttempt(
    first,
    fingerprint,
    () => `key-${++keyCalls}`,
    () => "2026-08-25T00:01:00Z",
  );

  assert.strictEqual(retry, first);
  assert.equal(retry.idempotencyKey, "key-1");
  assert.equal(keyCalls, 1);
});

test("a materially different request receives a new idempotency identity", async () => {
  const firstFingerprint = await submissionFingerprint(identity);
  const secondFingerprint = await submissionFingerprint({ ...identity, seed: 8 });
  let keyCalls = 0;
  const first = retainOrCreateSubmissionAttempt(
    null,
    firstFingerprint,
    () => `key-${++keyCalls}`,
    () => "first",
  );
  const second = retainOrCreateSubmissionAttempt(
    first,
    secondFingerprint,
    () => `key-${++keyCalls}`,
    () => "second",
  );

  assert.notEqual(second.idempotencyKey, first.idempotencyKey);
  assert.equal(keyCalls, 2);
});

test("the pending identity is cleared only after a matching durable Job appears", async () => {
  const attempt = {
    fingerprint: await submissionFingerprint(identity),
    idempotencyKey: "durable-key",
    createdAt: "2026-08-25T00:00:00Z",
  };

  assert.equal(submissionAttemptWasPersisted(attempt, [{ idempotency_key: "other" }]), false);
  assert.equal(
    submissionAttemptWasPersisted(attempt, [{ idempotency_key: "durable-key" }]),
    true,
  );
});

test("the persisted fingerprint is stable but contains neither prompt nor absolute data root", async () => {
  const reorderedTarget = {
    resource_profile_id: identity.executionTarget.resource_profile_id,
    runtime_variant_id: identity.executionTarget.runtime_variant_id,
    execution_domain_id: identity.executionTarget.execution_domain_id,
  };
  const first = await submissionFingerprint(identity);
  const second = await submissionFingerprint({ ...identity, executionTarget: reorderedTarget });

  assert.equal(first, second);
  assert.match(first, /^sha256:[0-9a-f]{64}$/);
  assert.equal(first.includes(identity.prompt), false);
  assert.equal(first.includes(identity.vireaHome), false);
});
