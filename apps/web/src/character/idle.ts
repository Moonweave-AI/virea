import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import type { PoseSample } from "./recovery";

/** Captured relaxed stance plus small respiratory motion, separate from bind pose. */
export class RelaxedIdle {
  private elapsed = 0;
  private active = false;
  private readonly base = new Map<THREE.Object3D, THREE.Quaternion>();

  constructor(private readonly vrm: VRM, rotations: Record<string, number[]>) {
    for (const [name, values] of Object.entries(rotations)) {
      const bone = vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      if (!bone || values.length !== 4 || !values.every(Number.isFinite)) continue;
      const q = new THREE.Quaternion().fromArray(values).normalize();
      // Match createVRMAnimationHumanoidTracks' VRM 0 coordinate conversion.
      if (vrm.meta.metaVersion === "0") { q.x *= -1; q.z *= -1; }
      this.base.set(bone, q);
      bone.quaternion.copy(q);
    }
  }

  stop(): void { this.active = false; }

  start(pose: PoseSample): void {
    for (const [bone, q] of pose.rotations) this.base.set(bone, q.clone());
    this.elapsed = 0;
    this.active = true;
  }

  update(dt: number): void {
    if (!this.active) return;
    this.elapsed += dt;
    const blend = THREE.MathUtils.smootherstep(this.elapsed, 0, 1.5);
    const breath = Math.sin(this.elapsed * 1.45) * 0.008 * blend;
    const sway = Math.sin(this.elapsed * 0.61) * 0.006 * blend;
    for (const [bone, q] of this.base) bone.quaternion.copy(q);
    for (const [name, x, z] of [
      ["spine", breath * 0.4, sway], ["chest", breath, -sway * 0.4],
      ["neck", -breath * 0.3, -sway * 0.3],
      ["leftShoulder", breath * 0.3, breath * 0.3],
      ["rightShoulder", breath * 0.3, -breath * 0.3],
    ] as const) {
      this.vrm.humanoid.getNormalizedBoneNode(name)?.quaternion.multiply(
        new THREE.Quaternion().setFromEuler(new THREE.Euler(x, 0, z)));
    }
    const phase = this.elapsed % 4.7;
    const blink = phase < 0.16 ? Math.sin(Math.PI * phase / 0.16) : 0;
    for (const name of ["blinkLeft", "blinkRight"]) this.vrm.expressionManager?.setValue(name, blink);
  }
}
