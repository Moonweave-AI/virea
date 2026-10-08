import {test} from "node:test";
import assert from "node:assert/strict";
import {connectionView, readConnectionSettings} from "../src/vrchat-connection.mjs";

test("same-room log evidence does not claim avatar or audio acceptance", () => {
  const state = {connected: true, ready: false, feedback: {query: {
    state: "verified", last_checked_seconds_ago: 0,
    online: {same_instance: "matched_in_live_client_logs"},
  }}};
  const view = connectionView(state);
  assert.ok(view.steps.some(([name, ok]) => name === "同房间记录已匹配" && ok));
  assert.equal(view.ready, false);
  assert.match(view.detail, /仍需从观察者视角验收/);
  assert.equal(connectionView(state, true).steps[3][1], false);
  state.feedback.query.last_checked_seconds_ago = 5;
  assert.equal(connectionView(state).steps[3][1], false);
});

test("offline testing is visible even when local OSC is ready", () => {
  const view = connectionView({connected: true, ready: true, feedback: {query: {
    state: "verified", last_checked_seconds_ago: 0,
    online: {connection: "offline_testing", authentication: "authenticated_in_log"},
  }}});
  assert.match(view.title, /离线测试模式/);
  assert.match(view.detail, /launch.exe/);
  assert.ok(view.steps.some(([name, ok]) => name === "离线测试模式" && !ok));
  assert.equal(view.steps[1][1], true);
});

test("an HTTP session without a verified avatar never looks ready", () => {
  const view = connectionView({connected: true, ready: false});
  assert.equal(view.ready, false);
  assert.equal(view.title, "正在寻找 AI 客户端");
  assert.equal(view.steps[1][1], false);
});
test("live SDK avatar is shown with its local visibility boundary", () => {
  const view = connectionView({connected: true, ready: true, feedback: {
    values: {avatar_id: "local:sdk_VIREA Independent AI"},
    query: {state: "verified", last_checked_seconds_ago: 0.2, local_avatar: true},
  }});
  assert.equal(view.avatar, "VIREA Independent AI");
  assert.equal(view.steps[1][1], true);
  assert.match(view.detail, /仅当前客户端可见/);
});
test("API loss overrides cached ready state", () => {
  const view = connectionView({connected: true, ready: true}, true);
  assert.equal(view.ready, false);
  assert.ok(view.steps.every(([, ok]) => !ok));
  assert.match(view.title, /不可用/);
});
test("avatar mismatch and missing rig have actionable distinct messages", () => {
  assert.match(connectionView({connected: true, config: {avatar_id: "avtr_old"}, feedback: {values: {avatar_id: "avtr_new"}}}).title, /角色已切换/);
  assert.match(connectionView({connected: true, feedback: {query: {state: "verified", last_checked_seconds_ago: 0, missing_parameters: ["AI_Active"]}}}).title, /缺少控制参数/);
});
test("settings tolerate corrupt storage and preserve deliberate disconnect", () => {
  assert.equal(readConnectionSettings("bad"), null);
  assert.equal(readConnectionSettings('{"version":2,"fields":{}}'), null);
  assert.equal(readConnectionSettings('{"version":1,"fields":{"auto-bind":true},"wanted":false}').wanted, false);
});

test("logged API errors do not declare a live account offline or require re-login", () => {
  const view = connectionView({connected: true, ready: true, feedback: {query: {
    state: "verified", last_checked_seconds_ago: 0, local_avatar: true,
    online: {authentication: "api_auth_error_in_log"},
  }}});
  assert.match(view.title, /本机/);
  assert.match(view.detail, /401/);
  assert.equal(view.ready, true);
  assert.match(view.detail, /仅当前客户端可见/);
  assert.match(view.detail, /不能据此认定账号掉线/);
  assert.doesNotMatch(view.detail, /重新登录|登录已失效/);
  assert.ok(view.steps.some(([name, ok]) => name === "接口有错误记录" && !ok));
});
