/** Display server-confirmed milestones; elapsed time never invents progress. */
export function calibrationView(state, offline = false) {
  if (!state || state.stage === "waiting") return {visible: false};
  const total = Math.max(1, Math.trunc(Number(state.total_steps) || 8));
  const step = Math.max(0, Math.min(total, Math.trunc(Number(state.step) || 0)));
  const complete = state.stage === "completed" && !!state.completed_at && !state.error;
  const percent = Math.max(0, Math.min(complete ? 100 : 99, Math.round(Number(state.percent) || 0)));
  const active = !!state.active && !complete;
  const label = state.step_label || "等待校准进度";
  const title = offline ? "连接中断，等待恢复进度" : state.stage === "failed" ? "自动校准未完成"
    : state.stage === "cancelled" ? "自动校准已取消" : complete ? "自动校准完成" : "自动校准进行中";
  return {visible: true, active, complete, percent, step, total, label, title,
    count: `[${step}/${total}]`,
    detail: offline ? "服务恢复后会继续显示实际进度，请勿重复启动。" : state.error || state.detail || "",
    failed: state.stage === "failed", offline};
}
