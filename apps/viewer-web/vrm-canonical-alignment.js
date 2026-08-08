function dotVec3(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function crossVec3(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

const IDENTITY_QUATERNION = [0, 0, 0, 1];

function stableQuatSign(q) {
  const normalized = normalizeQuatArray(q);
  return normalized[3] < 0 ? normalized.map((value) => -value) : normalized;
}

export const TERMINAL_PARENT = {
  leftLowerLeg: "leftUpperLeg",
  leftFoot: "leftLowerLeg",
  leftToes: "leftFoot",
  rightLowerLeg: "rightUpperLeg",
  rightFoot: "rightLowerLeg",
  rightToes: "rightFoot",
  leftHand: "leftLowerArm",
  rightHand: "rightLowerArm",
};

for (const side of ["left", "right"]) {
  for (const finger of ["Thumb", "Index", "Middle", "Ring", "Little"]) {
    TERMINAL_PARENT[`${side}${finger}Proximal`] = `${side}Hand`;
    TERMINAL_PARENT[`${side}${finger}Intermediate`] = `${side}${finger}Proximal`;
    TERMINAL_PARENT[`${side}${finger}Distal`] = `${side}${finger}Intermediate`;
  }
}

const TERMINAL_PRIMARY_CHILD = {
  leftLowerLeg: "leftFoot",
  leftFoot: "leftToes",
  rightLowerLeg: "rightFoot",
  rightFoot: "rightToes",
};

for (const side of ["left", "right"]) {
  for (const finger of ["Thumb", "Index", "Middle", "Ring", "Little"]) {
    TERMINAL_PRIMARY_CHILD[`${side}${finger}Proximal`] = `${side}${finger}Intermediate`;
    TERMINAL_PRIMARY_CHILD[`${side}${finger}Intermediate`] = `${side}${finger}Distal`;
  }
}

function subtractVec3(a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

function projectedAwayFromAxis(vector, axis) {
  const amount = dotVec3(vector, axis);
  return [
    vector[0] - amount * axis[0],
    vector[1] - amount * axis[1],
    vector[2] - amount * axis[2],
  ];
}

function angleBetweenVec3(a, b) {
  const na = normalizeVec3Array(a);
  const nb = normalizeVec3Array(b);
  if (!na || !nb) return null;
  return Math.acos(Math.max(-1, Math.min(1, dotVec3(na, nb)))) * 180 / Math.PI;
}

function finiteVec3(v) {
  return (
    Array.isArray(v) &&
    v.length >= 3 &&
    Number.isFinite(v[0]) &&
    Number.isFinite(v[1]) &&
    Number.isFinite(v[2])
  );
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

export function quatFromTwoVectorsArray(from, to) {
  const source = normalizeVec3Array(from);
  const target = normalizeVec3Array(to);
  if (!source || !target) return null;
  const cosine = Math.max(-1, Math.min(1, dotVec3(source, target)));
  if (cosine > 1 - 1e-8) return [...IDENTITY_QUATERNION];
  if (cosine < -1 + 1e-8) {
    const helper = Math.abs(source[0]) <= Math.abs(source[1]) && Math.abs(source[0]) <= Math.abs(source[2])
      ? [1, 0, 0]
      : Math.abs(source[1]) <= Math.abs(source[2])
        ? [0, 1, 0]
        : [0, 0, 1];
    const axis = normalizeVec3Array(crossVec3(source, helper));
    return axis ? normalizeQuatArray([axis[0], axis[1], axis[2], 0]) : null;
  }
  const axis = crossVec3(source, target);
  return normalizeQuatArray([axis[0], axis[1], axis[2], 1 + cosine]);
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

function frameFromPrimaryLateral(primary, lateral) {
  const x = normalizeVec3Array(primary);
  if (!x) return null;
  const lateralProjected = projectedAwayFromAxis(lateral, x);
  let y = normalizeVec3Array(lateralProjected);
  if (!y) return null;
  const z = normalizeVec3Array(crossVec3(x, y));
  if (!z) return null;
  y = normalizeVec3Array(crossVec3(z, x));
  if (!y) return null;
  return { x, y, z };
}

function frameCorrection(targetPrimary, targetLateral, canonicalPrimary, canonicalLateral) {
  const targetFrame = frameFromPrimaryLateral(targetPrimary, targetLateral);
  const canonicalFrame = frameFromPrimaryLateral(canonicalPrimary, canonicalLateral);
  if (!targetFrame || !canonicalFrame) return null;
  return stableQuatSign(
    multiplyQuatArray(quatFromAxes(canonicalFrame), invertQuatArray(quatFromAxes(targetFrame))),
  );
}

function canonicalOffset(canonicalOffsets, boneName) {
  const offset = canonicalOffsets?.[boneName];
  return finiteVec3(offset) ? offset.slice(0, 3).map(Number) : null;
}

function targetOffset(targetPositions, boneName) {
  const parentName = TERMINAL_PARENT[boneName];
  const point = targetPositions?.[boneName];
  const parent = targetPositions?.[parentName];
  return finiteVec3(point) && finiteVec3(parent) ? subtractVec3(point, parent) : null;
}

/**
 * Build target-rest -> canonical-rest global frame corrections for terminal
 * chains only. The returned C_j values are consumed hierarchically as
 * C_parent^-1 L_j C_j; they must never be used as C_j L_j C_j^-1.
 */
export function buildTerminalRestPoseCorrections(canonicalOffsets, targetCanonicalPositions) {
  const globalCorrections = {};
  const missingBones = new Set();
  const calibratedEdges = [];

  const setSingleChildCorrection = (boneName, childName) => {
    const target = targetOffset(targetCanonicalPositions, childName);
    const canonical = canonicalOffset(canonicalOffsets, childName);
    const correction = target && canonical ? quatFromTwoVectorsArray(target, canonical) : null;
    if (!correction) {
      missingBones.add(boneName);
      missingBones.add(childName);
      return false;
    }
    globalCorrections[boneName] = stableQuatSign(correction);
    calibratedEdges.push({ boneName, childName, target, canonical });
    return true;
  };

  for (const [boneName, childName] of Object.entries(TERMINAL_PRIMARY_CHILD)) {
    setSingleChildCorrection(boneName, childName);
  }

  for (const side of ["left", "right"]) {
    const hand = `${side}Hand`;
    const middle = `${side}MiddleProximal`;
    const index = `${side}IndexProximal`;
    const little = `${side}LittleProximal`;
    const targetPrimary = targetOffset(targetCanonicalPositions, middle);
    const canonicalPrimary = canonicalOffset(canonicalOffsets, middle);
    const targetIndex = targetOffset(targetCanonicalPositions, index);
    const targetLittle = targetOffset(targetCanonicalPositions, little);
    const canonicalIndex = canonicalOffset(canonicalOffsets, index);
    const canonicalLittle = canonicalOffset(canonicalOffsets, little);
    const correction = targetPrimary && canonicalPrimary && targetIndex && targetLittle && canonicalIndex && canonicalLittle
      ? frameCorrection(
        targetPrimary,
        subtractVec3(targetIndex, targetLittle),
        canonicalPrimary,
        subtractVec3(canonicalIndex, canonicalLittle),
      )
      : null;
    if (correction) globalCorrections[hand] = correction;
    else {
      missingBones.add(hand);
      missingBones.add(middle);
      missingBones.add(index);
      missingBones.add(little);
    }
  }

  // Never apply only half of a terminal chain. A missing/degenerate target
  // bone falls back to the untouched portable mapping for that complete chain.
  for (const side of ["left", "right"]) {
    const lowerLeg = `${side}LowerLeg`;
    const foot = `${side}Foot`;
    const toes = `${side}Toes`;
    if (!globalCorrections[lowerLeg] || !globalCorrections[foot]) {
      delete globalCorrections[lowerLeg];
      delete globalCorrections[foot];
      delete globalCorrections[toes];
    }
    const hand = `${side}Hand`;
    if (!globalCorrections[hand]) {
      for (const finger of ["Thumb", "Index", "Middle", "Ring", "Little"]) {
        delete globalCorrections[`${side}${finger}Proximal`];
        delete globalCorrections[`${side}${finger}Intermediate`];
        delete globalCorrections[`${side}${finger}Distal`];
      }
      continue;
    }
    for (const finger of ["Thumb", "Index", "Middle", "Ring", "Little"]) {
      const proximal = `${side}${finger}Proximal`;
      const intermediate = `${side}${finger}Intermediate`;
      const distal = `${side}${finger}Distal`;
      if (!globalCorrections[proximal] || !globalCorrections[intermediate]) {
        delete globalCorrections[proximal];
        delete globalCorrections[intermediate];
        delete globalCorrections[distal];
      }
    }
  }

  // Terminal leaf rotations remain expressed in the already aligned parent
  // frame. Inheriting C_parent makes an identity leaf rotation stay identity.
  for (const side of ["left", "right"]) {
    const foot = `${side}Foot`;
    const toes = `${side}Toes`;
    if (globalCorrections[foot]) globalCorrections[toes] = [...globalCorrections[foot]];
    for (const finger of ["Thumb", "Index", "Middle", "Ring", "Little"]) {
      const intermediate = `${side}${finger}Intermediate`;
      const distal = `${side}${finger}Distal`;
      if (globalCorrections[intermediate]) {
        globalCorrections[distal] = [...globalCorrections[intermediate]];
      }
    }
  }

  const errors = calibratedEdges.filter(({ boneName }) => globalCorrections[boneName]).map(({ boneName, target, canonical }) => (
    angleBetweenVec3(applyQuatArray(globalCorrections[boneName], target), canonical)
  )).filter(Number.isFinite);
  return {
    mode: "hierarchical-terminal-rest.v1",
    globalCorrections,
    correctionCount: Object.keys(globalCorrections).length,
    calibratedEdgeCount: errors.length,
    maxCalibratedErrorDeg: errors.length ? Math.max(...errors) : null,
    missingBones: [...missingBones].sort(),
  };
}

export function hierarchicalRestLocalRotation(q, boneName, globalCorrections) {
  const local = normalizeQuatArray(q);
  const current = globalCorrections?.[boneName] || IDENTITY_QUATERNION;
  const parentName = TERMINAL_PARENT[boneName];
  const parent = globalCorrections?.[parentName] || IDENTITY_QUATERNION;
  return multiplyQuatArray(multiplyQuatArray(invertQuatArray(parent), local), current);
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
