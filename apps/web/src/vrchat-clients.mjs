/** The game restores saved sessions; a started process is not a logged-in user. */
export function clientLaunchView(state, role, offline = false, busy = false) {
  const client = state?.clients?.[role];
  const active = !!client?.active;
  const total = client?.total_steps || 5;
  const step = Math.max(0, Math.min(total, client?.step || 0));
  const blocked = offline || state?.configured !== true || busy || active;
  return {
    label: role === "observer" ? "观察者" : "AI",
    detail: offline ? "控制服务暂时不可用，恢复后自动更新。" : state?.error || client?.detail || "正在读取客户端状态…",
    account: client?.label || "独立账号",
    progress: Math.round(step / total * 100), step, total,
    active,
    showProgress: !offline && (active || ["waiting_login", "loading_world"].includes(client?.stage)),
    ready: !offline && client?.stage === "ready" && !active,
    startDisabled: blocked || client?.running === true || client?.stage === "conflict",
    restartDisabled: blocked || client?.running !== true || client?.stage === "conflict",
    startText: active ? "处理中…" : client?.running ? "已启动" : `启动${role === "observer" ? "观察者" : " AI"}`,
  };
}
