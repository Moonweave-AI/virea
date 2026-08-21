import test from "node:test";
import assert from "node:assert/strict";

import * as THREE from "three";

import {
  assertFiniteClip,
  assertUsableAnimationRestHips,
  advancePlanarCameraFollow,
  computeCameraFraming,
  ensureVRMLookAtQuaternionProxy,
} from "../src/viewer-compat.ts";
import { VRMLookAtQuaternionProxy } from "@pixiv/three-vrm-animation";

function animationWithRestHeight(height) {
  return { restHipsPosition: new THREE.Vector3(0, height, 0) };
}

test("zero-height VRMA metadata fails before binding can create non-finite tracks", () => {
  assert.throws(() => assertUsableAnimationRestHips(animationWithRestHeight(0)), /hips rest height/);
  assert.throws(() => assertUsableAnimationRestHips(animationWithRestHeight(-1)), /hips rest height/);
  assert.throws(() => assertUsableAnimationRestHips(animationWithRestHeight(Number.NaN)), /hips rest height/);
});

test("valid VRMA rest height passes without mutation", () => {
  const animation = animationWithRestHeight(1.12);

  assert.doesNotThrow(() => assertUsableAnimationRestHips(animation));
  assert.equal(animation.restHipsPosition.y, 1.12);
});

test("look-at proxy is explicitly named, registered once, and bound to the Avatar lookAt", () => {
  const scene = new THREE.Group();
  const lookAt = { yaw: 0, pitch: 0 };
  const vrm = { scene, lookAt };

  const first = ensureVRMLookAtQuaternionProxy(vrm);
  const second = ensureVRMLookAtQuaternionProxy(vrm);

  assert.ok(first instanceof VRMLookAtQuaternionProxy);
  assert.equal(first.name, "VRMLookAtQuaternionProxy");
  assert.equal(first.vrmLookAt, lookAt);
  assert.equal(second, first);
  assert.deepEqual(scene.children, [first]);
});

test("Avatar without VRM look-at semantics gets no proxy", () => {
  const scene = new THREE.Group();

  assert.equal(ensureVRMLookAtQuaternionProxy({ scene, lookAt: null }), null);
  assert.deepEqual(scene.children, []);
});

test("animation clips containing non-finite track values are rejected", () => {
  const invalid = new THREE.AnimationClip("invalid", 1, [
    new THREE.VectorKeyframeTrack("hips.position", [0, 1], [0, 0, 0, Number.POSITIVE_INFINITY, 0, 0]),
  ]);
  assert.throws(() => assertFiniteClip(invalid), /hips\.position/);

  const valid = new THREE.AnimationClip("valid", 1, [
    new THREE.VectorKeyframeTrack("hips.position", [0, 1], [0, 0, 0, 0.2, 0, 0]),
  ]);
  assert.doesNotThrow(() => assertFiniteClip(valid));
});

test("camera framing fits both avatar height and T-pose width at the current aspect", () => {
  const portrait = computeCameraFraming(2.4, 1.8, 0.4, 0.6, THREE.MathUtils.degToRad(30));
  const landscape = computeCameraFraming(2.4, 1.8, 0.4, 1.8, THREE.MathUtils.degToRad(30));

  assert.ok(portrait.distance > landscape.distance, "horizontal FOV must constrain portrait canvases");
  assert.ok(portrait.near > 0);
  assert.ok(portrait.far > portrait.distance);
  assert.throws(
    () => computeCameraFraming(Number.NaN, 1.8, 0.4, 1.8, THREE.MathUtils.degToRad(30)),
    /包围盒或 Viewer 尺寸无效/,
  );
});

test("camera follows real hips X/Z while preserving vertical full-body framing and animation input", () => {
  const hips = { x: 2.5, y: 4.0, z: -1.25 };
  const snapshot = { ...hips };
  const step = advancePlanarCameraFollow(
    { x: 0, y: 1, z: 4 },
    { x: 0, y: 1, z: 0 },
    { x: 0, y: 1, z: 0 },
    { x: 0.5, y: 1, z: -0.25 },
    hips,
    1,
    100,
  );

  assert.deepEqual(hips, snapshot, "camera behavior must never rewrite the animation's root translation");
  assert.ok(Math.abs(step.target.x - 2) < 1e-9);
  assert.equal(step.target.y, 1, "hips vertical motion must not introduce camera bounce");
  assert.ok(Math.abs(step.target.z + 1) < 1e-9);
  assert.deepEqual(
    {
      x: step.cameraPosition.x - step.target.x,
      y: step.cameraPosition.y - step.target.y,
      z: step.cameraPosition.z - step.target.z,
    },
    { x: 0, y: 0, z: 4 },
    "camera-to-target offset must be invariant",
  );
});

test("camera follow smoothing is frame-rate stable and rejects non-finite hips", () => {
  function followAtFps(fps) {
    let camera = { x: 0, y: 1, z: 4 };
    let target = { x: 0, y: 1, z: 0 };
    for (let frame = 0; frame < fps; frame += 1) {
      const step = advancePlanarCameraFollow(
        camera,
        target,
        { x: 0, y: 1, z: 0 },
        { x: 0, y: 1, z: 0 },
        { x: 3, y: 2, z: -2 },
        1 / fps,
      );
      camera = step.cameraPosition;
      target = step.target;
    }
    return { camera, target };
  }

  const at30 = followAtFps(30);
  const at60 = followAtFps(60);
  assert.ok(Math.abs(at30.target.x - at60.target.x) < 1e-12);
  assert.ok(Math.abs(at30.target.z - at60.target.z) < 1e-12);
  assert.equal(at30.target.y, 1);
  assert.throws(
    () =>
      advancePlanarCameraFollow(
        { x: 0, y: 1, z: 4 },
        { x: 0, y: 1, z: 0 },
        { x: 0, y: 1, z: 0 },
        { x: 0, y: 1, z: 0 },
        { x: Number.NaN, y: 1, z: 0 },
        1 / 60,
      ),
    /相机跟随输入无效/,
  );
});

test("camera follow snaps across a locomotion loop discontinuity without changing camera offset", () => {
  const step = advancePlanarCameraFollow(
    { x: 5, y: 1, z: 8 },
    { x: 5, y: 1, z: 4 },
    { x: 0, y: 1, z: 0 },
    { x: 0, y: 1, z: 0 },
    { x: 0, y: 1.4, z: 0 },
    1 / 60,
    12,
    true,
  );

  assert.deepEqual(step.target, { x: 0, y: 1, z: 0 });
  assert.deepEqual(step.cameraPosition, { x: 0, y: 1, z: 4 });
});
