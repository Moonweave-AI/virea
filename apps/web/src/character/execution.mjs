/** Validate a prepared performance before the browser acquires the body channel. */
export function validateExecution(packet, executable) {
  if (!packet.execution) return; // Existing saved recordings retain their legacy envelope.
  const command = packet.execution;
  if (command.schema_version !== "virea.execution_command.v1"
    || executable?.schema_version !== "virea.executable_performance.v1"
    || command.target_kind !== "browser"
    || command.target_id !== `browser:${command.session_id}`
    || command.command_id !== packet.id || command.epoch !== packet.epoch
    || command.plan_id !== executable.plan_id || executable.performance_id !== packet.id
    || !command.authorized_capabilities?.includes("body")
    || command.expires_at * 1000 <= Date.now()) {
    throw new Error("表演与当前角色会话不匹配，请重新生成。");
  }
  const a = executable.speech, b = packet.performance.speech;
  if (Math.abs(executable.duration_seconds - packet.performance.duration_seconds) > 1e-6
    || !Array.isArray(a) || !Array.isArray(b) || a.length !== b.length
    || a.some((clip, i) => ["id", "text", "start_seconds", "duration_seconds"].some(key => clip[key] !== b[i][key]))) {
    throw new Error("表演轨道与已校验的结果不一致。");
  }
}

export function executionLabel(snapshot) {
  if (!snapshot) return "";
  const states = {accepted: "已接收", planning: "规划中", preparing: "准备中", ready: "已准备", playing: "执行中", paused: "已暂停", holding: "保持当前姿态", completed: "执行完成", cancelled: "已取消", failed: "执行失败"};
  const evidence = {planned: "计划已建立", generated: "已生成", validated: "已校验", sent: "已发送", device_ack: "播放端已确认", observed_rendered: "画面已观测", semantically_satisfied: "任务效果已验证"};
  return `${states[snapshot.state] ?? snapshot.state} · 第 ${snapshot.epoch} 轮${snapshot.receipt ? ` · ${evidence[snapshot.receipt.evidence] ?? snapshot.receipt.evidence}` : ""}`;
}
