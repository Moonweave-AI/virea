import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import { RotationBridge, rotationVector } from "./continuity";
import { GroundSupport } from "./support";

export type BodyOwner = "ardy" | "sentiavatar" | "hold";
type Pose = Map<string, { q: THREE.Quaternion; p: THREE.Vector3 }>;

/** One body source per frame. Handoffs decay the old boundary error, not another animation. */
export class BodyAuthority {
  private bones = new Map<string, THREE.Object3D>();
  private speech: Pose | null = null;
  private last: Pose;
  private velocity = new Map<string, THREE.Vector3>();
  private bridges = new Map<string, RotationBridge>();
  private support: GroundSupport;
  private positionError = new THREE.Vector3();
  private key = "hold";
  private clip = 0;
  private elapsed = 0;
  owner: BodyOwner = "hold";

  constructor(vrm: VRM) {
    this.support = new GroundSupport(vrm);
    for (const name of Object.keys(vrm.humanoid.humanBones)) {
      const bone = vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      if (bone) this.bones.set(name, bone);
    }
    this.last = this.snapshot();
  }

  private snapshot(): Pose {
    return new Map([...this.bones].map(([name, b]) => [name, { q: b.quaternion.clone(), p: b.position.clone() }]));
  }
  private restore(pose: Pose): void {
    for (const [name, value] of pose) { const b = this.bones.get(name)!; b.quaternion.copy(value.q); b.position.copy(value.p); }
  }
  beginSpeech(): void { this.clip++; }
  get speechReady(): boolean { return this.speech !== null; }
  get groundClearance(): number | null { return this.support.clearance(); }
  release(): void { this.speech = null; }
  capture(sample: () => void): void {
    const held = this.snapshot();
    try { sample(); this.speech = this.snapshot(); }
    finally { this.restore(held); }
  }

  render(requested: BodyOwner, dt: number, sampleArdy: () => void, ardyReady: boolean): void {
    const owner = requested === "ardy" && ardyReady ? "ardy"
      : requested === "sentiavatar" && this.speech ? "sentiavatar" : "hold";
    this.restore(this.last);
    if (owner === "ardy") sampleArdy();
    if (owner === "sentiavatar") this.restore(this.speech!);
    if (owner === "sentiavatar") this.support.align();
    const key = owner === "sentiavatar" ? `${owner}:${this.clip}` : owner;
    const hips = this.bones.get("hips");
    if (key !== this.key) {
      this.bridges.clear(); this.elapsed = 0;
      for (const [name, b] of this.bones)
        this.bridges.set(name, new RotationBridge(this.last.get(name)!.q, b.quaternion, this.velocity.get(name)));
      if (hips) this.positionError.copy(this.last.get("hips")!.p).sub(hips.position);
      this.key = key;
    }
    if (owner !== "hold" && hips) {
      const t = THREE.MathUtils.clamp(this.elapsed / .4, 0, 1);
      hips.position.addScaledVector(this.positionError, 2 * t ** 3 - 3 * t ** 2 + 1);
    }
    if (owner !== "hold") for (const [name, b] of this.bones) this.bridges.get(name)?.apply(b.quaternion, this.elapsed);
    if (dt > 0) for (const [name, b] of this.bones)
      this.velocity.set(name, rotationVector(b.quaternion.clone().multiply(this.last.get(name)!.q.clone().invert())).divideScalar(dt));
    this.last = this.snapshot(); this.elapsed += dt; this.owner = owner;
  }
}
