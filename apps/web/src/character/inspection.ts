import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";

const chains = [
  ["hips", "spine", "chest", "upperChest", "neck", "head"],
  ["upperChest", "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand"],
  ["upperChest", "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand"],
  ["hips", "leftUpperLeg", "leftLowerLeg", "leftFoot", "leftToes"],
  ["hips", "rightUpperLeg", "rightLowerLeg", "rightFoot", "rightToes"],
];

/** Native joints alongside the retargeted rig make conversion errors observable. */
export class MotionInspection {
  readonly object = new THREE.LineSegments(new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({ color: 0x3b82f6, depthTest: false, transparent: true, opacity: .8 }));

  constructor() { this.object.visible = false; this.object.renderOrder = 10; }

  update(vrm: VRM, joints: Map<string, THREE.Vector3>): number {
    const points: THREE.Vector3[] = [], angles: number[] = [];
    for (const chain of chains) for (let i = 1; i < chain.length; i++) {
      const a = chain[i - 1]!, b = chain[i]!;
      const first = joints.get(a), last = joints.get(b);
      if (!first || !last) continue;
      points.push(first, last);
      const source = vrm.humanoid.getNormalizedBoneNode(a as VRMHumanBoneName);
      const target = vrm.humanoid.getNormalizedBoneNode(b as VRMHumanBoneName);
      if (source && target) {
        const native = last.clone().sub(first);
        const actual = target.getWorldPosition(new THREE.Vector3()).sub(source.getWorldPosition(new THREE.Vector3()));
        if (native.length() > .02 && actual.length() > .02) angles.push(native.angleTo(actual) * 180 / Math.PI);
      }
    }
    if (this.object.visible) {
      this.object.geometry.setFromPoints(points);
      this.object.geometry.computeBoundingSphere();
    }
    return angles.length ? Math.max(...angles) : 0;
  }
}
