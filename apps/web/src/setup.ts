import "./setup.css";

type Preset = {name: string; kind: string; base_url: string; model: string; voice?: string; local?: boolean};
type Connection = {id: string; provider: string; kind: string; base_url: string; model: string; voice: string; has_key: boolean; structured?: string; api_key_env?: string; pending_changes?: boolean};
type Job = {id: string; status: string; message: string; step: number; total_steps: number; percent: number; stage_percent: number | null; downloaded_bytes?: number; total_bytes?: number; request: Record<string, unknown>};
type Snapshot = {providers: Record<string, Preset>; connections: Connection[]; active: Record<string,string>; jobs: Job[]; services?: {recipe:string;owned_running:boolean;auto_start:boolean}[]; recipes: {id: string; name: string; license_url: string; storage_gib: number}[]};
const root = document.querySelector<HTMLElement>("#setup")!;
const esc = (value: unknown) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]!));
const el = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
let snapshot: Snapshot = {providers: {}, connections: [], active: {}, jobs: [], recipes: []};
let polling: ReturnType<typeof setTimeout> | undefined;
let kind = "language";

root.innerHTML = `<aside><a class="wordmark" href="./">VIREA<span> / setup</span></a><p>从这里开始</p><nav><a href="#device">01 <span>检测设备</span></a><a href="#connections">02 <span>接入模型</span></a><a href="#local">03 <span>部署本地模型</span></a><a href="#finish">04 <span>开始使用</span></a></nav><div class="aside-bottom">配置保存在本机<br>语音检查不会播放声音</div></aside>
<main><header><span class="eyebrow">YOUR OWN AI WORKSPACE</span><h1>准备好，让角色动起来。</h1><p>选择你熟悉的模型服务，或交给 VIREA 部署本地模型。每一步都能看到进度。</p></header>
<div id="notice" role="status" aria-live="polite" hidden></div>
<section id="device"><div class="section-heading"><div><span class="number">01</span><h2>你的设备</h2></div><button id="detect">重新检测</button></div><div id="machine" class="card muted">正在检测设备及已启动的本地模型…</div><div id="discovered" class="discovered"></div></section>
<section id="connections"><div class="section-heading"><div><span class="number">02</span><h2>接入语言和语音模型</h2></div></div><p class="hint">语言负责理解和回复，语音负责合成声音，可以分别选择不同服务。</p>
<div class="tabs" role="tablist"><button id="language-tab" role="tab" aria-selected="true">语言模型</button><button id="speech-tab" role="tab" aria-selected="false">语音模型</button></div>
<form id="connection-form" class="card"><div class="form-grid"><label>服务提供方<select id="provider"></select></label><label>连接名称<input id="connection-id" required maxlength="64" pattern="[a-zA-Z0-9][a-zA-Z0-9_-]*" /></label><label class="wide">API Key <span class="hint">本地服务通常留空；已保存时留空表示保留</span><input id="api-key" type="password" autocomplete="off" placeholder="只保存在本机服务端" /></label><label>模型 ID<input id="model" list="model-options" required placeholder="先读取模型列表，或填写控制台的模型 ID" /><datalist id="model-options"></datalist></label><label id="voice-field" hidden>声线 ID<input id="voice" placeholder="如 alloy、Cherry 或已导入的声线" /></label></div>
<details><summary>高级设置</summary><div class="form-grid"><label class="wide">API 基础地址<input id="base-url" type="url" required /></label><label>结构化输出<select id="structured"><option value="auto">由供应商预设决定</option><option value="json_object">JSON Object（兼容性优先）</option><option value="json_schema">JSON Schema</option></select></label><label>密钥环境变量（可选）<input id="key-env" placeholder="例如 OPENAI_API_KEY" /></label></div></details>
<div class="actions"><button type="submit" class="primary">保存连接</button><button type="button" id="fetch-models">读取模型列表</button><span id="form-status" class="hint"></span></div></form><div id="saved-connections"></div><p class="hint">“测试并启用”会发送一条短测试请求，云服务可能计费。语音测试只检查音频，不外放。不同地区的百炼密钥与地址需对应。</p></section>
<section id="local"><div class="section-heading"><div><span class="number">03</span><h2>部署本地模型</h2></div></div><p class="hint">先检测再安装。已有服务会直接复用，模型在独立环境中运行。动作使用真实模型推理。</p><form id="deploy-form" class="card"><div class="form-grid"><label>要部署的模型<select id="recipe"></select></label><label>计算设备<select id="device-choice"><option value="auto">自动选择</option><option value="cpu">CPU（更慢，无需独立显卡）</option><option value="cuda">NVIDIA GPU（至少 12 GiB 显存）</option></select></label><label id="ollama-model-field">本地语言模型<input id="ollama-model" value="qwen3:4b" list="local-model-options" /><datalist id="local-model-options"><option>qwen3:4b</option><option>qwen3:8b</option><option>qwen3:1.7b</option></datalist></label></div><p id="recipe-detail" class="hint"></p><label class="check"><input type="checkbox" id="license" /><span>我已阅读所选模型及依赖的<a id="license-link" target="_blank" rel="noreferrer">使用条款</a>，同意下载并在本机安装。</span></label><div class="actions"><button type="submit" class="primary" id="deploy-button">检测并部署</button><span class="hint">可取消、可重试 · 不自动播放声音</span></div></form><div id="jobs" aria-live="polite"></div></section>
<section id="finish" class="finish"><div><span class="number">04</span><h2>开始创作</h2><p>接入语言、语音及动作模型后，打开工作室。已有配置可以随时回来切换。</p></div><div class="actions"><a class="primary button" href="./character.html">进入 Motion Studio ↗</a><a class="button" href="./vrchat.html">打开 VRChat ↗</a></div><p id="platform-note" class="hint"></p></section>
</main>`;

function notify(message: string, error = false) {
  el("notice").hidden = false; el("notice").textContent = message; el("notice").className = error ? "error" : "success";
}
async function api(path = "", method = "GET", body?: unknown) {
  const response = await fetch(`/api/v1/onboarding${path}`, {method, headers: {"X-Virea-Setup":"1", "Content-Type":"application/json"}, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(150_000)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `请求失败 (${response.status})`);
  return data;
}
async function action(work: () => Promise<void>) { try { await work(); } catch (error) { notify(error instanceof Error ? error.message : String(error), true); } }
const value = (id: string) => el<HTMLInputElement>(id).value.trim();

function changeProvider() {
  const id = value("provider"), preset = snapshot.providers[id]!;
  if (!preset) return;
  el<HTMLInputElement>("connection-id").value = id;
  el<HTMLInputElement>("base-url").value = preset.base_url;
  el<HTMLInputElement>("model").value = preset.model;
  el<HTMLInputElement>("voice").value = preset.voice ?? "";
  el<HTMLInputElement>("api-key").value = "";
  el<HTMLInputElement>("key-env").value = "";
  el<HTMLSelectElement>("structured").value = "auto";
  el("voice-field").hidden = kind !== "speech";
  el("fetch-models").textContent = kind === "language" ? "读取模型列表" : "读取声线列表";
  el<HTMLDetailsElement>("connection-form").querySelector("details")!.open = !preset.base_url || id === "azure-speech";
  el("form-status").textContent = "";
  el("model-options").innerHTML = "";
  el("voice-options").innerHTML = "";
}
function chooseKind(next: string) {
  kind = next;
  for (const name of ["language", "speech"]) el(`${name}-tab`).setAttribute("aria-selected", String(name === kind));
  el("provider").innerHTML = Object.entries(snapshot.providers).filter(([,p]) => p.kind === kind).map(([id,p]) => `<option value="${esc(id)}">${esc(p.name)}</option>`).join("");
  changeProvider();
}
function connectionBody(forModels = false) {
  const key = value("api-key");
  return {id:value("connection-id"), provider:value("provider"), base_url:value("base-url"), model:value("model") || (forModels ? "select-a-model" : ""), voice:value("voice"), structured:value("structured"), api_key_env:value("key-env"), ...(key ? {api_key:key} : {})};
}
async function save(forModels = false) {
  const result = await api("/connections", "PUT", connectionBody(forModels));
  el<HTMLInputElement>("api-key").value = "";
  Object.assign(snapshot, result); renderConnections();
  el("form-status").textContent = "已保存到本机";
}
function renderConnections() {
  el("saved-connections").innerHTML = snapshot.connections.map(c => `<article class="saved card"><div><strong>${esc(c.id)} ${snapshot.active[c.kind] === c.id ? `<span class="badge">${c.pending_changes ? '更改待启用' : '使用中'}</span>` : ""}</strong><p>${esc(snapshot.providers[c.provider]!.name)} · ${esc(c.model)}</p><small>${c.has_key ? "密钥已保存" : "无密钥"}</small></div><div class="actions"><button data-edit="${esc(c.id)}">编辑</button><button data-activate="${esc(c.id)}">测试并启用</button><button data-remove="${esc(c.id)}" aria-label="删除连接 ${esc(c.id)}">删除</button></div></article>`).join("") || '<p class="hint">还没有添加连接。下方也可以一键部署本地模型。</p>';
}
function recipeChanged() {
  const recipe = snapshot.recipes.find(r => r.id === value("recipe"))!;
  el("ollama-model-field").hidden = recipe.id !== "ollama";
  el<HTMLSelectElement>("device-choice").disabled = !["motioncraft","syntalker"].includes(recipe.id);
  el("recipe-detail").textContent = `建议至少预留 ${recipe.storage_gib} GiB 可用空间。CPU 运行大模型可能较慢，启动阶段会显示真实等待状态。`;
  el<HTMLAnchorElement>("license-link").href = recipe.license_url;
  el<HTMLInputElement>("license").checked = false;
}
function renderJobs() {
  el("services").innerHTML = (snapshot.services ?? []).map(s => `<article class="card saved"><div><strong>${esc(s.recipe)}</strong><p>下次启动自动恢复 · ${s.owned_running ? '由 VIREA 运行' : '复用外部服务或等待恢复'}</p></div><button data-stop="${esc(s.recipe)}">停止与关闭自动启动</button></article>`).join("");
  el("jobs").innerHTML = snapshot.jobs.slice().reverse().slice(0,6).map(j => `<article class="card job"><div class="section-heading"><strong>${esc(j.request.recipe)} <span class="badge">${esc(({running:"部署中",queued:"排队中",succeeded:"已就绪",failed:"失败",cancelled:"已取消",interrupted:"已中断"} as Record<string,string>)[j.status] ?? j.status)}</span></strong><span>${j.percent}% · [${j.step}/${j.total_steps}]</span></div><progress max="100" value="${j.percent}" aria-label="${esc(j.request.recipe)} 整体部署进度"></progress><p>${esc(j.message)}</p>${j.status === "running" ? `<progress class="stage-progress" max="100" ${j.stage_percent === null ? "" : `value="${j.stage_percent}"`} aria-label="当前步骤进度"></progress><small>${j.stage_percent === null ? "当前步骤处理中，等待实际进度" : `当前步骤 ${j.stage_percent}%`}${j.total_bytes ? ` · ${(Number(j.downloaded_bytes)/1048576).toFixed(1)} / ${(j.total_bytes/1048576).toFixed(1)} MiB` : ""}</small>` : ""}<div class="actions">${["queued","running"].includes(j.status) ? `<button data-cancel="${j.id}">取消部署</button>` : ["failed","interrupted","cancelled"].includes(j.status) ? `<button data-retry="${j.id}">重试（复用缓存）</button>` : ""}</div></article>`).join("");
  el<HTMLButtonElement>("deploy-button").disabled = snapshot.jobs.some(j => ["queued","running"].includes(j.status));
}
async function refreshJobs() {
  let delay = 1000;
  try {
    const updated = await api() as Snapshot;
    snapshot.jobs = updated.jobs; snapshot.active = updated.active; snapshot.connections = updated.connections; snapshot.services = updated.services;
    renderJobs(); renderConnections();
  } catch {
    delay = 3000; notify("暂时无法读取部署进度，正在自动重连；后台任务继续执行。", true);
  } finally {
    if (snapshot.jobs.some(j => ["queued","running"].includes(j.status))) polling = setTimeout(() => void refreshJobs(), delay);
  }
}
async function detect() {
  el("machine").textContent = "正在检测，通常几秒内完成…";
  const report = await api("/discover", "POST");
  el("machine").innerHTML = `<div class="machine-facts"><strong>${esc(report.platform)} <small>${esc(report.architecture)}</small></strong><strong>${esc(report.free_disk_gib)} GiB <small>可用空间</small></strong><strong>${report.services.length} <small>已发现本地服务</small></strong></div><p class="path">运行数据：${esc(report.data_directory)}</p>`;
  el("platform-note").textContent = report.vrchat_supported ? "VRChat 双客户端和虚拟 VR 驱动仅适用于 Windows；工作室与模型接入独立运行。" : "本机可使用 Motion Studio 和模型接口；VRChat 双客户端及虚拟 VR 驱动需要 Windows。";
  el("discovered").innerHTML = report.services.map((s: any, i: number) => `<article class="card saved"><div><strong>${esc(s.provider)} <span class="badge">已发现</span></strong><p>${esc(s.base_url)}</p><small>${esc((s.models ?? []).join(" · "))}</small></div>${s.kind !== "motion" ? `<button data-discovery="${i}">使用此服务</button>` : '<span class="hint">部署时自动复用</span>'}</article>`).join("");
  el("discovered").querySelectorAll<HTMLButtonElement>("[data-discovery]").forEach(button => button.onclick = () => {
    const s = report.services[Number(button.dataset.discovery)]; chooseKind(s.kind);
    el<HTMLSelectElement>("provider").value = s.provider; changeProvider();
    el<HTMLInputElement>("base-url").value = s.base_url;
    el<HTMLInputElement>("model").value = s.models?.[0] ?? (s.kind === "speech" ? s.model : "");
    el<HTMLInputElement>("voice").value = s.voices?.[0]?.id ?? "";
    el("connections").scrollIntoView({behavior:"smooth"});
  });
}

el("provider").onchange = changeProvider;
el("recipe").onchange = recipeChanged;
el("language-tab").onclick = () => chooseKind("language");
el("speech-tab").onclick = () => chooseKind("speech");
el("detect").onclick = () => void action(detect);
el("connection-form").onsubmit = e => {e.preventDefault(); void action(() => save());};
el("fetch-models").onclick = () => void action(async () => {
  await save(true); el("form-status").textContent = "正在读取列表…";
  const speech = kind === "speech";
  const result = await api(`/connections/${encodeURIComponent(value("connection-id"))}/${speech ? 'voices' : 'models'}`);
  const options = speech ? result.voices.map((v: {id: string; name: string}) => `<option value="${esc(v.id)}">${esc(v.name)}</option>`) : result.models.map((m: string) => `<option value="${esc(m)}"></option>`);
  el(speech ? "voice-options" : "model-options").innerHTML = options.join("");
  if (!speech && result.models.length) el<HTMLInputElement>("model").value = result.models[0];
  el("form-status").textContent = `已发现 ${options.length} 个${speech ? '声线' : '模型'}；选好后保存`;
});
el("saved-connections").onclick = e => void action(async () => {
  const target = (e.target as HTMLElement).closest<HTMLButtonElement>("button"); if (!target) return;
  const id = target.dataset.activate || target.dataset.remove || target.dataset.edit;
  if (target.dataset.edit) {
    const c = snapshot.connections.find(c => c.id === id)!; chooseKind(c.kind);
    el<HTMLSelectElement>("provider").value = c.provider; changeProvider();
    for (const [field,val] of Object.entries({"connection-id":c.id,"base-url":c.base_url,model:c.model,voice:c.voice})) el<HTMLInputElement>(field).value = val;
    el<HTMLSelectElement>("structured").value = c.structured || "auto";
    el<HTMLInputElement>("key-env").value = c.api_key_env || "";
    return;
  }
  target.disabled = true;
  try {
    notify(target.dataset.remove ? "正在删除连接…" : "正在测试接口；语音保持静音…");
    Object.assign(snapshot, await api(`/connections/${encodeURIComponent(id!)}` + (target.dataset.activate ? "/activate" : ""), target.dataset.activate ? "POST" : "DELETE"));
    renderConnections(); notify(target.dataset.activate ? "测试通过，后续请求使用此连接。" : "连接已删除。");
  } finally { target.disabled = false; }
});
el("deploy-form").onsubmit = e => {e.preventDefault(); void action(async () => {
  const body = {recipe:value("recipe"),model:value("ollama-model"),device:value("device-choice"),accepted_license:el<HTMLInputElement>("license").checked};
  if (!body.accepted_license) throw new Error("请先阅读并勾选模型使用条款。");
  await api("/deployments","POST",body); if (polling) clearTimeout(polling); await refreshJobs();
});};
el("jobs").onclick = e => void action(async () => {
  const target = (e.target as HTMLElement).closest<HTMLButtonElement>("button"); if (!target) return;
  if (target.dataset.cancel) await api(`/deployments/${target.dataset.cancel}/cancel`,"POST");
  if (target.dataset.retry) await api("/deployments","POST",snapshot.jobs.find(j => j.id === target.dataset.retry)!.request);
  if (polling) clearTimeout(polling); await refreshJobs();
});
async function initialize() {
  root.querySelectorAll<HTMLButtonElement>("button").forEach(button => button.disabled = true);
  try {
  snapshot = await api(); chooseKind("language"); renderConnections();
  el("recipe").innerHTML = snapshot.recipes.map(r => `<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("");
  el<HTMLSelectElement>("recipe").value = "motioncraft"; recipeChanged(); renderJobs();
  if (snapshot.jobs.some(j => ["queued","running"].includes(j.status))) polling = setTimeout(() => void action(refreshJobs),1000);
  await detect();
  } catch {
    notify("无法连接本机服务。请确认启动器仍在运行，然后点击重新检测。", true);
  } finally {
    root.querySelectorAll<HTMLButtonElement>("button").forEach(button => button.disabled = false);
    renderJobs();
  }
}
el("detect").onclick = () => void action(Object.keys(snapshot.providers).length ? detect : initialize);
el<HTMLInputElement>("voice").setAttribute("list", "voice-options");
el("voice-field").insertAdjacentHTML("beforeend", '<datalist id="voice-options"></datalist>');
el("jobs").insertAdjacentHTML("afterend", '<div id="services"></div>');
el("services").onclick = e => void action(async () => {
  const button = (e.target as HTMLElement).closest<HTMLButtonElement>("[data-stop]");
  if (!button) return;
  const result = await api(`/services/${encodeURIComponent(button.dataset.stop!)}/stop`, "POST");
  notify(result.message); await refreshJobs();
});
void initialize();
