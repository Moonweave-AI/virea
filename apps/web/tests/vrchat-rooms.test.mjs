import test from "node:test";
import assert from "node:assert/strict";
import {roomView} from "../src/vrchat-rooms.mjs";

test("room progress displays resolved direction before claiming arrival", () => {
  const state = {stage: "waiting_for_arrival", direction: "观察者加入 AI，保留 AI 当前站位", same_instance: false};
  const view = roomView(state);
  assert.equal(view.active, true);
  assert.match(view.text, /观察者加入 AI/);
  assert.match(view.text, /等待两端实际到达/);
  assert.doesNotMatch(view.text, /已确认到达/);
  assert.match(roomView({...state, stage: "arrived", same_instance: true}).text, /已确认到达/);
});

test("room errors, offline state and pipe acknowledgements cannot fake arrival", () => {
  assert.equal(roomView(null).visible, false);
  assert.match(roomView({stage: "failed", error: "没有管道"}).text, /没有管道/);
  assert.doesNotMatch(roomView({stage: "arrived", same_instance: false}).text, /已确认到达/);
  assert.match(roomView({stage: "arrived", same_instance: true}, true).text, /连接中断/);
});

test("private invite progress and auth failures remain distinct from arrival", () => {
  assert.equal(roomView({stage: "inviting"}).active, true);
  assert.match(roomView({stage: "inviting"}).text, /发送.*邀请/);
  assert.equal(roomView({stage: "invitation_verified"}).active, true);
  assert.doesNotMatch(roomView({stage: "invitation_verified"}).text, /已确认到达/);
  const auth = roomView({stage: "authentication_required", error: "观察者 API 401"});
  assert.equal(auth.active, false);
  assert.match(auth.text, /观察者 API 401/);
  assert.equal(roomView({stage: "invitation_required", error: "需要邀请"}).active, false);
});
