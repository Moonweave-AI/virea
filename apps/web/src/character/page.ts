import "./style.css";
import { CharacterStage } from "./stage";
import type { Expression, Session } from "./contracts";

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
      <p class="hint">需要本地 Qwen、Kokoro 和已安装的 SentiAvatar。静默时保留姿态；移动由场景引擎执行。</p>
      <div id="conversation" role="log" aria-label="对话记录"></div>
      <form><label for="message">对角色说</label><textarea id="message" rows="3" maxlength="4000" placeholder="你好，看看你左边的杯子。" required></textarea>
        <div class="buttons"><button type="submit" id="send" disabled>发送</button><button type="button" id="interrupt" disabled>打断并留在此刻</button></div></form>
      <div id="error" role="alert"></div>
      <details><summary>运行状态与能力边界</summary><p>片段衔接使用播放器姿态混合。当前 SentiAvatar 不支持原生历史或实际姿态条件输入。手指使用上游固定资源，面部映射为近似转换。</p><output id="metrics">尚无测量</output></details>
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

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1/characters${path}`, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === "string" ? payload.detail : `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function showError(error: unknown): void {
  element("#error").textContent = error instanceof Error ? error.message : String(error);
}

function renderState(value: Session): void {
  const labels: Record<string, string> = { waiting: "正在等待", thinking: "正在思考", generating: "准备声音与动作", awaiting_playback: "正在表达", error: "需要处理", closed: "已结束" };
  element("#status").textContent = labels[value.status] ?? value.status;
  element("#metrics").textContent = `首个完整表达包：${value.metrics.first_expression_seconds?.toFixed(2) ?? "—"} 秒；生成 RTF：${value.metrics.rtf?.toFixed(2) ?? "—"}`;
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
  let status = "completed";
  let message = "";
  let durations = { audio_seconds: 0, motion_seconds: 0 };
  try {
    durations = await stage.perform(packet, () => { element("#subtitle").textContent = packet.text; });
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
    element("#subtitle").textContent = "";
  }
}

async function interrupt(): Promise<void> {
  playbackGeneration++;
  const body = stage.stop();
  playing = null;
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
  mutating = true;
  try {
    await stage.unlockAudio();
    session = await request<Session>("", "POST", {});
    await request(`/${session.id}/environment`, "POST", { kind: "context", silent: true,
      summary: "用户在正前方，杯子在角色左侧。move_to 是平移，无生成式步态。",
      targets: { user: { x: 0, y: 1.5, z: 3 }, cup: { x: 1, y: 0.9, z: 0.4 } } });
    for (const id of ["#send", "#interrupt", "#close"]) element<HTMLButtonElement>(id).disabled = false;
    element<HTMLInputElement>("#avatar").disabled = true;
    element<HTMLButtonElement>("#start").disabled = true;
    element("#error").textContent = "";
    renderState(session);
  } catch (error) { showError(error); }
  finally { mutating = false; }
};

element<HTMLFormElement>("form").onsubmit = async (event) => {
  event.preventDefault();
  const text = element<HTMLTextAreaElement>("#message").value.trim();
  if (!session || !text || mutating) return;
  mutating = true;
  try {
    await stage.unlockAudio();
    await interrupt();
    session = await request(`/${session!.id}/messages`, "POST", { text });
    element<HTMLTextAreaElement>("#message").value = "";
    element("#error").textContent = "";
  } catch (error) { showError(error); }
  finally { mutating = false; }
};

element("#interrupt").onclick = async () => {
  if (mutating) return;
  mutating = true;
  try { await interrupt(); } catch (error) { showError(error); }
  finally { mutating = false; }
};
element("#sound").onclick = () => { void stage.unlockAudio().catch(showError); };
element("#close").onclick = async () => {
  if (!session || mutating) return;
  closing = true; mutating = true;
  playbackGeneration++; stage.stop(); playing = null;
  try { await request(`/${session.id}`, "DELETE"); }
  catch (error) { showError(error); }
  finally {
    session = null; closing = false; mutating = false; handled.clear();
    element("#status").textContent = "已结束";
    element("#subtitle").textContent = "";
    element<HTMLInputElement>("#avatar").disabled = false;
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
          if (value.pending && !playing && !handled.has(value.pending.id)) void play(value.pending, id);
        }
      } catch (error) { showError(error); }
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
}
window.addEventListener("pagehide", () => {
  disposed = true; stage.dispose();
  if (session) void fetch(`/api/v1/characters/${session.id}`, { method: "DELETE", keepalive: true });
});
void poll();
