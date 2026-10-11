import test from "node:test";
import assert from "node:assert/strict";
import {clientLaunchView} from "../src/vrchat-clients.mjs";

const state = client => ({configured:true, clients:{ai:client}});
test("launch controls distinguish process, login, scene and API failure", () => {
  assert.equal(clientLaunchView(null, "ai").startDisabled, true);
  assert.equal(clientLaunchView(state({stage:"stopped", running:false}), "ai").startDisabled, false);
  const login = clientLaunchView(state({stage:"waiting_login", running:true, step:3, total_steps:5}), "ai");
  assert.equal(login.ready, false);
  assert.equal(login.showProgress, true);
  assert.equal(login.progress, 60);
  assert.equal(login.startDisabled, true);
  assert.equal(login.restartDisabled, false);
  assert.equal(clientLaunchView(state({stage:"auth_error", running:true}), "ai").ready, false);
  assert.equal(clientLaunchView(state({stage:"ready", running:true}), "ai").ready, true);
});
test("launching, errors and offline snapshots cannot enable unsafe repeat actions", () => {
  const current=state({stage:"launching", active:true, running:true, step:2, total_steps:5});
  assert.equal(clientLaunchView(current, "ai").restartDisabled, true);
  assert.equal(clientLaunchView(current, "ai").progress, 40);
  assert.equal(clientLaunchView(state({stage:"conflict"}), "ai").startDisabled, true);
  assert.equal(clientLaunchView(state({stage:"ready", running:true}), "ai", true).ready, false);
  assert.equal(clientLaunchView(state({stage:"ready", running:true}), "ai", true).restartDisabled, true);
  assert.match(clientLaunchView({configured:false,error:"配置无效"}, "ai").detail,/配置无效/);
});
