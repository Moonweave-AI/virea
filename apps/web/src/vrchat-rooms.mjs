/** Room progress follows server evidence, including the actual join direction. */
export function roomView(state, offline = false) {
  if (!state || state.stage === "idle") return {visible: false, active: false, text: ""};
  const active = ["checking", "inviting", "invitation_verified", "sending", "confirming_join", "waiting_for_arrival"].includes(state.stage);
  const direction = state.direction ? `${state.direction}。` : "";
  const text = offline ? `${direction}连接中断，等待恢复入房状态。`
    : state.error ? `${direction}${state.error}`
    : state.stage === "arrived" && state.same_instance ? `${direction}两个账号已确认到达同一房间。`
    : state.stage === "invitation_sent" ? `${direction}邀请已发送，尚未确认同房间。`
    : state.stage === "checking" ? `${direction}正在核对两个账号和可用的入房方向…`
    : state.stage === "inviting" ? `${direction}正在通过房主账号发送当前私人房间的邀请…`
    : state.stage === "invitation_verified" ? `${direction}当前房间邀请已确认，正在准备加入…`
    : state.stage === "confirming_join" ? `${direction}正在确认游戏中的加入提示…`
    : state.stage === "cancelled" ? `${direction}房间操作已取消，尚未确认同房间。`
    : `${direction}入房处理中，正在等待两端实际到达…`;
  return {visible: true, active, text};
}
