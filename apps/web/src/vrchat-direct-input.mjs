/** Pure input state: DOM focus is managed by the viewport, never globally. */
export function imageBounds(rect, width, height) {
  if (!(width > 0 && height > 0 && rect.width > 0 && rect.height > 0)) return null;
  const scale = Math.min(rect.width / width, rect.height / height);
  const w = width * scale, h = height * scale;
  return {left: rect.left + (rect.width - w) / 2, top: rect.top + (rect.height - h) / 2, width: w, height: h};
}

export function imagePoint(rect, width, height, x, y) {
  const box = imageBounds(rect, width, height);
  if (!box || x < box.left || y < box.top || x > box.left + box.width || y > box.top + box.height) return null;
  return {pointer_x: (x - box.left) / box.width * 2 - 1, pointer_y: (y - box.top) / box.height * 2 - 1};
}

const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
const held = new Set(["KeyW", "KeyA", "KeyS", "KeyD", "ShiftLeft", "ShiftRight", "Space", "KeyE", "KeyG", "KeyF", "KeyH", "KeyZ", "KeyC",
  "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", ...[1,2,3,4,6,7,8,9].map(n => `Numpad${n}`), "NumpadAdd", "NumpadSubtract", "NumpadDivide", "NumpadMultiply"]);
const shortcuts = new Set(["KeyQ", "Escape", "Backquote", "KeyM", "KeyB", "Backspace", "Home", "KeyR", "KeyT", "Enter", "NumpadEnter", "Numpad0", "Numpad5", "NumpadDecimal", "F8", "Digit0", "Digit1", "Digit2", "BracketLeft", "BracketRight"]);
const neutral = () => ({trigger: false, trigger_left: false, vertical: 0, horizontal: 0, turn: 0,
  run: false, jump: false, grab: false, drop: false, grab_left: false, drop_left: false,
  scroll_x: 0, scroll_y: 0, move_hold: 0});

export class DirectInput {
  constructor(initial = {}) {
    this.state = {head_yaw: 0, head_pitch: 0, pointer_x: 0, pointer_y: 0, view_aspect: 16 / 9, horizontal_fov: 90, projection_center_x: 0, projection_center_y: 0,
      head_x: 0, head_y: 0, head_z: 0, left_hand: [0,0,0,0,0,0], right_hand: [0,0,0,0,0,0],
      calibration: false, ...structuredClone(initial), ...neutral()};
    this.keys = new Set();
    this.edges = [];
    this.target = "head";
    this.wheelRemaining = 0;
  }
  enqueue(command = null) {
    // Do not replay a large backlog of physical input after a stalled request.
    if (this.edges.length >= 32) throw new Error("输入连接延迟过高，已释放控制");
    this.edges.push({state: structuredClone(this.state), command});
  }
  next() { return this.edges.shift() ?? {state: structuredClone(this.state), command: null}; }
  aim(point, aspect) {
    if (this.state.calibration) return;
    Object.assign(this.state, point, {view_aspect: aspect});
  }
  look(dx, dy) {
    this.state.head_yaw = ((this.state.head_yaw + dx + 540) % 360) - 180;
    this.state.head_pitch = clamp(this.state.head_pitch - dy, -70, 70);
  }
  pointer(down, left = false) {
    const key = left ? "trigger_left" : "trigger";
    if (this.state[key] === down) return;
    this.state[key] = down;
    this.enqueue();
  }
  wheel(dx, dy, shift = false, control = false) {
    if (control) this.state.move_hold = clamp(-dy / 100, -1, 1);
    else {
      this.state.scroll_x = clamp((shift ? dy : dx) / 100, -1, 1);
      this.state.scroll_y = shift ? 0 : clamp(-dy / 100, -1, 1);
    }
    this.wheelRemaining = .16;
  }
  advance(seconds) {
    const dt = clamp(seconds, 0, .1), axis = (positive, negative) => Number(this.keys.has(positive)) - Number(this.keys.has(negative));
    this.wheelRemaining -= dt;
    if (this.wheelRemaining <= 0) Object.assign(this.state, {scroll_x: 0, scroll_y: 0, move_hold: 0});
    if (this.state.calibration) return;
    this.look(axis("ArrowRight", "ArrowLeft") * 65 * dt, axis("ArrowDown", "ArrowUp") * 65 * dt);
    const speed = this.state.run ? 2 : 1;
    if (this.target === "head") {
      this.look(axis("Numpad6", "Numpad4") * 65 * dt, axis("Numpad2", "Numpad8") * 65 * dt);
      for (const [key, value] of [["head_x", axis("Numpad9", "Numpad7")], ["head_z", axis("Numpad3", "Numpad1")], ["head_y", axis("NumpadAdd", "NumpadSubtract")]])
        this.state[key] = clamp(this.state[key] + value * .35 * dt * speed, -.6, .6);
    } else {
      const hand = this.state[`${this.target}_hand`];
      const axes = [axis("Numpad6", "Numpad4"), axis("NumpadAdd", "NumpadSubtract"), axis("Numpad2", "Numpad8"),
        axis("Numpad9", "Numpad7"), axis("Numpad1", "Numpad3"), axis("NumpadMultiply", "NumpadDivide")];
      axes.forEach((value, i) => { hand[i] = clamp(hand[i] + value * dt * speed * (i < 3 ? .3 : 60), i < 3 ? -.6 : -90, i < 3 ? .6 : 90); });
    }
  }
  reset() {
    if (this.target === "head") Object.assign(this.state, {head_pitch: 0, head_x: 0, head_y: 0, head_z: 0, pointer_x: 0, pointer_y: 0});
    else this.state[`${this.target}_hand`] = [0,0,0,0,0,0];
  }
  release() {
    this.keys.clear();
    Object.assign(this.state, neutral());
    this.wheelRemaining = 0;
    this.edges.length = 0;
    this.enqueue();
  }
  key(code, down, repeat = false) {
    if (!held.has(code) && !shortcuts.has(code)) return false;
    if (held.has(code)) {
      if (this.keys.has(code) === down) return true;
      if (down) this.keys.add(code); else this.keys.delete(code);
      Object.assign(this.state, {
        vertical: Number(this.keys.has("KeyW")) - Number(this.keys.has("KeyS")),
        horizontal: Number(this.keys.has("KeyD")) - Number(this.keys.has("KeyA")),
        turn: Number(this.keys.has("KeyC")) - Number(this.keys.has("KeyZ")),
        run: this.keys.has("ShiftLeft") || this.keys.has("ShiftRight"), jump: this.keys.has("Space"),
        grab: this.keys.has("KeyE"), drop: this.keys.has("KeyG"),
        grab_left: this.keys.has("KeyF"), drop_left: this.keys.has("KeyH"),
      });
      this.enqueue();
    } else if (down) {
      if (!repeat) {
        if (code === "F8") return "release";
        if (code.startsWith("Digit")) { this.release(); this.target = ["head", "left", "right"][Number(code.slice(-1))]; return true; }
        if (code === "KeyR" || code === "Numpad5") this.reset();
        if (code === "NumpadDecimal") { this.state.left_hand.fill(0); this.state.right_hand.fill(0); this.target = "head"; this.reset(); }
        if (code === "KeyT") this.state.calibration = !this.state.calibration;
        const commands = {KeyQ: "menu", Escape: "menu", Backquote: "menu_right", KeyM: "main_menu", KeyB: "action_menu", Backspace: "back", Home: "dashboard", BracketLeft: "turn_left", BracketRight: "turn_right"};
        this.enqueue(["Enter", "NumpadEnter", "Numpad0"].includes(code) ? (this.state.calibration ? "confirm" : this.target === "left" ? "click_left" : "click") : commands[code] ?? null);
      }
    }
    return true;
  }
}
