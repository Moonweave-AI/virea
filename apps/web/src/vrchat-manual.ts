import {DirectInput, imageBounds, imagePoint, type DirectState} from "./vrchat-direct-input.mjs";
import type {FrameInfo} from "./vrchat-views.mjs";
import {calibrationView, type CalibrationSnapshot} from "./vrchat-calibration.mjs";
import {roomView, type RoomSnapshot} from "./vrchat-rooms.mjs";

/** Human-operated input stays inside this viewport and its short-lived lease. */
export function mountManualControls(card: HTMLElement, keepBackground = () => false) {
  const screen = card.querySelector<HTMLElement>(".view-screen")!;
  screen.tabIndex = 0;
  screen.setAttribute("role", "group");
  screen.setAttribute("aria-label", "AI 游戏画面，点击接管，右键拖动视角，F8 释放");
  screen.setAttribute("aria-describedby", "manual-key-help");
  const tools = document.createElement("div");
  tools.className = "manual-toolbar";
  tools.innerHTML = `<button type="button" class="manual-toggle" aria-pressed="false">接管 AI</button><button type="button" class="auto-calibrate" title="原地完成全身校准，保持站位与身体朝向">自动校准</button><button type="button" class="room-join" title="自动选择可用的入房方向，优先让观察者加入 AI，保留 AI 站位">同房间</button><button type="button" class="manual-align" disabled title="测量实际画面投影，自动对齐准星和射线">对齐准星</button><button type="button" class="manual-expand" aria-pressed="false" title="放大 AI 画面">放大</button><button type="button" class="manual-help-toggle" aria-expanded="false">键位 ?</button>`;
  card.querySelector("figcaption")!.append(tools);
  const overlay = document.createElement("div");
  overlay.className = "manual-overlay";
  overlay.innerHTML = `<span class="manual-reticle" hidden aria-hidden="true"></span><span class="manual-ack" hidden aria-hidden="true"></span><span class="manual-focus-hint" hidden>点击画面继续键鼠操作</span><span class="manual-calibration" hidden>T 形校准中 · Enter 双手确认 · T 返回</span><span class="manual-mode" hidden></span>`;
  screen.append(overlay);
  const help = document.createElement("div");
  help.className = "manual-help";
  help.id = "manual-key-help";
  help.hidden = true;
  help.innerHTML = `<dl><dt>鼠标移动 · 左键 · 中键</dt><dd>右手瞄准 · 右扳机 / 拖动 · 左扳机</dd><dt>右键拖动 / 方向键</dt><dd>头部观察；Z / C 身体转向，[ / ] 分段转身</dd><dt>滚轮 · Shift + 滚轮 · Ctrl + 滚轮</dt><dd>菜单上下滚动 · 横向 / 径向菜单选择 · 手持物品远近</dd><dt>W A S D · Shift · 空格</dt><dd>角色移动 · 跑步 · 跳跃（需世界支持）</dd><dt>Q / Esc · 反引号 · M · B</dt><dd>左快捷菜单 · 右快捷菜单 · 主菜单 · 径向动作菜单</dd><dt>Backspace / 鼠标后侧键 · Home</dt><dd>菜单返回 · SteamVR 面板</dd><dt>E / G · F / H</dt><dd>右手抓取 / 放下 · 左手抓取 / 放下</dd><dt>主键盘 0 / 1 / 2</dt><dd>小键盘调整目标：头部 / 左手 / 右手</dd><dt>小键盘：头部模式</dt><dd>4 / 6 左右看，8 / 2 上下看；7 / 9 平移，1 / 3 前后探身，+ / − 高度</dd><dt>小键盘：手柄模式</dt><dd>4 / 6 左右，8 / 2 前后，+ / − 高度；7 / 9 偏转，1 / 3 俯仰，÷ / × 翻腕</dd><dt>R / 小键盘 5 · 小键盘小数点</dt><dd>还原当前调整，保留朝向 · 双手还原并回到头部模式</dd><dt>Enter / 小键盘 Enter / 0 · T</dt><dd>扳机确认（左手模式为左扳机） · T 形校准，再 Enter 双手确认</dd><dt>F8 / 点击画面外</dt><dd>结束接管 / 释放所有按键</dd></dl><p>仅画面获焦时接收键鼠；按物理小键盘位置识别，不受 NumLock 影响。手柄自由调整后准星会隐藏，小数点恢复瞄准。首次点击只接管。绿色回执仅表示驱动收到输入，请以游戏射线和按钮高亮确认命中。全程不切换麦克风。</p>`;
  card.append(help);
  const setupStatus = document.createElement("p");
  setupStatus.className = "manual-setup-status";
  setupStatus.setAttribute("role", "status");
  setupStatus.hidden = true;
  card.append(setupStatus);
  let roomPending = false;
  let roomState: RoomSnapshot | null = null;
  let roomBeforeRequest = "";
  function setRooms(snapshot: RoomSnapshot | null, offline = false) {
    // A poll started before the POST may still contain the previous operation.
    if (roomPending && (!snapshot || snapshot.stage === "idle" || JSON.stringify(snapshot) === roomBeforeRequest)) return;
    roomState = snapshot;
    const view = roomView(snapshot, offline);
    setupStatus.hidden = !view.visible;
    setupStatus.textContent = view.text;
    tools.querySelector<HTMLButtonElement>(".room-join")!.disabled = roomPending || view.active || offline;
  }
  const calibrationPanel = document.createElement("section");
  calibrationPanel.className = "calibration-progress";
  calibrationPanel.hidden = true;
  calibrationPanel.setAttribute("aria-label", "自动全身校准进度");
  calibrationPanel.innerHTML = `<div class="calibration-progress-heading"><strong data-title></strong><span data-percent></span></div><progress max="100" value="0" aria-label="自动校准完成百分比"></progress><div class="calibration-progress-step" role="status"><span data-step></span><button type="button" data-cancel>取消</button></div><p data-detail></p>`;
  card.querySelector("figcaption")!.after(calibrationPanel);
  const calibrateButton = tools.querySelector<HTMLButtonElement>(".auto-calibrate")!;
  const cancelCalibration = calibrationPanel.querySelector<HTMLButtonElement>("[data-cancel]")!;
  let calibrationState: CalibrationSnapshot | null = null;
  let setupPending = false, calibrationOffline = false;
  function setCalibration(snapshot: CalibrationSnapshot | null, offline = false) {
    if (!setupPending) calibrationState = snapshot;
    calibrationOffline = offline;
    const view = calibrationView(calibrationState, offline);
    calibrationPanel.hidden = !view.visible;
    if (view.visible) {
      calibrationPanel.dataset.state = offline ? "offline" : view.failed ? "failed" : view.complete ? "completed" : "running";
      calibrationPanel.querySelector<HTMLElement>("[data-title]")!.textContent = view.title!;
      calibrationPanel.querySelector<HTMLElement>("[data-percent]")!.textContent = `${view.percent}%`;
      const progress = calibrationPanel.querySelector("progress")!;
      progress.value = view.percent!;
      progress.setAttribute("aria-valuetext", `${view.percent}% ${view.count} ${view.label}`);
      calibrationPanel.querySelector<HTMLElement>("[data-step]")!.textContent = `${view.count} ${view.label}`;
      calibrationPanel.querySelector<HTMLElement>("[data-detail]")!.textContent = view.detail!;
    }
    cancelCalibration.hidden = !view.active;
    cancelCalibration.disabled = setupPending || offline;
    calibrateButton.disabled = setupPending || !!view.active || offline;
    calibrateButton.textContent = view.active ? "校准中…" : view.failed ? "重试校准" : "自动校准";
  }
  async function calibrationRequest(action: "start" | "cancel") {
    setupPending = true;
    if (action === "start") {
      calibrationState = {stage: "preparing", active: true, step: 1, total_steps: 8, percent: 0,
        step_label: "正在启动自动全身校准"};
    }
    setCalibration(calibrationState);
    try {
      const response = await fetch("/api/v1/vrchat/calibration", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action}), signal: AbortSignal.timeout(10000)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "自动校准请求失败");
      calibrationState = result;
    } catch (error) {
      calibrationState = {...calibrationState, stage: "failed", active: false, error: String(error)};
    } finally {
      setupPending = false;
      setCalibration(calibrationState, calibrationOffline);
    }
  }
  calibrateButton.addEventListener("click", () => { void calibrationRequest("start"); });
  cancelCalibration.addEventListener("click", () => { void calibrationRequest("cancel"); });
  for (const [selector, endpoint, body] of [
    [".room-join", "rooms", {action: "join", target: "auto"}],
  ] as const) {
    const button = tools.querySelector<HTMLButtonElement>(selector)!;
    button.addEventListener("click", async () => {
      button.disabled = true;
      roomPending = true;
      roomBeforeRequest = JSON.stringify(roomState);
      setupStatus.hidden = false;
      setupStatus.textContent = "正在发送入房命令并等待两端到达…";
      try {
        const response = await fetch(`/api/v1/vrchat/${endpoint}`, {method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify(body), signal: AbortSignal.timeout(120000)});
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail ?? "自动设置失败");
        roomPending = false;
        setRooms(result);
      } catch (error) { roomPending = false; setRooms({stage: "failed", error: String(error)}); }
      finally { roomPending = false; button.disabled = false; }
    });
  }
  const status = document.createElement("p");
  status.className = "manual-status";
  status.setAttribute("role", "status");
  status.textContent = "点击画面接管 · 右键拖动看向四周";
  card.append(status);
  const toggle = tools.querySelector<HTMLButtonElement>(".manual-toggle")!;
  const align = tools.querySelector<HTMLButtonElement>(".manual-align")!;
  const expand = tools.querySelector<HTMLButtonElement>(".manual-expand")!;
  const helpToggle = tools.querySelector<HTMLButtonElement>(".manual-help-toggle")!;
  const reticle = overlay.querySelector<HTMLElement>(".manual-reticle")!;
  const ack = overlay.querySelector<HTMLElement>(".manual-ack")!;
  const focusHint = overlay.querySelector<HTMLElement>(".manual-focus-hint")!;
  const calibration = overlay.querySelector<HTMLElement>(".manual-calibration")!;
  const mode = overlay.querySelector<HTMLElement>(".manual-mode")!;
  let token: string | null = null, sending = false, starting = false, aligning = false, calibrated = false, generation = 0;
  let input = new DirectInput(), applied: DirectState | null = null;
  let frame: FrameInfo | null = null;
  let drag: {id: number; x: number; y: number} | null = null;

  async function request(body: unknown, keepalive = false, timeout = 3000) {
    const response = await fetch("/api/v1/vrchat/manual", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body), keepalive, signal: AbortSignal.timeout(timeout)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail ?? "接管请求失败");
    return result;
  }
  function draw() {
    const active = !!token;
    toggle.textContent = active ? "结束接管" : "接管 AI";
    toggle.setAttribute("aria-pressed", String(active));
    align.disabled = !active || aligning || input.state.calibration;
    align.textContent = aligning ? "对齐中…" : "对齐准星";
    screen.classList.toggle("manual-aim", active && calibrated && !input.state.right_hand.some(value => value !== 0));
    screen.classList.toggle("manual-looking", !!drag);
    const focused = document.activeElement === screen;
    focusHint.hidden = !active || focused;
    calibration.hidden = !active || !input.state.calibration;
    mode.hidden = !active || input.state.calibration;
    const adjusted = input.state.right_hand.some(value => value !== 0);
    mode.textContent = `小键盘：${{head: "头部", left: "左手", right: "右手"}[input.target]} · 0 / 1 / 2 切换${adjusted ? " · 自由手柄，小数点恢复瞄准" : !calibrated ? " · 准星尚未校准" : ""}`;
    const rect = screen.getBoundingClientRect();
    const box = frame && imageBounds(rect, Number(frame.width), Number(frame.height));
    for (const [element, pose] of [[reticle, input.state], [ack, applied]] as const) {
      element.hidden = !active || !box || !pose || input.state.calibration || adjusted || !calibrated;
      if (box && pose) {
        element.style.left = `${box.left - rect.left + (pose.pointer_x + 1) / 2 * box.width}px`;
        element.style.top = `${box.top - rect.top + (pose.pointer_y + 1) / 2 * box.height}px`;
      }
    }
    reticle.classList.toggle("is-pressed", input.state.trigger);
    ack.classList.toggle("is-pending", !!applied && (Math.abs(applied.head_yaw - input.state.head_yaw) > 1 || Math.abs(applied.head_pitch - input.state.head_pitch) > 1));
  }
  function release() {
    input.release();
    const captured = drag?.id; drag = null;
    if (captured !== undefined && screen.hasPointerCapture(captured)) screen.releasePointerCapture(captured);
    draw();
  }
  async function stop() {
    generation++;
    const previous = token; token = null; calibrated = false;
    release(); applied = null;
    status.textContent = "接管已结束 · 点击画面重新接管";
    if (previous) await request({action: "end", token: previous}, true).catch(() => {});
  }
  async function start() {
    if (starting || token || !frame) return;
    starting = true; toggle.disabled = true;
    const attempt = ++generation;
    try {
      const result = await request({action: "begin"});
      if (attempt !== generation || !frame) {
        await request({action: "end", token: result.token}, true); return;
      }
      input = new DirectInput(result.state);
      input.state.view_aspect = Number(frame.width) / Number(frame.height);
      token = result.token; applied = null;
      calibrated = !!result.ray_alignment;
      screen.focus({preventScroll: true}); draw();
      status.textContent = "键鼠接管中 · 左键确认 · 右键看 · Q 菜单 · F8 退出";
      void pump(token!);
      if (!calibrated) await alignProjection();
    } catch (error) { status.textContent = String(error); }
    finally { starting = false; toggle.disabled = !frame; }
  }
  async function alignProjection() {
    if (!token || aligning) return;
    const lease = token;
    aligning = true; release();
    status.textContent = "正在对齐游戏射线，视角和手柄会短暂移动，请稍候…";
    try {
      // Drain the one in-flight update; it must not overwrite calibration.
      while (sending && token === lease) await new Promise(resolve => setTimeout(resolve, 20));
      if (token !== lease) return;
      const result = await request({action: "align", token: lease}, false, 30000);
      if (token !== lease) return;
      input = new DirectInput(result.state);
      applied = result.applied_state ?? null;
      calibrated = !!result.ray_alignment;
      status.textContent = "游戏射线已校准 · 左键确认 · 右键看 · F8 退出";
    } catch (error) {
      if (token === lease) status.textContent = `对齐未完成：${error instanceof Error ? error.message : error}。仍可操作，请以游戏内射线为准；需要时点击「对齐准星」重试。`;
    } finally {
      aligning = false; draw();
      if (token === lease) { screen.focus({preventScroll: true}); void pump(lease); }
    }
  }
  function updateAim(event: PointerEvent) {
    if (!frame) return false;
    const point = imagePoint(screen.getBoundingClientRect(), Number(frame.width), Number(frame.height), event.clientX, event.clientY);
    if (!point) return false;
    input.aim(point, Number(frame.width) / Number(frame.height));
    return true;
  }
  function handle(action: () => void) {
    try { action(); draw(); }
    catch (error) { void stop().then(() => {status.textContent = String(error);}); }
  }
  toggle.addEventListener("click", () => { if (token) void stop(); else void start(); });
  align.addEventListener("click", () => { void alignProjection(); });
  expand.addEventListener("click", () => {
    const expanded = card.closest(".live-views")!.classList.toggle("ai-expanded");
    expand.setAttribute("aria-pressed", String(expanded)); expand.textContent = expanded ? "还原" : "放大";
    if (token) screen.focus({preventScroll: true}); draw();
  });
  helpToggle.addEventListener("click", () => { help.hidden = !help.hidden; helpToggle.setAttribute("aria-expanded", String(!help.hidden)); });
  screen.addEventListener("contextmenu", event => event.preventDefault());
  screen.addEventListener("pointerdown", event => {
    if (!frame || aligning || event.button < 0 || event.button > 4) return;
    event.preventDefault();
    if (!token) { if (event.button === 0) void start(); return; }
    screen.focus({preventScroll: true});
    if (!updateAim(event)) { draw(); return; }
    handle(() => {
      screen.setPointerCapture(event.pointerId);
      if (event.button === 2) drag = {id: event.pointerId, x: event.clientX, y: event.clientY};
      else if (event.button < 2) input.pointer(true, event.button === 1);
      else input.enqueue(event.button === 3 ? "back" : "menu");
    });
  });
  screen.addEventListener("pointermove", event => {
    if (!token || !frame || aligning || document.activeElement !== screen) return;
    handle(() => {
      if (drag?.id === event.pointerId) {
        const rect = screen.getBoundingClientRect();
        input.look((event.clientX - drag.x) * 180 / rect.width, (event.clientY - drag.y) * 120 / rect.height);
        drag.x = event.clientX; drag.y = event.clientY;
      } else updateAim(event);
    });
  });
  screen.addEventListener("pointerup", event => {
    if (!token) return;
    handle(() => {
      if (event.button === 0) input.pointer(false);
      if (event.button === 1) input.pointer(false, true);
      if (event.button === 2) drag = null;
      if (!event.buttons && screen.hasPointerCapture(event.pointerId)) screen.releasePointerCapture(event.pointerId);
    });
  });
  screen.addEventListener("pointercancel", release);
  screen.addEventListener("lostpointercapture", () => { if (input.state.trigger || input.state.trigger_left || drag) release(); });
  screen.addEventListener("auxclick", event => event.preventDefault());
  screen.addEventListener("wheel", event => {
    if (!token || !frame || aligning || document.activeElement !== screen) return;
    event.preventDefault(); event.stopPropagation();
    const unit = event.deltaMode === 1 ? 24 : event.deltaMode === 2 ? 300 : 1;
    handle(() => input.wheel(event.deltaX * unit, event.deltaY * unit, event.shiftKey, event.ctrlKey));
  }, {passive: false});
  screen.addEventListener("blur", release);
  screen.addEventListener("focus", draw);
  for (const name of ["keydown", "keyup"] as const) screen.addEventListener(name, event => {
    if (!token || !frame || aligning || event.target !== screen) return;
    if (event.altKey || event.metaKey || (event.ctrlKey && !event.code.startsWith("Control"))) { release(); return; }
    handle(() => {
      const action = input.key(event.code, name === "keydown", event.repeat);
      if (!action) return;
      event.preventDefault(); event.stopPropagation();
      if (action === "release") { void stop(); screen.blur(); }
    });
  });
  async function pump(lease: string) {
    if (sending) return;
    sending = true;
    let lastTick = performance.now();
    try {
      while (token === lease && !aligning) {
        const now = performance.now();
        input.advance((now - lastTick) / 1000); lastTick = now;
        const next = input.next();
        const result = await request({action: "update", token: lease, ...next, wait_ms: 50});
        if (token !== lease) break;
        if (result.error || !result.active) throw new Error(result.error ?? "接管已结束");
        applied = result.applied_state ?? null; draw();
      }
    } catch (error) { if (token === lease) {
      await stop();
      status.textContent = String(error).includes("manual control expired")
        ? "接管已结束 · 点击画面可恢复控制（旧按键已释放）" : String(error);
    } }
    finally { sending = false; if (token && token !== lease) void pump(token); }
  }
  window.addEventListener("blur", release);
  document.addEventListener("visibilitychange", () => { if (document.hidden) { release(); if (!keepBackground()) void stop(); } });
  window.addEventListener("pagehide", () => { void stop(); });
  new ResizeObserver(draw).observe(screen);
  return {stop, setCalibration, setRooms, setFrame(info: FrameInfo | null) {
    if ((!info || (frame && info.pid !== frame.pid)) && (token || starting)) void stop();
    if (info && frame && Number(info.width) / Number(info.height) !== Number(frame.width) / Number(frame.height)) {
      calibrated = false;
      if (token) { release(); status.textContent = "画面比例已变化，可点击「对齐准星」重新校准；左键仍可直接操作"; }
    }
    frame = info; toggle.disabled = !frame || starting; draw();
  }};
}
