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
