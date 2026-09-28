import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import type { GestureWeights } from "./contracts";
import { RotationBridge } from "./continuity";

const regions: Record<string, keyof GestureWeights> = {
  spine: "torso", chest: "torso", upperChest: "torso", neck: "head", head: "head",
  ...Object.fromEntries(["left", "right"].flatMap(side =>
    ["Shoulder", "UpperArm", "LowerArm"].map(part => [side + part, side + "_arm"]))),
};

/** One final writer. Speech contributes a local rotational residual, never root/legs. */
export class PoseLayers {
  private readonly bones = new Map<string, THREE.Object3D>();
  private readonly reference = new Map<string, THREE.Quaternion>();
  private base = new Map<string, THREE.Quaternion>();
  private speech = new Map<string, THREE.Quaternion>();
  private envelope = 0;
  private target = 0;
  private weights = new Map<string, number>();
  private bridges = new Map<string, RotationBridge>();
  private newClip = false;

  constructor(vrm: VRM) {
    for (const name of Object.keys(vrm.humanoid.humanBones)) {
      const bone = vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      if (bone) { this.bones.set(name, bone); this.reference.set(name, bone.quaternion.clone()); }
    }
    this.saveBase();
  }

  private saveBase(): void {
    for (const [name, bone] of this.bones) this.base.set(name, bone.quaternion.clone());
  }

  restoreBase(): void { for (const [name, bone] of this.bones) bone.quaternion.copy(this.base.get(name)!); }
  release(): void { this.target = 0; }
  beginSpeech(): void { this.newClip = true; this.bridges.clear(); }

  capture(sample: () => void, elapsed = 0): void {
    // Mixer sampling is isolated from the executed skeleton, including translation.
    const held = new Map([...this.bones].map(([name, bone]) => [name, { q: bone.quaternion.clone(), p: bone.position.clone() }]));
    try {
      sample();
      const incoming = new Map([...this.bones].map(([name, bone]) => [name, bone.quaternion.clone()]));
      if (this.newClip) for (const [name, q] of incoming)
        this.bridges.set(name, new RotationBridge(this.speech.get(name) ?? this.reference.get(name)!, q));
      this.newClip = false;
      for (const [name, q] of incoming) this.bridges.get(name)?.apply(q, elapsed);
      this.speech = incoming;
      this.target = 1;
    } finally {
      for (const [name, bone] of this.bones) { bone.quaternion.copy(held.get(name)!.q); bone.position.copy(held.get(name)!.p); }
    }
  }

  apply(dt: number, weights?: GestureWeights | null, protectedBones: ReadonlySet<string> = new Set()): void {
    this.saveBase();
    const blend = 1 - Math.exp(-Math.max(0, dt) / .12);
    this.envelope = THREE.MathUtils.lerp(this.envelope, this.target, blend);
    for (const [name, bone] of this.bones) {
      const region = regions[name] ?? (/(Hand|Thumb|Index|Middle|Ring|Little)/.test(name) ? "hands" : undefined);
      if (!region) continue;
      const desired = protectedBones.has(name) ? 0 : weights?.[region] ?? 1;
      const weight = THREE.MathUtils.lerp(this.weights.get(name) ?? desired, desired, blend);
      this.weights.set(name, weight);
      const speech = this.speech.get(name), reference = this.reference.get(name);
      if (!speech || !reference) continue;
      const residual = reference.clone().invert().multiply(speech);
      bone.quaternion.multiply(new THREE.Quaternion().slerp(residual, weight * this.envelope)).normalize();
    }
  }
}
