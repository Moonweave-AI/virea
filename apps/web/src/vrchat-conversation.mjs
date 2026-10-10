/** Merge the server's bounded history without duplicating turns on every poll. */
export function mergeTranscript(previous, current) {
  const incoming = current.filter(turn => ["user", "assistant"].includes(turn.role) && typeof turn.content === "string" && turn.content.trim());
  const equal = (a, b) => a.role === b.role && a.content === b.content;
  for (let overlap = Math.min(previous.length, incoming.length); overlap > 0; overlap--) {
    if (incoming.slice(0, overlap).every((turn, index) => equal(previous[previous.length - overlap + index], turn))) {
      return [...previous, ...incoming.slice(overlap)].slice(-200);
    }
  }
  return [...previous, ...incoming].slice(-200);
}

export function readConversations(raw) {
  try {
    const parsed = JSON.parse(raw ?? "null");
    if (parsed?.version !== 1 || !Array.isArray(parsed.items)) return [];
    return parsed.items.slice(0, 50).filter(item => typeof item.id === "string" && Array.isArray(item.messages)).map(item => ({
      id: item.id.slice(0, 80),
      title: typeof item.title === "string" ? item.title.slice(0, 60) : "新的对话",
      sessionId: typeof item.sessionId === "string" ? item.sessionId.slice(0, 80) : null,
      updatedAt: Number.isFinite(item.updatedAt) ? item.updatedAt : 0,
      messages: item.messages.filter(turn => ["user", "assistant"].includes(turn?.role) && typeof turn.content === "string" && turn.content.trim()).slice(-200).map(turn => ({role: turn.role, content: turn.content.slice(0, 4000)})),
    }));
  } catch { return []; }
}

export function bridgeError(state) {
  if (state.error) return state.error;
  if (state.session?.status === "error") {
    return [...(state.session.events ?? [])].reverse().find(event => event.kind === "error")?.message ?? "任务没有完成，请重试。";
  }
  return "";
}

/** Only feedback from the current task may describe its completion. */
export function executionResult(state) {
  const session = state.session;
  if (!Number.isInteger(session?.epoch)) return null;
  const event = [...(session.events ?? [])].reverse().find(item => item.epoch === session.epoch && ["interrupted", "playback_feedback"].includes(item.kind));
  if (event?.kind === "interrupted") return {status: "interrupted", motion_seconds: null};
  if (!event?.feedback) return null;
  const result = state.recent_performances?.find(item => item.packet_id === event.feedback.packet_id) ?? event.feedback;
  return {status: result.status, motion_seconds: result.motion_seconds ?? null};
}

export function statusLabel(state) {
  if (!state.connected) return "尚未连接";
  if (bridgeError(state)) return "任务遇到问题";
  if (state.paused) return "已暂停";
  if (!state.ready) return "等待 VRChat 连接";
  const result = executionResult(state);
  if (state.session?.status === "waiting" && !state.autonomy?.active && result) {
    return result.status === "completed" ? "本次输出已完成" : result.status === "interrupted" ? "已停止" : "本次输出未完成";
  }
  return ({thinking: "正在理解你的想法", generating: "正在准备声音与动作", awaiting_playback: "正在 VRChat 中执行", waiting: state.autonomy?.active ? "正在准备下一步" : "随时可以开始"})[state.session?.status] ?? "已连接 VRChat";
}

/** Describe transmitted controls separately from a model's generated motion. */
export function executionNote(state) {
  const event = [...(state.session?.events ?? [])].reverse().find(item => item.epoch === state.session?.epoch && item.kind === "playback_feedback");
  const result = state.recent_performances?.find(item => item.packet_id === event?.feedback?.packet_id);
  const output = state.execution ?? result?.execution;
  if (!output) return "";
  if (output.mode === "generated_vr") return `模型姿态驱动：头部、手腕、手指与身体追踪。驱动确认 ${output.pose_driver?.acknowledged ?? 0} 帧；VRChat 经 IK 呈现，效果需从观察者画面核对。`;
  if (output.mode !== "desktop") return "输出已配置的身体追踪点；头手需要外部设备，画面效果需在观察者视角核对。";
  const sent = output.emotes_sent?.length ?? 0, observed = output.emotes_observed?.length ?? 0;
  const missing = (output.segments ?? []).filter(segment => segment.body_output === "not_transmitted").map(segment => segment.prompt);
  return `${sent ? `桌面预设动画：${sent} 种已发送，${observed} 种收到游戏参数回传。` : "桌面端仅输出手指姿势与可用表情。"}模型生成的全身骨骼未传递。${missing.length ? `未映射的身体动作：${missing.join("；")}` : ""}`;
}

export function acceptSnapshot(current, incoming, busy) {
  if (busy) return false;
  return !current.session || incoming.session?.id !== current.session.id || !(incoming.session.epoch < current.session.epoch);
}
