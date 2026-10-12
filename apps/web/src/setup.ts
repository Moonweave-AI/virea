import "./setup.css";
import {mountModelLibrary} from "./studio/model-library";
import {mountEnvironments} from "./studio/environments";
import {mountStudioChrome} from "./studio/chrome";
import {t, subscribe} from "./studio/preferences";
import {showHardware, showJobs, mountActivity, showVerification, clearPanel, type DeploymentJob} from "./studio/setup-panels";

type Preset = {name: string; kind: string; base_url: string; model: string; voice?: string; local?: boolean};
type Proof = {generated:boolean; kind?:string; model?:string; message?:string; verified_at?:string; elapsed_seconds?:number; bytes?:number; seconds?:number; frames?:number; fps?:number; dimensions?:number; result?:unknown; sample_text?:string; waveform?:number[]; artifact_url?:string; format?:string};
type Connection = {id: string; provider: string; kind: string; base_url: string; model: string; voice: string; has_key: boolean; structured?: string; api_key_env?: string; pending_changes?: boolean; verification?:Proof};
type Job = DeploymentJob;
type Snapshot = {providers: Record<string, Preset>; connections: Connection[]; active: Record<string,string>; jobs: Job[]; services?: {recipe:string;owned_running:boolean;auto_start:boolean}[]; recipes: {id: string; name: string; license_url: string; storage_gib: number}[]};
const root = document.querySelector<HTMLElement>("#setup")!;
const esc = (value: unknown) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]!));
const el = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
let snapshot: Snapshot = {providers: {}, connections: [], active: {}, jobs: [], recipes: []};
let polling: ReturnType<typeof setTimeout> | undefined;
let kind = "language";
let formRevision = 0;
let resolvedRevision = -1;
let resolution: Promise<void> | undefined;
type Choice = {id: string; name: string};

root.innerHTML = `<aside><a class="wordmark" href="./">VIREA<span> / setup</span></a><p>从这里开始</p><nav><a href="#device">01 <span>检测设备</span></a><a href="#connections">02 <span>接入模型</span></a><a href="#local">03 <span>部署本地模型</span></a><a href="#motion-models">04 <span>动作模型库</span></a><a href="#environments">05 <span>运行环境</span></a><a href="#finish">06 <span>开始使用</span></a></nav><div class="aside-bottom">配置保存在本机<br>语音检查不会播放声音</div></aside>
<main><header><span class="eyebrow">YOUR OWN AI WORKSPACE</span><h1>准备好，让角色动起来。</h1><p>选择你熟悉的模型服务，或交给 VIREA 部署本地模型。每一步都能看到进度。</p></header>
<div id="notice" role="status" aria-live="polite" hidden></div>
<section id="device"><div class="section-heading"><div><span class="number">01</span><h2>你的设备</h2></div><button id="detect">重新检测</button></div><div id="machine" class="card muted">正在检测设备及已启动的本地模型…</div><div id="discovered" class="discovered"></div></section>
<section id="connections"><div class="section-heading"><div><span class="number">02</span><h2>接入语言和语音模型</h2></div></div><p class="hint">语言负责理解和回复，语音负责合成声音，可以分别选择不同服务。</p>
<div class="tabs" role="tablist"><button id="language-tab" role="tab" aria-selected="true">语言模型</button><button id="speech-tab" role="tab" aria-selected="false">语音模型</button></div>
<form id="connection-form" class="card"><input id="connection-id" type="hidden" /><div class="form-grid"><label>服务提供方<select id="provider"></select></label><label id="region-field" hidden>Azure 资源地区<select id="region"><option value="eastus">美国东部</option><option value="westus">美国西部</option><option value="eastasia">东亚 · 香港</option><option value="southeastasia">东南亚 · 新加坡</option><option value="japaneast">日本东部</option><option value="koreacentral">韩国中部</option><option value="westeurope">西欧</option><option value="uksouth">英国南部</option><option value="australiaeast">澳大利亚东部</option><option value="centralindia">印度中部</option></select></label><label class="wide">API Key <span class="hint">云端只需粘贴密钥；本地服务无需填写</span><input id="api-key" type="password" autocomplete="off" placeholder="只保存在本机服务端" /></label><label>模型<select id="model"><option value="">检测后自动推荐，也可自行选择</option></select></label><label id="voice-field" hidden>声线<select id="voice"><option value="">自动读取可用声线</option></select></label></div>
<details><summary>高级设置</summary><div class="form-grid"><label class="wide">API 基础地址<input id="base-url" type="url" required /></label><label>结构化输出<select id="structured"><option value="auto">由供应商预设决定</option><option value="json_object">JSON Object（兼容性优先）</option><option value="json_schema">JSON Schema</option></select></label><label>密钥环境变量（可选）<input id="key-env" placeholder="例如 OPENAI_API_KEY" /></label></div></details>
<div class="actions"><button type="submit" id="connect-button" class="primary">自动检测并启用</button><button type="button" id="fetch-models">重新检测可选项</button><span id="form-status" class="hint" role="status"></span></div></form><div id="saved-connections"></div><p class="hint">自动读取模型和声线，优先推荐适用选项；不需要填写技术 ID。启用前会发送一条短测试请求，云服务可能计费。语音测试始终静音。</p></section>
<section id="local"><div class="section-heading"><div><span class="number">03</span><h2>部署本地模型</h2></div></div><p class="hint">先检测再安装。已有服务会直接复用，模型在独立环境中运行。动作使用真实模型推理。</p><form id="deploy-form" class="card"><div class="form-grid"><label>要部署的模型<select id="recipe"></select></label><label>计算设备<select id="device-choice"><option value="auto">自动选择</option><option value="cpu">CPU（更慢，无需独立显卡）</option><option value="gpu">GPU（自动检测加速后端）</option></select></label><label id="ollama-model-field">本地语言模型<select id="ollama-model"><option value="auto">按设备内存自动选择（推荐）</option></select></label></div><p id="recipe-detail" class="hint"></p><label class="check"><input type="checkbox" id="license" /><span>我已阅读所选模型及依赖的<a id="license-link" target="_blank" rel="noreferrer">使用条款</a>，同意下载并在本机安装。</span></label><div class="actions"><button type="submit" class="primary" id="deploy-button">检测并部署</button><span class="hint">可取消、可重试 · 不自动播放声音</span></div></form><div id="jobs" aria-live="polite"></div></section>
<section id="finish" class="finish"><div><span class="number">06</span><h2>开始创作</h2><p>接入语言、语音及动作模型后，打开工作室。已有配置可以随时回来切换。</p></div><div class="actions"><a class="button" href="./">打开 Motion Lab ↗</a><a class="primary button" href="./character.html">进入 Character Studio ↗</a><a class="button" href="./vrchat.html">打开 VRChat ↗</a></div><p id="platform-note" class="hint"></p></section>
</main>`;
mountStudioChrome("setup", root);
el("form-status").parentElement!.insertAdjacentHTML("afterend", '<div id="verification-progress" hidden></div>');
el("finish").insertAdjacentHTML("beforebegin", '<section id="activity"></section>');
mountActivity(el("activity"));
el("local").insertAdjacentHTML("afterend", '<section id="motion-models"></section>');
mountModelLibrary(el("motion-models"));
el("motion-models").insertAdjacentHTML("afterend", '<section id="environments"></section>');
mountEnvironments(el("environments"));

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
  formRevision++; resolvedRevision = -1; resolution = undefined;
  const id = value("provider"), preset = snapshot.providers[id]!;
  if (!preset) return;
  el<HTMLInputElement>("connection-id").value = id;
  el<HTMLInputElement>("base-url").value = preset.base_url;
  choices("model", [], ""); choices("voice", [], "");
  el<HTMLInputElement>("api-key").value = "";
  el<HTMLInputElement>("key-env").value = "";
  el<HTMLSelectElement>("structured").value = "auto";
  el("voice-field").hidden = kind !== "speech";
  el("region-field").hidden = id !== "azure-speech";
  el<HTMLSelectElement>("region").value = "eastus";
  el<HTMLDetailsElement>("connection-form").querySelector("details")!.open = !preset.base_url;
  el("form-status").textContent = "";
}
function chooseKind(next: string) {
  kind = next;
  for (const name of ["language", "speech"]) {
    el(`${name}-tab`).setAttribute("aria-selected", String(name === kind));
    el(`${name}-tab`).tabIndex = name === kind ? 0 : -1;
  }
  el("provider").innerHTML = Object.entries(snapshot.providers).filter(([,p]) => p.kind === kind).map(([id,p]) => `<option value="${esc(id)}">${esc(p.name)}</option>`).join("");
  changeProvider();
}
function connectionBody() {
  const key = value("api-key");
  return {id:value("connection-id"), provider:value("provider"), base_url:value("base-url"), model:value("model"), voice:value("voice"), structured:value("structured"), api_key_env:value("key-env"), ...(key ? {api_key:key} : {})};
}
function choices(id: string, rows: Choice[], selected: string) {
  el(id).innerHTML = rows.length ? rows.map(row => `<option value="${esc(row.id)}">${esc(row.name)}${row.id === selected ? ' · 推荐/当前选择' : ''}</option>`).join("") : '<option value="">等待自动检测</option>';
  if (selected) el<HTMLSelectElement>(id).value = selected;
}
async function resolveOptions(force = false): Promise<void> {
  if (!force && resolvedRevision === formRevision) return;
  if (resolution) return resolution;
  const revision = formRevision;
  const work = (async () => {
    el("form-status").textContent = "正在自动读取模型和声线…";
    const result = await api("/resolve", "POST", connectionBody());
    if (revision !== formRevision) return;
    if (result.base_url) el<HTMLInputElement>("base-url").value = result.base_url;
    choices("model", result.models, result.model); choices("voice", result.voices, result.voice);
    resolvedRevision = revision;
    el("notice").hidden = true;
    el("form-status").textContent = `已找到 ${result.models.length} 个模型${kind === 'speech' ? `、${result.voices.length} 个声线` : ''}，已自动选择；可直接启用。`;
  })();
  resolution = work;
  try { await work; } catch (error) {
    if (revision !== formRevision) return;
    choices("model", [], ""); choices("voice", [], "");
    el("form-status").textContent = "检测未完成；请按提示处理后点击重新检测。";
    throw error;
  } finally { if (resolution === work) resolution = undefined; }
}
async function save() {
  const revision = formRevision;
  const button = el<HTMLButtonElement>("connect-button"); button.disabled = true;
  try {
  await resolveOptions();
  if (revision !== formRevision) return;
  if (!value("model") || (kind === "speech" && !value("voice"))) throw new Error("尚未发现可用选项，请检查服务并重新检测。");
  const id = value("connection-id");
  const result = await api("/connections", "PUT", connectionBody());
  el<HTMLInputElement>("api-key").value = "";
  Object.assign(snapshot, result); renderConnections();
  el("form-status").textContent = "正在验证推荐配置；语音保持静音…";
  el("verification-progress").hidden = false;
  showVerification(el("verification-progress"), value("model"));
  Object.assign(snapshot, await api(`/connections/${encodeURIComponent(id)}/activate`, "POST"));
  renderConnections(); notify("模型与声线测试通过，已启用。后续请求使用此连接。");
  el("form-status").textContent = "已就绪";
  } finally {clearPanel(el("verification-progress")); el("verification-progress").hidden = true; button.disabled = false; try {Object.assign(snapshot, await api()); renderConnections();} catch { /* Preserve the original connection error. */ }}
}
function proofMarkup(proof?: Proof) {
  if (!proof?.generated) return `<p class="hint">${esc(proof?.message || t('尚无真实生成检验结果', 'Run a generation test to see a result here.'))}</p>`;
  const detail = proof.kind === 'language' ? `<pre>${esc(JSON.stringify(proof.result))}</pre>`
    : proof.kind === 'speech' ? `<p>${esc(proof.sample_text)}</p><p>${Number(proof.seconds).toFixed(2)} s · ${esc(proof.bytes)} bytes · ${t('未播放声音','No audio played')}</p><svg viewBox="0 0 256 48" width="256" height="48" role="img" aria-label="${t('实际生成音频的振幅','Generated audio waveform')}"><path d="${(proof.waveform ?? []).map((v,i) => `M${i*4},${24-v*22}v${v*44}`).join(' ')}" stroke="currentColor" stroke-width="2"/></svg>`
    : `<p>${esc(proof.frames)} ${t('帧','frames')} · ${esc(proof.fps)} FPS · ${esc(proof.dimensions)} ${t('维','dimensions')} · ${esc(proof.seconds)} s</p>`;
  return `<details class="verification" open><summary>${t('真实生成检验通过','Real generation verified')}</summary><small>${esc(proof.model)} · ${esc(proof.verified_at ? new Date(proof.verified_at).toLocaleString() : '')} · ${esc(proof.elapsed_seconds)} s</small>${detail}<button class="button button--secondary" data-artifact="${esc(proof.artifact_url)}" data-format="${esc(proof.format)}">${t('下载生成结果','Download result')} (${esc(proof.format?.toUpperCase())})</button></details>`;
}
function renderConnections() {
  const expanded = new Set(Array.from(el("saved-connections").querySelectorAll("article:has(details[open]) [data-check]")).map(node => (node as HTMLElement).dataset.check));
  el("saved-connections").innerHTML = snapshot.connections.map(c => `<article class="saved card"><div><strong>${esc(c.id)} ${snapshot.active[c.kind] === c.id ? `<span class="badge">${c.pending_changes ? '更改待启用' : '使用中'}</span>` : ""}</strong><p>${esc(snapshot.providers[c.provider]!.name)} · ${esc(c.model)}</p><small>${c.has_key ? "密钥已保存" : "无密钥"}</small>${proofMarkup(c.verification).replace(/(<details[^>]*?)\sopen/g, "$1")}</div><div class="actions"><button data-check="${esc(c.id)}">重新生成检验</button><button data-edit="${esc(c.id)}">编辑</button><button data-activate="${esc(c.id)}">测试并启用</button><button data-remove="${esc(c.id)}" aria-label="删除连接 ${esc(c.id)}">删除</button></div></article>`).join("") || '<p class="hint">还没有添加连接。下方也可以一键部署本地模型。</p>';
  for (const button of el("saved-connections").querySelectorAll<HTMLElement>("[data-check]")) {
    if (expanded.has(button.dataset.check)) button.closest("article")?.querySelector("details")?.setAttribute("open", "");
  }
}
function recipeChanged() {
  const recipe = snapshot.recipes.find(r => r.id === value("recipe"))!;
  el("ollama-model-field").hidden = recipe.id !== "ollama";
  el<HTMLSelectElement>("device-choice").disabled = false;
  el("recipe-detail").textContent = `建议至少预留 ${recipe.storage_gib} GiB 可用空间。CPU 运行大模型可能较慢，启动阶段会显示真实等待状态。`;
  el<HTMLAnchorElement>("license-link").href = recipe.license_url;
  el<HTMLInputElement>("license").checked = false;
}
function renderJobs() {
  showJobs(el("jobs"), snapshot.jobs, proofMarkup, snapshot.services ?? []);
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
  clearPanel(el("machine"));
  el("machine").textContent = "正在检测，通常几秒内完成…";
  const report = await api("/discover", "POST");
  const localChoice = value("ollama-model");
  el("ollama-model").innerHTML = `<option value="auto">按设备内存自动选择${report.recommended_language_model ? ` · ${esc(report.recommended_language_model)}（推荐）` : '（推荐）'}</option>` + (report.language_models ?? []).map((row: Choice) => `<option value="${esc(row.id)}">${esc(row.name)}</option>`).join("");
  el<HTMLSelectElement>("ollama-model").value = localChoice || "auto";
  showHardware(el("machine"), report);
  el("platform-note").textContent = report.vrchat_supported ? "VRChat 双客户端和虚拟 VR 驱动仅适用于 Windows；工作室与模型接入独立运行。" : "本机可使用 Motion Lab、Character Studio 和模型接口；VRChat 双客户端及虚拟 VR 驱动需要 Windows。";
  el("discovered").innerHTML = report.services.map((s: any, i: number) => `<article class="card saved"><div><strong>${esc(snapshot.providers[s.provider]?.name ?? s.provider)} <span class="badge">已发现</span></strong><p>${esc(s.base_url)}</p><small>${esc((s.models ?? []).join(" · "))}</small></div>${s.kind !== "motion" ? `<button data-discovery="${i}">一键接入</button>` : '<span class="hint">部署时自动复用</span>'}</article>`).join("");
  el("discovered").querySelectorAll<HTMLButtonElement>("[data-discovery]").forEach(button => button.onclick = () => void action(async () => {
    button.disabled = true;
    try {
    const s = report.services[Number(button.dataset.discovery)]; chooseKind(s.kind);
    el<HTMLSelectElement>("provider").value = s.provider; changeProvider();
    el<HTMLInputElement>("base-url").value = s.base_url;
    el<HTMLInputElement>("connection-id").value = `${s.provider}-${new URL(s.base_url).port || 'local'}`;
    const models = s.kind === "speech" ? [s.model].filter(Boolean) : s.models ?? [];
    choices("model", models.map((id: string) => ({id, name:id})), models[0] ?? "");
    choices("voice", s.voices ?? [], s.voice || s.voices?.[0]?.id || "");
    el("connections").scrollIntoView({behavior:"smooth"});
    await save();
    } finally {button.disabled = false;}
  }));
}

function invalidateOptions() {formRevision++; resolvedRevision = -1; resolution = undefined;}
el("provider").onchange = () => {changeProvider(); if (snapshot.providers[value("provider")]?.local) void action(() => resolveOptions());};
for (const id of ["api-key", "key-env", "base-url"]) el(id).oninput = invalidateOptions;
el("api-key").onblur = () => {if (value("api-key")) void action(() => resolveOptions());};
el("region").onchange = () => {
  el<HTMLInputElement>("base-url").value = `https://${value("region")}.tts.speech.microsoft.com`;
  invalidateOptions(); if (value("api-key")) void action(() => resolveOptions());
};
el("model").onchange = () => {if (kind === "speech") {invalidateOptions(); void action(() => resolveOptions());}};
el("recipe").onchange = recipeChanged;
el("language-tab").onclick = () => chooseKind("language");
el("speech-tab").onclick = () => chooseKind("speech");
el("language-tab").parentElement!.addEventListener("keydown", event => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  chooseKind(event.key === "Home" ? "language" : event.key === "End" ? "speech" : kind === "language" ? "speech" : "language");
  el(`${kind}-tab`).focus();
});
el("detect").onclick = () => void action(detect);
el("connection-form").onsubmit = e => {e.preventDefault(); void action(() => save());};
el("fetch-models").onclick = () => void action(() => resolveOptions(true));
el("saved-connections").onclick = e => void action(async () => {
  const target = (e.target as HTMLElement).closest<HTMLButtonElement>("button"); if (!target) return;
  if (target.dataset.artifact) return;
  const id = target.dataset.activate || target.dataset.remove || target.dataset.edit || target.dataset.check;
  if (target.dataset.edit) {
    const c = snapshot.connections.find(c => c.id === id)!; chooseKind(c.kind);
    el<HTMLSelectElement>("provider").value = c.provider; changeProvider();
    for (const [field,val] of Object.entries({"connection-id":c.id,"base-url":c.base_url})) el<HTMLInputElement>(field).value = val;
    choices("model", [{id:c.model, name:c.model}], c.model);
    choices("voice", c.voice ? [{id:c.voice, name:c.voice}] : [], c.voice);
    el<HTMLSelectElement>("structured").value = c.structured || "auto";
    el<HTMLInputElement>("key-env").value = c.api_key_env || "";
    await resolveOptions(); return;
  }
  target.disabled = true;
  try {
    if (!target.dataset.remove) {el("verification-progress").hidden = false; showVerification(el("verification-progress"), id!);}
    notify(target.dataset.remove ? "正在删除连接…" : "正在等待模型实际生成结果；语音保持静音…");
    if (target.dataset.check) {
      await api(`/connections/${encodeURIComponent(id!)}/test`, "POST");
      notify("真实生成检验通过，可查看或下载本次结果。"); return;
    }
    Object.assign(snapshot, await api(`/connections/${encodeURIComponent(id!)}` + (target.dataset.activate ? "/activate" : ""), target.dataset.activate ? "POST" : "DELETE"));
    renderConnections(); notify(target.dataset.activate ? "测试通过，后续请求使用此连接。" : "连接已删除。");
  } finally { clearPanel(el("verification-progress")); el("verification-progress").hidden = true; target.disabled = false; try {Object.assign(snapshot, await api()); renderConnections();} catch { /* Preserve original error. */ } }
});
el("deploy-form").onsubmit = e => {e.preventDefault(); void action(async () => {
  const body = {recipe:value("recipe"),model:value("ollama-model"),device:value("device-choice"),accepted_license:el<HTMLInputElement>("license").checked};
  if (!body.accepted_license) throw new Error("请先阅读并勾选模型使用条款。");
  await api("/deployments","POST",body); if (polling) clearTimeout(polling); await refreshJobs();
});};
el("jobs").onclick = e => void action(async () => {
  const target = (e.target as HTMLElement).closest<HTMLButtonElement>("button"); if (!target) return;
  if (target.dataset.artifact) return;
  if (target.dataset.stop) {
    target.disabled = true;
    try {
      const result = await api(`/services/${encodeURIComponent(target.dataset.stop)}/stop`, "POST");
      notify(result.message);
    } finally { target.disabled = false; }
  }
  if (target.dataset.cancel) await api(`/deployments/${target.dataset.cancel}/cancel`,"POST");
  if (target.dataset.retry) await api("/deployments","POST",snapshot.jobs.find(j => j.id === target.dataset.retry)!.request);
  if (polling) clearTimeout(polling); await refreshJobs();
});
root.addEventListener("click", e => {
  const button = (e.target as HTMLElement).closest<HTMLButtonElement>("[data-artifact]");
  if (!button) return;
  void action(async () => {
    const url = button.dataset.artifact!;
    if (!/^\/api\/v1\/onboarding\/verification\/[a-f0-9]{32}\/artifact$/.test(url)) throw new Error("检验结果地址无效，请重新检验。");
    const response = await fetch(url, {headers:{"X-Virea-Setup":"1"}});
    if (!response.ok) throw new Error("检验结果已不可用，请重新生成检验。");
    const object = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = object; link.download = `virea-check.${button.dataset.format}`;
    link.click(); setTimeout(() => URL.revokeObjectURL(object), 1000);
  });
});
async function initialize() {
  const controls = ["detect", "language-tab", "speech-tab", "connect-button", "fetch-models", "deploy-button"];
  controls.forEach(id => el<HTMLButtonElement>(id).disabled = true);
  try {
  snapshot = await api(); chooseKind("language"); renderConnections();
  el("recipe").innerHTML = snapshot.recipes.map(r => `<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("");
  el<HTMLSelectElement>("recipe").value = "motioncraft"; recipeChanged(); renderJobs();
  if (snapshot.jobs.some(j => ["queued","running"].includes(j.status))) polling = setTimeout(() => void action(refreshJobs),1000);
  await detect();
  } catch {
    notify("无法连接本机服务。请确认启动器仍在运行，然后点击重新检测。", true);
  } finally {
    controls.forEach(id => el<HTMLButtonElement>(id).disabled = false);
    renderJobs();
  }
}
el("detect").onclick = () => void action(Object.keys(snapshot.providers).length ? detect : initialize);
subscribe(() => { renderConnections(); renderJobs(); });
void initialize();
