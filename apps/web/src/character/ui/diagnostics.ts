import type { Session } from "../contracts";
import type { CharacterStage } from "../stage";
import { downloadJSON } from "./history";
import { interactionPlan } from "./interaction-plan";
import {getLanguage, subscribe, t} from "../../studio/preferences";
import {translateLabel} from "../../studio/legacy";

const eventLabels: Record<string, string> = {
  user_message: "用户输入", dialogue_appraised: "对话理解与行为承诺", performance_planned: "身体任务编排", body_replanned: "身体执行器重规划",
  expression_ready: "语音与文本就绪", motion_ready: "SentiAvatar 就绪", motion_error: "表达动作失败",
  behavior_planned: "预订身体时段", behavior_ready: "ARDY 就绪与支撑检查", behavior_feedback: "身体播放回执",
  playback_feedback: "语音播放回执", body_release_requested: "回应结束，请求收势", response_finished: "语音回应结束",
  body_error: "身体任务失败", interrupted: "已打断", error: "执行错误",
  speech_timing_planned: "话语时机规划", speech_waiting: "话语等待动作条件", speech_released: "话语条件已满足",
  timing_observed: "已执行动作事件", timing_error: "时序依赖冲突",
  activity_reviewed: "执行层活动完成判断",
  motion_window_generated: "原生动作窗口生成完成", speech_clip_ready: "独立语音片段就绪",
};
const owners: Record<string, string> = { ardy: "ARDY", sentiavatar: "SentiAvatar", motioncraft: "MotionCraft", syntalker: "SynTalker", hold: "保持姿态", retraction: "手势收尾" };
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
  private current: [Session, ReturnType<CharacterStage["diagnostics"]>] | null = null;
  private signature = "";
  private root: HTMLElement;
  constructor(root: HTMLElement) {
    this.root = root;
    const unsubscribe = subscribe(() => {if (this.current) this.update(...this.current);});
    window.addEventListener("pagehide", unsubscribe, {once:true});
    const toggle = (open: boolean) => {
      const wasOpen = !this.el("#trace-drawer").hidden;
      this.el("#trace-drawer").hidden = !open;
      this.el("#trace-toggle").setAttribute("aria-expanded", String(open));
      if (open) {
        this.el("#history-drawer").hidden = true;
        this.el("#history-toggle").setAttribute("aria-expanded", "false");
        this.el("#trace-export").focus();
      } else if (wasOpen) this.el("#trace-toggle").focus();
    };
    this.el("#trace-toggle").onclick = () => toggle(this.el("#trace-drawer").hidden);
    this.el("#trace-close").onclick = () => toggle(false);
    root.addEventListener("keydown", event => {if (event.key === "Escape") toggle(false);});
    this.el("#trace-export").onclick = () => downloadJSON("virea-execution-trace.json", this.data);
  }
  private el(selector: string): HTMLElement { return this.root.querySelector(selector)!; }
  update(session: Session, playback: ReturnType<CharacterStage["diagnostics"]>): void {
    this.current = [session, playback];
    const { recording, speech } = playback;
    const events = session.events.filter(e => e.epoch === session.epoch);
    const slots = (session.behavior_timeline ?? []).filter(s => s.epoch === session.epoch);
    const motions = events.filter(e => e.kind === "motion_ready");
    const ready = motions.filter(e => e.status === "ready");
    const unified = session.motion_backend === "motioncraft" || session.motion_backend === "syntalker";
    const nativeWindows = events.filter(e => e.kind === "motion_window_generated");
    const owner = translateLabel(playback.retracting ? owners.retraction! : owners[playback.body_owner] ?? playback.body_owner);
    const body = session.body_program;
    const remainder = playback.body_active ? Math.max(0, playback.body_duration - playback.body_elapsed) : 0;
    const driver = playback.preview ? t("正在回放完整录制", "Replaying the recording") : `${owner}${playback.phase && playback.body_owner !== "hold" ? ` · ${playback.phase}` : ""}`;
    const waiting = Object.values(session.timing?.waiting ?? {});
    const conditions = [...new Set(waiting)].map(translateLabel).join(t("、", ", "));
    this.el("#current-driver").textContent = `${driver} · ${speech.active ? t("语音播放中", "Speech playing") : waiting.length ? t(`准备发言，等待 ${conditions}`, `Speech waiting for ${conditions}`) : t("当前无语音", "No active speech")}`;
    this.el("#current-driver").title = playback.reason;
    const scope = body && ["completed", "failed", "interrupted"].includes(body.status)
      ? t("空间任务已结束，当前为对话表达", "Spatial task finished; conversational expression active")
      : body?.scope === "activity" ? t("独立活动，可持续到目标完成", "Independent activity until its goal is met")
      : t("本次回应及最终收势", "Current response and final settling pose");
    const failures = events.filter(e => ["motion_error", "body_error", "timing_error", "error"].includes(e.kind)).length;
    const mark = Object.keys(playback.synchronization.marks).at(-1) ?? t("等待语音开始", "Waiting for speech");
    this.el("#trace-live").textContent = [
      driver, playback.reason || t("等待可执行行为", "Waiting for an action"),
      t("语音：", "Speech: ") + (speech.active ? t(`剩余 ${speech.remaining_seconds.toFixed(2)} 秒`, `${speech.remaining_seconds.toFixed(2)}s remaining`) : t("已结束或尚未开始", "Finished or not started")),
      t(`同步点：${mark} · 语音与动作就绪独立计量`, `Sync marker: ${mark} · speech and motion readiness are measured independently`),
      t("发言条件：", "Speech conditions: ") + (conditions || t("当前没有待满足条件", "No pending conditions")),
      t("身体：", "Body: ") + (playback.retracting ? t("手势回收进行中", "Retracting the gesture") : t(`${playback.body_status}，当前时段剩余 ${remainder.toFixed(2)} 秒`, `${playback.body_status}; ${remainder.toFixed(2)}s left in this slot`)),
      t("任务范围：", "Scope: ") + scope,
      t(`实播录制：${recording.duration_seconds.toFixed(2)} 秒 / ${recording.speech.length} 个语音窗口`, `Recorded playback: ${recording.duration_seconds.toFixed(2)}s / ${recording.speech.length} speech windows`),
      unified ? t(`动作交付：${nativeWindows.length} 个原生窗口，完整表演准备后播放`, `Motion delivery: ${nativeWindows.length} native windows; playback begins when the performance is ready`)
        : t(`动作交付：${ready.length}/${motions.length} 个窗口及时就绪，${motions.length-ready.length} 个过期`, `Motion delivery: ${ready.length}/${motions.length} windows ready on time; ${motions.length-ready.length} expired`),
      t(`失败：${failures}（展开执行事件查看原因）`, `Failures: ${failures} (expand execution events for details)`),
      t(`头部角速度：${playback.head_speed_deg_s.toFixed(1)}°/s（本轮峰值 ${playback.peak_head_speed_deg_s.toFixed(1)}）`, `Head angular speed: ${playback.head_speed_deg_s.toFixed(1)}°/s (peak ${playback.peak_head_speed_deg_s.toFixed(1)})`),
      t(`峰值采样：旋转 ${playback.peak_head_delta_deg.toFixed(2)}° / ${(playback.peak_head_frame_seconds*1000).toFixed(2)} ms`, `Peak sample: ${playback.peak_head_delta_deg.toFixed(2)}° / ${(playback.peak_head_frame_seconds*1000).toFixed(2)} ms`),
      t("峰值来源：播放 +", "Peak source: playback +") + `${playback.peak_head_at_seconds.toFixed(2)}s / ${translateLabel(owners[playback.peak_head_owner] ?? playback.peak_head_owner)} / ${playback.peak_head_joint}`,
      t("最大关节角速度：", "Maximum joint angular speed: ") + `${playback.max_joint_speed_deg_s.toFixed(1)}°/s · ${playback.worst_joint}`,
      t("脚底间距：", "Ground clearance: ") + `${((playback.ground_clearance??0)*100).toFixed(2)} cm · ` + t("骨架方向差：", "Skeleton direction difference: ") + `${playback.retarget_max_angle.toFixed(1)}°`,
    ].join("\n");
    this.data = { schema: "virea.execution_trace.v1", session_id: session.id, epoch: session.epoch,
      event_range: { first: session.events[0]?.sequence, last: session.events.at(-1)?.sequence,
        earlier_events_expired: (session.events[0]?.sequence ?? 1) > 1 },
      route: session.route, performance: session.performance, body_program: body, timing: session.timing, metrics: session.metrics,
      behavior_timeline: session.behavior_timeline, events: facts(session.events), playback,
      expressions: [...(session.ready ?? []), ...(session.latest_expression ? [session.latest_expression] : [])].map(
        ({ id, stream_id, sequence, offset_seconds, audio_seconds, motion, motion_status }) =>
          ({ id, stream_id, sequence, offset_seconds, audio_seconds, motion, motion_status })) };
    if (this.el("#trace-drawer").hidden) return;
    this.el("#trace-range").textContent = t(
      `当前第 ${session.epoch} 轮，${events.length} 条事件 / ${slots.length} 个身体时段。导出保留完整会话事件 #${session.events[0]?.sequence ?? 0}–#${session.events.at(-1)?.sequence ?? 0}。字幕按语音窗口分段。`,
      `Turn ${session.epoch}: ${events.length} events / ${slots.length} body slots. Export includes events #${session.events[0]?.sequence ?? 0}–#${session.events.at(-1)?.sequence ?? 0}. Captions follow speech windows.`)
      + ((session.events[0]?.sequence ?? 1) > 1 ? t("较早事件已超出会话缓冲区。", " Earlier events have left the session buffer.") : "");
    const signature = JSON.stringify([getLanguage(),session.events.at(-1)?.sequence, session.behavior_timeline, recording.speech.length, recording.drivers.length, playback.synchronization.marks]);
    if (signature === this.signature) return;
    this.signature = signature;
    this.el("#trace-plan").replaceChildren(unified
      ? text("pre", JSON.stringify(session.performance ?? events.find(e => e.kind === "performance_planned")?.plan ?? {}, null, 2))
      : interactionPlan(events.filter(event => event.kind === "dialogue_appraised").at(-1)?.appraisal));
    const entries: HTMLElement[] = [];
    for (const event of events) {
      const row = document.createElement("details"), title = document.createElement("summary");
      title.textContent = `${t("会话", "Session")} +${(event.at_seconds ?? 0).toFixed(2)}s · ${translateLabel(eventLabels[event.kind] ?? event.kind)}`;
      row.dataset.kind = event.kind;
      row.append(title, text("pre", JSON.stringify(facts(event), null, 2))); entries.push(row);
    }
    this.el("#trace-events").replaceChildren(...entries);
    this.el("#trace-slots").replaceChildren(...slots.map(slot => {
      const row = document.createElement("details"), title = document.createElement("summary");
      title.textContent = `${translateLabel(owners[slot.owner] ?? slot.owner)} · ${slot.seconds.toFixed(2)}s · ${slot.status}`;
      row.append(title, text("p", slot.reason), text("pre", JSON.stringify(slot, null, 2))); return row;
    }));
    this.el("#trace-playback").replaceChildren(...Object.entries(playback.synchronization.marks).map(([name, at]) => text("p",
      `${t("语音同步点", "Speech sync marker")} · ${name} · ${t("音频时钟", "Audio clock")} ${at.toFixed(3)}s`)), ...recording.drivers.map(d => text("p",
      `${t("播放", "Playback")} +${d.at.toFixed(2)}s · ${translateLabel(owners[d.owner] ?? d.owner)}\n${d.reason}`)),
      ...recording.speech.map(c => text("p", `${t("语音", "Speech")} +${c.at.toFixed(2)}–${(c.at + c.seconds).toFixed(2)}s · ${c.id}\n${c.text}`)));
  }
}
