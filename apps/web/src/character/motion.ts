import * as THREE from "three";

/** Rebase root translation to the actually held root. This is playback alignment. */
export function anchorClip(clip: THREE.AnimationClip, hips: THREE.Object3D): THREE.AnimationClip {
  const anchored = clip.clone();
  for (const track of anchored.tracks) {
    if (track.name !== `${hips.name}.position` || track.getValueSize() !== 3) continue;
    const dx = hips.position.x - track.values[0]!;
    const dz = hips.position.z - track.values[2]!;
    for (let index = 0; index < track.values.length; index += 3) {
      track.values[index] = track.values[index]! + dx;
      track.values[index + 2] = track.values[index + 2]! + dz;
    }
  }
  return anchored;
}

export function sceneDestination(value: { x: number; y: number; z: number }): THREE.Vector3 {
  if (![value.x, value.y, value.z].every(Number.isFinite)
      || Math.abs(value.x) > 20 || Math.abs(value.z) > 20) throw new Error("场景目标超出范围");
  return new THREE.Vector3(value.x, value.y, value.z);
}
