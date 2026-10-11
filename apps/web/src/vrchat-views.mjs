const errors = {
  windows_required: "实时视角需要在 Windows 上运行 VIREA。",
  window_not_found: "等待 VRChat 窗口。请启动对应客户端并启用 OSC。",
  ambiguous_window: "检测到窗口绑定冲突，请检查两个客户端的独立 OSC 端口。",
  window_minimized: "窗口已最小化。恢复窗口后，画面会自动继续。",
  window_closed: "VRChat 窗口已关闭，正在等待重新连接。",
  waiting_for_frame: "正在等待第一帧…",
  frame_stale: "画面暂未更新，请检查 VRChat 是否仍在运行。",
  capture_not_installed: "缺少窗口采集组件，请安装 VIREA 的 vrchat 依赖。",
  capture_failed: "暂时无法采集这个窗口，正在重试。",
};

export function viewError(code) {
  return errors[code] ?? "画面连接暂时中断，正在自动重试。";
}

/** One outstanding request per view; hiding a pane invalidates even late replies. */
export class FramePump {
  constructor(role, onFrame, onStatus, fetcher = fetch) {
    this.role = role;
    this.onFrame = onFrame;
    this.onStatus = onStatus;
    this.fetcher = fetcher;
    this.generation = 0;
    this.active = false;
    this.controller = null;
    this.timer = null;
  }

  start() {
    if (this.active) return;
    this.active = true;
    void this.tick(++this.generation);
  }

  stop() {
    this.active = false;
    ++this.generation;
    this.controller?.abort();
    clearTimeout(this.timer);
    this.controller = null;
  }

  async tick(generation) {
    if (!this.active || this.generation !== generation) return;
    const controller = new AbortController();
    this.controller = controller;
    const deadline = setTimeout(() => controller.abort(), 4000);
    let failed = false;
    try {
      const fetcher = this.fetcher;
      const response = await fetcher(`/api/v1/vrchat/views/${this.role}/frame`, {
        headers: {"X-Virea-Capture": "1", "X-Virea-Pace": "1"}, cache: "no-store", signal: controller.signal,
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body?.detail?.code ?? "connection_lost");
      }
      const blob = await response.blob();
      if (!this.active || this.generation !== generation) return;
      if (Number(response.headers.get("X-Capture-Age-Ms")) > 1500) throw new Error("frame_stale");
      this.onFrame(blob, {
        pid: response.headers.get("X-Capture-Pid") ?? "",
        sequence: response.headers.get("X-Capture-Sequence") ?? "",
        width: response.headers.get("X-Capture-Width") ?? "",
        height: response.headers.get("X-Capture-Height") ?? "",
      });
    } catch (error) {
      if (this.active && this.generation === generation) this.onStatus(viewError(error?.message));
      failed = true;
    } finally {
      clearTimeout(deadline);
      if (this.active && this.generation === generation) {
        if (failed) this.timer = setTimeout(() => void this.tick(generation), 1200);
        else void this.tick(generation);
      }
    }
  }
}
