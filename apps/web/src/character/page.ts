import "./style.css";
import { studioShell } from "./ui/shell";
import { StudioHistory, downloadJSON } from "./ui/history";
import { StudioPreferences } from "./ui/preferences";
import { StudioDiagnostics } from "./ui/diagnostics";
import { MotionBackendPicker, renderPerformanceTracks } from "./ui/performance";
import { CharacterStage } from "./stage";
import { downloadVideo } from "./video";
import type { Expression, Session, PlaybackProgress } from "./contracts";

const root = document.querySelector<HTMLDivElement>("#character")!;
root.innerHTML = studioShell;

function element<T extends HTMLElement>(selector: string): T { return root.querySelector<T>(selector)!; }
const stage = new CharacterStage(element("canvas"));
const history = new StudioHistory(root);
const preferences = new StudioPreferences(root, showError);
const motionBackend = new MotionBackendPicker(root, showError);
const diagnostics = new StudioDiagnostics(root);
let session: Session | null = null;
let playing: string | null = null;
let handled = new Set<string>();
let closing = false;
let disposed = false;
let mutating = false;
let playbackGeneration = 0;
let previewing = false;

function setMutating(value: boolean): void {
  mutating = value;
  for (const id of ["#send", "#interrupt", "#close"]) {
    element<HTMLButtonElement>(id).disabled = value || !session;
  }
}

class RequestError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

function showProgress(value: PlaybackProgress): void {
  const dataset = element<HTMLCanvasElement>("canvas").dataset;
  const bodyPlaying = !previewing && ["playing", "settling"].includes(dataset.bodyStatus ?? "");
  const bodyElapsed = bodyPlaying ? Number(dataset.bodyElapsed ?? 0) : value.elapsed;
  const bodyDuration = bodyPlaying ? Number(dataset.bodyDuration ?? 0) : value.motionDuration;
  const duration = Math.max(value.audioDuration, bodyDuration);
  const timeline = element<HTMLProgressElement>("#timeline-progress");
  timeline.max = Math.max(duration, 0.001); timeline.value = Math.min(bodyPlaying ? bodyElapsed : value.elapsed, duration);
  element("#timeline-state").textContent = `${value.paused ? "已暂停 · " : ""}${timeline.value.toFixed(2)} / ${duration.toFixed(2)} 秒`;
  if (!previewing) {
    const recorded = stage.diagnostics().recording;
    element("#timeline-state").textContent = `${value.paused ? "已暂停 · " : ""}本轮已播放 ${recorded.duration_seconds.toFixed(1)} 秒`;
  }
  if (value.caption !== undefined) element("#subtitle").textContent = value.caption;
  else if (value.elapsed >= value.audioDuration) element("#subtitle").textContent = "";
  for (const [name, duration] of [["audio", value.audioDuration], ["motion", bodyDuration]] as const) {
    const elapsed = Math.min(name === "motion" ? bodyElapsed : value.elapsed, duration);
    const bar = element<HTMLProgressElement>(`#${name}-progress`);
    bar.max = Math.max(duration, 0.001); bar.value = elapsed;
    bar.dataset.seconds = elapsed.toFixed(3);
    element(`#${name}-state`).textContent = duration
      ? `${value.paused ? "已暂停 · " : ""}${elapsed.toFixed(1)} / ${duration.toFixed(1)} 秒`
      : name === "audio" ? "无语音" : "本次未播放动作";
  }
  element("#pause").textContent = value.paused ? "继续" : "暂停";
  const phase = element<HTMLCanvasElement>("canvas").dataset.motionPhase;
  element("#active-phase").textContent = session?.body_program && phase ? phase : "播放时间轴";
  const index = Number(element<HTMLCanvasElement>("canvas").dataset.motionPhaseIndex ?? -1);
  element("#motion-plan").querySelectorAll("li").forEach((node, i) => node.dataset.active = String(playing !== null && i === index));
}

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1/characters${path}`, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new RequestError(response.status, typeof payload.detail === "string" ? payload.detail : `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function showError(error: unknown): void {
  element("#error").textContent = error instanceof Error ? error.message : String(error);
  element("#settings-error").textContent = element("#error").textContent;
}

function renderState(value: Session): void {
  renderPerformanceTracks(root, value.performance);
  stage.track(value);
  diagnostics.update(value, stage.diagnostics());
  root.dataset.sessionId = value.id;
  const labels: Record<string, string> = { routing: "理解对话", waiting: "就绪", thinking: "规划中", synthesizing: "合成语音", generating: "生成动作", awaiting_playback: "播放中", error: "需要处理", closed: "已结束" };
  element("#status").textContent = previewing ? "动作预览" : labels[value.status] ?? value.status;
  const seconds = (value: number | null) => value?.toFixed(2) ?? "—";
  element("#metrics").textContent = `语言流水线 ${seconds(value.metrics.language_seconds)}s · TTS ${seconds(value.metrics.tts_seconds)}s · 动作 ${seconds(value.metrics.motion_seconds)}s\n语音就绪 ${seconds(value.metrics.first_audio_seconds)}s · 首包就绪 ${seconds(value.metrics.first_expression_seconds)}s · ${value.playback_mode === "synchronized" ? "动作" : "生成"} RTF ${seconds(value.metrics.rtf)}`;
  element("#response-text").textContent = value.draft_text || (value.route?.engine === "ardy" ? "" : ["thinking", "routing"].includes(value.status) ? "正在准备…" : "和角色聊聊。");
  element("#reply-owner").textContent = "VIREA";
  element("#route-card").hidden = !value.route;
  element("#route-model").textContent = value.route?.engine === "motioncraft" ? "MotionCraft" : value.route?.engine === "syntalker" ? "SynTalker"
    : value.route?.engine === "temporal" ? "对话 · 行为调度" : value.route?.engine === "ardy" ? "ARDY" : "SentiAvatar";
  element("#route-reason").textContent = value.route?.reason ?? "";
  const body = value.body_program;
  const archivedPlan = body && (body.origin_epoch ?? value.epoch) < value.epoch
    && ["completed", "failed", "interrupted"].includes(body.status);
  const activePlan = archivedPlan ? [] : body?.actions ?? value.motion_plan ?? [];
  const plan = element("#motion-plan"), signature = JSON.stringify(activePlan);
  if (plan.dataset.plan !== signature) {
    plan.dataset.plan = signature;
    plan.replaceChildren(...activePlan.map((action, i) => {
      const li = document.createElement("li"), index = document.createElement("span"), label = document.createElement("span"), time = document.createElement("small");
      index.className = "phase-number"; index.textContent = String(i + 1);
      label.textContent = action.label ?? action.kind; time.textContent = `${action.duration_seconds ?? "自动"}s`;
      li.title = action.description ?? ""; li.append(index, label, time); return li;
    }));
  }
  element("#text-state").textContent = value.route?.engine === "ardy"
    ? value.motion_plan?.length ? "动作序列" : "正在编排" : value.draft_text ? "实时回复" : "尚未生成";
  const idle = !playing && !stage.bodyRunning && !previewing && ["waiting", "error"].includes(value.status);
  element<HTMLButtonElement>("#pause").disabled = !playing && !stage.bodyRunning && !previewing;
  const latest = value.latest_expression;
  element<HTMLButtonElement>("#replay-audio").disabled = !idle || !stage.recordedAudio;
  element<HTMLButtonElement>("#replay-motion").disabled = !idle || !stage.replayAvailable;
  element<HTMLButtonElement>("#export-motion").disabled = !idle || !stage.motionRecording().length;
  element<HTMLButtonElement>("#export-video").disabled = !idle || !stage.replayAvailable;
  element<HTMLButtonElement>("#replay-sync").disabled = !idle || !stage.replayAvailable || !stage.recordedAudio;
  if (!playing && !previewing) {
    element("#motion-state").textContent = value.status === "generating" ? "动作生成中…" : latest?.motion || stage.motionRecording().length ? "动作已就绪 · 可重播" : "保留当前姿态";
    if (value.status === "synthesizing") element("#audio-state").textContent = "合成语音中…";
  }
  history.update(value);
  if (value.status === "error") {
    const error = [...value.events].reverse().find(event => event.kind === "error");
    if (error?.message) showError(new Error(error.message));
  }
}

async function play(packet: Expression, sessionId: string): Promise<void> {
  playing = packet.id;
  handled.add(packet.id);
  if (handled.size > 128) handled.delete(handled.values().next().value!);
  const generation = playbackGeneration;
  element<HTMLButtonElement>("#pause").disabled = false;
  element("#playback-note").textContent = packet.performance ? "同一模型连续生成动作，语音在独立轨道的指定位置播放。"
    : packet.motion
    ? "身体按时段选择一个动作模型；语音、口型与表情使用统一时钟。"
    : packet.route?.engine === "ardy" ? "动作序列连续生成，共用一条时间轴。" : "语音与字幕同步播放。";
  let status = "completed";
  let message = "";
  let durations = { audio_seconds: 0, motion_seconds: 0 };
  try {
    durations = await stage.perform({ ...packet, session_id: sessionId }, () => { element("#subtitle").textContent = packet.caption ?? packet.text; }, showProgress);
  } catch (error) {
    status = error instanceof DOMException && error.name === "AbortError" ? "interrupted" : "failed";
    message = error instanceof Error ? error.message : String(error);
    if (status === "failed") { stage.stopSpeech(); showError(error); }
  }
  if (generation === playbackGeneration && session?.id === sessionId && !closing) {
    const acknowledged = request(`/${sessionId}/feedback`, "POST", { packet_id: packet.id, epoch: packet.epoch,
      status, body: stage.state(), message, ...durations });
    const successor = status === "completed" && !mutating
      ? session.ready?.find(value => value.parent_id === packet.id && !handled.has(value.id)) : null;
    if (successor) {
      // Its audio is already scheduled. Render its first frame without an HTTP gap.
      const continuation = play(successor, sessionId);
      try { await acknowledged; } catch (error) { stage.stopSpeech(); showError(error); }
      await continuation;
      return;
    }
    try { await acknowledged; } catch (error) { stage.stopSpeech(); showError(error); }
    playing = null;
    element<HTMLButtonElement>("#pause").disabled = !stage.bodyRunning;
    element("#subtitle").textContent = "";
    // Consume a prepared successor immediately after its parent is acknowledged.
    const next = await request<Session>(`/${sessionId}`).catch(() => null);
    if (next && generation === playbackGeneration && session?.id === sessionId && !mutating && !closing) {
      session = next; renderState(next);
      if (next.pending && !handled.has(next.pending.id)) await play(next.pending, sessionId);
    }
  }
}

async function interrupt(): Promise<void> {
  playbackGeneration++;
  const body = stage.stop();
  playing = null;
  previewing = false;
  element<HTMLButtonElement>("#pause").disabled = true;
  element("#subtitle").textContent = "";
  if (session) session = await request(`/${session.id}/interrupt`, "POST", body);
}

element<HTMLInputElement>("#avatar").onchange = async (event) => {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  try {
    if (session) return;
    await motionBackend.ready;
    await stage.loadAvatar(file, motionBackend.value);
    element("#avatar-name").textContent = file.name.replace(/\.vrm$/i, "");
    root.classList.add("avatar-loaded");
    element<HTMLButtonElement>("#start").disabled = false;
    element("#error").textContent = "";
    element("#settings-error").textContent = "";
  } catch (error) { showError(error); }
};

element("#start").onclick = async () => {
  if (session || mutating) return;
  setMutating(true);
  try {
    await stage.unlockAudio();
    await Promise.all([preferences.ready, motionBackend.ready]);
    session = await request<Session>("", "POST", { motion_backend: motionBackend.value,
      playback_mode: element<HTMLSelectElement>("#playback-mode").value, ...preferences.values() });
    motionBackend.locked = true;
    element<HTMLSelectElement>("#playback-mode").disabled = true;
    await request(`/${session.id}/environment`, "POST", { kind: "context", silent: true,
      summary: "平坦地面 y=0。用户在正前方；杯子在左侧小圆台上，cup 是接触点，cup_side 是杯子旁的地面站位。move_to 只能选择地面站位；reach 选择杯子接触点。",
      targets: { user: { x: 0, y: 1.5, z: 3 }, cup: { x: 1, y: 0.98, z: 0.4 }, cup_side: { x: 1.3, y: 0, z: .35 }, center: { x: 0, y: 0, z: 0 } },
      affordances: { user: ["look_at"], cup: ["look_at", "reach"], cup_side: ["move_to"], center: ["move_to", "sit"] } });
    for (const id of ["#send", "#interrupt", "#close"]) element<HTMLButtonElement>(id).disabled = false;
    element<HTMLInputElement>("#avatar").disabled = true;
    element<HTMLButtonElement>("#start").disabled = true;
    element<HTMLDialogElement>("#settings-dialog").close();
    root.classList.add("connected");
    element("#error").textContent = "";
    element("#settings-error").textContent = "";
    renderState(session);
  } catch (error) { showError(error); }
  finally { setMutating(false); }
};

element<HTMLFormElement>("form").onsubmit = async (event) => {
  event.preventDefault();
  const text = element<HTMLTextAreaElement>("#message").value.trim();
  if (!session || !text || mutating) return;
  setMutating(true);
  try {
    await stage.unlockAudio();
    playbackGeneration++;
    const body = stage.stopSpeech(); playing = null; previewing = false;
    element("#subtitle").textContent = "";
    session = await request(`/${session!.id}/messages`, "POST", { text, body, ...preferences.values() });
    element<HTMLTextAreaElement>("#message").value = "";
    element("#error").textContent = "";
    element("#settings-error").textContent = "";
  } catch (error) { showError(error); }
  finally { setMutating(false); }
};

element("#interrupt").onclick = async () => {
  if (mutating) return;
  setMutating(true);
  try { await interrupt(); } catch (error) { showError(error); }
  finally { setMutating(false); }
};
element("#sound").onclick = () => { void stage.unlockAudio().catch(showError); };
element("#pause").onclick = async () => {
  try {
    const paused = await stage.togglePause();
    if (session && playing) await request(`/${session.id}/playback-control`, "POST", { epoch: session.epoch, paused });
  } catch (error) { showError(error); }
};
element<HTMLInputElement>("#volume").oninput = event => stage.setVolume(Number((event.target as HTMLInputElement).value));

async function replay(kind: "audio" | "motion" | "synchronized", record = false): Promise<void> {
  if (!stage.replayAvailable || playing || stage.bodyRunning || previewing || mutating) return;
  previewing = true;
  const generation = ++playbackGeneration;
  stage.stop();
  element<HTMLButtonElement>("#pause").disabled = false;
  element("#playback-note").textContent = kind === "audio" ? "正在单独重播语音。" : kind === "motion" ? "正在单独预览动作（无声音）。" : "正在同步重播语音、动作与字幕。";
  try {
    await stage.unlockAudio();
    const caption = (text: string) => { element("#subtitle").textContent = text; };
    if (record) await downloadVideo(await stage.recordVideo(caption, showProgress), session?.id);
    else await stage.replay(kind, caption, showProgress);
    if (generation === playbackGeneration) element("#playback-note").textContent = "回放结束。";
  } catch (error) {
    if (!(error instanceof DOMException && error.name === "AbortError")) showError(error);
  } finally {
    if (generation === playbackGeneration) {
      previewing = false; element<HTMLButtonElement>("#pause").disabled = true;
      element("#subtitle").textContent = "";
    }
  }
}
element("#replay-audio").onclick = () => { void replay("audio"); };
element("#replay-motion").onclick = () => { void replay("motion"); };
element("#replay-sync").onclick = () => { void replay("synchronized"); };
element("#export-video").onclick = () => { void replay("synchronized", true); };

element("#export-motion").onclick = () => {
  const windows = stage.motionRecording();
  downloadJSON("virea-motion.json", {
    schema: "virea.spatial_recording.v1", fps: windows[0]?.fps ?? 30, coordinate_system: "right-handed-y-up", quaternion_order: "xyzw",
    phases: windows.filter((w, i) => !i || w.phase_index !== windows[i - 1]!.phase_index)
      .map(w => ({ label: w.phase_label, description: w.prompt, kind: w.phase_kind, seconds: w.phase_seconds, offset: w.phase_offset, target: w.target })),
    windows,
  });
};
element("#settings-toggle").onclick = () => element<HTMLDialogElement>("#settings-dialog").showModal();
element("#settings-close").onclick = () => element<HTMLDialogElement>("#settings-dialog").close();
const toggleHistory = (open: boolean) => {
  element("#history-drawer").hidden = !open;
  element("#history-toggle").setAttribute("aria-expanded", String(open));
  if (open) element<HTMLInputElement>("#history-search").focus();
};
element("#history-toggle").onclick = () => toggleHistory(element("#history-drawer").hidden);
element("#history-close").onclick = () => toggleHistory(false);
element("#chat-collapse").onclick = () => {
  const collapsed = root.classList.toggle("chat-collapsed");
  element("#chat-collapse").textContent = collapsed ? "展开" : "收起";
  element("#chat-collapse").setAttribute("aria-expanded", String(!collapsed));
};
element("#reset-camera").onclick = () => stage.resetCamera();
element("#toggle-grid").onclick = () => {
  const visible = element("#toggle-grid").getAttribute("aria-pressed") !== "true";
  element("#toggle-grid").setAttribute("aria-pressed", String(visible)); stage.setGrid(visible);
};
element("#toggle-skeleton").onclick = () => {
  const visible = element("#toggle-skeleton").getAttribute("aria-pressed") !== "true";
  element("#toggle-skeleton").setAttribute("aria-pressed", String(visible)); stage.setSkeleton(visible);
};
element<HTMLTextAreaElement>("#message").onkeydown = event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); element<HTMLFormElement>("#composer").requestSubmit(); }
};
document.addEventListener("keydown", event => { if (event.key === "Escape") toggleHistory(false); });
element("#close").onclick = async () => {
  if (!session || mutating) return;
  closing = true; setMutating(true);
  playbackGeneration++; stage.stop(); playing = null; previewing = false;
  try { await request(`/${session.id}`, "DELETE"); }
  catch (error) { showError(error); }
  finally {
    session = null; motionBackend.locked = false; closing = false; setMutating(false); handled.clear();
    root.classList.remove("connected");
    element("#status").textContent = "已结束";
    element("#subtitle").textContent = "";
    element<HTMLInputElement>("#avatar").disabled = false;
    element<HTMLSelectElement>("#playback-mode").disabled = false;
    for (const id of ["#pause", "#replay-audio", "#replay-motion", "#replay-sync"]) element<HTMLButtonElement>(id).disabled = true;
    element<HTMLButtonElement>("#start").disabled = false;
    for (const id of ["#send", "#interrupt", "#close"]) element<HTMLButtonElement>(id).disabled = true;
  }
};

element("#new-session").onclick = async () => {
  if (mutating || closing) return;
  if (session) await element("#close").onclick?.(new PointerEvent("click"));
  element<HTMLDialogElement>("#settings-dialog").showModal();
};

async function poll(): Promise<void> {
  while (!disposed) {
    if (session && !closing && !mutating) {
      const id = session.id, generation = playbackGeneration;
      try {
        const value = await request<Session>(`/${id}`);
        if (session?.id === id && generation === playbackGeneration && !mutating) {
          session = value; renderState(value);
          if (!previewing && (!value.motion_backend || value.motion_backend === "sentiavatar_ardy")) stage.syncBody(value.body_program ?? null, id, showProgress, (programId, status, message) => {
            if (session?.id !== id || closing) return;
            if (status === "failed") showError(new Error(message));
          });
          if (value.status === "error" && playing) {
            playbackGeneration++; stage.stopSpeech(); playing = null;
            element<HTMLButtonElement>("#pause").disabled = true;
            element("#subtitle").textContent = "";
          }
          for (const packet of value.ready?.length ? value.ready : value.buffered ? [value.buffered] : []) void stage.preload(packet).catch(error => {
            if (generation === playbackGeneration && session?.id === id && !mutating) showError(error);
          });
          const fastEnough = value.pending && value.metrics.motion_seconds !== null
            && value.metrics.motion_seconds < value.pending.audio_seconds * 0.7;
          const bufferedStart = value.pending?.independent_speech || !value.pending?.stream_id || !value.pending.continues || fastEnough || (value.ready?.length ?? 0) >= 2;
          if (value.pending && !playing && !handled.has(value.pending.id) && bufferedStart) void play(value.pending, id);
        }
      } catch (error) {
        if (error instanceof RequestError && error.status === 404 && session?.id === id) {
          playbackGeneration++; stage.stop(); playing = null; previewing = false;
          session = null; motionBackend.locked = false; handled.clear();
          element("#status").textContent = "会话已结束";
          element("#subtitle").textContent = "";
          element<HTMLInputElement>("#avatar").disabled = false;
          element<HTMLSelectElement>("#playback-mode").disabled = false;
          element<HTMLButtonElement>("#start").disabled = false;
          for (const name of ["#send", "#interrupt", "#close", "#pause", "#replay-audio", "#replay-motion", "#replay-sync"]) element<HTMLButtonElement>(name).disabled = true;
          showError(new Error("会话已结束或服务已重启，请重新开始会话。"));
        } else showError(error);
      }
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
}
window.addEventListener("pagehide", () => {
  disposed = true; stage.dispose();
  if (session) void fetch(`/api/v1/characters/${session.id}`, { method: "DELETE", keepalive: true });
});
void poll();
element<HTMLDialogElement>("#settings-dialog").showModal();
