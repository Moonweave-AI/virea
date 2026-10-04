import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { registerHooks } from "node:module";
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { BodyAuthority } = await import("../src/character/body_authority.ts");

test("unanimated joints never feed a transition correction back into the source pose", () => {
  const bones = Object.fromEntries(["hips", "head", "leftHand"].map(n => [n, new THREE.Object3D()]));
  const authority = new BodyAuthority({ humanoid: { humanBones: bones, getNormalizedBoneNode: n => bones[n] } });
  const axis = new THREE.Vector3(0, 1, 0);
  for (let i = 0; i < 60; i++) authority.render("ardy", 1 / 60, () => bones.head.quaternion.setFromAxisAngle(axis, i / 120), true);
  const held = bones.head.quaternion.clone();
  authority.beginSpeech();
  for (let i = 0; i < 90; i++) {
    authority.capture(() => bones.leftHand.quaternion.setFromAxisAngle(axis, .2));
    authority.render("sentiavatar", 1 / 60, () => {}, false);
  }
  assert.ok(bones.head.quaternion.angleTo(held) < 1e-6, "head accumulated transition error despite having no source animation");
});
