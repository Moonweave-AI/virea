import * as THREE from "three";

type Rows = number[][];

function frame(rows: Rows, index: number, previous?: Rows, next?: Rows): number[] {
  if (index < 0) return previous?.[previous.length - 2] ?? rows[0]!;
  if (index >= rows.length) return next?.[1] ?? rows.at(-1)!;
  return rows[index]!;
}

/** Neighbour windows share one endpoint. Derivatives use real adjacent frames. */
export function samplePosition(rows: Rows, cursor: number, previous?: Rows, next?: Rows): THREE.Vector3 {
  const index = Math.floor(cursor), t = cursor - index;
  const p = [-1, 0, 1, 2].map(offset => new THREE.Vector3().fromArray(frame(rows, index + offset, previous, next)));
  const result = new THREE.Vector3();
  for (const axis of ["x", "y", "z"] as const) {
    const [a, b, c, d] = p.map(point => point[axis]);
    result[axis] = .5 * (2 * b! + (-a! + c!) * t + (2 * a! - 5 * b! + 4 * c! - d!) * t * t + (-a! + 3 * b! - 3 * c! + d!) * t * t * t);
  }
  return result;
}

function logarithm(q: THREE.Quaternion): THREE.Vector3 {
  const sine = Math.hypot(q.x, q.y, q.z);
  return new THREE.Vector3(q.x, q.y, q.z).multiplyScalar(sine > 1e-8 ? Math.atan2(sine, q.w) / sine : 1);
}

function tangent(previous: THREE.Quaternion, q: THREE.Quaternion, next: THREE.Quaternion): THREE.Quaternion {
  const inverse = q.clone().invert();
  const v = logarithm(inverse.clone().multiply(previous)).add(logarithm(inverse.multiply(next))).multiplyScalar(-.25);
  const angle = v.length(), scale = angle > 1e-8 ? Math.sin(angle) / angle : 1;
  return q.clone().multiply(new THREE.Quaternion(v.x * scale, v.y * scale, v.z * scale, Math.cos(angle))).normalize();
}

export function sampleRotation(rows: Rows, cursor: number, previous?: Rows, next?: Rows): THREE.Quaternion {
  const index = Math.floor(cursor), t = cursor - index;
  const q = [-1, 0, 1, 2].map(offset => new THREE.Quaternion().fromArray(frame(rows, index + offset, previous, next)).normalize());
  for (let i = 1; i < q.length; i++) if (q[i - 1]!.dot(q[i]!) < 0) {
    const value = q[i]!; value.set(-value.x, -value.y, -value.z, -value.w);
  }
  return q[1]!.clone().slerp(q[2]!, t).slerp(tangent(q[0]!, q[1]!, q[2]!).slerp(tangent(q[1]!, q[2]!, q[3]!), t), 2 * t * (1 - t));
}
