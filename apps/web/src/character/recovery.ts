import * as THREE from "three";
import { RotationBridge, rotationVector } from "./continuity";

export interface PoseSample {
  rotations: Map<THREE.Object3D, THREE.Quaternion>;
  position: THREE.Vector3;
}

/** Each speech gesture retracts from its actual velocity to a relaxed stance. */
export class PoseRecovery {
  readonly duration: number;
  private readonly rotations: { bone: THREE.Object3D; target: THREE.Quaternion; bridge: RotationBridge }[];
  private readonly offset: THREE.Vector3;
  private readonly velocity: THREE.Vector3;
  private readonly target: THREE.Vector3;
  private readonly hips: THREE.Object3D;

  constructor(hips: THREE.Object3D, before: PoseSample, last: PoseSample, rest: PoseSample, dt: number) {
    this.hips = hips;
    const targets = [...last.rotations].map(([bone, q]) => {
      const target = rest.rotations.get(bone)?.clone() ?? q.clone();
      // Preserve the executed heading while letting pelvic tilt relax.
      if (bone === hips) target.copy(new THREE.Quaternion(0, q.y, 0, q.w).normalize());
      return { bone, q, target };
    });
    const angle = Math.max(0, ...targets.map(({ q, target }) => q.angleTo(target)));
    this.duration = THREE.MathUtils.clamp(0.65 + angle / 2.5, 0.65, 1.6);
    this.rotations = targets.map(({ bone, q, target }) => ({ bone, target,
      bridge: new RotationBridge(q, target,
        rotationVector(q.clone().multiply((before.rotations.get(bone) ?? q).clone().invert())).divideScalar(dt),
        new THREE.Vector3(), this.duration),
    }));
    // Keep the executed ground position. Only the pelvis height returns to standing.
    this.target = last.position.clone();
    this.target.y = rest.position.y;
    this.offset = last.position.clone().sub(this.target);
    this.velocity = last.position.clone().sub(before.position).divideScalar(dt).clampLength(0, 1);
  }

  apply(seconds: number): void {
    for (const { bone, target, bridge } of this.rotations) {
      bone.quaternion.copy(target);
      bridge.apply(bone.quaternion, seconds);
    }
    const t = THREE.MathUtils.clamp(seconds / this.duration, 0, 1);
    this.hips.position.copy(this.target).addScaledVector(this.offset, 2 * t ** 3 - 3 * t ** 2 + 1)
      .addScaledVector(this.velocity, (t ** 3 - 2 * t ** 2 + t) * this.duration);
  }
}

/** Blink and visemes release promptly; affect relaxes over the longer body recovery. */
export function faceRelease(name: string, seconds: number, duration: number): number {
  return 1 - THREE.MathUtils.smootherstep(seconds, 0,
    /^(blink|eyeBlink|jawOpen|mouth(?!Smile|Frown|Dimple|Stretch)|aa$|ih$|ou$|ee$|oh$)/.test(name) ? 0.18 : duration);
}
