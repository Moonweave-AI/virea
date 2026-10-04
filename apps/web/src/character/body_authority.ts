import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import { RotationBridge, rotationVector } from "./continuity";
import { GroundSupport } from "./support";

export type BodyOwner = "ardy" | "sentiavatar" | "motioncraft" | "syntalker" | "hold";
type Pose = Map<string, { q: THREE.Quaternion; p: THREE.Vector3 }>;

/** One body source per frame. Handoffs decay the old boundary error, not another animation. */
export class BodyAuthority {
  private bones = new Map<string, THREE.Object3D>();
  private speech: Pose | null = null;
  private speechBasis: Pose | null = null;
  private ardy: Pose | null = null;
  private last: Pose;
  private resting: Pose;
  private retraction: { elapsed: number | null; duration: number; bridges: Map<string, RotationBridge>; offset: THREE.Vector3 } | null = null;
  private velocity = new Map<string, THREE.Vector3>();
  private bridges = new Map<string, RotationBridge>();
  private support: GroundSupport;
  private positionError = new THREE.Vector3();
  private key = "hold";
  private clip = 0;
  private gestureNeedsRetraction = false;
  private elapsed = 0;
  owner: BodyOwner = "hold";

  constructor(vrm: VRM) {
    this.support = new GroundSupport(vrm);
    for (const name of Object.keys(vrm.humanoid.humanBones)) {
      const bone = vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      if (bone) this.bones.set(name, bone);
    }
    this.last = this.snapshot();
    this.resting = this.snapshot();
  }

  private snapshot(): Pose {
    return new Map([...this.bones].map(([name, b]) => [name, { q: b.quaternion.clone(), p: b.position.clone() }]));
  }
  private restore(pose: Pose): void {
    for (const [name, value] of pose) { const b = this.bones.get(name)!; b.quaternion.copy(value.q); b.position.copy(value.p); }
  }
  beginSpeech(): void { this.clip++; this.retraction = null; this.speech = null; this.speechBasis = this.snapshot(); }
  commitRest(): void { this.resting = this.snapshot(); this.gestureNeedsRetraction = false; }
  get retracting(): boolean { return this.retraction !== null; }
  /** Return a completed gesture to its contextual support pose, never the bind pose. */
  retract(): void {
    if (!this.gestureNeedsRetraction || this.retraction) return;
    const duration = Math.min(1.6, Math.max(.65,
      ...[...this.last].map(([name, value]) => value.q.angleTo(this.resting.get(name)!.q) / 2.5 + .65)));
    const bridges = new Map([...this.last].map(([name, value]) => [name,
      new RotationBridge(value.q, this.resting.get(name)!.q, this.velocity.get(name), undefined, duration)]));
    this.retraction = { elapsed: null, duration, bridges,
      offset: this.last.get("hips")!.p.clone().sub(this.resting.get("hips")!.p) };
  }
  get speechReady(): boolean { return this.speech !== null; }
  get groundClearance(): number | null { return this.support.clearance(); }
  release(): void { this.speech = null; this.retraction = null; }
  capture(sample: () => void): void {
    const held = this.snapshot();
    this.speechBasis ??= held;
    // Three's PropertyMixer skips unchanged values. Restore the previous
    // uncorrected sample, not the entry pose, so constant tracks cannot revert.
    try { this.restore(this.speech ?? this.speechBasis); sample(); this.speech = this.snapshot(); }
    finally { this.restore(held); }
  }

  render(requested: BodyOwner, dt: number, sampleArdy: () => void, ardyReady: boolean): void {
    const spatialOwner = requested === "ardy" || requested === "motioncraft" || requested === "syntalker";
    const owner = spatialOwner && ardyReady ? requested
      : requested === "sentiavatar" && this.speech ? "sentiavatar" : "hold";
    this.restore(this.last);
    if (owner !== "hold") this.retraction = null;
    if (owner !== "hold") this.gestureNeedsRetraction = owner === "sentiavatar";
    if (owner === "ardy" || owner === "motioncraft" || owner === "syntalker") {
      // Source sampling must never inherit the last rendered correction. Sparse
      // tracks otherwise integrate that error repeatedly (notably head/fingers).
      if (this.owner !== owner || !this.ardy) this.ardy = this.snapshot();
      this.restore(this.ardy); sampleArdy(); this.ardy = this.snapshot();
    }
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
    } else this.elapsed += dt;
    if (owner !== "hold" && hips) {
      const t = THREE.MathUtils.clamp(this.elapsed / .4, 0, 1);
      hips.position.addScaledVector(this.positionError, 2 * t ** 3 - 3 * t ** 2 + 1);
    }
    if (owner !== "hold") for (const [name, b] of this.bones) this.bridges.get(name)?.apply(b.quaternion, this.elapsed);
    if (owner === "hold" && this.retraction) {
      const r = this.retraction;
      r.elapsed = r.elapsed === null ? 0 : Math.min(r.duration, r.elapsed + dt);
      for (const [name, b] of this.bones) {
        b.quaternion.copy(this.resting.get(name)!.q);
        r.bridges.get(name)!.apply(b.quaternion, r.elapsed);
      }
      if (hips) {
        const t = THREE.MathUtils.clamp(r.elapsed / r.duration, 0, 1);
        // The resting support height is contextual; world travel is retained.
        hips.position.y = this.resting.get("hips")!.p.y + r.offset.y * (2 * t ** 3 - 3 * t ** 2 + 1);
      }
      if (r.elapsed >= r.duration) { this.retraction = null; this.gestureNeedsRetraction = false; this.key = "hold"; }
    }
    if (dt > 0) for (const [name, b] of this.bones)
      this.velocity.set(name, rotationVector(b.quaternion.clone().multiply(this.last.get(name)!.q.clone().invert())).divideScalar(dt));
    this.last = this.snapshot(); this.owner = owner;
  }
}
