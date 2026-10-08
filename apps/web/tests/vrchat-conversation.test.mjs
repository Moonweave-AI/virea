import test from "node:test";
import assert from "node:assert/strict";
import {mergeTranscript, readConversations, bridgeError, executionResult, statusLabel} from "../src/vrchat-conversation.mjs";

test("VRChat polling and truncated server history do not duplicate conversation turns", () => {
  const turns = [{role: "user", content: "hello"}, {role: "assistant", content: "hello"}, {role: "user", content: "again"}];
  assert.deepEqual(mergeTranscript(turns, turns), turns);
  const reply = {role: "assistant", content: "again"};
  assert.deepEqual(mergeTranscript(turns, [turns[1], turns[2], reply]), [...turns, reply]);
  assert.deepEqual(mergeTranscript(turns, []), turns);
});

test("VRChat restored history excludes system-role injection and malformed storage", () => {
  assert.deepEqual(readConversations("bad json"), []);
  assert.deepEqual(readConversations('{"version":2,"items":[]}'), []);
  const saved = readConversations(JSON.stringify({version:1,items:[{id:"one",messages:[{role:"system",content:"instructions"},{role:"user",content:"<script>literal text</script>"},null]}]}));
  assert.equal(saved[0].messages.length, 1);
  assert.equal(saved[0].messages[0].content, "<script>literal text</script>");
});

test("VRChat task errors and playback states are visible rather than masked by connection state", () => {
  const state = {connected:true,ready:true,session:{status:"error",events:[{kind:"error",message:"model unavailable"}]}};
  assert.equal(bridgeError(state), "model unavailable");
  assert.equal(statusLabel(state), "任务遇到问题");
  assert.equal(statusLabel({connected:true,ready:true,paused:true}), "已暂停");
  assert.equal(statusLabel({connected:true,ready:false}), "等待 VRChat 连接");
});

test("VRChat stopped generation cannot reuse the preceding performance's success", () => {
  const state = {connected:true,ready:true,session:{epoch:4,status:"waiting",events:[
    {kind:"playback_feedback",epoch:2,feedback:{packet_id:"previous",status:"completed",motion_seconds:12}},
    {kind:"user_message",epoch:3}, {kind:"interrupted",epoch:4},
  ]},recent_performances:[{packet_id:"previous",status:"completed",motion_seconds:12}]};
  assert.deepEqual(executionResult(state), {status:"interrupted",motion_seconds:null});
  assert.equal(statusLabel(state), "已停止");
  assert.equal(statusLabel({...state,error:"bridge unavailable"}), "任务遇到问题");
  assert.equal(statusLabel({...state,session:{...state.session,epoch:5,status:"thinking"}}), "正在理解你的想法");
  assert.equal(executionResult({...state,session:{...state.session,epoch:5}}), null);
});

test("VRChat completion follows current-epoch feedback and retains pause/error priority", () => {
  const state = {connected:true,ready:true,session:{epoch:2,status:"waiting",events:[
    {kind:"interrupted",epoch:1},
    {kind:"playback_feedback",epoch:2,feedback:{packet_id:"current",status:"completed",motion_seconds:6}},
  ]},recent_performances:[{packet_id:"current",status:"completed",motion_seconds:6},{packet_id:"old",status:"completed",motion_seconds:12}]};
  assert.deepEqual(executionResult(state), {status:"completed",motion_seconds:6});
  assert.equal(statusLabel(state), "本次输出已完成");
  assert.equal(statusLabel({...state,paused:true}), "已暂停");
  assert.equal(statusLabel({...state,error:"device failed"}), "任务遇到问题");
  assert.deepEqual(executionResult({...state,recent_performances:[]}), {status:"completed",motion_seconds:6});
  assert.equal(executionResult({...state,session:{...state.session,events:[]}}), null);
});
