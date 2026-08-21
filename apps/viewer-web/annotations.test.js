import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  activeAnnotations,
  buildTimelineRows,
  canonicalChannelVectorAt,
  collectSidecarReferences,
  canonicalPart,
  channelVectorAt,
  confidenceLabel,
  interpolatePositionFrame,
  normalizeAnnotations,
  normalizeChannels,
  originalTimeLabel,
  partJointIndices,
  timeLabel,
  verifiedSidecarReference,
} from "./annotations.js";
import {
  applyQuatArray,
  buildHumanoidSpaceAlignment,
  CANONICAL_REST_OFFSETS_V3,
  canonicalFloat32ArraySha256,
  multiplyQuatArray,
  normalizedLocalPoseRotation,
  validateVrmMotionPayload,
  vrmSpecWorldAlignment,
} from "./vrm-canonical-alignment.js";

const CONTRACT_CORE_BONES = [
  "spine", "chest", "upperChest", "neck", "head",
  "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
  "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
  "leftUpperLeg", "leftLowerLeg", "leftFoot", "leftToes",
  "rightUpperLeg", "rightLowerLeg", "rightFoot", "rightToes",
];

const CONTRACT_HAND_BONES = ["left", "right"].flatMap((side) =>
  ["Thumb", "Index", "Middle", "Ring", "Little"].flatMap((finger) =>
    ["Proximal", "Intermediate", "Distal"].map((segment) => `${side}${finger}${segment}`)));

function validV3MotionPreview(frameCount = 2) {
  const identity = [0, 0, 0, 1];
  const restBones = ["hips", ...CONTRACT_CORE_BONES, ...CONTRACT_HAND_BONES];
  const motion = {
    schema_version: "virea.vrm_motion_payload.v3.0.0",
    canonical_schema_version: "virea.canonical_motion.v3.0.0",
    rotation_semantics: "rest_relative_normalized_pose_delta",
    frame_count: frameCount,
    coordinate_system: "gltf_y_up_z_forward",
    unit: "meter",
    root_translation: Array.from({ length: frameCount }, () => [0, 0, 0]),
    root_rotation: Array.from({ length: frameCount }, () => [...identity]),
    core_bones: [...CONTRACT_CORE_BONES],
    core_quaternions: Array.from({ length: frameCount }, () =>
      CONTRACT_CORE_BONES.map(() => [...identity])),
    hand_bones: [...CONTRACT_HAND_BONES],
    hand_quaternions: Array.from({ length: frameCount }, () =>
      CONTRACT_HAND_BONES.map(() => [...identity])),
    canonical_to_vrm: {
      leftThumbProximal: "leftThumbMetacarpal",
      leftThumbIntermediate: "leftThumbProximal",
      leftThumbDistal: "leftThumbDistal",
      rightThumbProximal: "rightThumbMetacarpal",
      rightThumbIntermediate: "rightThumbProximal",
      rightThumbDistal: "rightThumbDistal",
    },
    rest_bones: restBones,
    rest_offsets: Object.fromEntries(
      restBones.map((name) => [name, [...CANONICAL_REST_OFFSETS_V3[name]]]),
    ),
    rest_source: "virea_canonical_rest.v3",
    hand_constraint_certificate: {
      schema_version: "virea.hand_constraint_certificate.v1.0.0",
      policy_id: "virea.constraint_aware_hand_retarget.v1",
      policy_sha256: "2e088df30861b1e022928606d556b7d734c6893b32d7a6b7defcf1063a201801",
      status: "passed_noop",
      postconditions_passed: true,
      frame_count: frameCount,
      observation_sha256: "0".repeat(64),
      evidence_sha256: "1".repeat(64),
      pre_solver_hand_sha256: "2".repeat(64),
      output_hand_sha256: "",
      report_sha256: "4".repeat(64),
      certificate: {
        algorithm: "sha256",
        sha256: "5".repeat(64),
        covers: "report_without_certificate_including_output_sha256",
        verified: true,
      },
      artifact_replay_verified: true,
      viewer_pose_mutation_count: 0,
      payload_frame_interval_frames_half_open: [0, frameCount],
    },
  };
  motion.hand_constraint_certificate.output_hand_sha256 = canonicalFloat32ArraySha256(
    motion.hand_quaternions,
    [frameCount, CONTRACT_HAND_BONES.length, 4],
  );
  return {
    frame_count: frameCount,
    skeleton: {
      joint_names: restBones,
      coordinate_system: "gltf_y_up_z_forward",
      unit: "meter",
    },
    frames: {
      positions: Array.from({ length: frameCount }, () => restBones.map(() => [0, 0, 0])),
    },
    motion,
  };
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function quatFromAxisAngle(axis, angle) {
  const length = Math.hypot(...axis);
  const scale = Math.sin(angle / 2) / length;
  return [axis[0] * scale, axis[1] * scale, axis[2] * scale, Math.cos(angle / 2)];
}

function invertQuat(q) {
  return [-q[0], -q[1], -q[2], q[3]];
}

function quatsEquivalent(a, b, tolerance = 1e-8) {
  const dot = Math.abs(a.reduce((sum, value, index) => sum + value * b[index], 0));
  return 1 - dot <= tolerance;
}

function mirrorQuatAcrossX(q) {
  // For S=diag(-1, 1, 1), S R(q) S is represented by (x, -y, -z, w).
  return [q[0], -q[1], -q[2], q[3]];
}

test("VRM viewer accepts the complete canonical v3 constrained normalized-pose contract", () => {
  const result = validateVrmMotionPayload(validV3MotionPreview());
  assert.equal(result.supported, true, result.errors.join("\n"));
  assert.equal(result.motion.schema_version, "virea.vrm_motion_payload.v3.0.0");
});

test("Viewer hand payload SHA-256 matches Python shape+NUL+little-endian-f32 canonicalization", () => {
  const value = [[[0, -0, 0.10000000149011612, 1]]];
  assert.equal(
    canonicalFloat32ArraySha256(value, [1, 1, 4]),
    "4d930b2e5f967c50c22307f91e04a4a301d6e789068ee989eb8f5c614b393fdc",
  );
});

test("VRM viewer accepts a truncated payload only when its slice hash is recomputed", () => {
  const payload = validV3MotionPreview(2);
  payload.frame_count = 1;
  payload.frames.positions = payload.frames.positions.slice(0, 1);
  payload.motion.frame_count = 1;
  payload.motion.root_translation = payload.motion.root_translation.slice(0, 1);
  payload.motion.root_rotation = payload.motion.root_rotation.slice(0, 1);
  payload.motion.core_quaternions = payload.motion.core_quaternions.slice(0, 1);
  payload.motion.hand_quaternions = payload.motion.hand_quaternions.slice(0, 1);
  const proof = payload.motion.hand_constraint_certificate;
  proof.payload_frame_interval_frames_half_open = [0, 1];
  proof.output_hand_sha256 = canonicalFloat32ArraySha256(
    payload.motion.hand_quaternions,
    [1, CONTRACT_HAND_BONES.length, 4],
  );

  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, true, result.errors.join("\n"));
  assert.equal(proof.frame_count, 2, "the upstream artifact frame count remains unchanged");
});

test("VRM viewer rejects a finite unit hand quaternion changed after certification", () => {
  const payload = validV3MotionPreview();
  payload.motion.hand_quaternions[0][0] = quatFromAxisAngle([0, 0, 1], 0.01);

  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(
    result.errors.join("\n"),
    /output_hand_sha256.*does not match.*little-endian-f32 payload hash/,
  );
});

test("VRM viewer rejects a well-formed but fake repeated output hash", () => {
  const payload = validV3MotionPreview();
  payload.motion.hand_constraint_certificate.output_hand_sha256 = "3".repeat(64);

  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /output_hand_sha256.*does not match/);
});

test("VRM viewer rejects v1 payloads instead of guessing their pose semantics", () => {
  const payload = validV3MotionPreview();
  payload.motion.schema_version = "virea.vrm_motion_payload.v2.0.0";
  payload.motion.canonical_schema_version = "virea.canonical_motion.v2.0.0";
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.equal(result.motion, null);
  assert.match(result.errors.join("\n"), /motion\.schema_version/);
  assert.match(result.errors.join("\n"), /motion\.canonical_schema_version/);
});

test("VRM viewer rejects raw-local rotations at the normalized-pose boundary", () => {
  const payload = validV3MotionPreview();
  payload.motion.rotation_semantics = "raw_local_rotation";
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /motion\.rotation_semantics/);
});

test("VRM viewer rejects malformed and non-finite v3 motion arrays", () => {
  const malformed = cloneJson(validV3MotionPreview());
  malformed.motion.core_quaternions[1].pop();
  const shapeResult = validateVrmMotionPayload(malformed);
  assert.equal(shapeResult.supported, false);
  assert.match(shapeResult.errors.join("\n"), /motion\.core_quaternions\[1\]/);

  const nonFinite = validV3MotionPreview();
  nonFinite.motion.hand_quaternions[0][0][2] = Number.NaN;
  const finiteResult = validateVrmMotionPayload(nonFinite);
  assert.equal(finiteResult.supported, false);
  assert.match(finiteResult.errors.join("\n"), /motion\.hand_quaternions\[0\]\[0\]/);
});

test("VRM viewer rejects mislabeled units, rest source label, and bone order", () => {
  const payload = validV3MotionPreview();
  payload.motion.unit = "centimeter";
  payload.motion.rest_source = "avatar_raw_rest";
  [payload.motion.hand_bones[0], payload.motion.hand_bones[1]] = [
    payload.motion.hand_bones[1],
    payload.motion.hand_bones[0],
  ];
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /motion\.unit/);
  assert.match(result.errors.join("\n"), /motion\.rest_source/);
  assert.match(result.errors.join("\n"), /motion\.hand_bones\[0\]/);
});

test("VRM viewer rejects canonical v3 rest-offset numeric drift", () => {
  const payload = validV3MotionPreview();
  payload.motion.rest_offsets.leftIndexIntermediate[0] += 0.001;
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.equal(result.motion, null);
  assert.match(result.errors.join("\n"), /motion\.rest_offsets\.leftIndexIntermediate\[0\]/);
});

test("VRM viewer rejects left-right rest-offset exchange", () => {
  const payload = validV3MotionPreview();
  [
    payload.motion.rest_offsets.leftThumbIntermediate,
    payload.motion.rest_offsets.rightThumbIntermediate,
  ] = [
    payload.motion.rest_offsets.rightThumbIntermediate,
    payload.motion.rest_offsets.leftThumbIntermediate,
  ];
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /motion\.rest_offsets\.leftThumbIntermediate\[0\]/);
  assert.match(result.errors.join("\n"), /motion\.rest_offsets\.rightThumbIntermediate\[0\]/);
});

test("VRM viewer rejects extra canonical v3 rest-offset keys", () => {
  const payload = validV3MotionPreview();
  payload.motion.rest_offsets.leftIndexTip = [0.01, 0.0, 0.0];
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /motion\.rest_offsets\.leftIndexTip/);
});

test("VRM viewer requires the hips rest offset", () => {
  const payload = validV3MotionPreview();
  delete payload.motion.rest_offsets.hips;
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /motion\.rest_offsets\.hips/);
});

test("VRM viewer rejects canonical-to-VRM remapping outside the fixed v3 table", () => {
  const payload = validV3MotionPreview();
  payload.motion.canonical_to_vrm.leftIndexProximal = "rightLittleDistal";
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.equal(result.motion, null);
  assert.match(result.errors.join("\n"), /motion\.canonical_to_vrm\.leftIndexProximal/);
});

test("VRM viewer rejects extra canonical-to-VRM mapping keys", () => {
  const payload = validV3MotionPreview();
  payload.motion.canonical_to_vrm.unversionedThumbAlias = "leftThumbMetacarpal";
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /motion\.canonical_to_vrm\.unversionedThumbAlias/);
});

test("VRM viewer rejects missing canonical-to-VRM mapping keys", () => {
  const payload = validV3MotionPreview();
  delete payload.motion.canonical_to_vrm.rightThumbIntermediate;
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /motion\.canonical_to_vrm\.rightThumbIntermediate/);
});

test("VRM viewer rejects v3 motion without a verified hand certificate", () => {
  const payload = validV3MotionPreview();
  delete payload.motion.hand_constraint_certificate;
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /hand_constraint_certificate/);
});

test("VRM viewer rejects a mismatched policy hash and nonzero pose mutation count", () => {
  const payload = validV3MotionPreview();
  payload.motion.hand_constraint_certificate.policy_sha256 = "f".repeat(64);
  payload.motion.hand_constraint_certificate.artifact_replay_verified = false;
  payload.motion.hand_constraint_certificate.viewer_pose_mutation_count = 1;
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /policy_sha256/);
  assert.match(result.errors.join("\n"), /artifact_replay_verified/);
  assert.match(result.errors.join("\n"), /viewer_pose_mutation_count/);
});

test("VRM viewer rejects certificate fields that could encode presentation corrections", () => {
  const payload = validV3MotionPreview();
  payload.motion.hand_constraint_certificate.finger_clamp = { rightIndexProximal: 30 };
  const result = validateVrmMotionPayload(payload);
  assert.equal(result.supported, false);
  assert.match(result.errors.join("\n"), /finger_clamp/);
  assert.match(result.errors.join("\n"), /cannot carry pose corrections/);
});

test("three-vrm normalized axes reject the removed per-bone self-conjugation path", () => {
  const identity = [0, 0, 0, 1];
  const local = quatFromAxisAngle([1, 0.2, -0.1], Math.PI / 4);
  const offsetDerivedFrame = quatFromAxisAngle([0, 1, 0], Math.PI / 3);
  const artificialRetarget = multiplyQuatArray(
    multiplyQuatArray(offsetDerivedFrame, local),
    invertQuat(offsetDerivedFrame),
  );

  assert.ok(quatsEquivalent(normalizedLocalPoseRotation(local), local));
  assert.ok(
    !quatsEquivalent(artificialRetarget, local, 1e-4),
    "avatar rest-offset geometry is not a second normalized-pose coordinate frame",
  );
  assert.ok(quatsEquivalent(normalizedLocalPoseRotation(identity), identity));
});

test("non-commuting normalized rotations match the three-vrm raw mesh transfer oracle", () => {
  const vrm0Alignment = quatFromAxisAngle([0, 1, 0], Math.PI);
  const canonicalDelta = quatFromAxisAngle([0.3, 1, 0.2], Math.PI / 3);
  const rawParentWorldRest = quatFromAxisAngle([1, -0.4, 0.2], Math.PI / 5);
  const rawBoneLocalRest = quatFromAxisAngle([-0.1, 0.6, 1], Math.PI / 7);
  const normalizedDelta = normalizedLocalPoseRotation(canonicalDelta, vrm0Alignment);

  // This is the exact transfer implemented by VRMHumanoidRig.update():
  // rawLocal = P^-1 * normalizedDelta * P * rawLocalRest.
  const rawLocal = multiplyQuatArray(
    multiplyQuatArray(
      multiplyQuatArray(invertQuat(rawParentWorldRest), normalizedDelta),
      rawParentWorldRest,
    ),
    rawBoneLocalRest,
  );
  const actualCanonicalWorld = multiplyQuatArray(
    multiplyQuatArray(vrm0Alignment, rawParentWorldRest),
    rawLocal,
  );
  const expectedCanonicalWorld = multiplyQuatArray(
    canonicalDelta,
    multiplyQuatArray(
      multiplyQuatArray(vrm0Alignment, rawParentWorldRest),
      rawBoneLocalRest,
    ),
  );
  assert.ok(quatsEquivalent(actualCanonicalWorld, expectedCanonicalWorld));

  const identityDelta = [0, 0, 0, 1];
  const rawIdentityLocal = multiplyQuatArray(
    multiplyQuatArray(
      multiplyQuatArray(invertQuat(rawParentWorldRest), identityDelta),
      rawParentWorldRest,
    ),
    rawBoneLocalRest,
  );
  assert.ok(quatsEquivalent(rawIdentityLocal, rawBoneLocalRest));
});

test("a two-level non-commuting terminal chain matches the raw mesh world triad oracle", () => {
  const vrm0Alignment = quatFromAxisAngle([0, 1, 0], Math.PI);
  const canonicalParentDelta = quatFromAxisAngle([0.7, -0.2, 0.4], Math.PI / 4);
  const canonicalChildDelta = quatFromAxisAngle([-0.1, 0.8, 0.3], Math.PI / 3);
  const rawGrandparentWorldRest = quatFromAxisAngle([0.2, 0.5, -0.7], Math.PI / 7);
  const rawParentLocalRest = quatFromAxisAngle([0.9, 0.1, 0.3], Math.PI / 6);
  const rawParentWorldRest = multiplyQuatArray(rawGrandparentWorldRest, rawParentLocalRest);
  const rawChildLocalRest = quatFromAxisAngle([-0.4, 0.2, 1], Math.PI / 8);
  const normalizedParentDelta = normalizedLocalPoseRotation(
    canonicalParentDelta,
    vrm0Alignment,
  );
  const normalizedChildDelta = normalizedLocalPoseRotation(
    canonicalChildDelta,
    vrm0Alignment,
  );

  const animatedRawParentLocal = multiplyQuatArray(
    multiplyQuatArray(
      multiplyQuatArray(invertQuat(rawGrandparentWorldRest), normalizedParentDelta),
      rawGrandparentWorldRest,
    ),
    rawParentLocalRest,
  );
  const animatedRawParentWorld = multiplyQuatArray(
    rawGrandparentWorldRest,
    animatedRawParentLocal,
  );
  const animatedRawChildLocal = multiplyQuatArray(
    multiplyQuatArray(
      multiplyQuatArray(invertQuat(rawParentWorldRest), normalizedChildDelta),
      rawParentWorldRest,
    ),
    rawChildLocalRest,
  );
  const actualCanonicalChildWorld = multiplyQuatArray(
    vrm0Alignment,
    multiplyQuatArray(animatedRawParentWorld, animatedRawChildLocal),
  );
  const rawChildWorldRest = multiplyQuatArray(rawParentWorldRest, rawChildLocalRest);
  const expectedCanonicalChildWorld = multiplyQuatArray(
    canonicalParentDelta,
    multiplyQuatArray(
      canonicalChildDelta,
      multiplyQuatArray(vrm0Alignment, rawChildWorldRest),
    ),
  );
  assert.ok(quatsEquivalent(actualCanonicalChildWorld, expectedCanonicalChildWorld));
});

test("left and right portable terminal rotations remain mirrored on arbitrary raw rest frames", () => {
  for (const [label, leftDelta] of [
    ["wrist/fingers", quatFromAxisAngle([0.8, 0.3, -0.2], Math.PI / 4)],
    ["ankle/toes", quatFromAxisAngle([0.2, -0.7, 0.4], Math.PI / 5)],
  ]) {
    const leftParentRest = quatFromAxisAngle([0.4, 1, 0.2], Math.PI / 6);
    const leftBoneRest = quatFromAxisAngle([-0.3, 0.2, 1], Math.PI / 8);
    const rightDelta = mirrorQuatAcrossX(leftDelta);
    const rightParentRest = mirrorQuatAcrossX(leftParentRest);
    const rightBoneRest = mirrorQuatAcrossX(leftBoneRest);

    const rawWorld = (delta, parentRest, boneRest) => {
      const rawLocal = multiplyQuatArray(
        multiplyQuatArray(
          multiplyQuatArray(invertQuat(parentRest), normalizedLocalPoseRotation(delta)),
          parentRest,
        ),
        boneRest,
      );
      return multiplyQuatArray(parentRest, rawLocal);
    };
    const leftWorld = rawWorld(leftDelta, leftParentRest, leftBoneRest);
    const rightWorld = rawWorld(rightDelta, rightParentRest, rightBoneRest);
    assert.ok(
      quatsEquivalent(rightWorld, mirrorQuatAcrossX(leftWorld)),
      `${label} lost left/right mirror symmetry`,
    );
  }
});

test("mirrored finger flexion keeps the same signed palm-side displacement", () => {
  const leftFlexion = quatFromAxisAngle([0, 0, 1], Math.PI / 3);
  const rightFlexion = mirrorQuatAcrossX(leftFlexion);
  const leftSegment = applyQuatArray(normalizedLocalPoseRotation(leftFlexion), [1, 0, 0]);
  const rightSegment = applyQuatArray(normalizedLocalPoseRotation(rightFlexion), [-1, 0, 0]);

  assert.ok(leftSegment[1] > 0, "left finger flexion changed to the dorsal side");
  assert.ok(rightSegment[1] > 0, "right finger flexion changed to the dorsal side");
  assert.ok(Math.abs(leftSegment[0] + rightSegment[0]) < 1e-8);
  assert.ok(Math.abs(leftSegment[1] - rightSegment[1]) < 1e-8);
  assert.ok(Math.abs(leftSegment[2] - rightSegment[2]) < 1e-8);
});

test("VRM normalized local rotations are conjugated exactly once into the aligned avatar frame", () => {
  const rawRest = {
    hips: [0, 0, 0],
    spine: [0, 0.9723, -0.2337],
    leftUpperLeg: [-1, 0, 0],
    rightUpperLeg: [1, 0, 0],
  };
  const canonicalRest = {
    hips: [0, 0, 0],
    spine: [0, 1, 0],
    leftUpperLeg: [1, 0, 0],
    rightUpperLeg: [-1, 0, 0],
  };
  const inferredFromSpine = buildHumanoidSpaceAlignment(rawRest, canonicalRest);
  assert.ok(inferredFromSpine);
  const alignment = vrmSpecWorldAlignment("0");
  assert.deepEqual(alignment.alignment_quaternion, [0, 1, 0, 0]);
  assert.deepEqual(vrmSpecWorldAlignment("1").alignment_quaternion, [0, 0, 0, 1]);
  assert.equal(vrmSpecWorldAlignment("unknown"), null);
  assert.notDeepEqual(
    inferredFromSpine.alignment_quaternion.map((value) => Number(value.toFixed(6))),
    alignment.alignment_quaternion,
    "anatomical spine lean must not be mistaken for a world-axis correction",
  );

  const local = [Math.sin(0.35), 0.1, -0.05, Math.cos(0.35)];
  const normalized = normalizedLocalPoseRotation(local, alignment.alignment_quaternion);
  const left = multiplyQuatArray(alignment.alignment_quaternion, normalized);
  const right = multiplyQuatArray(local, alignment.alignment_quaternion);
  assert.ok(Math.abs(left.reduce((sum, value, index) => sum + value * right[index], 0)) > 1 - 1e-8);
  assert.notDeepEqual(
    normalized.map((value) => Number(value.toFixed(8))),
    normalizedLocalPoseRotation(local).map((value) => Number(value.toFixed(8))),
  );

  const source = readFileSync(new URL("./vrm-viewer.js", import.meta.url), "utf8");
  const poseFunction = source.match(/function poseObjectFromFrame\(frame\) \{[\s\S]*?\n  \}/)?.[0] || "";
  assert.match(poseFunction, /normalizedLocalPoseRotation/);
  assert.match(poseFunction, /vrmWorldAlignment\?\.alignment_quaternion/);
  assert.doesNotMatch(poseFunction, /hierarchicalRestLocalRotation|targetRest|restCorrection/);
  assert.doesNotMatch(poseFunction, /conjugateQuatByBasis|alignBasis/);
  assert.doesNotMatch(source, /setRawPose/);
  assert.doesNotMatch(source, /VRMUtils\.rotateVRM0/);
  assert.match(source, /vrmSpecWorldAlignment\(vrm\.meta\?\.metaVersion\)/);
  assert.doesNotMatch(source, /buildTerminalRestPoseCorrections|hierarchicalRestLocalRotation/);
  assert.match(source, /"three-vrm-portable-normalized"/);
  assert.match(source, /"unsupported-motion-contract"/);
  assert.match(source, /validateVrmMotionPayload\(payload\)/);
  assert.match(source, /state\.motion = contract\.motion/);
  assert.match(source, /Unsupported motion payload; VRM playback is disabled/);
  assert.match(source, /legacyTerminalSelfConjugationCount: 0/);
  assert.match(source, /targetRestCorrectionCount: 0/);
  assert.match(source, /restFrameCorrectionCount: 0/);
  assert.match(source, /does not expose normalized humanoid pose application/);
});

test("real VRM QA waits for structured preview readiness instead of presentation copy", () => {
  const source = readFileSync(new URL("../../scripts/qa_real_vrm.mjs", import.meta.url), "utf8");
  assert.match(source, /__vireaShowcase\.loadSample/);
  assert.match(source, /previewReady\?\.sampleId/);
  assert.match(source, /previewReady\?\.frames/);
  assert.match(source, /dataset\.hasVrmHumanoid === "true"/);
  assert.doesNotMatch(source, /dataset\.anchorModes.*includes\("humanoid"\)/);
  assert.match(source, /realDiagnostics\.normalizedPoseAxisMode !== "three-vrm-portable-normalized"/);
  assert.match(source, /realDiagnostics\.legacyTerminalSelfConjugationCount !== 0/);
  assert.match(source, /realDiagnostics\.targetRestCorrectionCount !== 0/);
  assert.match(source, /VIREA_QA_OUTPUT_DIR/);
  assert.match(source, /resolve\(tmpdir\(\), "virea"\)/);
  assert.match(source, /resolve\(process\.env\.VIREA_HOME, "tmp"\)/);
  assert.match(source, /qa-real-vrm-\$\{process\.pid\}-\$\{Date\.now\(\)\}/);
  assert.match(source, /rmSync\(autoOutputDir/);
  assert.doesNotMatch(source, /resolve\(projectRoot, "tmp"/);
  assert.doesNotMatch(source, /resolve\(projectRoot, "\.virea-runtime"\)/);
  assert.doesNotMatch(source, /VIREA_QA_OUTPUT_PREFIX/);
  assert.doesNotMatch(source, /hierarchicalRestCorrection/);
  assert.doesNotMatch(source, /startsWith\(["']Frames:/);
});

test("dataset-native sample text is never inserted as HTML", () => {
  const source = readFileSync(new URL("./app.js", import.meta.url), "utf8");
  const renderSamples = source.match(/function renderSamples\(\) \{[\s\S]*?\n\}/)?.[0] || "";
  assert.match(renderSamples, /description\.textContent/);
  assert.doesNotMatch(renderSamples, /item\.innerHTML/);
  assert.doesNotMatch(renderSamples, /sampleText\(sample\).*innerHTML/);
  assert.match(source, /replaceOptions\(\$\("datasetSelect"\)/);
  assert.doesNotMatch(source, /datasetSelect"\)\.innerHTML/);
});

test("quality UI separates processed observable-hand errors from source diagnostics", () => {
  const appSource = readFileSync(new URL("./app.js", import.meta.url), "utf8");
  const annotationSource = readFileSync(new URL("./annotations.js", import.meta.url), "utf8");
  assert.match(appSource, /retarget_hand_direction_error/);
  assert.match(appSource, /Observable Hand Direction Error/);
  assert.match(appSource, /Observable hand mean:/);
  assert.match(annotationSource, /Source hand geometry/);
  assert.match(annotationSource, /no hidden clamp or smoothing/);
});

test("VRM marker updates traverse the avatar scene at most once per annotation pass", () => {
  const source = readFileSync(new URL("./vrm-viewer.js", import.meta.url), "utf8");
  const cacheFunction = source.match(/function humanoidWorldPositionCache\(specs\) \{[\s\S]*?\n  \}/)?.[0] || "";
  const averageFunction = source.match(/function averageHumanoidWorldPosition\(boneNames, worldPositions\) \{[\s\S]*?\n  \}/)?.[0] || "";
  assert.equal((cacheFunction.match(/updateMatrixWorld\(true\)/g) || []).length, 1);
  assert.doesNotMatch(averageFunction, /updateMatrixWorld/);
  assert.match(source, /connector\.frustumCulled = false/);
  assert.doesNotMatch(source, /connectorGeometry\.computeBoundingSphere/);
});

test("skeleton playback reuses normalized-frame and shared-bounds storage", () => {
  const source = readFileSync(new URL("./app.js", import.meta.url), "utf8");
  const normalizeFunction = source.match(/function normalizeFrames\(payload, anchorFrameIndex = null\) \{[\s\S]*?\n\}/)?.[0] || "";
  assert.match(source, /const normalizedFramesCache = new WeakMap\(\)/);
  assert.match(normalizeFunction, /normalizedFramesCache\.get\(payload\)/);
  assert.match(normalizeFunction, /target\[0\] = point\[0\] - anchor\[0\]/);
  assert.match(source, /sharedBoundsCache\.value/);
  assert.match(source, /panel\.__vireaQuality === quality/);
  assert.match(source, /const skeletonCanvasVisibility = new WeakMap\(\)/);
  assert.match(source, /new IntersectionObserver/);
  assert.match(source, /const shared = skeletonVisible \? boundsFor/);
  assert.match(source, /const cssVariableCache = new Map\(\)/);
  assert.match(source, /projectionTrigCache\.yaw !== yaw/);
});

test("VRM render loop resizes the drawing buffer only after a size change", () => {
  const source = readFileSync(new URL("./vrm-viewer.js", import.meta.url), "utf8");
  const renderFunction = source.match(/function render\(now\) \{[\s\S]*?\n  \}/)?.[0] || "";
  const resizeFunction = source.match(/function resize\(\) \{[\s\S]*?\n  \}/)?.[0] || "";
  assert.match(renderFunction, /if \(resizeDirty\) resize\(\)/);
  assert.match(resizeFunction, /if \(width === renderWidth && height === renderHeight\) return/);
  assert.match(source, /new ResizeObserver/);
  assert.match(source, /const MAX_RENDER_HZ = 60/);
  assert.match(renderFunction, /now < nextRenderMs - 1/);
  assert.match(renderFunction, /nextRenderMs \+ renderIntervalMs/);
  assert.match(renderFunction, /scheduledNext <= now \? now \+ renderIntervalMs : scheduledNext/);
});

test("VRM model loading ignores stale async results and disposes attached scenes once", () => {
  const source = readFileSync(new URL("./vrm-viewer.js", import.meta.url), "utf8");
  const loadModel = source.match(/async function loadModel\(file\) \{[\s\S]*?\n  \}/)?.[0] || "";
  const clearModel = source.match(/function clearCurrentModel\(\) \{[\s\S]*?\n  \}/)?.[0] || "";
  assert.match(loadModel, /const loadGeneration = \+\+state\.modelLoadGeneration/);
  assert.match(loadModel, /loadGeneration !== state\.modelLoadGeneration/);
  assert.match(loadModel, /disposeObject\(gltf\.scene\)/);
  assert.doesNotMatch(clearModel, /disposeObject\(state\.(?:vrm|staticScene)/);
  assert.match(clearModel, /clearGroup\(canonicalRoot\)/);
  assert.match(clearModel, /clearGroup\(staticRoot\)/);
});

test("VRM pose application avoids duplicate raw resets and humanoid updates", () => {
  const source = readFileSync(new URL("./vrm-viewer.js", import.meta.url), "utf8");
  const applyFunction = source.match(/function applyVrmFrame\(frame\) \{[\s\S]*?\n  \}/)?.[0] || "";
  assert.doesNotMatch(applyFunction, /resetNormalizedPose[\s\S]*resetRawPose[\s\S]*const pose/);
  assert.match(applyFunction, /if \(typeof state\.vrm\.update === "function"\) state\.vrm\.update\(0\);\n    else state\.vrm\.humanoid\.update\?\.\(\)/);
  assert.match(source, /if \(signature === state\.diagnosticsSignature\) return/);
});

test("annotation v1 preserves provenance, confidence, extras, and half-open time", () => {
  const [annotation] = normalizeAnnotations({
    fps: 10,
    frame_count: 20,
    annotations: [{
      schema_version: "virea.annotation.v1.0.0",
      id: "native-1",
      level: "action",
      type: "gesture",
      text: "wave",
      bodypart: null,
      start_sec: 0.5,
      end_sec: 1.0,
      start_frame: 5,
      end_frame: 10,
      confidence: { value: 7, min: 0, max: 10, unit: "ordinal" },
      source: "beat.tsv:gesture",
      provenance: "native",
      reasoning: null,
      original: { start_sec: 0.5, end_sec: 1.0, vendor_record: { label_id: 42 } },
      clipped: false,
      extras: { semantic_relevancy: 7, custom: { enabled: true } },
    }],
  });

  assert.equal(annotation.id, "native-1");
  assert.equal(annotation.provenance, "native");
  assert.equal(annotation.confidence.value, 7);
  assert.equal(confidenceLabel(annotation.confidence), "confidence 7 (0-10) ordinal");
  assert.deepEqual(annotation.extras.custom, { enabled: true });
  assert.deepEqual(annotation.original.vendor_record, { label_id: 42 });
  assert.equal(timeLabel(annotation), "[0.50, 1.00)s");
  assert.equal(activeAnnotations([annotation], 9.999, 10).length, 1);
  assert.equal(activeAnnotations([annotation], 10, 10).length, 0, "end frame must be exclusive");
});

test("compatibility annotations retain unknown fields and remain visibly unverified", () => {
  const annotations = normalizeAnnotations({
    fps: 30,
    frame_count: 60,
    annotations: [{ type: "gesture", text: "point", start_frame: 3, end_frame: 8, vendor_column: "kept" }],
  });
  const annotation = annotations.find((item) => item.text === "point");
  assert.equal(annotation.schemaVersion, "virea.annotation.compat.v0");
  assert.equal(annotation.provenance, "legacy");
  assert.equal(annotation.extras.vendor_column, "kept");
  assert.equal(annotation.startFrame, 3);
  assert.equal(annotation.endFrame, 8);
});

test("hand biomechanics review remains derived and explicitly non-mutating", () => {
  const annotations = normalizeAnnotations({
    fps: 20,
    frame_count: 139,
    metadata: {
      hand_biomechanics: {
        schema_version: "virea.hand_biomechanics.v2.0.0",
        status: "review_required",
        violation_count: 21,
        pip_limit_violation_count: 21,
        extension_limit_violation_count: 25,
        bend_plane_violation_count: 52,
        hard_pip_limit_deg: 130,
        pip_extension_upper_limits_deg: {
          Index: 29.3,
          Middle: 31.8,
          Ring: 32.2,
          Little: 30.0,
        },
        bend_plane_review_deg: 45,
        motion_mutated: false,
        regularization_applied: false,
        per_joint: { rightRingPIP: { violation_frames_half_open: [[67, 88]] } },
      },
    },
  });
  const review = annotations.find((item) => item.type === "hand_biomechanics_review");
  assert.equal(review.provenance, "derived");
  assert.equal(review.bodypart, "hands");
  assert.match(review.text, /21 PIP flexion frame-joints exceed 130°/);
  assert.match(review.text, /25 PIP extension frame-joints exceed the 29.3–32.2° per-finger envelope/);
  assert.match(review.text, /52 bend-plane frame-joints exceed 45°/);
  assert.match(review.reasoning, /positive flexion and negative extension/i);
  assert.match(review.reasoning, /neither dataset-native labels nor a biomechanical regularizer/i);
  assert.match(review.reasoning, /no hidden clamp or smoothing/i);
  assert.equal(review.extras.hand_biomechanics.motion_mutated, false);
  assert.deepEqual(
    review.extras.hand_biomechanics.per_joint.rightRingPIP.violation_frames_half_open,
    [[67, 88]],
  );
});

test("extension-only hand review never renders as zero diagnosed violations", () => {
  const annotations = normalizeAnnotations({
    fps: 30,
    frame_count: 1,
    metadata: {
      hand_biomechanics: {
        schema_version: "virea.hand_biomechanics.v2.0.0",
        status: "review_required",
        pip_limit_violation_count: 0,
        extension_limit_violation_count: 8,
        bend_plane_violation_count: 0,
        hard_pip_limit_deg: null,
        pip_upper_limits_deg: {
          Index: 131.0,
          Middle: 127.8,
          Ring: 127.8,
          Little: 117.2,
        },
        pip_extension_upper_limits_deg: {
          Index: 29.3,
          Middle: 31.8,
          Ring: 32.2,
          Little: 30.0,
        },
        bend_plane_review_deg: 45,
        motion_mutated: false,
      },
    },
  });
  const review = annotations.find((item) => item.type === "hand_biomechanics_review");
  assert.match(review.text, /0 PIP flexion frame-joints/);
  assert.match(review.text, /8 PIP extension frame-joints/);
  assert.doesNotMatch(review.text, /0 frame-joints flagged/);
});

test("unobservable antiparallel hand review is explicit instead of guessing direction", () => {
  const annotations = normalizeAnnotations({
    metadata: {
      hand_biomechanics: {
        schema_version: "virea.hand_biomechanics.v2.0.0",
        status: "review_required",
        pip_limit_violation_count: 0,
        extension_limit_violation_count: 0,
        bend_plane_violation_count: 0,
        direction_unobservable_violation_count: 8,
        review_candidate_count: 8,
        motion_mutated: false,
      },
    },
  });
  const review = annotations.find((item) => item.type === "hand_biomechanics_review");
  assert.match(review.text, /8 extreme frame-joints have an unobservable bend direction/);
  assert.match(review.reasoning, /positive flexion and negative extension/i);
});

test("clipping changes effective range while retaining original range", () => {
  const [annotation] = normalizeAnnotations({
    fps: 10,
    frame_count: 10,
    annotations: [{
      schema_version: "virea.annotation.v1.0.0",
      id: "clip-1",
      level: "action",
      type: "action",
      text: "long action",
      bodypart: null,
      start_sec: -0.5,
      end_sec: 2.5,
      start_frame: -5,
      end_frame: 25,
      confidence: null,
      source: "test",
      provenance: "native",
      reasoning: null,
      original: { time: { start_sec: -0.5, end_sec: 2.5, start_frame: -5, end_frame: 25, source_fps: 10 } },
      clipped: true,
      extras: {},
    }],
  });
  assert.equal(annotation.startSec, 0);
  assert.equal(annotation.endSec, 1);
  assert.equal(annotation.startFrame, 0);
  assert.equal(annotation.endFrame, 10);
  assert.equal(annotation.clipped, true);
  assert.equal(originalTimeLabel(annotation), "[-0.50, 2.50)s");
});

test("sequence annotations without a native range apply to the whole clip without inventing time", () => {
  const [annotation] = normalizeAnnotations({
    fps: 25,
    frame_count: 100,
    annotations: [{
      schema_version: "virea.annotation.v1.0.0",
      id: "caption-1",
      level: "sequence",
      type: "caption",
      text: "A person walks forward.",
      bodypart: null,
      start_sec: null,
      end_sec: null,
      start_frame: null,
      end_frame: null,
      confidence: null,
      source: "caption",
      provenance: "native",
      reasoning: null,
      original: {},
      clipped: false,
      extras: {},
    }],
  });
  assert.equal(annotation.startSec, null);
  assert.equal(annotation.endSec, null);
  assert.equal(timeLabel(annotation), "whole clip / no native range");
  assert.equal(activeAnnotations([annotation], 99, 25).length, 1);
});

test("part aliases cover compact hand names and payload-defined custom skeleton names", () => {
  const payload = {
    skeleton: {
      joint_names: ["Root", "CustomPalmL", "CustomPalmR", "LeftUpperArm", "RightUpperArm"],
      bodypart_aliases: {
        left_arm: ["CustomPalmL"],
        right_arm: ["CustomPalmR"],
        custom_left: "left_arm",
      },
      joint_aliases: {
        CustomPalmL: "LeftHand",
        CustomPalmR: "RightHand",
      },
    },
  };
  assert.equal(canonicalPart("lhand"), "left_arm");
  assert.equal(canonicalPart("rhand"), "right_arm");
  assert.equal(canonicalPart("custom_left", payload), "left_arm");
  assert.deepEqual(partJointIndices(payload, "left_arm"), [1, 3]);
  assert.deepEqual(partJointIndices(payload, "right_arm"), [2, 4]);
});

test("timeline aggregation limits visible rows without dropping annotations", () => {
  const annotations = Array.from({ length: 12 }, (_, index) => ({
    id: String(index),
    level: index < 6 ? "part" : "context",
    bodypart: `custom_${index}`,
    text: `item ${index}`,
    color: "#123456",
    anchorColor: "#123456",
  }));
  const rows = buildTimelineRows(annotations, 5);
  assert.equal(rows.length, 5);
  assert.equal(rows.at(-1).aggregated, true);
  assert.equal(rows.reduce((count, row) => count + row.annotations.length, 0), annotations.length);
});

test("position playback interpolates adjacent frames", () => {
  const frame = interpolatePositionFrame([[[0, 0, 0]], [[2, 4, 6]]], 0.25);
  assert.deepEqual(frame, [[0.5, 1, 1.5]]);
});

test("elapsed-time playback caps redraw work without advancing by render frames", () => {
  const source = readFileSync(new URL("./app.js", import.meta.url), "utf8");
  const playback = source.match(/function startPlayback\(\) \{[\s\S]*?\n\}/)?.[0] || "";
  assert.match(source, /const MAX_PLAYBACK_RENDER_HZ = 60/);
  assert.match(playback, /now >= state\.playbackNextRenderMs - 1/);
  assert.match(playback, /state\.playbackNextRenderMs \+ renderIntervalMs/);
  assert.match(playback, /scheduledNext <= now/);
  assert.match(playback, /const elapsedSec = Math\.max\(0, \(now - state\.playbackStartMs\) \/ 1000\)/);
  assert.match(playback, /state\.frame = timeSec \* playbackFps\(\)/);
  assert.doesNotMatch(playback, /state\.frame\s*\+=/);
});

test("multimodal channel descriptors preserve availability and resolve object/contact anchors", () => {
  const [channel] = normalizeChannels({
    channels: [{
      schema_version: "virea.channel.v1.0.0",
      id: "contact-1",
      kind: "contact_points",
      availability: "inline",
      representation: "points",
      fps: 30,
      frame_count: 2,
      coordinate_system: "gltf_y_up_z_forward",
      source: "contact.npy",
      provenance: "native",
      preview: { points_m: [[[0, 0, 0], [2, 2, 2]], [[4, 4, 4]]] },
    }],
  });
  assert.equal(channel.kind, "contact");
  assert.equal(channel.availability, "inline");
  assert.equal(channel.coordinateSystem, "gltf_y_up_z_forward");
  assert.deepEqual(channelVectorAt(channel, 0), [1, 1, 1]);
});

test("3D spatial anchors consume canonical channels and never raw source coordinates", () => {
  const channels = normalizeChannels({
    channels: [
      {
        id: "native-object",
        kind: "object_pose",
        coordinate_system: "grab_source_world_z_up",
        unit: "meter",
        fps: 120,
        preview: { translation_m: [[0.01, -0.43, 0.90]] },
      },
      {
        id: "canonical-object",
        kind: "object_pose",
        coordinate_system: "gltf_y_up_z_forward",
        unit: "meter",
        fps: 120,
        preview: { translation_m: [[-0.04, -0.05, 1.32]] },
      },
    ],
  });
  assert.deepEqual(canonicalChannelVectorAt(channels, "object", 0, 120), [-0.04, -0.05, 1.32]);
  assert.equal(canonicalChannelVectorAt([channels[0]], "object", 0, 120), null);
});

test("sidecar references are local, content-addressed, and recursively discoverable", () => {
  const digest = "a".repeat(64);
  const reference = {
    path: `sidecars/${digest}.json`,
    sha256: digest,
    byte_length: 42,
    media_type: "application/json",
    encoding: "utf-8",
    read_api: `/api/artifacts/sidecars/${digest}`,
  };
  assert.equal(verifiedSidecarReference(reference)?.readApi, `/api/artifacts/sidecars/${digest}`);
  assert.equal(collectSidecarReferences({ nested: { sidecar: reference } }).length, 1);
  assert.equal(verifiedSidecarReference({ ...reference, read_api: "https://evil.example/payload" }), null);
  assert.equal(verifiedSidecarReference({ ...reference, path: `../${digest}.json` }), null);
});
