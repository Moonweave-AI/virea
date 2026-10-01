import type { Session } from "../contracts";
import type { CharacterStage } from "../stage";
import { downloadJSON } from "./history";
import { interactionPlan } from "./interaction-plan";

const eventLabels: Record<string, string> = {
  user_message: "用户输入", dialogue_appraised: "对话理解与行为承诺", performance_planned: "身体任务编排", body_replanned: "身体执行器重规划",
  expression_ready: "语音与文本就绪", motion_ready: "SentiAvatar 就绪", motion_error: "表达动作失败",
  behavior_planned: "预订身体时段", behavior_ready: "ARDY 就绪与支撑检查", behavior_feedback: "身体播放回执",
  playback_feedback: "语音播放回执", body_release_requested: "回应结束，请求收势", response_finished: "语音回应结束",
  body_error: "身体任务失败", interrupted: "已打断", error: "执行错误",
  speech_timing_planned: "话语时机规划", speech_waiting: "话语等待动作条件", speech_released: "话语条件已满足",
  timing_observed: "已执行动作事件", timing_error: "时序依赖冲突",
};
const owners: Record<string, string> = { ardy: "ARDY", sentiavatar: "SentiAvatar", hold: "保持姿态", retraction: "手势收尾" };
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
    const events = session.events.filter(e => e.epoch === session.epoch);
    const slots = (session.behavior_timeline ?? []).filter(s => s.epoch === session.epoch);
    const motions = events.filter(e => e.kind === "motion_ready");
    const ready = motions.filter(e => e.status === "ready");
    const owner = playback.retracting ? owners.retraction : owners[playback.body_owner] ?? playback.body_owner;
    const body = session.body_program;
    const remainder = playback.body_active ? Math.max(0, playback.body_duration - playback.body_elapsed) : 0;
    const driver = playback.preview ? "正在回放完整录制" : `${owner}${playback.phase && playback.body_owner !== "hold" ? ` · ${playback.phase}` : ""}`;
    const waiting = Object.values(session.timing?.waiting ?? {});
    this.el("#current-driver").textContent = `${driver} · ${speech.active ? "语音播放中" : waiting.length ? `准备发言，等待 ${[...new Set(waiting)].join("、")}` : "当前无语音"}`;
    this.el("#current-driver").title = playback.reason;
    this.el("#trace-live").textContent = `${driver}\n${playback.reason || "等待可执行行为"}\n`
      + `语音：${speech.active ? `剩余 ${speech.remaining_seconds.toFixed(2)} 秒` : "已结束或尚未开始"}\n`
      + `同步点：${Object.keys(playback.synchronization.marks).at(-1) ?? "等待语音开始"} · 语音与动作就绪独立计量\n`
      + `发言条件：${waiting.length ? [...new Set(waiting)].join("、") : "当前没有待满足条件"}\n`
      + `身体：${playback.retracting ? "手势回收进行中" : `${playback.body_status}，当前时段剩余 ${remainder.toFixed(2)} 秒`}\n`
      + `任务范围：${body && ["completed", "failed", "interrupted"].includes(body.status) ? "空间任务已结束，当前为对话表达" : body?.scope === "activity" ? "独立活动，可持续到目标完成" : "本次回应及最终收势"}\n`
      + `实播录制：${recording.duration_seconds.toFixed(2)} 秒 / ${recording.speech.length} 个语音窗口\n`
      + `动作交付：${ready.length}/${motions.length} 个窗口及时就绪，${motions.length - ready.length} 个过期\n`
      + `失败：${events.filter(e => ["motion_error", "body_error", "timing_error", "error"].includes(e.kind)).length}（展开执行事件查看原因）\n`
      + `头部角速度：${playback.head_speed_deg_s.toFixed(1)}°/s（本轮峰值 ${playback.peak_head_speed_deg_s.toFixed(1)}）\n`
      + `峰值采样：旋转 ${playback.peak_head_delta_deg.toFixed(2)}° / ${(playback.peak_head_frame_seconds * 1000).toFixed(2)} ms\n`
      + `峰值来源：播放 +${playback.peak_head_at_seconds.toFixed(2)} 秒 / ${owners[playback.peak_head_owner] ?? playback.peak_head_owner} / ${playback.peak_head_joint}\n`
      + `最大关节角速度：${playback.max_joint_speed_deg_s.toFixed(1)}°/s · ${playback.worst_joint}\n`
      + `脚底间距：${((playback.ground_clearance ?? 0) * 100).toFixed(2)} cm · 骨架方向差：${playback.retarget_max_angle.toFixed(1)}°`;
    this.data = { schema: "virea.execution_trace.v1", session_id: session.id, epoch: session.epoch,
      event_range: { first: session.events[0]?.sequence, last: session.events.at(-1)?.sequence,
        earlier_events_expired: (session.events[0]?.sequence ?? 1) > 1 },
      route: session.route, body_program: body, timing: session.timing, metrics: session.metrics,
      behavior_timeline: session.behavior_timeline, events: facts(session.events), playback,
      expressions: [...(session.ready ?? []), ...(session.latest_expression ? [session.latest_expression] : [])].map(
        ({ id, stream_id, sequence, offset_seconds, audio_seconds, motion, motion_status }) =>
          ({ id, stream_id, sequence, offset_seconds, audio_seconds, motion, motion_status })) };
    if (this.el("#trace-drawer").hidden) return;
    this.el("#trace-range").textContent = `当前第 ${session.epoch} 轮，${events.length} 条事件 / ${slots.length} 个身体时段。导出保留完整会话事件 #${session.events[0]?.sequence ?? 0}–#${session.events.at(-1)?.sequence ?? 0}。字幕按 PCM 窗口分段，非逐字强制对齐。`
      + ((session.events[0]?.sequence ?? 1) > 1 ? "较早事件已超出会话缓冲区。" : "");
    const signature = JSON.stringify([session.events.at(-1)?.sequence, session.behavior_timeline, recording.speech.length, recording.drivers.length, playback.synchronization.marks]);
    if (signature === this.signature) return;
    this.signature = signature;
    this.el("#trace-plan").replaceChildren(interactionPlan(
      events.filter(event => event.kind === "dialogue_appraised").at(-1)?.appraisal));
    const entries: HTMLElement[] = [];
    for (const event of events) {
      const row = document.createElement("details"), title = document.createElement("summary");
      title.textContent = `会话 +${(event.at_seconds ?? 0).toFixed(2)}s · ${eventLabels[event.kind] ?? event.kind}`;
      row.dataset.kind = event.kind;
      row.append(title, text("pre", JSON.stringify(facts(event), null, 2))); entries.push(row);
    }
    this.el("#trace-events").replaceChildren(...entries);
    this.el("#trace-slots").replaceChildren(...slots.map(slot => {
      const row = document.createElement("details"), title = document.createElement("summary");
      title.textContent = `${owners[slot.owner] ?? slot.owner} · ${slot.seconds.toFixed(2)}s · ${slot.status}`;
      row.append(title, text("p", slot.reason), text("pre", JSON.stringify(slot, null, 2))); return row;
    }));
    this.el("#trace-playback").replaceChildren(...Object.entries(playback.synchronization.marks).map(([name, at]) => text("p",
      `语音同步点 · ${name} · 音频时钟 ${at.toFixed(3)}s`)), ...recording.drivers.map(d => text("p",
      `播放 +${d.at.toFixed(2)}s · ${owners[d.owner] ?? d.owner}\n${d.reason}`)),
      ...recording.speech.map(c => text("p", `语音 +${c.at.toFixed(2)}–${(c.at + c.seconds).toFixed(2)}s · ${c.id}\n${c.text}`)));
  }
}
