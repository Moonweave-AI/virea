interface Voice { id: string; name: string; language: string; seconds?: number; transcript?: string; warnings?: string[] }
interface Preferences { voice?: string; persona: string }
interface Catalogue extends Preferences { voices: Voice[]; speech_error?: string | null }

export function selectedVoice(voices: Voice[], saved?: string, fallback?: string): string {
  return [saved, fallback].find(id => voices.some(voice => voice.id === id)) ?? voices[0]?.id ?? "";
}

async function checked(response: Response): Promise<Response> {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `语音请求失败 (${response.status})`);
  }
  return response;
}

function audioBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]!);
    reader.onerror = () => reject(new Error("无法读取参考音频"));
    reader.readAsDataURL(file);
  });
}

/** Session preferences come from the provider catalogue, never a baked-in voice list. */
export class StudioPreferences {
  private readonly voice: HTMLSelectElement;
  private readonly persona: HTMLTextAreaElement;
  private readonly player: HTMLAudioElement;
  private previewURL: string | null = null;
  private referenceURL: string | null = null;
  private readonly root: HTMLElement;
  private readonly report: (error: unknown) => void;
  private voices: Voice[] = [];
  private busy = false;
  private serviceError: string | null = null;
  private preferredVoice: string | undefined;
  readonly ready: Promise<void>;

  constructor(root: HTMLElement, report: (error: unknown) => void) {
    this.root = root; this.report = report;
    this.voice = root.querySelector<HTMLSelectElement>("#voice")!;
    this.persona = root.querySelector<HTMLTextAreaElement>("#persona")!;
    this.player = root.querySelector<HTMLAudioElement>("#voice-player")!;
    let saved: Partial<Preferences> = {};
    try { saved = JSON.parse(localStorage.getItem("virea.preferences") ?? "{}") ?? {}; } catch { /* Use server defaults. */ }
    if (typeof saved.persona === "string") this.persona.value = saved.persona;
    this.ready = this.load(saved.voice, saved.persona === undefined).catch(error => {
      this.element("#voice-status").textContent = "无法连接语音服务，可在服务启动后刷新声线。";
      report(error);
    });
    this.voice.onchange = () => { this.stopPreview(); this.update(); this.save(); };
    this.persona.onchange = () => this.save();
    this.element("#voice-preview").onclick = () => { void this.operation(() => this.preview()); };
    this.element("#voice-refresh").onclick = () => { void this.operation(() => this.load(this.voice.value)); };
    this.element("#voice-import").onclick = () => { void this.operation(() => this.importVoice()); };
    this.element("#voice-delete").onclick = () => { void this.operation(() => this.deleteVoice()); };
    this.element<HTMLInputElement>("#voice-reference").onchange = () => this.referenceChanged();
    window.addEventListener("pagehide", () => {
      this.stopPreview();
      if (this.referenceURL) URL.revokeObjectURL(this.referenceURL);
    }, { once: true });
  }

  private element<T extends HTMLElement = HTMLElement>(selector: string): T { return this.root.querySelector<T>(selector)!; }

  private async operation(action: () => Promise<void>): Promise<void> {
    if (this.busy) return;
    this.busy = true; this.update();
    this.element("#voice-import-status").textContent = "";
    try { await this.ready; await action(); }
    catch (error) {
      this.element("#voice-import-status").textContent = error instanceof Error ? error.message : String(error);
      this.report(error);
    } finally { this.busy = false; this.update(); }
  }

  private async load(preferred?: string, loadPersona = false): Promise<void> {
    this.preferredVoice = preferred || this.preferredVoice;
    let data: Catalogue;
    try {
      const response = await checked(await fetch("/api/v1/characters/preferences"));
      data = await response.json() as Catalogue;
    } catch (error) {
      this.serviceError = "无法连接语音服务，可在服务启动后刷新声线。";
      this.update(); throw error;
    }
    this.serviceError = data.speech_error ?? null;
    this.voices = data.voices;
    this.voice.replaceChildren(...data.voices.map(voice => new Option(voice.name, voice.id)));
    this.voice.value = selectedVoice(data.voices, this.preferredVoice, data.voice);
    if (loadPersona) this.persona.value = data.persona;
    this.update();
    if (!data.speech_error) this.save();
  }

  private update(): void {
    const selected = this.voices.find(v => v.id === this.voice.value);
    this.voice.disabled = this.busy || !this.voices.length;
    for (const id of ["#voice-preview", "#voice-delete"]) this.element<HTMLButtonElement>(id).disabled = this.busy || !selected;
    for (const id of ["#voice-import", "#voice-refresh"]) this.element<HTMLButtonElement>(id).disabled = this.busy;
    this.element("#voice-status").textContent = this.serviceError ?? (selected
      ? `${selected.name}${selected.seconds ? ` · ${selected.seconds.toFixed(1)} 秒参考录音` : ""} · 从下一次回复生效${selected.warnings?.length ? `。${selected.warnings.join("；")}` : ""}`
      : "尚未导入声线。请添加参考音频与逐字文本，启用 dots.tts 声音克隆。");
  }

  private stopPreview(): void {
    this.player.pause(); this.player.removeAttribute("src"); this.player.hidden = true;
    if (this.previewURL) URL.revokeObjectURL(this.previewURL);
    this.previewURL = null;
  }

  private async preview(): Promise<void> {
    this.stopPreview();
    const text = this.element<HTMLInputElement>("#voice-sample").value.trim();
    if (!text) throw new Error("请输入试听文本");
    const response = await checked(await fetch("/api/v1/characters/voice-preview", { method: "POST",
      headers: { "content-type": "application/json" }, body: JSON.stringify({ text, voice: this.voice.value }) }));
    this.player.src = this.previewURL = URL.createObjectURL(await response.blob());
    this.player.hidden = false;
    await this.player.play();
  }

  private referenceChanged(): void {
    const player = this.element<HTMLAudioElement>("#voice-reference-player");
    player.pause(); player.removeAttribute("src"); player.hidden = true;
    if (this.referenceURL) URL.revokeObjectURL(this.referenceURL);
    this.referenceURL = null;
    const file = this.element<HTMLInputElement>("#voice-reference").files?.[0];
    if (!file) return;
    if (file.size > 12 * 1024 * 1024) { this.report(new Error("参考音频必须小于 12 MiB")); return; }
    player.src = this.referenceURL = URL.createObjectURL(file); player.hidden = false;
    const name = this.element<HTMLInputElement>("#voice-name");
    if (!name.value.trim()) name.value = file.name.replace(/\.[^.]+$/, "").slice(0, 80);
  }

  private async importVoice(): Promise<void> {
    const file = this.element<HTMLInputElement>("#voice-reference").files?.[0];
    const name = this.element<HTMLInputElement>("#voice-name").value.trim();
    const transcript = this.element<HTMLTextAreaElement>("#voice-transcript").value.trim();
    if (!file || !name || !transcript) throw new Error("请选择参考音频，并填写声线名称和录音逐字文本");
    if (!file.size || file.size > 12 * 1024 * 1024) throw new Error("参考音频必须为非空文件且小于 12 MiB");
    this.element("#voice-import-status").textContent = "正在上传并检查参考音频…";
    const response = await checked(await fetch("/api/v1/characters/voices", { method: "POST",
      headers: { "content-type": "application/json" }, body: JSON.stringify({ name, transcript, audio: await audioBase64(file) }) }));
    const voice = await response.json() as Voice;
    this.serviceError = null;
    this.stopPreview();
    this.voices.push(voice); this.voice.add(new Option(voice.name, voice.id)); this.voice.value = voice.id;
    this.save();
    this.element<HTMLInputElement>("#voice-reference").value = "";
    this.element<HTMLInputElement>("#voice-name").value = "";
    this.element<HTMLTextAreaElement>("#voice-transcript").value = "";
    this.referenceChanged();
    this.element("#voice-import-status").textContent = `已导入并选用「${voice.name}」。点击「试听克隆」检查效果。`;
  }

  private async deleteVoice(): Promise<void> {
    const voice = this.voice.value;
    if (!voice) return;
    await checked(await fetch(`/api/v1/characters/voices/${encodeURIComponent(voice)}`, { method: "DELETE" }));
    this.stopPreview();
    this.voices = this.voices.filter(item => item.id !== voice);
    this.voice.replaceChildren(...this.voices.map(item => new Option(item.name, item.id)));
    this.voice.value = selectedVoice(this.voices);
    this.save();
    this.element("#voice-import-status").textContent = "参考声线已删除。";
  }

  values(): Preferences { return { ...(this.voice.value ? { voice: this.voice.value } : {}), persona: this.persona.value }; }
  private save(): void {
    this.preferredVoice = this.voice.value || (this.serviceError ? this.preferredVoice : undefined);
    localStorage.setItem("virea.preferences", JSON.stringify({ ...this.values(), ...(this.preferredVoice ? { voice: this.preferredVoice } : {}) }));
  }
}
