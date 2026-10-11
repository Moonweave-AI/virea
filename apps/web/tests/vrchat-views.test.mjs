import test from "node:test";
import assert from "node:assert/strict";
import {FramePump, viewError} from "../src/vrchat-views.mjs";

const nextTurn = () => new Promise(resolve => setImmediate(resolve));
const jpeg = () => new Response(new Blob(["frame"], {type: "image/jpeg"}), {headers: {
  "X-Capture-Age-Ms": "50", "X-Capture-Pid": "22", "X-Capture-Sequence": "7",
}});

test("browser fetch is called without binding the pump as its receiver", async () => {
  let delivered;
  const delivery = new Promise(resolve => { delivered = resolve; });
  const pump = new FramePump("ai", () => delivered(), () => {}, function () {
    assert.equal(this, undefined);
    return Promise.resolve(jpeg());
  });
  pump.start();
  await delivery;
  pump.stop();
});

test("closing the pane aborts in-flight work and ignores a late successful response", async () => {
  let resolve;
  let signal;
  const frames = [];
  const errors = [];
  const pump = new FramePump("ai", (...args) => frames.push(args), e => errors.push(e), (_, options) => {
    signal = options.signal;
    return new Promise(done => { resolve = done; });
  });
  pump.start();
  pump.stop();
  assert.equal(signal.aborted, true);
  resolve(jpeg());
  await nextTurn();
  assert.deepEqual(frames, []);
  assert.deepEqual(errors, []);
});

test("rapid reopen cannot display the prior session's late frame", async () => {
  const replies = [];
  const frames = [];
  let delivered;
  const delivery = new Promise(resolve => { delivered = resolve; });
  const pump = new FramePump("observer", (_, info) => { frames.push(info); delivered(); }, () => {}, (url, options) => {
    assert.equal(url, "/api/v1/vrchat/views/observer/frame");
    assert.equal(options.headers["X-Virea-Capture"], "1");
    return new Promise(resolve => replies.push(resolve));
  });
  pump.start(); pump.start();
  assert.equal(replies.length, 1);
  pump.stop(); pump.start();
  replies[0](jpeg());
  await nextTurn();
  assert.equal(frames.length, 0);
  replies[1](jpeg());
  await delivery;
  pump.stop();
  assert.equal(frames.length, 1);
  assert.equal(frames[0].pid, "22");
});

test("minimized and stale views show status instead of pretending to be live", async () => {
  const errors = [];
  let images = 0;
  const minimized = new FramePump("ai", () => images++, e => errors.push(e), async () =>
    Response.json({detail: {code: "window_minimized"}}, {status: 409}));
  minimized.start();
  await nextTurn();
  minimized.stop();
  assert.match(errors[0], /最小化/);
  const stale = new FramePump("ai", () => images++, e => errors.push(e), async () =>
    new Response("old", {headers: {"X-Capture-Age-Ms": "2000"}}));
  stale.start();
  await nextTurn();
  stale.stop();
  assert.match(errors[1], /暂未更新/);
  assert.equal(images, 0);
  assert.match(viewError("unrecognized"), /自动重试/);
});
