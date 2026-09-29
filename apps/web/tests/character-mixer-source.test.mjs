import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { registerHooks } from "node:module";
registerHooks({ resolve(s, c, next) { try { return next(s, c); } catch (e) { if (s.startsWith(".")) return next(s + ".ts", c); throw e; } } });
const { BodyAuthority } = await import("../src/character/body_authority.ts");
const { sampleClip } = await import("../src/character/motion.ts");

test("cached constant mixer tracks retain the source pose during a model handoff", () => {
  const hips = new THREE.Object3D(), head = new THREE.Object3D();
  hips.name = "hips"; head.name = "head"; hips.add(head);
  head.rotation.y = .6; // The completed spatial activity's actual head pose.
  const bones = { hips, head };
  const owner = new BodyAuthority({ humanoid: { humanBones: bones, getNormalizedBoneNode: n => bones[n] } });
  const clip = new THREE.AnimationClip("speech", 2, [
    new THREE.QuaternionKeyframeTrack("head.quaternion", [0, 2], [0, 0, 0, 1, 0, 0, 0, 1]),
  ]);
  const mixer = new THREE.AnimationMixer(hips), action = mixer.clipAction(clip);
  action.setLoop(THREE.LoopOnce, 1); action.clampWhenFinished = true; action.play();
  owner.beginSpeech();
  let previous = head.quaternion.clone(), peak = 0;
  for (let i = 0; i < 300; i++) {
    owner.capture(() => sampleClip(mixer, action, i / 240));
    owner.render("sentiavatar", 1 / 240, () => {}, false);
    peak = Math.max(peak, head.quaternion.angleTo(previous) * 240);
    previous.copy(head.quaternion);
  }
  assert.ok(peak < 6, `constant source generated ${peak.toFixed(2)} rad/s`);
  assert.ok(head.quaternion.angleTo(new THREE.Quaternion()) < 1e-6);
});
