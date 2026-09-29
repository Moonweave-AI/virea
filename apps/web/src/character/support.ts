import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";

/** Avatar proportions change foot clearance even when joint rotations match. */
export class GroundSupport {
  private readonly feet: { name: string; bone: THREE.Object3D }[];
  private readonly sole: number;
  private readonly vrm: VRM;
  constructor(vrm: VRM) {
    this.vrm = vrm;
    this.feet = ["leftFoot", "rightFoot", "leftToes", "rightToes"].flatMap(name => {
      const bone = vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      return bone ? [{ name, bone }] : [];
    });
    vrm.scene?.updateMatrixWorld(true);
    this.sole = this.feet.length ? Math.min(...this.feet.map(({ bone }) => bone.getWorldPosition(new THREE.Vector3()).y)) - (vrm.scene?.position.y ?? 0) : 0;
  }
  clearance(): number | null {
    if (!this.feet.length) return null;
    this.vrm.scene.updateMatrixWorld(true);
    return Math.min(...this.feet.map(({ bone }) => bone.getWorldPosition(new THREE.Vector3()).y)) - this.vrm.scene.position.y - this.sole;
  }
  align(native?: ReadonlyMap<string, THREE.Vector3>): void {
    const hips = this.vrm.humanoid.getNormalizedBoneNode("hips");
    if (!hips?.parent || !this.feet.length) return;
    const floor = this.vrm.scene.position.y;
    const samples = this.feet.flatMap(({ name }) => native?.has(name) ? [native.get(name)!.y - floor] : []);
    if (native && !samples.length) return;
    const target = samples.length ? Math.max(0, Math.min(...samples)) : 0;
    const error = target - this.clearance()!;
    const root = hips.getWorldPosition(new THREE.Vector3()); root.y += error;
    hips.position.copy(hips.parent.worldToLocal(root));
    this.vrm.scene.updateMatrixWorld(true);
  }
}
