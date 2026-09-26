import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { anchorClip, sceneDestination } from "../src/character/motion.ts";

test("next motion is anchored at executed planar root without modifying the source", () => {
  const hips = new THREE.Object3D();
  hips.name = "hips"; hips.position.set(3, 1, -2);
  const source = new THREE.AnimationClip("next", 1, [new THREE.VectorKeyframeTrack("hips.position", [0, 1], [0, 1, 0, 1, 1, 2])]);
  const result = anchorClip(source, hips);
  assert.deepEqual([...result.tracks[0].values], [3, 1, -2, 4, 1, 0]);
  assert.deepEqual([...source.tracks[0].values], [0, 1, 0, 1, 1, 2]);
});

test("engine destinations reject nonfinite or out-of-world positions", () => {
  assert.throws(() => sceneDestination({ x: Infinity, y: 0, z: 0 }));
  assert.throws(() => sceneDestination({ x: 30, y: 0, z: 0 }));
  assert.deepEqual(sceneDestination({ x: 1, y: 0, z: -2 }).toArray(), [1, 0, -2]);
});
