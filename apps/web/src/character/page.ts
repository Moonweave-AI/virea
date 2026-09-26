import "./style.css";
import { CharacterStage } from "./stage";
import type { Expression, Session, PlaybackProgress } from "./contracts";

const root = document.querySelector<HTMLDivElement>("#character")!;
root.innerHTML = `
  <header><a href="./">VIREA</a><span>持续角色 · 实验预览</span><a href="./">返回动作工作室 ↗</a></header>
  <main>
    <section class="stage"><canvas aria-label="持续角色三维场景"></canvas>
      <div class="stage-title"><small>CHARACTER / LIVE SPACE</small><h1>在这里，继续对话。</h1><p>话语会结束，角色留在原地。</p></div>
      <div id="subtitle" aria-live="polite"></div><div class="stage-note">拖动旋转 · 滚轮缩放</div>
    </section>
    <aside>
      <div class="session-heading"><h2>角色会话</h2><span id="status">未连接</span></div>
      <label class="file">载入 VRM 角色<input id="avatar" type="file" accept=".vrm,.glb"></label>
      <div class="buttons"><button id="start" disabled>开始会话</button><button id="sound">继续声音</button><button id="close" disabled>结束</button></div>
      <label class="mode">播放方式<select id="playback-mode"><option value="synchronized">严格同步 · 统一时间轴</option><option value="voice_first">语音优先 · 动作稍后预览</option></select></label>
      <section class="expression-panel" aria-label="语音、动作与文本">
        <div class="track"><strong>统一时间轴</strong><span id="timeline-state">等待资源就绪</span><progress id="timeline-progress" max="1" value="0" aria-label="统一播放进度"></progress></div>
        <div class="track"><strong>语音</strong><span id="audio-state">等待语音</span><progress id="audio-progress" max="1" value="0" aria-label="语音进度"></progress></div>
        <div class="track"><strong>动作</strong><span id="motion-state">保留当前姿态</span><progress id="motion-progress" max="1" value="0" aria-label="动作进度"></progress></div>
        <div class="buttons"><button id="pause" disabled>暂停</button><button id="replay-audio" disabled>重播语音</button><button id="replay-motion" disabled>预览动作</button><button id="replay-sync" disabled>同步重播</button></div>
        <label class="volume">音量<input id="volume" type="range" min="0" max="1" step="0.05" value="1"></label>
        <p id="playback-note" class="hint">声音、动作和面部全部就绪后统一起播；字幕随语音显示。</p>
        <div class="text-heading"><strong>文本</strong><span id="text-state">等待回复</span></div><p id="response-text">回复生成后会先显示在这里。</p>
      </section>
      <div id="conversation" role="log" aria-label="对话记录"></div>
      <form><label for="message">对角色说</label><textarea id="message" rows="3" maxlength="4000" placeholder="你好，看看你左边的杯子。" required></textarea>
        <div class="buttons"><button type="submit" id="send" disabled>发送</button><button type="button" id="interrupt" disabled>打断并留在此刻</button></div></form>
      <div id="error" role="alert"></div>
      <details><summary>运行状态与能力边界</summary><p>片段衔接结合历史动作码约束、解码重叠和实际姿态的惯性过渡。动作规划器仍不支持完整历史或实际姿态条件输入。手指使用上游固定资源，面部映射为近似转换。</p><output id="metrics">尚无测量</output></details>
    </aside>
  </main>`;

function element<T extends HTMLElement>(selector: string): T { return root.querySelector<T>(selector)!; }
const stage = new CharacterStage(element("canvas"));
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
  const duration = Math.max(value.audioDuration, value.motionDuration);
  const timeline = element<HTMLProgressElement>("#timeline-progress");
  timeline.max = Math.max(duration, 0.001); timeline.value = Math.min(value.elapsed, duration);
  element("#timeline-state").textContent = `${value.paused ? "已暂停 · " : ""}${timeline.value.toFixed(2)} / ${duration.toFixed(2)} 秒`;
  if (value.elapsed >= value.audioDuration) element("#subtitle").textContent = "";
  for (const [name, duration] of [["audio", value.audioDuration], ["motion", value.motionDuration]] as const) {
    const elapsed = Math.min(value.elapsed, duration);
    const bar = element<HTMLProgressElement>(`#${name}-progress`);
    bar.max = Math.max(duration, 0.001); bar.value = elapsed;
    bar.dataset.seconds = elapsed.toFixed(3);
    element(`#${name}-state`).textContent = duration
      ? `${value.paused ? "已暂停 · " : ""}${elapsed.toFixed(1)} / ${duration.toFixed(1)} 秒`
      : name === "audio" ? "无语音" : "本次未播放动作";
  }
  element("#pause").textContent = value.paused ? "继续" : "暂停";
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
}

function renderState(value: Session): void {
  const labels: Record<string, string> = { waiting: "正在等待", thinking: "正在思考", synthesizing: "合成语音", generating: "生成动作", awaiting_playback: "正在表达", error: "需要处理", closed: "已结束" };
  element("#status").textContent = labels[value.status] ?? value.status;
  const seconds = (value: number | null) => value?.toFixed(2) ?? "—";
  element("#metrics").textContent = `语言 ${seconds(value.metrics.language_seconds)}s · TTS ${seconds(value.metrics.tts_seconds)}s · 动作 ${seconds(value.metrics.motion_seconds)}s\n语音就绪 ${seconds(value.metrics.first_audio_seconds)}s · 完整表达 ${seconds(value.metrics.first_expression_seconds)}s · RTF ${seconds(value.metrics.rtf)}`;
  element("#response-text").textContent = value.draft_text || (value.status === "thinking" ? "正在准备回复…" : "此刻没有需要说出的文本。");
  element("#text-state").textContent = value.draft_text ? "完整文本已就绪" : "尚未生成";
  const idle = !playing && !previewing && ["waiting", "error"].includes(value.status);
  const latest = value.latest_expression;
  element<HTMLButtonElement>("#replay-audio").disabled = !idle || !latest?.audio_url;
  element<HTMLButtonElement>("#replay-motion").disabled = !idle || !latest?.motion;
  element<HTMLButtonElement>("#replay-sync").disabled = !idle || !latest?.motion || !latest?.audio_url;
  if (!playing && !previewing) {
    element("#motion-state").textContent = value.status === "generating" ? "动作生成中…" : latest?.motion ? "动作已就绪 · 可预览" : "保留当前姿态";
    if (value.status === "synthesizing") element("#audio-state").textContent = "合成语音中…";
  }
  const log = element("#conversation");
  log.replaceChildren(...value.history.map(item => {
    const paragraph = document.createElement("p");
    paragraph.className = item.role;
    paragraph.textContent = `${item.role === "user" ? "你" : "角色"} · ${item.content}`;
    return paragraph;
  }));
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
  element("#playback-note").textContent = packet.motion
    ? "语音、动作与字幕使用同一播放时钟；整句结束后身体自然收势，字幕随语音结束。"
    : "优先播放语音与字幕，口型按音量近似驱动；生成动作可稍后预览或同步重播。";
  let status = "completed";
  let message = "";
  let durations = { audio_seconds: 0, motion_seconds: 0 };
  try {
    durations = await stage.perform(packet, () => { element("#subtitle").textContent = packet.text; }, showProgress);
  } catch (error) {
    status = error instanceof DOMException && error.name === "AbortError" ? "interrupted" : "failed";
    message = error instanceof Error ? error.message : String(error);
    if (status === "failed") { stage.stop(); showError(error); }
  }
  if (generation === playbackGeneration && session?.id === sessionId && !closing) {
    try {
      await request(`/${sessionId}/feedback`, "POST", { packet_id: packet.id, epoch: packet.epoch,
        status, body: stage.state(), message, ...durations });
    } catch (error) { showError(error); }
    playing = null;
    element<HTMLButtonElement>("#pause").disabled = true;
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
    await stage.loadAvatar(file);
    element<HTMLButtonElement>("#start").disabled = false;
    element("#error").textContent = "";
  } catch (error) { showError(error); }
};

element("#start").onclick = async () => {
  if (session || mutating) return;
  setMutating(true);
  try {
    await stage.unlockAudio();
    session = await request<Session>("", "POST", { playback_mode: element<HTMLSelectElement>("#playback-mode").value });
    element<HTMLSelectElement>("#playback-mode").disabled = true;
    await request(`/${session.id}/environment`, "POST", { kind: "context", silent: true,
      summary: "用户在正前方，杯子在角色左侧。move_to 是平移，无生成式步态。",
      targets: { user: { x: 0, y: 1.5, z: 3 }, cup: { x: 1, y: 0.9, z: 0.4 } } });
    for (const id of ["#send", "#interrupt", "#close"]) element<HTMLButtonElement>(id).disabled = false;
    element<HTMLInputElement>("#avatar").disabled = true;
    element<HTMLButtonElement>("#start").disabled = true;
    element("#error").textContent = "";
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
    await interrupt();
    session = await request(`/${session!.id}/messages`, "POST", { text });
    element<HTMLTextAreaElement>("#message").value = "";
    element("#error").textContent = "";
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
element("#pause").onclick = () => { void stage.togglePause().catch(showError); };
element<HTMLInputElement>("#volume").oninput = event => stage.setVolume(Number((event.target as HTMLInputElement).value));

async function replay(kind: "audio" | "motion" | "synchronized"): Promise<void> {
  const packet = session?.latest_expression;
  if (!packet || playing || previewing || mutating) return;
  previewing = true;
  const generation = ++playbackGeneration;
  stage.stop();
  element<HTMLButtonElement>("#pause").disabled = false;
  element("#playback-note").textContent = kind === "audio" ? "正在单独重播语音。" : kind === "motion" ? "正在单独预览动作（无声音）。" : "正在同步重播语音、动作与字幕。";
  try {
    await stage.unlockAudio();
    await stage.perform({ ...packet, actions: [], audio_url: kind === "motion" ? null : packet.audio_url,
      motion: kind === "audio" ? null : packet.motion }, () => {
        element("#subtitle").textContent = kind === "motion" ? "" : packet.text;
      }, showProgress);
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
element("#close").onclick = async () => {
  if (!session || mutating) return;
  closing = true; setMutating(true);
  playbackGeneration++; stage.stop(); playing = null; previewing = false;
  try { await request(`/${session.id}`, "DELETE"); }
  catch (error) { showError(error); }
  finally {
    session = null; closing = false; setMutating(false); handled.clear();
    element("#status").textContent = "已结束";
    element("#subtitle").textContent = "";
    element<HTMLInputElement>("#avatar").disabled = false;
    element<HTMLSelectElement>("#playback-mode").disabled = false;
    for (const id of ["#pause", "#replay-audio", "#replay-motion", "#replay-sync"]) element<HTMLButtonElement>(id).disabled = true;
    element<HTMLButtonElement>("#start").disabled = false;
    for (const id of ["#send", "#interrupt", "#close"]) element<HTMLButtonElement>(id).disabled = true;
  }
};

async function poll(): Promise<void> {
  while (!disposed) {
    if (session && !closing && !mutating) {
      const id = session.id, generation = playbackGeneration;
      try {
        const value = await request<Session>(`/${id}`);
        if (session?.id === id && generation === playbackGeneration && !mutating) {
          session = value; renderState(value);
          if (value.status === "error" && playing) {
            playbackGeneration++; stage.stop(); playing = null;
            element<HTMLButtonElement>("#pause").disabled = true;
            element("#subtitle").textContent = "";
          }
          if (value.buffered) void stage.preload(value.buffered).catch(error => {
            if (generation === playbackGeneration && session?.id === id && !mutating) showError(error);
          });
          if (value.pending && !playing && !handled.has(value.pending.id)) void play(value.pending, id);
        }
      } catch (error) {
        if (error instanceof RequestError && error.status === 404 && session?.id === id) {
          playbackGeneration++; stage.stop(); playing = null; previewing = false;
          session = null; handled.clear();
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
