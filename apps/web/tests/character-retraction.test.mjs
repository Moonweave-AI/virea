import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { registerHooks } from "node:module";
registerHooks({ resolve(s, c, next) { try { return next(s, c); } catch (e) { if (s.startsWith(".")) return next(s + ".ts", c); throw e; } } });
const { BodyAuthority } = await import("../src/character/body_authority.ts");

test("final gesture retracts continuously to the contextual seated pose and keeps travel", () => {
  const bones = Object.fromEntries(["hips", "head", "leftUpperLeg"].map(n => [n, new THREE.Object3D()]));
  bones.hips.position.set(2, .6, 3);
  bones.leftUpperLeg.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), -.8);
  const rest = bones.leftUpperLeg.quaternion.clone();
  const owner = new BodyAuthority({ humanoid: { humanBones: bones, getNormalizedBoneNode: n => bones[n] } });
  owner.beginSpeech();
  owner.capture(() => { bones.head.rotation.z = .8; bones.leftUpperLeg.rotation.x = -.2; });
  for (let i = 0; i < 90; i++) owner.render("sentiavatar", 1 / 60, () => {}, false);
  const boundary = bones.head.quaternion.clone();
  // Audio ends before the facial release finishes. A hold frame between the
  // body lease and end-of-utterance must not lose the need to retract.
  owner.render("hold", .32, () => {}, false);
  owner.release(); owner.retract();
  owner.render("hold", 1 / 60, () => assert.fail(), false);
  assert.ok(bones.head.quaternion.angleTo(boundary) < 1e-6);
  for (let i = 0; i < 120; i++) owner.render("hold", 1 / 60, () => assert.fail(), false);
  assert.equal(owner.retracting, false);
  assert.ok(bones.leftUpperLeg.quaternion.angleTo(rest) < 1e-7);
  assert.deepEqual(bones.hips.position.toArray(), [2, .6, 3]);
});

test("explicit interruption cancels a pending gesture retraction", () => {
  const hips = new THREE.Object3D();
  const owner = new BodyAuthority({ humanoid: { humanBones: { hips }, getNormalizedBoneNode: n => n === "hips" ? hips : null } });
  owner.capture(() => { hips.rotation.x = 1; });
  owner.render("sentiavatar", .1, () => {}, false);
  owner.release(); owner.retract(); assert.ok(owner.retracting);
  owner.release(); assert.equal(owner.retracting, false);
});

test("a frame hitch advances the handoff and retraction on the current frame", () => {
  function rig() {
    const hips = new THREE.Object3D();
    return { hips, owner: new BodyAuthority({ humanoid: { humanBones: { hips }, getNormalizedBoneNode: n => n === "hips" ? hips : null } }) };
  }
  const a = rig(), b = rig();
  for (const r of [a, b]) {
    r.owner.beginSpeech(); r.owner.capture(() => { r.hips.rotation.x = .8; });
    r.owner.render("sentiavatar", .004, () => {}, false);
  }
  a.owner.render("sentiavatar", .1, () => {}, false);
  for (let i = 0; i < 25; i++) b.owner.render("sentiavatar", .004, () => {}, false);
  assert.ok(a.hips.quaternion.angleTo(b.hips.quaternion) < 1e-6);
  for (const r of [a, b]) {
    for (let i = 0; i < 150; i++) r.owner.render("sentiavatar", .004, () => {}, false);
    r.owner.release(); r.owner.retract(); r.owner.render("hold", .004, () => {}, false);
  }
  a.owner.render("hold", .1, () => {}, false);
  for (let i = 0; i < 25; i++) b.owner.render("hold", .004, () => {}, false);
  assert.ok(a.hips.quaternion.angleTo(b.hips.quaternion) < 1e-6);
});
