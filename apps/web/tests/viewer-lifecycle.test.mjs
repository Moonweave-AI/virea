import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const vrmViewer = fs.readFileSync(path.join(root, "src", "viewer.ts"), "utf8");
const sourceViewer = fs.readFileSync(path.join(root, "src", "source-viewer.ts"), "utf8");

test("both motion viewers expose complete OrbitControls interaction and reset", () => {
  for (const source of [vrmViewer, sourceViewer]) {
    assert.match(source, /OrbitControls/);
    assert.match(source, /enablePan = true/);
    assert.match(source, /enableRotate = true/);
    assert.match(source, /enableZoom = true/);
    assert.match(source, /public resetView\(\): void/);
    assert.match(source, /addEventListener\("dblclick", this\.handleResetGesture\)/);
    assert.match(source, /removeEventListener\("dblclick", this\.handleResetGesture\)/);
  }
});

test("root locomotion translates the camera and user control target without replacing the view", () => {
  const vrmFollow = vrmViewer.slice(
    vrmViewer.indexOf("private followAvatarHips"),
    vrmViewer.indexOf("private resize"),
  );
  assert.match(vrmFollow, /advancePlanarCameraFollow/);
  assert.match(vrmFollow, /this\.camera\.position\.set\(step\.cameraPosition/);
  assert.match(vrmFollow, /this\.controls\.target\.add\(this\.followTranslation\)/);

  const sourceFrame = sourceViewer.slice(
    sourceViewer.indexOf("private updateFrame"),
    sourceViewer.indexOf("private updateCameraFraming"),
  );
  assert.match(sourceFrame, /this\.camera\.position\.add\(this\.followTranslation\)/);
  assert.match(sourceFrame, /this\.controls\.target\.add\(this\.followTranslation\)/);
  assert.doesNotMatch(sourceFrame, /this\.camera\.lookAt/);
});

test("inactive, hidden, and context-lost viewers cancel rather than spin their RAF", () => {
  for (const source of [vrmViewer, sourceViewer]) {
    assert.match(source, /document\.addEventListener\("visibilitychange"/);
    assert.match(source, /!this\.disposed && this\.active && !this\.contextLost && !document\.hidden/);
    assert.match(source, /cancelAnimationFrame\(this\.frameHandle\)/);
    assert.match(source, /this\.frameHandle = null/);
    assert.doesNotMatch(source, /if \(!this\.active\)[\s\S]{0,160}requestAnimationFrame/);
  }
});

test("VRM asynchronous loads are single-flight, epoch guarded, and mixers are uncached", () => {
  assert.match(vrmViewer, /url === this\.avatarLoadUrl && this\.avatarLoadPromise/);
  assert.match(vrmViewer, /url === this\.animationLoadUrl && this\.animationLoadPromise/);
  assert.match(vrmViewer, /epoch !== this\.avatarLoadEpoch/);
  assert.match(vrmViewer, /epoch !== this\.animationLoadEpoch/);
  assert.match(vrmViewer, /VRMUtils\.deepDispose\(vrm\?\.scene \?\? gltf\.scene\)/);
  assert.match(vrmViewer, /this\.mixer\.uncacheClip\(this\.boundClip\)/);
  assert.match(vrmViewer, /this\.mixer\.uncacheRoot\(this\.vrm\.scene\)/);
});

test("viewer teardown and WebGL recovery are observable and release owned resources", () => {
  for (const source of [vrmViewer, sourceViewer]) {
    assert.match(source, /webglContextRecovery = "lost"/);
    assert.match(source, /webglContextRecovery = "restored"/);
    assert.match(source, /renderer\.resetState\(\)/);
    assert.match(source, /controls\.dispose\(\)/);
    assert.match(source, /renderer\.renderLists\.dispose\(\)/);
    assert.match(source, /renderer\.dispose\(\)/);
    assert.match(source, /TELEMETRY_INTERVAL_MS = 250/);
  }
  assert.match(vrmViewer, /VRMUtils\.deepDispose\(this\.vrm\.scene\)/);
  assert.match(sourceViewer, /actor\.lines\.geometry\.dispose\(\)/);
  assert.match(sourceViewer, /actor\.points\.geometry\.dispose\(\)/);
});
