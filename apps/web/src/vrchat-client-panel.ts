import {clientLaunchView} from "./vrchat-clients.mjs";

export function mountClientLaunchers(root: HTMLElement) {
  const panel = document.createElement("section");
  panel.className = "client-launchers";
  panel.setAttribute("aria-label", "启动 VRChat 客户端");
  panel.innerHTML = `<div class="client-launch-heading"><strong>VRChat 窗口</strong><span>独立账号 · 静音启动</span></div>
    <div class="client-launch-grid">${(["observer", "ai"] as const).map(role => `<article data-client="${role}" class="client-launch-card">
      <div class="client-launch-title"><strong>${role === "observer" ? "观察者" : "AI"}</strong><span>${role === "observer" ? "桌面模式" : "虚拟 VR · 全身动作"}</span></div>
      <span class="client-account"></span><p class="client-launch-detail" role="status" aria-live="polite"></p>
      <div class="client-launch-progress"><progress max="100" value="0" aria-label="${role === "observer" ? "观察者" : "AI"}启动进度"></progress><span></span></div>
      <div class="client-launch-actions"><button type="button" data-start disabled>启动</button><button type="button" data-restart disabled>重启此窗口</button></div>
    </article>`).join("")}</div><p class="client-launch-note">游戏会恢复各自保存的登录状态；凭据失效或需要验证码时，在对应窗口完成验证。重启后自动恢复画面与角色连接。</p>`;
  root.querySelector(".connection-card")!.after(panel);
  let state: any = null;
  let offline = false;
  let busy = false;
  let sequence = 0;
  let stopped = false;
  let timer = 0;
  const cards = (["observer", "ai"] as const).map(role => ({role, card: panel.querySelector<HTMLElement>(`[data-client=${role}]`)!}));
  const render = () => {
    for (const {role, card} of cards) {
      const view = clientLaunchView(state, role, offline, busy);
      card.querySelector(".client-account")!.textContent = view.account;
      card.querySelector(".client-launch-detail")!.textContent = view.detail;
      card.classList.toggle("is-ready", view.ready);
      const start = card.querySelector<HTMLButtonElement>("[data-start]")!;
      start.textContent = view.startText; start.disabled = view.startDisabled;
      card.querySelector<HTMLButtonElement>("[data-restart]")!.disabled = view.restartDisabled;
      const bar = card.querySelector<HTMLElement>(".client-launch-progress")!;
      bar.hidden = !view.showProgress;
      bar.querySelector("progress")!.value = view.progress;
      bar.querySelector("span")!.textContent = `${view.progress}% · ${view.step}/${view.total}`;
    }
  };
  const request = async (path = "", body?: unknown) => {
    const response = await fetch(`/api/v1/vrchat/clients${path}`, {method: body ? "POST" : "GET", headers: {"Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(15000)});
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || "客户端启动请求失败");
    return value;
  };
  for (const {role, card} of cards) {
    for (const action of ["start", "restart"] as const) {
      card.querySelector(`[data-${action}]`)!.addEventListener("click", async () => {
        if (busy) return;
        busy = true; sequence++; render();
        try { state = await request(`/${role}`, {action}); offline = false; }
        catch (error) {
          state = {...state, clients: {...state?.clients, [role]: {...state?.clients?.[role], detail: String(error)}}};
        } finally { busy = false; render(); }
      });
    }
  }
  const poll = async () => {
    const own = sequence;
    try {
      if (!busy) {
        const result = await request();
        if (own === sequence && !busy) { state = result; offline = false; render(); }
      }
    } catch { if (own === sequence && !busy) { offline = true; render(); } }
    finally { if (!stopped) timer = window.setTimeout(poll, 2000); }
  };
  window.addEventListener("pagehide", () => { stopped = true; window.clearTimeout(timer); });
  window.addEventListener("pageshow", () => { if (stopped) { stopped = false; void poll(); } });
  render(); void poll();
}
