function dotVec3(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

export const VRM_MOTION_CONTRACT_V3 = Object.freeze({
  schemaVersion: "virea.vrm_motion_payload.v3.0.0",
  canonicalSchemaVersion: "virea.canonical_motion.v3.0.0",
  rotationSemantics: "rest_relative_normalized_pose_delta",
  restSource: "virea_canonical_rest.v3",
  coordinateSystem: "gltf_y_up_z_forward",
  unit: "meter",
  handSolverSchemaVersion: "virea.hand_constraint_certificate.v1.0.0",
  handPolicyId: "virea.constraint_aware_hand_retarget.v1",
  handPolicySha256: "2e088df30861b1e022928606d556b7d734c6893b32d7a6b7defcf1063a201801",
});

const CORE_BONES_V3 = Object.freeze([
  "spine",
  "chest",
  "upperChest",
  "neck",
  "head",
  "leftShoulder",
  "leftUpperArm",
  "leftLowerArm",
  "leftHand",
  "rightShoulder",
  "rightUpperArm",
  "rightLowerArm",
  "rightHand",
  "leftUpperLeg",
  "leftLowerLeg",
  "leftFoot",
  "leftToes",
  "rightUpperLeg",
  "rightLowerLeg",
  "rightFoot",
  "rightToes",
]);

const HAND_BONES_V3 = Object.freeze([
  "leftThumbProximal",
  "leftThumbIntermediate",
  "leftThumbDistal",
  "leftIndexProximal",
  "leftIndexIntermediate",
  "leftIndexDistal",
  "leftMiddleProximal",
  "leftMiddleIntermediate",
  "leftMiddleDistal",
  "leftRingProximal",
  "leftRingIntermediate",
  "leftRingDistal",
  "leftLittleProximal",
  "leftLittleIntermediate",
  "leftLittleDistal",
  "rightThumbProximal",
  "rightThumbIntermediate",
  "rightThumbDistal",
  "rightIndexProximal",
  "rightIndexIntermediate",
  "rightIndexDistal",
  "rightMiddleProximal",
  "rightMiddleIntermediate",
  "rightMiddleDistal",
  "rightRingProximal",
  "rightRingIntermediate",
  "rightRingDistal",
  "rightLittleProximal",
  "rightLittleIntermediate",
  "rightLittleDistal",
]);

const REST_BONES_V3 = Object.freeze(["hips", ...CORE_BONES_V3, ...HAND_BONES_V3]);

export const CANONICAL_REST_OFFSETS_V3 = Object.freeze({
  hips: Object.freeze([0.0, 0.0, 0.0]),
  spine: Object.freeze([0.0, 0.10, 0.0]),
  chest: Object.freeze([0.0, 0.12, 0.0]),
  upperChest: Object.freeze([0.0, 0.12, 0.0]),
  neck: Object.freeze([0.0, 0.08, 0.0]),
  head: Object.freeze([0.0, 0.10, 0.0]),
  leftShoulder: Object.freeze([0.08, 0.06, 0.0]),
  leftUpperArm: Object.freeze([0.14, 0.0, 0.0]),
  leftLowerArm: Object.freeze([0.26, 0.0, 0.0]),
  leftHand: Object.freeze([0.22, 0.0, 0.0]),
  rightShoulder: Object.freeze([-0.08, 0.06, 0.0]),
  rightUpperArm: Object.freeze([-0.14, 0.0, 0.0]),
  rightLowerArm: Object.freeze([-0.26, 0.0, 0.0]),
  rightHand: Object.freeze([-0.22, 0.0, 0.0]),
  leftUpperLeg: Object.freeze([0.09, -0.10, 0.0]),
  leftLowerLeg: Object.freeze([0.0, -0.45, 0.0]),
  leftFoot: Object.freeze([0.0, -0.45, 0.03]),
  leftToes: Object.freeze([0.0, 0.0, 0.16]),
  rightUpperLeg: Object.freeze([-0.09, -0.10, 0.0]),
  rightLowerLeg: Object.freeze([0.0, -0.45, 0.0]),
  rightFoot: Object.freeze([0.0, -0.45, 0.03]),
  rightToes: Object.freeze([0.0, 0.0, 0.16]),
  leftThumbProximal: Object.freeze([0.05, -0.02, 0.03]),
  leftThumbIntermediate: Object.freeze([0.0316227766, 0.0, 0.0316227766]),
  leftThumbDistal: Object.freeze([0.0254950976, 0.0, 0.0254950976]),
  leftIndexProximal: Object.freeze([0.06, 0.0, 0.04]),
  leftIndexIntermediate: Object.freeze([0.0447213595, 0.0, 0.0]),
  leftIndexDistal: Object.freeze([0.0360555128, 0.0, 0.0]),
  leftMiddleProximal: Object.freeze([0.065, 0.0, 0.015]),
  leftMiddleIntermediate: Object.freeze([0.0460977223, 0.0, 0.0]),
  leftMiddleDistal: Object.freeze([0.0364005494, 0.0, 0.0]),
  leftRingProximal: Object.freeze([0.06, 0.0, -0.01]),
  leftRingIntermediate: Object.freeze([0.0412310563, 0.0, 0.0]),
  leftRingDistal: Object.freeze([0.0316227766, 0.0, 0.0]),
  leftLittleProximal: Object.freeze([0.055, 0.0, -0.035]),
  leftLittleIntermediate: Object.freeze([0.0403112887, 0.0, 0.0]),
  leftLittleDistal: Object.freeze([0.0291547595, 0.0, 0.0]),
  rightThumbProximal: Object.freeze([-0.05, -0.02, 0.03]),
  rightThumbIntermediate: Object.freeze([-0.0316227766, 0.0, 0.0316227766]),
  rightThumbDistal: Object.freeze([-0.0254950976, 0.0, 0.0254950976]),
  rightIndexProximal: Object.freeze([-0.06, 0.0, 0.04]),
  rightIndexIntermediate: Object.freeze([-0.0447213595, 0.0, 0.0]),
  rightIndexDistal: Object.freeze([-0.0360555128, 0.0, 0.0]),
  rightMiddleProximal: Object.freeze([-0.065, 0.0, 0.015]),
  rightMiddleIntermediate: Object.freeze([-0.0460977223, 0.0, 0.0]),
  rightMiddleDistal: Object.freeze([-0.0364005494, 0.0, 0.0]),
  rightRingProximal: Object.freeze([-0.06, 0.0, -0.01]),
  rightRingIntermediate: Object.freeze([-0.0412310563, 0.0, 0.0]),
  rightRingDistal: Object.freeze([-0.0316227766, 0.0, 0.0]),
  rightLittleProximal: Object.freeze([-0.055, 0.0, -0.035]),
  rightLittleIntermediate: Object.freeze([-0.0403112887, 0.0, 0.0]),
  rightLittleDistal: Object.freeze([-0.0291547595, 0.0, 0.0]),
});

// One nanometer only absorbs insignificant JSON number round-off.  It is not
// a geometry compatibility range: canonical v3 has exactly one rest template.
const CANONICAL_REST_OFFSET_TOLERANCE_M = 1e-9;

// Canonical Viewer hand-payload hash:
//   SHA-256(JSON(shape) + 0x00 + C-order IEEE-754 binary32 bytes)
// Every float is explicitly encoded little-endian.  This is the browser-side
// equivalent of Python ``float32_array_sha256``; it does not hash JSON text.
const SHA256_ROUND_CONSTANTS = Object.freeze([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
  0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
  0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
  0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
  0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
  0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotateRight32(value, count) {
  return (value >>> count) | (value << (32 - count));
}

function sha256Hex(bytes) {
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const bitLength = bytes.length * 8;
  const paddedView = new DataView(padded.buffer);
  paddedView.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000), false);
  paddedView.setUint32(paddedLength - 4, bitLength >>> 0, false);

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;
  const words = new Uint32Array(64);

  for (let block = 0; block < paddedLength; block += 64) {
    for (let index = 0; index < 16; index += 1) {
      words[index] = paddedView.getUint32(block + index * 4, false);
    }
    for (let index = 16; index < 64; index += 1) {
      const previous15 = words[index - 15];
      const previous2 = words[index - 2];
      const sigma0 = rotateRight32(previous15, 7)
        ^ rotateRight32(previous15, 18)
        ^ (previous15 >>> 3);
      const sigma1 = rotateRight32(previous2, 17)
        ^ rotateRight32(previous2, 19)
        ^ (previous2 >>> 10);
      words[index] = (words[index - 16] + sigma0 + words[index - 7] + sigma1) >>> 0;
    }

    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight32(e, 6) ^ rotateRight32(e, 11) ^ rotateRight32(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temporary1 = (h + sum1 + choose + SHA256_ROUND_CONSTANTS[index] + words[index]) >>> 0;
      const sum0 = rotateRight32(a, 2) ^ rotateRight32(a, 13) ^ rotateRight32(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temporary2 = (sum0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temporary1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temporary1 + temporary2) >>> 0;
    }
    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }

  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((word) => word.toString(16).padStart(8, "0"))
    .join("");
}

export function canonicalFloat32ArraySha256(value, shape) {
  if (
    !Array.isArray(shape)
    || shape.length === 0
    || shape.some((dimension) => !Number.isInteger(dimension) || dimension < 0)
  ) {
    throw new TypeError("canonical float32 hash requires a non-negative integer shape");
  }
  const elementCount = shape.reduce((count, dimension) => count * dimension, 1);
  if (!Number.isSafeInteger(elementCount)) {
    throw new TypeError("canonical float32 hash shape is too large");
  }
  const shapeJson = `[${shape.join(",")}]`;
  const bytes = new Uint8Array(shapeJson.length + 1 + elementCount * 4);
  for (let index = 0; index < shapeJson.length; index += 1) {
    bytes[index] = shapeJson.charCodeAt(index);
  }
  const view = new DataView(bytes.buffer);
  let byteOffset = shapeJson.length + 1;

  function writeDimension(node, depth) {
    if (depth === shape.length) {
      if (typeof node !== "number" || !Number.isFinite(node)) {
        throw new TypeError("canonical float32 hash input contains a non-finite number");
      }
      view.setFloat32(byteOffset, node, true);
      byteOffset += 4;
      return;
    }
    if (!Array.isArray(node) || node.length !== shape[depth]) {
      throw new TypeError(`canonical float32 hash input does not match shape [${shape.join(", ")}]`);
    }
    for (const child of node) writeDimension(child, depth + 1);
  }

  writeDimension(value, 0);
  return sha256Hex(bytes);
}

const CANONICAL_TO_VRM_V3 = Object.freeze({
  leftThumbProximal: "leftThumbMetacarpal",
  leftThumbIntermediate: "leftThumbProximal",
  leftThumbDistal: "leftThumbDistal",
  rightThumbProximal: "rightThumbMetacarpal",
  rightThumbIntermediate: "rightThumbProximal",
  rightThumbDistal: "rightThumbDistal",
});

function addContractError(errors, path, message) {
  if (errors.length < 16) errors.push(`${path}: ${message}`);
}

function validateExactString(value, expected, path, errors) {
  if (value !== expected) addContractError(errors, path, `expected ${JSON.stringify(expected)}`);
}

function validateExactNames(value, expected, path, errors) {
  if (!Array.isArray(value)) {
    addContractError(errors, path, "expected an ordered bone-name array");
    return false;
  }
  if (value.length !== expected.length) {
    addContractError(errors, path, `expected ${expected.length} names, received ${value.length}`);
    return false;
  }
  for (let index = 0; index < expected.length; index += 1) {
    if (value[index] !== expected[index]) {
      addContractError(errors, `${path}[${index}]`, `expected ${JSON.stringify(expected[index])}`);
      return false;
    }
  }
  return true;
}

function finiteTuple(value, width) {
  return Array.isArray(value)
    && value.length === width
    && value.every((component) => Number.isFinite(component));
}

function validateVectorFrames(value, frameCount, width, path, errors) {
  if (!Array.isArray(value) || value.length !== frameCount) {
    addContractError(errors, path, `expected shape [${frameCount}, ${width}]`);
    return;
  }
  for (let frame = 0; frame < frameCount; frame += 1) {
    if (!finiteTuple(value[frame], width)) {
      addContractError(errors, `${path}[${frame}]`, `expected ${width} finite numbers`);
      return;
    }
  }
}

function validateQuaternion(value, path, errors) {
  if (!finiteTuple(value, 4)) {
    addContractError(errors, path, "expected four finite xyzw components");
    return false;
  }
  const norm = Math.hypot(value[0], value[1], value[2], value[3]);
  if (norm < 1e-8 || Math.abs(norm - 1) > 5e-3) {
    addContractError(errors, path, `expected a non-zero unit quaternion (norm ${norm})`);
    return false;
  }
  return true;
}

function validateQuaternionFrames(value, frameCount, boneCount, path, errors) {
  if (!Array.isArray(value) || value.length !== frameCount) {
    addContractError(errors, path, `expected shape [${frameCount}, ${boneCount}, 4]`);
    return false;
  }
  for (let frame = 0; frame < frameCount; frame += 1) {
    const row = value[frame];
    if (!Array.isArray(row) || row.length !== boneCount) {
      addContractError(errors, `${path}[${frame}]`, `expected ${boneCount} bone quaternions`);
      return false;
    }
    for (let bone = 0; bone < boneCount; bone += 1) {
      if (!validateQuaternion(row[bone], `${path}[${frame}][${bone}]`, errors)) return false;
    }
  }
  return true;
}

function validateCanonicalMapping(value, errors) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    addContractError(errors, "motion.canonical_to_vrm", "expected the canonical-to-VRM bone map");
    return;
  }
  for (const [source, target] of Object.entries(CANONICAL_TO_VRM_V3)) {
    if (value[source] !== target) {
      addContractError(errors, `motion.canonical_to_vrm.${source}`, `expected ${JSON.stringify(target)}`);
      return;
    }
  }
  for (const source of Object.keys(value)) {
    if (!Object.hasOwn(CANONICAL_TO_VRM_V3, source)) {
      addContractError(errors, `motion.canonical_to_vrm.${source}`, "unexpected canonical bone mapping");
      return;
    }
  }
}

function validateRestMetadata(motion, errors) {
  if (!validateExactNames(motion.rest_bones, REST_BONES_V3, "motion.rest_bones", errors)) return;
  if (!motion.rest_offsets || typeof motion.rest_offsets !== "object" || Array.isArray(motion.rest_offsets)) {
    addContractError(errors, "motion.rest_offsets", "expected canonical v3 rest offsets");
    return;
  }

  const expectedBones = new Set(REST_BONES_V3);
  for (const boneName of REST_BONES_V3) {
    if (!Object.hasOwn(motion.rest_offsets, boneName)) {
      addContractError(errors, `motion.rest_offsets.${boneName}`, "missing canonical v3 rest offset");
    }
  }
  for (const boneName of Object.keys(motion.rest_offsets)) {
    if (!expectedBones.has(boneName)) {
      addContractError(errors, `motion.rest_offsets.${boneName}`, "unexpected canonical v3 rest offset");
    }
  }

  for (const boneName of REST_BONES_V3) {
    const actual = motion.rest_offsets[boneName];
    if (!finiteTuple(actual, 3)) {
      addContractError(errors, `motion.rest_offsets.${boneName}`, "expected three finite meter components");
      continue;
    }
    const expected = CANONICAL_REST_OFFSETS_V3[boneName];
    for (let axis = 0; axis < 3; axis += 1) {
      if (Math.abs(actual[axis] - expected[axis]) > CANONICAL_REST_OFFSET_TOLERANCE_M) {
        addContractError(
          errors,
          `motion.rest_offsets.${boneName}[${axis}]`,
          `expected canonical v3 value ${expected[axis]} within ${CANONICAL_REST_OFFSET_TOLERANCE_M} meter`,
        );
      }
    }
  }
}

function validateSha256(value, path, errors) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    addContractError(errors, path, "expected a lowercase SHA-256 digest");
    return false;
  }
  return true;
}

function validateHandConstraintCertificate(motion, frameCount, handQuaternionsValid, errors) {
  const proof = motion.hand_constraint_certificate;
  if (!proof || typeof proof !== "object" || Array.isArray(proof)) {
    addContractError(
      errors,
      "motion.hand_constraint_certificate",
      "canonical v3 requires a verified hand constraint certificate",
    );
    return;
  }
  const allowed = new Set([
    "schema_version", "policy_id", "policy_sha256", "status",
    "postconditions_passed", "frame_count", "observation_sha256",
    "evidence_sha256", "pre_solver_hand_sha256", "output_hand_sha256",
    "report_sha256", "certificate", "artifact_replay_verified",
    "viewer_pose_mutation_count",
    "payload_frame_interval_frames_half_open",
  ]);
  for (const key of Object.keys(proof)) {
    if (!allowed.has(key)) {
      addContractError(
        errors,
        `motion.hand_constraint_certificate.${key}`,
        "unexpected field; Viewer certificates cannot carry pose corrections",
      );
    }
  }
  validateExactString(
    proof.schema_version,
    VRM_MOTION_CONTRACT_V3.handSolverSchemaVersion,
    "motion.hand_constraint_certificate.schema_version",
    errors,
  );
  validateExactString(
    proof.policy_id,
    VRM_MOTION_CONTRACT_V3.handPolicyId,
    "motion.hand_constraint_certificate.policy_id",
    errors,
  );
  validateExactString(
    proof.policy_sha256,
    VRM_MOTION_CONTRACT_V3.handPolicySha256,
    "motion.hand_constraint_certificate.policy_sha256",
    errors,
  );
  if (!["passed_noop", "passed_constrained"].includes(proof.status)) {
    addContractError(errors, "motion.hand_constraint_certificate.status", "expected a passed solver status");
  }
  if (proof.postconditions_passed !== true) {
    addContractError(errors, "motion.hand_constraint_certificate.postconditions_passed", "expected true");
  }
  if (proof.viewer_pose_mutation_count !== 0) {
    addContractError(errors, "motion.hand_constraint_certificate.viewer_pose_mutation_count", "expected zero");
  }
  if (proof.artifact_replay_verified !== true) {
    addContractError(errors, "motion.hand_constraint_certificate.artifact_replay_verified", "expected true");
  }
  for (const key of [
    "observation_sha256", "evidence_sha256", "pre_solver_hand_sha256",
    "report_sha256",
  ]) {
    validateSha256(proof[key], `motion.hand_constraint_certificate.${key}`, errors);
  }
  const outputHashValid = validateSha256(
    proof.output_hand_sha256,
    "motion.hand_constraint_certificate.output_hand_sha256",
    errors,
  );
  if (handQuaternionsValid && outputHashValid) {
    const actualOutputHash = canonicalFloat32ArraySha256(
      motion.hand_quaternions,
      [frameCount, HAND_BONES_V3.length, 4],
    );
    if (actualOutputHash !== proof.output_hand_sha256) {
      addContractError(
        errors,
        "motion.hand_constraint_certificate.output_hand_sha256",
        "does not match the canonical shape+NUL+little-endian-f32 payload hash",
      );
    }
  }
  if (!Number.isInteger(proof.frame_count) || proof.frame_count < frameCount) {
    addContractError(
      errors,
      "motion.hand_constraint_certificate.frame_count",
      "expected an artifact frame count covering this payload",
    );
  }
  const interval = proof.payload_frame_interval_frames_half_open;
  if (
    !Array.isArray(interval)
    || interval.length !== 2
    || !Number.isInteger(interval[0])
    || !Number.isInteger(interval[1])
    || interval[0] < 0
    || interval[1] <= interval[0]
    || interval[1] - interval[0] !== frameCount
    || interval[1] > proof.frame_count
  ) {
    addContractError(
      errors,
      "motion.hand_constraint_certificate.payload_frame_interval_frames_half_open",
      "expected a valid interval matching motion.frame_count",
    );
  }
  const certificate = proof.certificate;
  if (!certificate || typeof certificate !== "object" || Array.isArray(certificate)) {
    addContractError(errors, "motion.hand_constraint_certificate.certificate", "missing report certificate");
  } else {
    validateExactString(certificate.algorithm, "sha256", "motion.hand_constraint_certificate.certificate.algorithm", errors);
    validateSha256(certificate.sha256, "motion.hand_constraint_certificate.certificate.sha256", errors);
    validateExactString(
      certificate.covers,
      "report_without_certificate_including_output_sha256",
      "motion.hand_constraint_certificate.certificate.covers",
      errors,
    );
    if (certificate.verified !== true) {
      addContractError(errors, "motion.hand_constraint_certificate.certificate.verified", "expected true");
    }
  }
}

function validatePreviewEnvelope(payload, motion, frameCount, errors) {
  if (!payload || payload === motion || payload.motion !== motion) return;
  if (!Number.isInteger(payload.frame_count) || payload.frame_count !== frameCount) {
    addContractError(errors, "frame_count", `must equal motion.frame_count (${frameCount})`);
  }
  validateExactString(
    payload?.skeleton?.coordinate_system,
    VRM_MOTION_CONTRACT_V3.coordinateSystem,
    "skeleton.coordinate_system",
    errors,
  );
  validateExactString(payload?.skeleton?.unit, VRM_MOTION_CONTRACT_V3.unit, "skeleton.unit", errors);
  const names = payload?.skeleton?.joint_names;
  if (!validateExactNames(names, REST_BONES_V3, "skeleton.joint_names", errors)) return;
  const positions = payload?.frames?.positions;
  if (!Array.isArray(positions) || positions.length !== frameCount) {
    addContractError(errors, "frames.positions", `expected ${frameCount} position frames`);
    return;
  }
  for (let frame = 0; frame < frameCount; frame += 1) {
    const row = positions[frame];
    if (!Array.isArray(row) || row.length !== names.length) {
      addContractError(errors, `frames.positions[${frame}]`, `expected ${names.length} joint positions`);
      return;
    }
    for (let joint = 0; joint < row.length; joint += 1) {
      if (!finiteTuple(row[joint], 3)) {
        addContractError(errors, `frames.positions[${frame}][${joint}]`, "expected three finite meter components");
        return;
      }
    }
  }
}

/**
 * Accept only the canonical v3 constrained normalized-pose contract consumed by three-vrm.
 * A version string alone is not enough: arrays, names, units and quaternion
 * invariants are checked together so raw-local or partially upgraded payloads
 * cannot silently enter normalized-pose playback.
 */
export function validateVrmMotionPayload(payload) {
  const errors = [];
  const motion = payload?.motion ?? payload;
  if (!motion || typeof motion !== "object" || Array.isArray(motion)) {
    return { supported: false, errors: ["motion: missing VRM motion payload"], motion: null };
  }
  validateExactString(motion.schema_version, VRM_MOTION_CONTRACT_V3.schemaVersion, "motion.schema_version", errors);
  validateExactString(
    motion.canonical_schema_version,
    VRM_MOTION_CONTRACT_V3.canonicalSchemaVersion,
    "motion.canonical_schema_version",
    errors,
  );
  validateExactString(
    motion.rotation_semantics,
    VRM_MOTION_CONTRACT_V3.rotationSemantics,
    "motion.rotation_semantics",
    errors,
  );
  validateExactString(motion.rest_source, VRM_MOTION_CONTRACT_V3.restSource, "motion.rest_source", errors);
  validateExactString(
    motion.coordinate_system,
    VRM_MOTION_CONTRACT_V3.coordinateSystem,
    "motion.coordinate_system",
    errors,
  );
  validateExactString(motion.unit, VRM_MOTION_CONTRACT_V3.unit, "motion.unit", errors);

  const frameCount = motion.frame_count;
  if (!Number.isInteger(frameCount) || frameCount <= 0) {
    addContractError(errors, "motion.frame_count", "expected a positive integer");
    return { supported: false, errors, motion: null };
  }
  const coreNamesValid = validateExactNames(motion.core_bones, CORE_BONES_V3, "motion.core_bones", errors);
  const handNamesValid = validateExactNames(motion.hand_bones, HAND_BONES_V3, "motion.hand_bones", errors);
  validateVectorFrames(motion.root_translation, frameCount, 3, "motion.root_translation", errors);
  if (!Array.isArray(motion.root_rotation) || motion.root_rotation.length !== frameCount) {
    addContractError(errors, "motion.root_rotation", `expected shape [${frameCount}, 4]`);
  } else {
    for (let frame = 0; frame < frameCount; frame += 1) {
      if (!validateQuaternion(motion.root_rotation[frame], `motion.root_rotation[${frame}]`, errors)) break;
    }
  }
  if (coreNamesValid) {
    validateQuaternionFrames(
      motion.core_quaternions,
      frameCount,
      CORE_BONES_V3.length,
      "motion.core_quaternions",
      errors,
    );
  }
  let handQuaternionsValid = false;
  if (handNamesValid) {
    handQuaternionsValid = validateQuaternionFrames(
      motion.hand_quaternions,
      frameCount,
      HAND_BONES_V3.length,
      "motion.hand_quaternions",
      errors,
    );
  }
  validateCanonicalMapping(motion.canonical_to_vrm, errors);
  validateRestMetadata(motion, errors);
  validateHandConstraintCertificate(motion, frameCount, handQuaternionsValid, errors);
  validatePreviewEnvelope(payload, motion, frameCount, errors);
  return {
    supported: errors.length === 0,
    errors,
    motion: errors.length === 0 ? motion : null,
  };
}

function crossVec3(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

export function normalizeVec3Array(v) {
  const len = Math.hypot(v?.[0] || 0, v?.[1] || 0, v?.[2] || 0);
  if (!Number.isFinite(len) || len < 1e-8) return null;
  return [v[0] / len, v[1] / len, v[2] / len];
}

export function normalizeQuatArray(q) {
  const len = Math.hypot(q?.[0] || 0, q?.[1] || 0, q?.[2] || 0, q?.[3] || 0);
  if (!Number.isFinite(len) || len < 1e-8) return [0, 0, 0, 1];
  return [q[0] / len, q[1] / len, q[2] / len, q[3] / len];
}

export function normalizedLocalPoseRotation(q, alignmentQuaternion = null) {
  const local = normalizeQuatArray(q);
  if (!alignmentQuaternion) return local;
  // three-vrm's normalized rig has identity rest rotations, but its offsets
  // are constructed in the avatar's load-time world frame. If the avatar is
  // placed under a canonical world/rest alignment A, the normalized local
  // rotation must be A^-1 q A so that A (A^-1 q A) o = q (A o).
  const alignment = normalizeQuatArray(alignmentQuaternion);
  const inverseAlignment = invertQuatArray(alignment);
  return multiplyQuatArray(multiplyQuatArray(inverseAlignment, local), alignment);
}

export function vrmSpecWorldAlignment(metaVersion) {
  const version = String(metaVersion ?? "").trim();
  if (version === "0") {
    return {
      source: "vrm0_spec_yaw_to_canonical",
      meta_version: "0",
      alignment_quaternion: [0, 1, 0, 0],
    };
  }
  if (version === "1") {
    return {
      source: "vrm1_spec_identity",
      meta_version: "1",
      alignment_quaternion: [0, 0, 0, 1],
    };
  }
  return null;
}

export function invertQuatArray(q) {
  const nq = normalizeQuatArray(q);
  return [-nq[0], -nq[1], -nq[2], nq[3]];
}

export function multiplyQuatArray(a, b) {
  const qa = normalizeQuatArray(a);
  const qb = normalizeQuatArray(b);
  return normalizeQuatArray([
    qa[3] * qb[0] + qa[0] * qb[3] + qa[1] * qb[2] - qa[2] * qb[1],
    qa[3] * qb[1] - qa[0] * qb[2] + qa[1] * qb[3] + qa[2] * qb[0],
    qa[3] * qb[2] + qa[0] * qb[1] - qa[1] * qb[0] + qa[2] * qb[3],
    qa[3] * qb[3] - qa[0] * qb[0] - qa[1] * qb[1] - qa[2] * qb[2],
  ]);
}

export function applyQuatArray(q, v) {
  const rotation = normalizeQuatArray(q);
  const vector = [v?.[0] || 0, v?.[1] || 0, v?.[2] || 0, 0];
  const rotated = multiplyQuatArrayRaw(
    multiplyQuatArrayRaw(rotation, vector),
    invertQuatArray(rotation),
  );
  return rotated.slice(0, 3);
}

function multiplyQuatArrayRaw(a, b) {
  return [
    a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
    a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
    a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
    a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
  ];
}

function quatFromAxes(axes) {
  const x = axes.x;
  const y = axes.y;
  const z = axes.z;
  const m00 = x[0];
  const m01 = y[0];
  const m02 = z[0];
  const m10 = x[1];
  const m11 = y[1];
  const m12 = z[1];
  const m20 = x[2];
  const m21 = y[2];
  const m22 = z[2];
  const trace = m00 + m11 + m22;
  let qx;
  let qy;
  let qz;
  let qw;

  if (trace > 0) {
    const s = Math.sqrt(trace + 1.0) * 2.0;
    qw = 0.25 * s;
    qx = (m21 - m12) / s;
    qy = (m02 - m20) / s;
    qz = (m10 - m01) / s;
  } else if (m00 > m11 && m00 > m22) {
    const s = Math.sqrt(1.0 + m00 - m11 - m22) * 2.0;
    qw = (m21 - m12) / s;
    qx = 0.25 * s;
    qy = (m01 + m10) / s;
    qz = (m02 + m20) / s;
  } else if (m11 > m22) {
    const s = Math.sqrt(1.0 + m11 - m00 - m22) * 2.0;
    qw = (m02 - m20) / s;
    qx = (m01 + m10) / s;
    qy = 0.25 * s;
    qz = (m12 + m21) / s;
  } else {
    const s = Math.sqrt(1.0 + m22 - m00 - m11) * 2.0;
    qw = (m10 - m01) / s;
    qx = (m02 + m20) / s;
    qy = (m12 + m21) / s;
    qz = 0.25 * s;
  }
  return normalizeQuatArray([qx, qy, qz, qw]);
}

export function buildHumanoidAxesFromPositionMap(positionMap) {
  const hips = positionMap.hips;
  const spine = positionMap.spine || positionMap.upperChest || positionMap.chest;
  const left = positionMap.leftUpperLeg || positionMap.leftUpperArm;
  const right = positionMap.rightUpperLeg || positionMap.rightUpperArm;
  if (!hips || !spine || !left || !right) return null;

  const up = normalizeVec3Array([
    spine[0] - hips[0],
    spine[1] - hips[1],
    spine[2] - hips[2],
  ]);
  const lateral = normalizeVec3Array([
    left[0] - right[0],
    left[1] - right[1],
    left[2] - right[2],
  ]);
  if (!up || !lateral) return null;

  let forward = normalizeVec3Array(crossVec3(lateral, up));
  if (!forward) return null;
  let orthoLateral = normalizeVec3Array(crossVec3(up, forward));
  if (!orthoLateral) return null;

  if (dotVec3(orthoLateral, lateral) < 0) {
    orthoLateral = [-orthoLateral[0], -orthoLateral[1], -orthoLateral[2]];
    forward = [-forward[0], -forward[1], -forward[2]];
  }

  return { x: orthoLateral, y: up, z: forward };
}

export function buildHumanoidSpaceAlignment(sourcePositionMap, targetPositionMap) {
  const sourceAxes = buildHumanoidAxesFromPositionMap(sourcePositionMap);
  const targetAxes = buildHumanoidAxesFromPositionMap(targetPositionMap);
  if (!sourceAxes || !targetAxes) return null;
  const sourceQuaternion = quatFromAxes(sourceAxes);
  const targetQuaternion = quatFromAxes(targetAxes);
  return {
    source_axes: sourceAxes,
    target_axes: targetAxes,
    source_quaternion: sourceQuaternion,
    target_quaternion: targetQuaternion,
    alignment_quaternion: multiplyQuatArray(targetQuaternion, invertQuatArray(sourceQuaternion)),
  };
}
