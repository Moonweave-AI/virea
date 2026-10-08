import {FramePump, type FrameInfo} from "./vrchat-views.mjs";

export function mountViews(root: HTMLElement) {
  const toggle = document.getElementById("toggle-views") as HTMLButtonElement;
  const panel = document.createElement("aside");
  panel.id = "live-views";
  panel.className = "live-views";
  panel.setAttribute("aria-label", "VRChat 实时双视角");
  panel.hidden = true;
  panel.innerHTML = `<header class="views-heading"><div><h2>实时视角</h2><p>两个 VRChat 窗口 · 本机画面</p></div><button type="button" class="icon-button" aria-label="收起实时视角">×</button></header>
    <div class="views-grid">${(["observer", "ai"] as const).map((role, index) => `<figure class="live-view" data-view="${role}">
      <figcaption><span class="view-role">${index === 0 ? "你的视角" : "AI 的视角"}</span><span class="view-state">连接中</span></figcaption>
      <div class="view-screen"><img alt="${index === 0 ? "观察者" : "AI"} VRChat 窗口实时画面" hidden draggable="false"><div class="view-placeholder"><span class="view-symbol">${index === 0 ? "◉" : "✧"}</span><p>正在连接窗口…</p></div></div>
      <div class="view-meta"><span>${index === 0 ? "观察者客户端" : "独立 AI 客户端"}</span><span class="view-resolution"></span></div>
    </figure>`).join("")}</div><footer class="views-footer">上方观察 AI 的表现，下方查看 AI 所在窗口。<br>恢复最小化的游戏窗口即可继续画面。收起后自动停止采集。</footer>`;
  root.append(panel);
  const close = panel.querySelector<HTMLButtonElement>(".views-heading button")!;
  const narrow = matchMedia("(max-width:900px)");
  const behind = [...root.querySelectorAll<HTMLElement>(".chat-shell, .sidebar")];
  let opened = false;
  const views = (["observer", "ai"] as const).map(role => {
    const card = panel.querySelector<HTMLElement>(`[data-view=${role}]`)!;
    const img = card.querySelector<HTMLImageElement>("img")!;
    const placeholder = card.querySelector<HTMLElement>(".view-placeholder")!;
    const label = card.querySelector<HTMLElement>(".view-state")!;
    const meta = card.querySelector<HTMLElement>(".view-resolution")!;
    let url = "";
    let lastFrame = "";
    let lastChanged = 0;
    const clear = (message: string) => {
      img.hidden = true;
      img.removeAttribute("src");
      if (url) URL.revokeObjectURL(url);
      url = "";
      lastFrame = "";
      placeholder.hidden = false;
      placeholder.querySelector("p")!.textContent = message;
      label.textContent = opened && !document.hidden ? "等待画面" : "已暂停";
      label.classList.remove("is-live");
      meta.textContent = "";
    };
    const display = (blob: Blob, info: FrameInfo) => {
      const identity = `${info.pid}:${info.sequence}`;
      if (identity !== lastFrame) { lastFrame = identity; lastChanged = performance.now(); }
      if (performance.now() - lastChanged > 1500) { clear("画面暂未更新，正在等待客户端。"); return; }
      const previous = url;
      url = URL.createObjectURL(blob);
      img.src = url;
      img.hidden = false;
      placeholder.hidden = true;
      if (previous) URL.revokeObjectURL(previous);
      label.textContent = "实时";
      label.classList.add("is-live");
      meta.textContent = `${info.width} × ${info.height} · PID ${info.pid}`;
    };
    const pump = new FramePump(role, display, clear);
    return {pump, clear};
  });
  const sync = () => {
    const modal = opened && narrow.matches;
    for (const region of behind) region.inert = modal;
    panel.setAttribute("role", modal ? "dialog" : "complementary");
    if (modal) panel.setAttribute("aria-modal", "true");
    else panel.removeAttribute("aria-modal");
    for (const view of views) {
      if (opened && !document.hidden) view.pump.start();
      else { view.pump.stop(); view.clear("画面已暂停"); }
    }
  };
  const setOpen = (next: boolean) => {
    opened = next;
    panel.hidden = !next;
    toggle.setAttribute("aria-expanded", String(next));
    toggle.setAttribute("aria-label", next ? "收起实时双视角" : "展开实时双视角");
    document.body.classList.toggle("views-open", next);
    if (next) { document.body.classList.remove("sidebar-open"); close.focus(); }
    sync();
    if (!next) toggle.focus();
  };
  toggle.addEventListener("click", () => setOpen(!opened));
  close.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && opened && !document.querySelector("dialog[open]")) setOpen(false);
    if (event.key === "Tab" && opened && narrow.matches) { event.preventDefault(); close.focus(); }
  });
  narrow.addEventListener("change", sync);
  document.addEventListener("visibilitychange", sync);
  window.addEventListener("pagehide", () => { for (const view of views) { view.pump.stop(); view.clear("画面已暂停"); } });
  window.addEventListener("pageshow", sync);
}
