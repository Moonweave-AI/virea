import type { SceneAction, Session } from "../contracts";

export interface TurnRecord {
  sequence: number; prompt: string; response: string; status: string;
  route: Session["route"]; actions: SceneAction[];
}
export interface ConversationRecord { id: string; title: string; updated: number; revision: number; turns: TurnRecord[] }
const storageKey = "virea.motion-studio.history.v1";

export function updateRecord(record: ConversationRecord, value: Session): void {
  for (const event of value.events) {
    if (event.kind === "user_message" && event.sequence > record.revision) {
      record.turns.push({ sequence: event.sequence, prompt: (event as { text?: string }).text ?? "", response: "", status: "thinking", route: null, actions: [] });
    }
  }
  const turn = record.turns.at(-1);
  if (turn) {
    turn.response = value.draft_text; turn.route = value.route;
    turn.actions = value.motion_plan ?? []; turn.status = value.status;
    for (const event of value.events.filter(e => e.sequence > turn.sequence)) {
      if (event.kind === "playback_feedback" && event.feedback?.status === "failed") turn.status = "failed";
      if (event.kind === "interrupted" && !["completed", "failed"].includes(turn.status)) turn.status = "interrupted";
      if (event.kind === "response_finished" && turn.status !== "failed") turn.status = event.interrupted ? "interrupted" : "completed";
    }
    record.title = record.turns[0]?.prompt.slice(0, 36) || "新会话";
  }
  record.revision = Math.max(record.revision, ...value.events.map(e => e.sequence));
  record.updated = Date.now();
}

export function downloadJSON(name: string, value: unknown): void {
  const text = JSON.stringify(value, null, 2), blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob), dialog = document.createElement("dialog");
  const title = document.createElement("h2"), info = document.createElement("p"), actions = document.createElement("div");
  const link = document.createElement("a"), copy = document.createElement("button"), close = document.createElement("button");
  const preview = document.createElement("details"), summary = document.createElement("summary"), content = document.createElement("textarea");
  dialog.setAttribute("aria-label", "导出 JSON"); title.textContent = "导出 JSON";
  info.textContent = `${name} · ${(blob.size / 1024).toFixed(1)} KB`;
  link.href = url; link.download = name; link.textContent = "保存文件";
  copy.textContent = "复制 JSON"; close.textContent = "关闭"; close.onclick = () => dialog.close();
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(text); copy.textContent = "已复制"; }
    catch { preview.open = true; content.select(); info.textContent = "请在下方 JSON 内容中手动复制。"; }
  };
  actions.className = "export-actions"; actions.append(link, copy, close);
  preview.className = "export-preview"; summary.textContent = "查看 JSON";
  content.readOnly = true; content.value = text; content.setAttribute("aria-label", "JSON 内容");
  preview.append(summary, content); dialog.append(title, info, actions, preview);
  dialog.onclose = () => { dialog.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
  document.body.append(dialog); dialog.showModal();
}

export class StudioHistory {
  private records: ConversationRecord[];
  private selected: string | null = null;
  private rendered = "";
  private current: string | null = null;
  private root: HTMLElement;

  constructor(root: HTMLElement) {
    this.root = root;
    try { this.records = JSON.parse(localStorage.getItem(storageKey) ?? "[]"); }
    catch { this.records = []; }
    this.el<HTMLInputElement>("#history-search").oninput = () => this.render();
    this.el("#export-history").onclick = () => downloadJSON("virea-conversation.json", this.records.find(r => r.id === this.selected) ?? this.records);
    this.render();
  }

  private el<T extends HTMLElement>(selector: string): T { return this.root.querySelector<T>(selector)!; }

  update(value: Session): void {
    const revision = Math.max(0, ...value.events.map(e => e.sequence));
    let record = this.records.find(r => r.id === value.id);
    if (record?.revision === revision) return;
    if (!record) {
      record = { id: value.id, title: "新会话", updated: Date.now(), revision: 0, turns: [] };
      this.records.unshift(record);
    }
    updateRecord(record, value);
    this.records = this.records.slice(0, 30);
    this.current = value.id;
    if (!this.selected || !this.records.some(r => r.id === this.selected) || record.turns.length === 1 && record.turns[0]?.status === "thinking") this.selected = value.id;
    try { localStorage.setItem(storageKey, JSON.stringify(this.records)); } catch { /* Current history remains available when storage is full. */ }
    this.el("#workspace-title").textContent = record.title;
    this.render();
  }

  selectCurrent(): void { this.selected = this.current; this.render(); }

  render(): void {
    const search = this.el<HTMLInputElement>("#history-search").value.trim().toLowerCase();
    const filtered = this.records.filter(r => r.turns.some(t => (t.prompt + t.response).toLowerCase().includes(search)) || !search);
    this.el("#session-list").replaceChildren(...filtered.map(record => {
      const button = document.createElement("button"); button.className = "session-item";
      button.setAttribute("aria-current", String(this.selected === record.id));
      button.textContent = record.title;
      button.onclick = () => { this.selected = record.id; this.render(); };
      return button;
    }));
    const record = this.records.find(r => r.id === this.selected);
    const signature = JSON.stringify(record);
    if (signature === this.rendered) return;
    this.rendered = signature;
    this.el("#history-title").textContent = record?.title ?? "还没有记录";
    const log = this.el("#conversation"), nodes: HTMLElement[] = [];
    for (const turn of record?.turns ?? []) {
      const article = document.createElement("article"); article.className = "history-turn";
      const prompt = document.createElement("p"); prompt.className = "user"; prompt.textContent = turn.prompt;
      article.append(prompt);
      if (turn.route) {
        const badge = document.createElement("small"); badge.className = "history-route";
        badge.textContent = `${turn.route.engine === "hybrid" ? "混合表达" : turn.route.engine === "ardy" ? "ARDY · 动作" : "SentiAvatar · 对话"} / ${turn.route.reason}`;
        article.append(badge);
      }
      if (turn.response) { const p = document.createElement("p"); p.textContent = turn.response; article.append(p); }
      if (turn.actions.length) {
        const details = document.createElement("details"), summary = document.createElement("summary");
        const status: Record<string, string> = { completed: "已完成", interrupted: "已打断", failed: "执行失败", error: "执行出错", waiting: "已结束" };
        summary.textContent = `${turn.actions.length} 个动作阶段 · ${status[turn.status] ?? "执行中"}`;
        details.append(summary);
        for (const action of turn.actions) {
          const p = document.createElement("p"); p.className = "motion-description";
          p.textContent = `${action.label ?? action.kind} · ${action.duration_seconds ?? "自动"} 秒\n${action.description ?? ""}`;
          details.append(p);
        }
        article.append(details);
      }
      nodes.push(article);
    }
    log.replaceChildren(...nodes);
    if (this.selected === this.current) log.scrollTop = log.scrollHeight;
  }
}
