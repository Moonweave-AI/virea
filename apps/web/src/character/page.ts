import "./style.css";
import { CharacterStage } from "./stage";
import type { Expression, Session, PlaybackProgress } from "./contracts";

const root = document.querySelector<HTMLDivElement>("#character")!;
root.innerHTML = `
  <header><a href="./">VIREA<span class="brand-dot">.</span></a><span>持续角色 / LIVE SPACE</span><a href="./">动作工作室 ↗</a></header>
  <main>
    <section class="stage"><canvas aria-label="持续角色三维场景"></canvas>
      <div class="stage-title"><small><i></i> CHARACTER SPACE</small><h1>在这里，继续对话。</h1><p>说话、倾听，自然相伴。</p></div>
      <div id="subtitle" aria-live="polite"></div><div class="stage-note">拖动旋转 · 滚轮缩放</div>
      <aside aria-label="角色聊天">
        <div class="session-heading"><div><small>CONVERSATION</small><h2>和角色聊聊</h2></div><div class="session-actions"><span id="status" role="status">未连接</span><button id="close" aria-label="结束会话" title="结束会话" disabled>×</button></div></div>
        <div class="chat-content">
          <details id="session-tools" class="settings" open><summary>角色与会话</summary><div class="settings-content">
            <label class="file">载入 VRM 角色<input id="avatar" type="file" accept=".vrm,.glb"></label>
            <label class="mode">播放方式<select id="playback-mode"><option value="synchronized">严格同步 · 统一时间轴</option><option value="voice_first">语音优先 · 动作稍后预览</option></select></label>
            <div class="buttons"><button id="start" class="primary" disabled>开始会话</button><button id="sound">继续声音</button></div>
          </div></details>
          <section class="latest-reply" aria-label="角色回复"><div class="text-heading"><strong>角色</strong><span id="text-state">等待回复</span></div><p id="response-text">载入角色，开始一段对话。</p></section>
          <section class="expression-panel" aria-label="语音、动作与文本">
            <div class="track timeline"><strong>统一时间轴</strong><span id="timeline-state">等待资源就绪</span><button id="pause" disabled>暂停</button><progress id="timeline-progress" max="1" value="0" aria-label="统一播放进度"></progress></div>
            <div class="track"><strong>语音</strong><span id="audio-state">等待语音</span><progress id="audio-progress" max="1" value="0" aria-label="语音进度"></progress></div>
            <div class="track"><strong>动作</strong><span id="motion-state">保留当前姿态</span><progress id="motion-progress" max="1" value="0" aria-label="动作进度"></progress></div>
            <details class="playback-tools"><summary>音量与重播</summary><div class="settings-content">
              <label class="volume">音量<input id="volume" type="range" min="0" max="1" step="0.05" value="1"></label>
              <div class="buttons"><button id="replay-audio" disabled>重播语音</button><button id="replay-motion" disabled>预览动作</button><button id="replay-sync" disabled>同步重播</button></div>
              <p id="playback-note" class="hint">声音、动作和面部全部就绪后统一起播；字幕随语音显示。</p>
            </div></details>
          </section>
          <details class="history"><summary>对话记录</summary><div id="conversation" role="log" aria-label="对话记录"></div></details>
          <details class="diagnostics"><summary>运行状态</summary><output id="metrics">尚无测量</output><p>讲话期间动作连续衔接，表达结束后放松收势。手指使用上游固定资源，标准 VRM 的面部映射为近似转换。</p></details>
        </div>
        <form><label class="sr-only" for="message">对角色说</label><textarea id="message" rows="2" maxlength="4000" placeholder="说点什么，让对话继续…" required></textarea>
          <div class="composer-actions"><button type="button" id="interrupt" title="打断并保留当前姿态" disabled>打断</button><button type="submit" id="send" class="primary" disabled>发送 <span aria-hidden="true">↗</span></button></div></form>
        <div id="error" role="alert"></div>
      </aside>
    </section>
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
  element("#metrics").textContent = `语言流水线 ${seconds(value.metrics.language_seconds)}s · TTS ${seconds(value.metrics.tts_seconds)}s · 动作 ${seconds(value.metrics.motion_seconds)}s\n语音就绪 ${seconds(value.metrics.first_audio_seconds)}s · 首包就绪 ${seconds(value.metrics.first_expression_seconds)}s · ${value.playback_mode === "synchronized" ? "动作" : "生成"} RTF ${seconds(value.metrics.rtf)}`;
  element("#response-text").textContent = value.draft_text || (value.status === "thinking" ? "正在准备回复…" : "此刻没有需要说出的文本。");
  element("#text-state").textContent = value.draft_text ? "实时回复" : "尚未生成";
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
    ? "动作在讲话期间持续衔接，结束后自然收势；语音、动作与字幕共用时间轴。"
    : "优先播放语音与字幕，口型按音量近似驱动；生成动作可稍后预览或同步重播。";
  let status = "completed";
  let message = "";
  let durations = { audio_seconds: 0, motion_seconds: 0 };
  try {
    durations = await stage.perform({ ...packet, session_id: sessionId }, () => { element("#subtitle").textContent = packet.caption ?? packet.text; }, showProgress);
  } catch (error) {
    status = error instanceof DOMException && error.name === "AbortError" ? "interrupted" : "failed";
    message = error instanceof Error ? error.message : String(error);
    if (status === "failed") { stage.stop(); showError(error); }
  }
  if (generation === playbackGeneration && session?.id === sessionId && !closing) {
    const acknowledged = request(`/${sessionId}/feedback`, "POST", { packet_id: packet.id, epoch: packet.epoch,
      status, body: stage.state(), message, ...durations });
    const successor = status === "completed" && !mutating
      ? session.ready?.find(value => value.parent_id === packet.id && !handled.has(value.id)) : null;
    if (successor) {
      // Its audio is already scheduled. Render its first frame without an HTTP gap.
      const continuation = play(successor, sessionId);
      try { await acknowledged; } catch (error) { stage.stop(); showError(error); }
      await continuation;
      return;
    }
    try { await acknowledged; } catch (error) { stage.stop(); showError(error); }
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
      summary: "平坦地面 y=0。用户在正前方；杯子在左侧小圆台上，cup 是接触点，cup_side 是杯子旁的地面站位。move_to 只能选择地面站位；reach 选择杯子接触点。",
      targets: { user: { x: 0, y: 1.5, z: 3 }, cup: { x: 1, y: 0.98, z: 0.4 }, cup_side: { x: 1.3, y: 0, z: .35 }, center: { x: 0, y: 0, z: 0 } } });
    for (const id of ["#send", "#interrupt", "#close"]) element<HTMLButtonElement>(id).disabled = false;
    element<HTMLInputElement>("#avatar").disabled = true;
    element<HTMLButtonElement>("#start").disabled = true;
    element<HTMLDetailsElement>("#session-tools").open = false;
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
          for (const packet of value.ready?.length ? value.ready : value.buffered ? [value.buffered] : []) void stage.preload(packet).catch(error => {
            if (generation === playbackGeneration && session?.id === id && !mutating) showError(error);
          });
          const fastEnough = value.pending && value.metrics.motion_seconds !== null
            && value.metrics.motion_seconds < value.pending.audio_seconds * 0.7;
          const bufferedStart = !value.pending?.stream_id || !value.pending.continues || fastEnough || (value.ready?.length ?? 0) >= 2;
          if (value.pending && !playing && !handled.has(value.pending.id) && bufferedStart) void play(value.pending, id);
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
