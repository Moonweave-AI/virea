import type { Performance } from "../contracts";
import "./performance.css";

export class MotionBackendPicker {
  readonly ready: Promise<void>;
  private select: HTMLSelectElement;
  constructor(root: HTMLElement, report: (error: unknown) => void) {
    this.select = root.querySelector<HTMLSelectElement>("#motion-backend")!;
    const status = root.querySelector<HTMLElement>("#motion-backend-status")!;
    this.ready = fetch("/api/v1/characters/motion-backends").then(async response => {
      if (!response.ok) throw new Error("无法读取动作路线");
      const value = await response.json() as { default: string; backends: { id: string; name: string; configured: boolean; ready: boolean | null; status: string; error: string | null }[] };
      this.select.replaceChildren(...value.backends.map(backend => {
        const unavailable = !backend.configured || backend.ready === false;
        const option = new Option(backend.name + (unavailable ? " · 未就绪" : ""), backend.id);
        option.disabled = unavailable; option.title = backend.error ?? "";
        return option;
      }));
      this.select.value = value.default;
      status.textContent = "会话使用所选路线。语音和动作可分别安排时间。";
      if (this.select.selectedOptions[0]?.disabled) status.textContent = "默认动作路线未就绪，请启动对应服务或选择已有路线。";
    }).catch(report);
  }
  get value(): string {
    if (!this.select.value || this.select.selectedOptions[0]?.disabled) throw new Error("请选择已就绪的动作路线");
    return this.select.value;
  }
  set locked(value: boolean) { this.select.disabled = value; }
}

export function renderPerformanceTracks(root: HTMLElement, performance: Performance | null | undefined): void {
  const host = root.querySelector<HTMLElement>("#performance-tracks")!;
  host.hidden = !performance;
  const signature = JSON.stringify(performance ? [performance.id, performance.duration_seconds, performance.motions, performance.speech] : null);
  if (host.dataset.signature === signature) return;
  host.dataset.signature = signature;
  host.replaceChildren();
  if (!performance) return;
  for (const [name, segments] of [["动作", performance.motions.map(s => ({ ...s, text: s.label || s.prompt }))],
    ["语音", performance.speech]] as const) {
    const row = document.createElement("div"), label = document.createElement("strong"), track = document.createElement("div");
    row.className = "performance-track"; label.textContent = name; track.className = "performance-lane";
    for (const segment of segments) {
      const bar = document.createElement("span");
      bar.className = name === "动作" ? "motion-segment" : "speech-segment";
      bar.textContent = segment.text;
      bar.title = `${segment.start_seconds.toFixed(2)}–${(segment.start_seconds + segment.duration_seconds).toFixed(2)}s · ${segment.text}`;
      bar.style.left = `${segment.start_seconds / performance.duration_seconds * 100}%`;
      bar.style.width = `${segment.duration_seconds / performance.duration_seconds * 100}%`;
      track.append(bar);
    }
    row.append(label, track); host.append(row);
  }
}
