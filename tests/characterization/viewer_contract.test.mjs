import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  applyQuatArray,
  buildHumanoidSpaceAlignment,
  normalizedLocalPoseRotation,
  vrmSpecWorldAlignment,
} from "../../apps/viewer-web/vrm-canonical-alignment.js";


function assertArrayClose(actual, expected, tolerance = 1e-9) {
  assert.equal(actual.length, expected.length);
  for (let index = 0; index < actual.length; index += 1) {
    assert.ok(
      Math.abs(actual[index] - expected[index]) <= tolerance,
      `index ${index}: expected ${expected[index]}, received ${actual[index]}`,
    );
  }
}


test("normalized humanoid local rotation obeys A^-1 q A conjugation", () => {
  const halfSqrt = Math.sqrt(0.5);
  const localRotation = [halfSqrt, 0, 0, halfSqrt];
  const alignment = [0, halfSqrt, 0, halfSqrt];
  const normalizedLocal = normalizedLocalPoseRotation(localRotation, alignment);
  const probe = [0.25, -0.5, 1.0];

  const alignedLocalResult = applyQuatArray(
    alignment,
    applyQuatArray(normalizedLocal, probe),
  );
  const localAlignedResult = applyQuatArray(
    localRotation,
    applyQuatArray(alignment, probe),
  );
  assertArrayClose(alignedLocalResult, localAlignedResult);
  assertArrayClose(
    normalizedLocalPoseRotation([0, 0, 0, 2], [0, 0, 0, 1]),
    [0, 0, 0, 1],
  );
});


test("humanoid alignment and VRM specification defaults remain model-neutral", () => {
  const normalizedHumanoidPositions = {
    hips: [0, 0, 0],
    spine: [0, 1, 0],
    leftUpperLeg: [0.5, -1, 0],
    rightUpperLeg: [-0.5, -1, 0],
  };
  const result = buildHumanoidSpaceAlignment(
    normalizedHumanoidPositions,
    normalizedHumanoidPositions,
  );

  assert.ok(result);
  assertArrayClose(result.alignment_quaternion, [0, 0, 0, 1]);
  assert.deepEqual(vrmSpecWorldAlignment("0"), {
    source: "vrm0_spec_yaw_to_canonical",
    meta_version: "0",
    alignment_quaternion: [0, 1, 0, 0],
  });
  assert.deepEqual(vrmSpecWorldAlignment("1"), {
    source: "vrm1_spec_identity",
    meta_version: "1",
    alignment_quaternion: [0, 0, 0, 1],
  });
  assert.equal(vrmSpecWorldAlignment("unknown"), null);
});


test("viewer applies normalized pose with zero legacy or model-specific repairs", () => {
  const viewerSource = readFileSync(
    new URL("../../apps/viewer-web/vrm-viewer.js", import.meta.url),
    "utf8",
  );

  assert.match(viewerSource, /\.humanoid\.setNormalizedPose\(pose\)/);
  assert.match(viewerSource, /legacyTerminalSelfConjugationCount:\s*0/);
  assert.match(viewerSource, /targetRestCorrectionCount:\s*0/);
  assert.match(viewerSource, /restFrameCorrectionCount:\s*0/);
  assert.doesNotMatch(
    viewerSource,
    /\b(?:AMASS|BABEL|BEAT|GRAB|HumanML3D|Motion-X|MoMask|MDM|FLOOD|SentiAvatar)\b/i,
  );
});
