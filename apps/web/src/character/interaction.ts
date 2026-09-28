import * as THREE from "three";

/** Small contact correction over the generated pose; keeps the body's model balance. */
export function contactIK(chain: THREE.Object3D[], hand: THREE.Object3D, target: THREE.Vector3, weight: number): number {
  const root = chain.at(-1)?.parent;
  if (!root || weight <= 0) return Infinity;
  root.updateWorldMatrix(true, true);
  const wanted = hand.getWorldPosition(new THREE.Vector3()).lerp(target, THREE.MathUtils.clamp(weight, 0, 1));
  for (let iteration = 0; iteration < 8; iteration++) {
    for (const joint of chain) {
      joint.updateWorldMatrix(true, true);
      const origin = joint.getWorldPosition(new THREE.Vector3());
      const from = hand.getWorldPosition(new THREE.Vector3()).sub(origin);
      const to = wanted.clone().sub(origin);
      if (from.lengthSq() < 1e-8 || to.lengthSq() < 1e-8) continue;
      const delta = new THREE.Quaternion().setFromUnitVectors(from.normalize(), to.normalize());
      const angle = delta.angleTo(new THREE.Quaternion());
      if (angle > .25) delta.slerp(new THREE.Quaternion(), 1 - .25 / angle);
      const parent = joint.parent?.getWorldQuaternion(new THREE.Quaternion()) ?? new THREE.Quaternion();
      joint.quaternion.premultiply(parent.clone().invert().multiply(delta).multiply(parent)).normalize();
    }
  }
  root.updateWorldMatrix(true, true);
  return hand.getWorldPosition(new THREE.Vector3()).distanceTo(target);
}
