import type { Session } from "../contracts";
import type { CharacterStage } from "../stage";
import { downloadJSON } from "./history";

const eventLabels: Record<string, string> = {
  user_message: "用户输入", dialogue_appraised: "对话理解与行为承诺", performance_planned: "身体任务编排",
  expression_ready: "语音与文本就绪", motion_ready: "SentiAvatar 就绪", motion_error: "表达动作失败",
  behavior_planned: "预订身体时段", behavior_ready: "ARDY 就绪与支撑检查", behavior_feedback: "身体播放回执",
  playback_feedback: "语音播放回执", body_release_requested: "回应结束，请求收势", response_finished: "语音回应结束",
  body_error: "身体任务失败", interrupted: "已打断", error: "执行错误",
};
const owners: Record<string, string> = { ardy: "ARDY", sentiavatar: "SentiAvatar", hold: "保持姿态" };
const text = (tag: string, value: string, className = "") => {
  const node = document.createElement(tag); node.textContent = value; node.className = className; return node;
};
const geometry = new Set(["pose", "history", "motion_tail", "planner_history", "rotations", "windows"]);
function facts(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(facts);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !geometry.has(key)).map(([key, v]) => [key, facts(v)]));
  return value;
}

/** Public execution facts only: no persona, opaque model state or inferred reasoning. */
export class StudioDiagnostics {
  private data: unknown = null;
  private signature = "";
  private root: HTMLElement;
  constructor(root: HTMLElement) {
    this.root = root;
    const toggle = (open: boolean) => {
      this.el("#trace-drawer").hidden = !open;
      this.el("#trace-toggle").setAttribute("aria-expanded", String(open));
    };
    this.el("#trace-toggle").onclick = () => toggle(this.el("#trace-drawer").hidden);
    this.el("#trace-close").onclick = () => toggle(false);
    this.el("#trace-export").onclick = () => downloadJSON("virea-execution-trace.json", this.data);
  }
  private el(selector: string): HTMLElement { return this.root.querySelector(selector)!; }
  update(session: Session, playback: ReturnType<CharacterStage["diagnostics"]>): void {
    const { recording, speech } = playback;
    const owner = owners[playback.body_owner] ?? playback.body_owner;
    const body = session.body_program;
    const remainder = Math.max(0, playback.body_duration - playback.body_elapsed);
    const driver = playback.preview ? "正在回放完整录制" : `${owner}${playback.phase && playback.body_owner !== "hold" ? ` · ${playback.phase}` : ""}`;
    this.el("#current-driver").textContent = `${driver} · ${speech.active ? "语音播放中" : "当前无语音"}`;
    this.el("#current-driver").title = playback.reason;
    this.el("#trace-live").textContent = `${driver}\n${playback.reason || "等待可执行行为"}\n`
      + `语音：${speech.active ? `剩余 ${speech.remaining_seconds.toFixed(2)} 秒` : "已结束或尚未开始"}\n`
      + `身体：${playback.body_status}，当前时段剩余 ${remainder.toFixed(2)} 秒\n`
      + `任务范围：${body?.scope === "activity" ? "独立活动，可持续到目标完成" : "本次回应及最终收势"}\n`
      + `实播录制：${recording.duration_seconds.toFixed(2)} 秒 / ${recording.speech.length} 个语音窗口\n`
      + `头部角速度：${playback.head_speed_deg_s.toFixed(1)}°/s（本轮峰值 ${playback.peak_head_speed_deg_s.toFixed(1)}）\n`
      + `最大关节角速度：${playback.max_joint_speed_deg_s.toFixed(1)}°/s · ${playback.worst_joint}\n`
      + `脚底间距：${((playback.ground_clearance ?? 0) * 100).toFixed(2)} cm · 骨架方向差：${playback.retarget_max_angle.toFixed(1)}°`;
    this.data = { schema: "virea.execution_trace.v1", session_id: session.id, epoch: session.epoch,
      event_range: { first: session.events[0]?.sequence, last: session.events.at(-1)?.sequence,
        earlier_events_expired: (session.events[0]?.sequence ?? 1) > 1 },
      route: session.route, body_program: body, metrics: session.metrics,
      behavior_timeline: session.behavior_timeline, events: facts(session.events), playback,
      expressions: [...(session.ready ?? []), ...(session.latest_expression ? [session.latest_expression] : [])].map(
        ({ id, stream_id, sequence, offset_seconds, audio_seconds, motion, motion_status }) =>
          ({ id, stream_id, sequence, offset_seconds, audio_seconds, motion, motion_status })) };
    if (this.el("#trace-drawer").hidden) return;
    this.el("#trace-range").textContent = `保留事件 #${session.events[0]?.sequence ?? 0}–#${session.events.at(-1)?.sequence ?? 0}，共 ${session.events.length} 条。`
      + ((session.events[0]?.sequence ?? 1) > 1 ? "较早事件已超出会话缓冲区。" : "");
    const signature = JSON.stringify([session.events.at(-1)?.sequence, session.behavior_timeline, recording.speech.length, recording.drivers.length]);
    if (signature === this.signature) return;
    this.signature = signature;
    const entries: HTMLElement[] = [];
    for (const event of session.events) {
      const row = document.createElement("details"), title = document.createElement("summary");
      title.textContent = `会话 +${(event.at_seconds ?? 0).toFixed(2)}s · ${eventLabels[event.kind] ?? event.kind}`;
      row.dataset.kind = event.kind;
      row.append(title, text("pre", JSON.stringify(facts(event), null, 2))); entries.push(row);
    }
    this.el("#trace-events").replaceChildren(...entries);
    this.el("#trace-slots").replaceChildren(...(session.behavior_timeline ?? []).map(slot => {
      const row = document.createElement("details"), title = document.createElement("summary");
      title.textContent = `${owners[slot.owner] ?? slot.owner} · ${slot.seconds.toFixed(2)}s · ${slot.status}`;
      row.append(title, text("p", slot.reason), text("pre", JSON.stringify(slot, null, 2))); return row;
    }));
    this.el("#trace-playback").replaceChildren(...recording.drivers.map(d => text("p",
      `播放 +${d.at.toFixed(2)}s · ${owners[d.owner] ?? d.owner}\n${d.reason}`)),
      ...recording.speech.map(c => text("p", `语音 +${c.at.toFixed(2)}–${(c.at + c.seconds).toFixed(2)}s · ${c.id}\n${c.text}`)));
  }
}
