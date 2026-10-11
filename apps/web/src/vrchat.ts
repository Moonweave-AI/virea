import "./vrchat.css";
import {acceptSnapshot, bridgeError, executionResult, executionNote, mergeTranscript, readConversations, statusLabel, type Conversation} from "./vrchat-conversation.mjs";
import {connectionView, readConnectionSettings} from "./vrchat-connection.mjs";
import {mountViews} from "./vrchat-view-panel";
import {mountClientLaunchers} from "./vrchat-client-panel";

const icon = (name: string) => ({menu: "☰", plus: "+", settings: "⚙", arrow: "↑", stop: "■", close: "×"})[name] ?? name;
const root = document.querySelector<HTMLElement>("#vrchat")!;
root.innerHTML = `
  <aside class="sidebar" id="sidebar" aria-label="对话导航">
    <a class="wordmark" href="./">VIREA<span class="wordmark-dot"></span></a>
    <button class="new-chat" id="new-chat">${icon("plus")} <span>新对话</span><kbd>Ctrl ⇧ O</kbd></button>
    <label class="search"><span class="sr-only">搜索本机对话</span><input id="search" type="search" placeholder="搜索对话" autocomplete="off"></label>
    <p class="nav-label">最近的对话</p><nav id="conversations" aria-label="聊天记录"></nav>
    <div class="sidebar-bottom"><a href="./character.html">Motion Studio <span>↗</span></a><button id="open-settings">${icon("settings")} <span>角色与连接设置</span></button><p>对话记录仅保存在此浏览器</p></div>
  </aside>
  <div class="chat-shell">
    <header class="chat-header"><div><button class="icon-button" id="toggle-sidebar" aria-label="切换侧栏" aria-expanded="true" aria-controls="sidebar">${icon("menu")}</button><label class="model-button">Virea <select id="model-choice" aria-label="动作方法"><option value="motioncraft">MotionCraft</option><option value="syntalker">SynTalker</option></select></label></div><div class="header-tools"><button id="connection" class="connection-pill" aria-label="查看连接状态"><i></i><span>尚未连接</span></button><button id="toggle-views" class="icon-button views-toggle" aria-label="展开实时双视角" aria-expanded="false" aria-controls="live-views" title="实时双视角"><svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="2" y="3" width="16" height="14" rx="3" stroke="currentColor" stroke-width="1.4"/><path d="M11 3v14m0-7h7" stroke="currentColor" stroke-width="1.4"/></svg></button></div></header>
    <div class="chat-scroll" id="chat-scroll">
      <section class="connection-card" aria-label="AI 角色连接" aria-live="polite"><div class="connection-card-heading"><span class="avatar-mark">V</span><div><strong id="connection-title">正在连接控制服务</strong><p id="character-name">正在识别角色</p></div><button id="reconnect" type="button">重新连接</button></div><div id="connection-steps" class="connection-steps"></div><p id="connection-detail"></p><button id="connection-settings" type="button">查看角色与输出设置 ↗</button></section>
      <section class="avatar-preview" aria-label="导入模型预览"><canvas id="avatar-canvas" aria-label="可拖动旋转的 VRM 模型预览"></canvas><p id="avatar-preview-note">正在加载导入的角色…</p><button id="reload-avatar" type="button" hidden>重新加载模型</button></section>
      <section class="welcome" id="welcome"><h1>有什么想让 Virea 做的？</h1><p>对话、语音与角色任务，都从这里开始。</p><div class="suggestions"><button data-prompt="用8秒做一个简短的欢迎介绍，在第2秒开始说：你好，我是 Virea，很高兴见到你。">打个招呼<span>一段有声音的欢迎介绍</span></button><button data-prompt="用12秒做一段安静的表演，A person stands calmly. 不要说话。">安静陪伴<span>保持动作，让声音休息一下</span></button><button data-prompt="做一段总长16秒的自我介绍。前8秒 A person stands calmly. 后8秒 A person turns slowly. 第3秒说：你好，我是 Virea。">安排一段表演<span>为动作与语音分别安排时间</span></button></div></section>
      <section id="messages" class="messages" role="log" aria-label="与 Virea 的对话" aria-live="polite" aria-relevant="additions text"></section>
      <section id="execution" class="execution" hidden><div class="execution-heading"><span class="pulse"></span><span id="session-state"></span><span id="elapsed"></span></div><div id="timeline"></div><p id="execution-note" class="note"></p><div class="execution-actions"><button id="pause">暂停</button><button id="stop">停止任务</button><button id="show-diagnostics">执行详情 ↗</button></div></section>
      <button id="scroll-bottom" class="scroll-bottom" aria-label="回到最新消息" hidden>↓</button>
    </div>
    <div class="composer-wrap">
      <div id="error" class="error-banner" role="alert" hidden><span id="error-text"></span><button id="retry">重试</button><button id="dismiss-error" class="icon-button" aria-label="关闭错误提示">×</button></div>
      <div id="context-note" class="context-note"></div>
      <form id="message-form" class="composer"><label class="sr-only" for="message">给 Virea 发消息</label><textarea id="message" rows="1" maxlength="4000" placeholder="给 Virea 发消息，或安排一个任务…" required></textarea><div class="composer-tools"><button id="quick-settings" type="button" aria-label="输出设置">${icon("settings")} <span id="output-label">桌面模式 · 语音关闭</span></button><span id="character-count"></span><button id="send" class="send-button" type="submit" aria-label="发送消息">${icon("arrow")}</button></div></form>
      <p class="composer-footnote">Enter 发送 · Shift + Enter 换行 <span>关闭页面后，当前任务仍会继续。</span></p>
    </div>
  </div>
  <dialog id="settings-dialog" aria-labelledby="settings-title"><div class="dialog-heading"><h2 id="settings-title">角色与连接</h2><button id="close-settings" class="icon-button" aria-label="关闭设置">×</button></div><div class="dialog-tabs"><button id="configuration-tab" aria-selected="true">设置</button><button id="diagnostics-tab" aria-selected="false">诊断</button></div><div class="dialog-body"><section id="configuration-panel">  <form id="connect-form"><fieldset id="settings">
    <section class="setup-guide"><h3>AI 是独立角色，你是观察者</h3><p>保留你当前的 VRChat 窗口。AI 使用第二个客户端和专用端口，登录独立账号。两个账号进入同一在线房间后，才能从你的视角观察 AI。</p><ol><li>启动 AI 客户端，并登录 AI 账号。<button type="button" id="copy-launch">复制 AI 启动参数</button></li><li>在 AI 窗口开启 Action Menu → Options → OSC，换上准备好的 AI 角色。</li><li>本页面自动识别并绑定已安装 VIREA 参数的角色，可在下方核对。</li></ol><p>SDK Build &amp; Test 角色仅本客户端可见；跨账号展示自定义 VRM 需要有上传权限的 AI 账号发布角色。<a href="https://creators.vrchat.com/avatars/creating-your-first-avatar/" target="_blank" rel="noreferrer">官方角色导入流程 ↗</a></p></section>
    <label>运行模式<select id="mode"><option value="generated_vr">模型姿态 → 虚拟 VR 设备</option><option value="desktop">桌面兼容模式（无生成全身动作）</option><option value="vr_trackers">实体 VR 设备 + 身体追踪</option></select></label>
    <p id="mode-note" class="note">桌面版输出移动、语音和自定义手势；不能通过 OSC 播放任意全身骨骼动画。</p>
    <label>动作模型<select id="backend"><option value="motioncraft">MotionCraft</option><option value="syntalker">SynTalker</option></select></label>
    <p class="note">可以随时切换；保存后停止当前任务，保留对话和 VRChat 连接。新消息使用新方法。</p>
    <label><input type="checkbox" id="desktop-emotes"> 桌面动作：使用角色的 SDK 预设动画</label>
    <p class="note">适用于已准备的 VIREA 角色：挥手、鼓掌、指向、欢呼和跳舞。预设动画按动作时间轴播放，不等同于 MotionCraft / SynTalker 生成骨骼的原样播放。其他动作会注明未传递。</p>
    <label>克隆声音<select id="voice"><option value="">使用已配置声音</option></select></label>
    <label>角色设定<textarea id="persona" rows="2" placeholder="留空沿用 VIREA 的角色设定"></textarea></label>
    <label>每个任务的自主跟进次数<input id="autonomy" type="number" value="3" min="0" max="10" required></label>
    <label>虚拟声卡播放端<select id="audio"><option value="">关闭语音输出</option></select></label>
    <p class="note">选择虚拟线缆的播放端，并在 VRChat 里选择对应的录音端。不会自动选择默认扬声器。</p>
    <div class="checks"><label><input type="checkbox" id="chatbox" checked> AI 回复显示在 AI 头顶</label><label><input type="checkbox" id="observer-chatbox" checked> 我的消息显示在我的角色头顶</label><label><input type="checkbox" id="locomotion"> 允许输入控制角色移动</label></div>
    <label><input id="auto-bind" type="checkbox" checked> 自动绑定专用 AI 客户端中已安装 VIREA 参数的角色</label>
    <label>AI Avatar ID<input id="avatar-id" placeholder="自动识别本地测试或已发布角色"></label>
    <details><summary>OSC 与校准</summary><label>AI 客户端 Profile<input id="ai-profile" type="number" value="2" min="0" max="99" required></label><div class="pair"><label>AI 接收端口<input id="send-port" type="number" value="19010" min="1024" max="65535" required></label><label>AI 回传端口<input id="receive-port" type="number" value="19011" min="1024" max="65535" required></label></div>
    <div class="pair"><label>身体比例<input id="scale" type="number" min="0.2" max="3" step="0.01" value="1"></label><label>追踪朝向（度）<input id="yaw" type="number" min="-180" max="180" value="0"></label></div>
    <p class="note">9000/9001 保留给观察端。AI 在专用端口上自动识别角色；请勿填写观察者客户端的端口。</p>
    <label><input type="checkbox" id="hold"> 语音段期间按住说话</label><p class="note">默认由你在 VRChat 中开麦。使用“按住说话”时，需要关闭 VRChat 的 Toggle Voice。</p></details>
  </fieldset><button id="connect" class="primary" type="submit">连接 VRChat 桥接</button></form>
  <p id="settings-error" class="error-banner" role="alert" hidden></p>
  <div id="avatar-binding" hidden><p>AI 专用端口收到的角色：<code id="observed-avatar"></code></p><button id="bind-avatar" type="button">绑定此 AI 角色</button></div>
  <button id="disconnect" type="button" hidden>断开连接</button>
<p class="setup-help">请在 AI 窗口启用 OSC；页面会自动检测角色。表情和手势需要 Avatar 安装 VIREA 参数。</p></section><section id="diagnostics-panel" hidden><h3>真实回传</h3><p id="receiver"></p><dl id="feedback"></dl><p class="note">发送帧数：<span id="frames">0</span>。UDP 发送成功并不代表角色已执行；此处不会将命令当作观测结果。</p><h3>最近执行记录</h3><pre id="results">[]</pre></section></div></dialog>`;

function element<T extends HTMLElement>(id: string): T { return document.getElementById(id) as T; }
function value(id: string) { return element<HTMLInputElement>(id).value; }
function checked(id: string) { return element<HTMLInputElement>(id).checked; }
const storageKey = "virea.vrchat.conversations.v1";
let conversations: Conversation[];
try { conversations = readConversations(localStorage.getItem(storageKey)); } catch { conversations = []; }
function createConversation(): Conversation {
  const item = {id: crypto.randomUUID(), title: "新的对话", sessionId: null, updatedAt: Date.now(), messages: []};
  conversations.unshift(item); return item;
}
let active = conversations[0] ?? createConversation();
let state: any = {connected: false};
let busy = false;
let sendingText = "";
let retryText = "";
let messagesKey = "";
let navigationKey = "";
let errorMessage = "";
let runtimeError = "";
let storageFailed = false;
let offline = false;
let connectionWanted = true;
let reconnectAt = 0;
let connectionError = "";
let settingsReady = false;
let hydratedSession = "";
const settingsKey = "virea.vrchat.connection.v1";
const settingIds = ["mode", "backend", "voice", "persona", "autonomy", "desktop-emotes", "audio", "avatar-id", "ai-profile", "send-port", "receive-port", "scale", "yaw", "chatbox", "observer-chatbox", "locomotion", "hold", "auto-bind"];
const liveSettingIds = new Set(["backend", "voice", "persona", "autonomy", "desktop-emotes"]);
let settingsSnapshotKey = "";
const drafts = new Map<string, string>();
const input = element<HTMLTextAreaElement>("message");
const scroller = element("chat-scroll");
const dialog = element<HTMLDialogElement>("settings-dialog");

function save() {
  try { localStorage.setItem(storageKey, JSON.stringify({version: 1, items: conversations.slice(0, 50)})); }
  catch { if (!storageFailed) { storageFailed = true; error("浏览器无法保存记录；当前任务可以继续，请及时复制需要保留的内容。"); } }
}
function error(message: string) {
  errorMessage = message;
  element("error-text").textContent = message;
  element("error").hidden = !message;
  element("settings-error").textContent = message;
  element("settings-error").hidden = !message;
  element<HTMLButtonElement>("retry").hidden = !retryText && !active.messages.some(turn => turn.role === "user");
}
async function api(path: string, body?: unknown): Promise<any> {
  const response = await fetch(`/api/v1/vrchat${path}`, {signal: AbortSignal.timeout(20000), ...(body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) {
    let detail = typeof data.detail === "string" ? data.detail : Array.isArray(data.detail) ? data.detail.map((item: any) => item.msg).join("；") : "请求未完成，请稍后重试。";
    if (detail.includes("9000/9001 are reserved")) detail = "9000/9001 是观察端端口。请使用 AI 专用端口，默认 19010/19011。";
    throw new Error(detail);
  }
  return data;
}
function ownSession() { return state.connected && active.sessionId === state.session?.id; }
function working() { return ownSession() && (["thinking", "generating", "awaiting_playback"].includes(state.session?.status) || state.autonomy?.active); }
function showSettings(diagnostics = false) {
  element("configuration-panel").hidden = diagnostics;
  element("diagnostics-panel").hidden = !diagnostics;
  element("configuration-tab").setAttribute("aria-selected", String(!diagnostics));
  element("diagnostics-tab").setAttribute("aria-selected", String(diagnostics));
  if (!dialog.open) dialog.showModal();
}
function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  element("character-count").textContent = input.value.length > 3500 ? `${input.value.length}/4000` : "";
  element<HTMLButtonElement>("send").disabled = busy || !input.value.trim();
}
function selectConversation(item: Conversation) {
  drafts.set(active.id, input.value); active = item;
  input.value = drafts.get(item.id) ?? "";
  messagesKey = ""; render(state); resizeInput();
  if (innerWidth < 900) document.body.classList.remove("sidebar-open");
  input.focus();
}
function renderNavigation() {
  const query = value("search").toLowerCase();
  const list = conversations.filter(item => `${item.title} ${item.messages.map(t => t.content).join(" ")}`.toLowerCase().includes(query)).sort((a, b) => b.updatedAt - a.updatedAt);
  const key = JSON.stringify([list.map(item => [item.id, item.title]), active.id, state.session?.id]);
  if (key === navigationKey) return; navigationKey = key;
  const nav = element("conversations"); nav.replaceChildren();
  for (const item of list.slice(0, 50)) {
    const button = document.createElement("button"); button.className = "conversation";
    button.textContent = item.title; button.title = item.title;
    button.setAttribute("aria-current", item.id === active.id ? "page" : "false");
    if (item.sessionId && item.sessionId === state.session?.id) button.classList.add("live-conversation");
    button.addEventListener("click", () => selectConversation(item)); nav.append(button);
  }
  if (!list.length) { const note = document.createElement("p"); note.className = "note"; note.textContent = "没有找到相关对话"; nav.append(note); }
}
function renderMessages() {
  const draft = ownSession() && state.session?.status !== "waiting" ? state.session?.draft_text ?? "" : "";
  const last = active.messages.at(-1);
  const visibleDraft = draft && !(last?.role === "assistant" && last.content === draft) ? draft : "";
  const key = JSON.stringify([active.id, active.messages, sendingText, visibleDraft]);
  if (messagesKey === key) return; messagesKey = key;
  const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
  const list = element("messages"); list.replaceChildren();
  const turns = [...active.messages, ...(sendingText ? [{role: "user", content: sendingText}] : []), ...(visibleDraft ? [{role: "assistant", content: visibleDraft}] : [])];
  element("welcome").hidden = turns.length > 0;
  for (const turn of turns) {
    const article = document.createElement("article"); article.className = `message ${turn.role}`;
    const label = document.createElement("span"); label.className = "message-author"; label.textContent = turn.role === "user" ? "你" : "Virea";
    const content = document.createElement("div"); content.className = "message-content"; content.textContent = turn.content;
    const actions = document.createElement("div"); actions.className = "message-actions";
    const copy = document.createElement("button"); copy.textContent = "复制"; copy.setAttribute("aria-label", "复制这条消息");
    copy.addEventListener("click", () => { void navigator.clipboard.writeText(turn.content).then(() => { copy.textContent = "已复制"; }).catch(() => error("复制失败，请选择消息文本后手动复制。")); }); actions.append(copy);
    if (turn.role === "user") { const edit = document.createElement("button"); edit.textContent = "编辑后重发"; edit.addEventListener("click", () => { input.value = turn.content; resizeInput(); input.focus(); }); actions.append(edit); }
    article.append(label, content, actions); list.append(article);
  }
  if (nearBottom || sendingText) requestAnimationFrame(() => { scroller.scrollTop = scroller.scrollHeight; });
}
function renderTimeline() {
  const timeline = element("timeline"); timeline.replaceChildren();
  const performance = ownSession() ? state.session?.pending?.performance : null;
  if (!performance) return;
  for (const [name, clips] of [["动作", performance.motions], ["语音", performance.speech]] as const) {
    const row = document.createElement("div"); row.className = "track"; row.setAttribute("aria-label", `${name}时间轴`);
    const label = document.createElement("span"); label.textContent = name;
    const rail = document.createElement("div"); rail.className = "rail";
    for (const clip of clips ?? []) {
      const bar = document.createElement("span"); bar.className = name === "动作" ? "motion" : "speech";
      bar.style.left = `${clip.start_seconds / performance.duration_seconds * 100}%`; bar.style.width = `${clip.duration_seconds / performance.duration_seconds * 100}%`;
      bar.title = `${clip.label ?? clip.prompt ?? clip.text} · ${clip.start_seconds.toFixed(1)}–${(clip.start_seconds + clip.duration_seconds).toFixed(1)}s`; rail.append(bar);
    }
    const cursor = document.createElement("i"); cursor.style.left = `${Math.min(100, state.elapsed_seconds / performance.duration_seconds * 100)}%`; rail.append(cursor);
    row.append(label, rail); timeline.append(row);
  }
}
function render(next: any) {
  state = next;
  liveViews.setCalibration(state.calibration ?? null, offline);
  liveViews.setRooms(state.rooms ?? null, offline);
  if (state.session) {
    let owner = conversations.find(item => item.sessionId === state.session.id);
    if (!owner) { owner = createConversation(); owner.sessionId = state.session.id; active = owner; }
    const merged = mergeTranscript(owner.messages, state.session.history ?? []);
    if (JSON.stringify(merged) !== JSON.stringify(owner.messages)) {
      owner.messages = merged; owner.title = merged.find(turn => turn.role === "user")?.content.slice(0, 36) ?? "新的对话"; owner.updatedAt = Date.now(); save();
    }
  }
  const view = connectionView(state, offline);
  const connection = element("connection"); connection.classList.toggle("connected", view.ready); connection.querySelector("span")!.textContent = view.title;
  element("connection-title").textContent = view.title;
  element("connection-detail").textContent = view.detail;
  element("character-name").textContent = view.avatar;
  element<HTMLButtonElement>("reconnect").disabled = busy;
  const steps = element("connection-steps"); steps.replaceChildren();
  for (const [name, complete] of view.steps) { const item = document.createElement("span"); item.className = complete ? "complete" : "pending"; item.textContent = `${complete ? "✓" : "○"} ${name}`; steps.append(item); }
  const observedAvatar = state.feedback?.values?.avatar_id;
  element("avatar-binding").hidden = !state.connected || !observedAvatar;
  element("observed-avatar").textContent = observedAvatar ?? "";
  element<HTMLButtonElement>("bind-avatar").disabled = busy || working() || !observedAvatar || state.config?.avatar_id === observedAvatar;
  element("bind-avatar").textContent = state.config?.avatar_id === observedAvatar ? "已绑定此 AI 角色" : "绑定此 AI 角色";
  element<HTMLSelectElement>("model-choice").value = state.session?.motion_backend ?? value("backend");
  element<HTMLSelectElement>("model-choice").disabled = busy;
  element<HTMLFieldSetElement>("settings").disabled = busy;
  for (const id of settingIds) element<HTMLInputElement>(id).disabled = busy || (state.connected && !liveSettingIds.has(id));
  const desktopMode = value("mode") === "desktop";
  element<HTMLInputElement>("desktop-emotes").disabled = busy || !desktopMode;
  if (!desktopMode) element<HTMLInputElement>("desktop-emotes").checked = false;
  element("mode-note").textContent = value("mode") === "generated_vr" ? "模型每帧生成的头、手、手指和身体姿态进入 SteamVR / OSC；AI 客户端需要 VR 模式及 FBT 校准。观察者可继续使用桌面版。" : desktopMode ? "桌面兼容模式没有模型生成的全身姿态输出。" : "使用实体头手设备和模型身体追踪，需要 VRMode=1 及 FBT 校准。";
  element("connect").textContent = state.connected ? "保存对话设置" : "连接 VRChat 桥接";
  element("disconnect").hidden = !state.connected;
  element<HTMLButtonElement>("connect").disabled = busy; element<HTMLButtonElement>("disconnect").disabled = busy;
  element<HTMLButtonElement>("new-chat").disabled = busy;
  element<HTMLButtonElement>("pause").disabled = busy || !ownSession();
  element<HTMLButtonElement>("stop").disabled = busy || !ownSession();
  element("pause").hidden = !working() && !state.paused;
  element("stop").hidden = !working() && !state.paused;
  element("pause").textContent = state.paused ? "继续" : "暂停";
  element("session-state").textContent = statusLabel(state);
  element("execution-note").textContent = executionNote(state) + (state.observer_chat?.error ? ` 我的字幕暂未送达：${state.observer_chat.error}` : state.observer_chat?.pending ? " 我的字幕正在排队发送。" : "");
  const lastResult = ownSession() ? executionResult(state) : null;
  element("execution").hidden = !ownSession() || (!working() && !lastResult && !state.paused);
  element("execution").classList.toggle("idle", !working());
  element("elapsed").textContent = working() ? `${(state.elapsed_seconds ?? 0).toFixed(1)} s` : lastResult?.motion_seconds != null ? `${lastResult.motion_seconds.toFixed(1)} s` : "";
  element("output-label").textContent = `${(state.config?.mode ?? value("mode")) === "desktop" ? "桌面模式" : "VR 追踪"} · ${(state.config?.audio_enabled ?? !!value("audio")) ? "语音开启" : "语音关闭"}`;
  element("context-note").textContent = state.connected && !ownSession() ? "继续此对话将结束当前正在连接的会话。" : working() ? "发送新消息会中断当前任务，按你的新要求继续。" : !state.connected ? "发送后自动连接。首次使用请先配置声音和 VRChat。" : !state.ready ? view.title : "";
  const feedback = element("feedback"); feedback.replaceChildren();
  for (const [key, item] of Object.entries(state.feedback?.values ?? {})) { const term = document.createElement("dt"), description = document.createElement("dd"); term.textContent = key; description.textContent = String(item); feedback.append(term, description); }
  const age = state.feedback?.last_received_seconds_ago;
  element("receiver").textContent = !state.connected ? "桥接已断开。" : state.waiting_for || (age == null ? "尚未收到回传。" : `最近回传：${age.toFixed(1)} 秒前。`);
  element("frames").textContent = String(state.frames_sent ?? 0);
  element("results").textContent = JSON.stringify(state.recent_performances ?? [], null, 2);
  const issue = bridgeError(state);
  if (issue !== runtimeError) { const previous = runtimeError; runtimeError = issue; if (issue || errorMessage === previous) error(issue); }
  renderNavigation(); renderMessages(); renderTimeline(); resizeInput();
}
async function action(work: () => Promise<any>) {
  if (busy) return; busy = true; error(""); render(state);
  try { render(await work()); } catch (e) { error(e instanceof Error ? e.message : String(e)); }
  finally { busy = false; sendingText = ""; render(state); }
}
function connectBody() {
  const generated = value("mode") === "generated_vr";
  return {motion_backend: value("backend"), autonomous_decisions: Number(value("autonomy")), voice: value("voice") || null, persona: value("persona") || null, history: active.messages.slice(-24), config: {mode: value("mode"), send_port: Number(value("send-port")), receive_port: Number(value("receive-port")), audio_enabled: !!value("audio"), audio_device: value("audio") || null, microphone: checked("hold") ? "hold" : "manual", chatbox: checked("chatbox"), observer_chatbox: checked("observer-chatbox"), locomotion: !generated && checked("locomotion"), desktop_emotes: !generated && checked("desktop-emotes"), auto_bind: checked("auto-bind"), avatar_id: checked("auto-bind") ? null : value("avatar-id") || null, scale: Number(value("scale")), yaw_degrees: generated ? 0 : Number(value("yaw")), ...(generated ? {tracker_bones: ["hips", "leftFoot", "rightFoot", "chest", "leftLowerLeg", "rightLowerLeg", "leftLowerArm", "rightLowerArm"]} : {})}};
}
function hydrateSessionSettings(snapshot: any, force = false) {
  if (!snapshot.connected || !settingsReady) return;
  const settings = snapshot.settings ?? {motion_backend: snapshot.session.motion_backend, voice: snapshot.session.voice, persona: snapshot.session.persona, autonomous_decisions: 3, desktop_emotes: snapshot.config.desktop_emotes};
  const key = JSON.stringify([snapshot.session.id, settings]);
  if (!force && key === settingsSnapshotKey) return;
  settingsSnapshotKey = key;
  for (const [id, name] of [["backend", "motion_backend"], ["voice", "voice"], ["persona", "persona"], ["autonomy", "autonomous_decisions"]]) element<HTMLInputElement>(id!).value = String(settings[name!] ?? "");
  element<HTMLInputElement>("desktop-emotes").checked = !!settings.desktop_emotes;
  persistConnection();
}
async function applySessionSettings() {
  if (!state.connected) { persistConnection(); return state; }
  try {
    const next = await api("/settings", {motion_backend: value("backend"), voice: value("voice") || null, persona: value("persona") || null, autonomous_decisions: Number(value("autonomy")), desktop_emotes: checked("desktop-emotes")});
    hydrateSessionSettings(next, true);
    return next;
  } catch (error) {
    hydrateSessionSettings(state, true);
    throw error;
  }
}
function persistConnection() {
  const fields: Record<string, string | boolean> = {};
  for (const id of settingIds) { const node = element<HTMLInputElement>(id); fields[id] = node.type === "checkbox" ? node.checked : node.value; }
  try { localStorage.setItem(settingsKey, JSON.stringify({version: 1, fields, wanted: connectionWanted})); } catch { /* Conversation storage reports persistence failures. */ }
}
function restoreConnection() {
  let saved;
  try { saved = readConnectionSettings(localStorage.getItem(settingsKey)); } catch { return; }
  if (!saved) return;
  connectionWanted = saved.wanted !== false;
  for (const id of settingIds) {
    const node = element<HTMLInputElement>(id), stored = saved.fields[id];
    if (node.type === "checkbox" && typeof stored === "boolean") node.checked = stored;
    else if (typeof stored === "string") node.value = stored;
  }
}
function hydrateConnection(snapshot: any) {
  hydrateSessionSettings(snapshot);
  if (!settingsReady || !snapshot.connected || hydratedSession === snapshot.session.id) return;
  hydratedSession = snapshot.session.id;
  for (const [id, key] of [["mode", "mode"], ["send-port", "send_port"], ["receive-port", "receive_port"], ["audio", "audio_device"], ["avatar-id", "avatar_id"], ["scale", "scale"], ["yaw", "yaw_degrees"]]) element<HTMLInputElement>(id!).value = String(snapshot.config[key!] ?? "");
  for (const id of ["chatbox", "locomotion"]) element<HTMLInputElement>(id).checked = !!snapshot.config[id];
  element<HTMLInputElement>("observer-chatbox").checked = !!snapshot.config.observer_chatbox;
  element<HTMLInputElement>("hold").checked = snapshot.config.microphone === "hold";
  element<HTMLInputElement>("backend").value = snapshot.session.motion_backend;
  element<HTMLInputElement>("voice").value = snapshot.session.voice ?? "";
  persistConnection();
}
let disposeAvatar: (() => void) | undefined;
async function loadAvatarPreview() {
  element("reload-avatar").hidden = true;
  try {
    disposeAvatar?.(); disposeAvatar = undefined;
    const {avatarPreview} = await import("./vrchat-avatar");
    disposeAvatar = await avatarPreview(element<HTMLCanvasElement>("avatar-canvas"));
    element("avatar-preview-note").textContent = "导入模型预览 · 可拖动旋转 · 非 VRChat 游戏画面";
  } catch {
    element("avatar-preview-note").textContent = "模型预览未加载。请运行完整启动脚本准备模型；VRChat 连接不受影响。";
    element("reload-avatar").hidden = false;
  }
}
element("reload-avatar").addEventListener("click", () => void loadAvatarPreview());
window.addEventListener("pagehide", () => disposeAvatar?.(), {once: true});
async function connectCurrent() {
  connectionWanted = true;
  persistConnection();
  if (state.connected && !ownSession()) { state = await api("/control", {action: "disconnect"}); }
  if (!state.connected) { const connected = await api("/connect", connectBody()); active.sessionId = connected.session.id; save(); state = connected; }
  return state;
}
async function submitMessage(text = input.value.trim()) {
  if (!text || busy) return;
  retryText = text; sendingText = text;
  await action(async () => {
    await connectCurrent();
    const response = await api("/messages", {text});
    sendingText = "";
    if (input.value.trim() === text) { input.value = ""; drafts.delete(active.id); }
    return response;
  });
  input.focus();
}
async function newConversation() {
  await action(async () => {
    if (state.connected) state = await api("/control", {action: "disconnect"});
    active = createConversation(); input.value = ""; retryText = ""; messagesKey = ""; save(); return state;
  }); input.focus();
}
element("message-form").addEventListener("submit", event => { event.preventDefault(); void submitMessage(); });
input.addEventListener("input", () => { drafts.set(active.id, input.value); resizeInput(); });
input.addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); void submitMessage(); } });
element("search").addEventListener("input", renderNavigation);
element("new-chat").addEventListener("click", () => void newConversation());
for (const node of document.querySelectorAll<HTMLButtonElement>("[data-prompt]")) node.addEventListener("click", () => { input.value = node.dataset.prompt!; resizeInput(); input.focus(); });
for (const id of ["open-settings", "quick-settings"]) element(id).addEventListener("click", () => showSettings());
for (const id of ["show-diagnostics", "connection", "diagnostics-tab"]) element(id).addEventListener("click", () => showSettings(true));
element("configuration-tab").addEventListener("click", () => showSettings());
element("close-settings").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", event => { if (event.target === dialog) { const box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close(); } });
element("toggle-sidebar").addEventListener("click", () => { const narrow = innerWidth < 900; document.body.classList.toggle(narrow ? "sidebar-open" : "sidebar-closed"); element("toggle-sidebar").setAttribute("aria-expanded", String(narrow ? document.body.classList.contains("sidebar-open") : !document.body.classList.contains("sidebar-closed"))); });
element("connect-form").addEventListener("submit", event => { event.preventDefault(); void action(state.connected ? applySessionSettings : connectCurrent); });
element("connection-settings").addEventListener("click", () => showSettings());
element("reconnect").addEventListener("click", () => void action(async () => {
  state = await api("");
  if (state.connected) state = await api("/control", {action: "disconnect"});
  hydratedSession = "";
  return connectCurrent();
}));
for (const id of settingIds) element(id).addEventListener("change", persistConnection);
element("bind-avatar").addEventListener("click", () => void action(async () => { const next = await api("/bind-avatar", {avatar_id: state.feedback.values.avatar_id}); element<HTMLInputElement>("avatar-id").value = next.config.avatar_id; return next; }));
element("copy-launch").addEventListener("click", async () => { try { await navigator.clipboard.writeText(`${value("mode") === "desktop" ? "--no-vr " : ""}--profile=${value("ai-profile")} --osc=${value("send-port")}:127.0.0.1:${value("receive-port")} --watch-avatars --watch-worlds -screen-fullscreen 0`); element("copy-launch").textContent = "已复制参数，请用于官方 launch.exe"; } catch { error("无法访问剪贴板，请从启动脚本启动 AI 客户端。"); } });
for (const [id, command] of [["disconnect", "disconnect"], ["stop", "interrupt"], ["pause", "pause"]]) element(id!).addEventListener("click", () => void action(() => { if (command === "disconnect") { connectionWanted = false; persistConnection(); } return api("/control", {action: command === "pause" && state.paused ? "resume" : command}); }));
element("mode").addEventListener("change", () => render(state));
element("audio").addEventListener("change", () => render(state));
element("backend").addEventListener("change", () => render(state));
element("model-choice").addEventListener("change", () => {
  element<HTMLSelectElement>("backend").value = value("model-choice");
  void action(applySessionSettings);
});
element("dismiss-error").addEventListener("click", () => error(""));
element("retry").addEventListener("click", () => void submitMessage(retryText || [...active.messages].reverse().find(turn => turn.role === "user")?.content));
scroller.addEventListener("scroll", () => { element("scroll-bottom").hidden = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 200; });
element("scroll-bottom").addEventListener("click", () => scroller.scrollTo({top: scroller.scrollHeight, behavior: "smooth"}));
document.addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "o") { event.preventDefault(); void newConversation(); } });

async function initialize() {
  restoreConnection();
  render(state);
  void poll();
  void loadAvatarPreview();
  const [devices, voices] = await Promise.allSettled([api("/audio-devices"), fetch("/api/v1/characters/preferences", {signal: AbortSignal.timeout(10000)}).then(r => r.json())]);
  if (devices.status === "fulfilled") {
    for (const device of devices.value.devices ?? []) { const option = document.createElement("option"); option.value = device.id; option.textContent = `${device.name} · ${device.host}`; element("audio").append(option); }
    if (!devices.value.available) error(devices.value.error);
  }
  if (voices.status === "fulfilled") for (const voice of voices.value.voices ?? []) { const option = document.createElement("option"); option.value = voice.id; option.textContent = voice.name ?? voice.id; element("voice").append(option); }
  restoreConnection();
  settingsReady = true;
  hydrateConnection(state);
  render(state);
}
async function poll() {
  try {
    if (!busy) {
      const snapshot = await api("");
      if (!acceptSnapshot(state, snapshot, busy)) return;
      offline = false;
      if (connectionError && errorMessage === connectionError) error("");
      connectionError = "";
      hydrateConnection(snapshot);
      render(snapshot);
      if (settingsReady && !state.connected && connectionWanted && Date.now() >= reconnectAt) {
        reconnectAt = Date.now() + 10000;
        await action(connectCurrent);
      }
    }
  } catch (e) {
    offline = true;
    connectionError = "控制服务暂时不可用，正在自动重试。请确认完整进程已启动。";
    error(connectionError); render(state);
  } finally { window.setTimeout(poll, offline ? 2000 : 1000); }
}
const liveViews = mountViews(root);
mountClientLaunchers(root);
void initialize();
