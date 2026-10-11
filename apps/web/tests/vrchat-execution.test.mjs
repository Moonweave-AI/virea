import test from "node:test";
import assert from "node:assert/strict";
import {acceptSnapshot, executionNote} from "../src/vrchat-conversation.mjs";

test("a poll begun before switching cannot restore the old backend", () => {
  const current = {session: {id: "same", epoch: 5, motion_backend: "motioncraft"}};
  assert.equal(acceptSnapshot(current, {session: {id: "same", epoch: 4}}, false), false);
  assert.equal(acceptSnapshot(current, current, true), false);
  assert.equal(acceptSnapshot(current, current, false), true);
  assert.equal(acceptSnapshot(current, {session: {id: "new", epoch: 0}}, false), true);
});

test("execution distinguishes preset send, parameter receipt, and unavailable body motion", () => {
  const state = {execution: {mode: "desktop", emotes_sent: [1], emotes_observed: [], segments: [
    {prompt: "A person waves.", body_output: "avatar_preset:wave"},
    {prompt: "A person nods.", body_output: "not_transmitted"},
  ]}};
  assert.match(executionNote(state), /1 种已发送，0 种收到游戏参数回传/);
  assert.match(executionNote(state), /模型生成的全身骨骼未传递/);
  assert.match(executionNote(state), /A person nods/);
  assert.doesNotMatch(executionNote(state), /A person waves/);
  assert.equal(executionNote({}), "");
});

test("the execution note cannot leak success from a previous task epoch", () => {
  const state = {session: {epoch: 3, events: [{kind: "playback_feedback", epoch: 2, feedback: {packet_id: "old"}}]}, recent_performances: [{packet_id: "old", execution: {mode: "desktop", emotes_sent: [1]}}]};
  assert.equal(executionNote(state), "");
});
