import test from "node:test";
import assert from "node:assert/strict";
import { captureVideo } from "../src/character/video.ts";

function captureFixture(t) {
  const calls = [], tracks = [0, 1].map(id => ({ stop: () => calls.push(`stop:${id}`) }));
  const paint = { drawImage() {}, fillText() {}, fillRect() {}, measureText: text => ({ width: text.length * 10 }) };
  const names = ["document", "MediaStream", "MediaRecorder", "requestAnimationFrame", "cancelAnimationFrame"];
  const saved = names.map(name => Object.getOwnPropertyDescriptor(globalThis, name));
  t.after(() => names.forEach((name, i) => {
    if (saved[i]) Object.defineProperty(globalThis, name, saved[i]); else delete globalThis[name];
  }));
  globalThis.document = { createElement: () => ({ width: 0, height: 0, getContext: () => paint,
    captureStream: () => ({ getVideoTracks: () => [tracks[0]] }) }) };
  globalThis.MediaStream = class { constructor(tracks) { this.tracks = tracks; } getTracks() { return this.tracks; } };
  let recorder;
  globalThis.MediaRecorder = class {
    static isTypeSupported() { return true; }
    state = "inactive";
    constructor() { recorder = this; }
    start() { this.state = "recording"; calls.push("start"); }
    stop() { this.state = "inactive"; calls.push("finish"); queueMicrotask(() => {
      this.ondataavailable({ data: new Blob(["actual frames"]) }); this.onstop();
    }); }
  };
  globalThis.requestAnimationFrame = () => 1;
  globalThis.cancelAnimationFrame = () => calls.push("cancel-frame");
  const context = { createMediaStreamDestination: () => ({ stream: { getAudioTracks: () => [tracks[1]] } }) };
  const output = { connect: () => calls.push("connect"), disconnect: () => calls.push("disconnect") };
  return { calls, recorder: () => recorder,
    run: playback => captureVideo({ width: 640, height: 480 }, context, output, playback, () => ({ caption: "你好", label: "sentiavatar" })) };
}

test("video export waits for encoded data and releases its audio and video tracks", async t => {
  const f = captureFixture(t);
  const result = await f.run(async () => { assert.equal(f.recorder().state, "recording"); });
  assert.equal(await result.text(), "actual frames");
  assert.deepEqual(f.calls, ["connect", "start", "cancel-frame", "finish", "disconnect", "stop:0", "stop:1"]);
});

test("an interrupted replay releases recording resources without exporting a partial success", async t => {
  const f = captureFixture(t);
  await assert.rejects(f.run(async () => { throw new DOMException("Stopped", "AbortError"); }), /Stopped/);
  assert.ok(f.calls.includes("finish") && f.calls.includes("disconnect") && f.calls.includes("stop:1"));
});

test("an encoder error is surfaced after cleanup", async t => {
  const f = captureFixture(t);
  await assert.rejects(f.run(async () => { f.recorder().onerror(); }), /编码失败/);
  assert.ok(f.calls.includes("stop:0"));
});
