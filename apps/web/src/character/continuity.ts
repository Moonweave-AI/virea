import * as THREE from "three";

/** Shortest local rotation vector, including the q/-q equivalence. */
export function rotationVector(value: THREE.Quaternion): THREE.Vector3 {
  const q = value.clone().normalize();
  if (q.w < 0) { q.x *= -1; q.y *= -1; q.z *= -1; q.w *= -1; }
  const length = Math.hypot(q.x, q.y, q.z);
  return length < 1e-8 ? new THREE.Vector3() : new THREE.Vector3(q.x, q.y, q.z)
    .multiplyScalar(2 * Math.atan2(length, q.w) / length);
}

export function rotation(value: THREE.Vector3): THREE.Quaternion {
  const angle = value.length();
  return angle < 1e-8 ? new THREE.Quaternion()
    : new THREE.Quaternion().setFromAxisAngle(value.clone().divideScalar(angle), angle);
}

/** Hermite correction: actual pose/velocity at entry, zero correction/velocity at exit. */
export class RotationBridge {
  private offset: THREE.Vector3;
  private velocity: THREE.Vector3;
  readonly duration: number;

  constructor(held: THREE.Quaternion, incoming: THREE.Quaternion,
    heldVelocity = new THREE.Vector3(), incomingVelocity = new THREE.Vector3()) {
    const correction = held.clone().multiply(incoming.clone().invert());
    this.offset = rotationVector(correction);
    const difference = heldVelocity.clone().sub(incomingVelocity.clone().applyQuaternion(correction));
    const angle = this.offset.length();
    const coefficient = angle < 1e-4 ? 1 / 12 : (1 - angle / (2 * Math.tan(angle / 2))) / angle ** 2;
    const cross = this.offset.clone().cross(difference);
    // Inverse SO(3) left Jacobian: offsets about another axis must preserve velocity too.
    this.velocity = difference.addScaledVector(cross, -0.5)
      .addScaledVector(this.offset.clone().cross(cross), coefficient).clampLength(0, 6);
    this.duration = THREE.MathUtils.clamp(this.offset.length() / 3, 0.24, 0.6);
  }

  apply(incoming: THREE.Quaternion, seconds: number): void {
    const t = THREE.MathUtils.clamp(seconds / this.duration, 0, 1);
    const offset = this.offset.clone().multiplyScalar(2 * t ** 3 - 3 * t ** 2 + 1)
      .addScaledVector(this.velocity, (t ** 3 - 2 * t ** 2 + t) * this.duration);
    incoming.premultiply(rotation(offset)).normalize();
  }
}
