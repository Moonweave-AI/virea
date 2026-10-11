import {test} from "node:test";
import assert from "node:assert/strict";
import {validateExecution, executionLabel} from "../src/character/execution.mjs";

function payload() {
  const executable = {schema_version: "virea.executable_performance.v1", performance_id: "p", plan_id: "plan", duration_seconds: 4, speech: []};
  const packet = {id: "p", epoch: 2, performance: {duration_seconds: 4, speech: []}, execution: {
    schema_version: "virea.execution_command.v1", command_id: "p", epoch: 2, target_kind: "browser",
    session_id: "s", target_id: "browser:s", plan_id: "plan", authorized_capabilities: ["body"], expires_at: Date.now() / 1000 + 60,
  }};
  return {packet, executable};
}

test("browser accepts its own current performance", () => {
  const {packet, executable} = payload();
  assert.doesNotThrow(() => validateExecution(packet, executable));
});
for (const change of [{target_kind: "vrchat"}, {epoch: 1}, {expires_at: 1}, {target_id: "browser:other"}, {authorized_capabilities: []}]) {
  test(`browser rejects ${JSON.stringify(change)}`, () => {
    const {packet, executable} = payload();
    Object.assign(packet.execution, change);
    assert.throws(() => validateExecution(packet, executable));
  });
}
test("receipt label reports target acknowledgement without claiming observation", () => {
  assert.equal(executionLabel({epoch: 2, state: "completed", receipt: {evidence: "device_ack"}}), "执行完成 · 第 2 轮 · 播放端已确认");
});
