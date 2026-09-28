interface Voice { id: string; name: string; language: string }
interface Preferences { voice: string; persona: string }

/** Session preferences come from the provider catalogue, never a baked-in voice list. */
export class StudioPreferences {
  private readonly voice: HTMLSelectElement;
  private readonly persona: HTMLTextAreaElement;
  private readonly player: HTMLAudioElement;
  private previewURL: string | null = null;
  readonly ready: Promise<void>;

  constructor(root: HTMLElement, report: (error: unknown) => void) {
    this.voice = root.querySelector<HTMLSelectElement>("#voice")!;
    this.persona = root.querySelector<HTMLTextAreaElement>("#persona")!;
    this.player = root.querySelector<HTMLAudioElement>("#voice-player")!;
    this.ready = this.load().catch(error => { report(error); throw error; });
    void this.ready.catch(() => {});
    this.voice.onchange = this.persona.onchange = () => this.save();
    const preview = root.querySelector<HTMLButtonElement>("#voice-preview")!;
    preview.onclick = async () => {
      preview.disabled = true;
      try {
        await this.ready;
        this.player.pause();
        const text = root.querySelector<HTMLInputElement>("#voice-sample")!.value.trim();
        const response = await fetch("/api/v1/characters/voice-preview", { method: "POST",
          headers: { "content-type": "application/json" }, body: JSON.stringify({ text, voice: this.voice.value }) });
        if (!response.ok) throw new Error((await response.json()).detail ?? "声线试听失败");
        if (this.previewURL) URL.revokeObjectURL(this.previewURL);
        this.player.src = this.previewURL = URL.createObjectURL(await response.blob());
        this.player.hidden = false;
        await this.player.play();
      } catch (error) { report(error); }
      finally { preview.disabled = false; }
    };
  }

  private async load(): Promise<void> {
    const response = await fetch("/api/v1/characters/preferences");
    if (!response.ok) throw new Error("无法读取角色与声线设置");
    const data = await response.json() as Preferences & { voices: Voice[] };
    let saved: Partial<Preferences> = {};
    try { saved = JSON.parse(localStorage.getItem("virea.preferences") ?? "{}"); } catch { /* Use server defaults. */ }
    this.voice.replaceChildren(...data.voices.map(voice => new Option(voice.name, voice.id)));
    this.voice.value = data.voices.some(v => v.id === saved.voice) ? saved.voice! : data.voice;
    this.persona.value = saved.persona ?? data.persona;
    this.voice.disabled = false;
  }

  values(): Preferences { return { voice: this.voice.value, persona: this.persona.value }; }
  private save(): void { localStorage.setItem("virea.preferences", JSON.stringify(this.values())); }
}
