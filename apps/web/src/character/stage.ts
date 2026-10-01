import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM, type VRMHumanBoneName } from "@pixiv/three-vrm";
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from "@pixiv/three-vrm-animation";
import { assertFiniteClip, computeCameraFraming, ensureVRMLookAtQuaternionProxy } from "../viewer-compat";
import { anchorClip, sceneDestination, sampleClip } from "./motion";
import { rotationVector } from "./continuity";
import { PoseRecovery, faceRelease, type PoseSample } from "./recovery";
import { RelaxedIdle } from "./idle";
import { ExpressionTimeline } from "./timeline";
import { SpatialPlayer, type SpatialWindow } from "./spatial";
import { BodyAuthority } from "./body_authority";
import { BehaviorPlayer, reservationMatches } from "./behavior_player";
import { SpeechClock, cueReached } from "./speech_clock";
import { MotionInspection } from "./inspection";
import { PerformanceRecording, mixRecordedAudio } from "./recording";
import type { BodyState, Expression, FaceTrack, PlaybackProgress, BodyProgram, Session } from "./contracts";

export class CharacterStage {
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(35, 1, 0.05, 100);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly resize: ResizeObserver;
  private readonly audio = new AudioContext();
  private readonly gain = this.audio.createGain();
  private readonly analyser = this.audio.createAnalyser();
  private readonly timeline = new ExpressionTimeline(this.audio, this.analyser);
  private readonly speechClock = new SpeechClock();
  private idle: RelaxedIdle | null = null;
  private readonly waveform = new Float32Array(256);
  private prepared = new Map<string, ReturnType<CharacterStage["prepare"]>>();
  private expressionUpdates = new Map<string, Expression>();
  private poseHistory = new Map<THREE.Object3D, { q: THREE.Quaternion; velocity: THREE.Vector3 }>();
  private rest: PoseSample | null = null;
  private authority: BodyAuthority | null = null;
  private behavior: BehaviorPlayer | null = null;
  private previewSpeech = false;
  private activity: BodyProgram | null = null;
  private activityElapsed = 0;
  private recordingId: string | null = null;
  private bodyRecording: SpatialWindow[] = [];
  private speechInfo = { text: "", end: 0, packet_id: null as string | null, stream_id: null as string | null };
  private tape = new PerformanceRecording();
  private turnKey = "";
  private replaying = false;
  private observedHead: THREE.Quaternion | null = null;
  private peakHeadPose: Record<string, unknown> = {};
  private poseMetrics = { head_speed_deg_s: 0, peak_head_speed_deg_s: 0, peak_head_delta_deg: 0,
    peak_head_frame_seconds: 0, peak_head_at_seconds: 0, peak_head_owner: "hold", peak_head_packet: "",
    peak_head_joint: "", head_world_norm: 1, max_joint_speed_deg_s: 0, worst_joint: "" };
  private bodyId: string | null = null;
  private bodyGeneration = 0;
  private observations: NonNullable<BodyState["history"]> = [];
  private observationTime = 0;
  private bodyRecovery: (() => void) | null = null;
  private cachedAudio: { url: string; buffer: AudioBuffer } | null = null;
  private vrm: VRM | null = null;
  private mixer: THREE.AnimationMixer | null = null;
  private action: THREE.AnimationAction | null = null;
  private source: AudioBufferSourceNode | null = null;
  private sampleExpression: (() => void) | null = null;
  private frame = 0;
  private epoch = 0;
  private disposed = false;
  private sceneActions: Promise<void> = Promise.resolve();
  private gaze: string | null = null;
  private gazePoint: THREE.Vector3 | null = null;
  private lastFrame = performance.now();
  private spatial: SpatialPlayer | null = null;
  private hipHeight = 1;
  private cameraRoot = new THREE.Vector3();
  private avatarSize = new THREE.Vector3(2, 2, .5);
  private readonly inspection = new MotionInspection();
  private readonly grid = new THREE.GridHelper(40, 80, 0xd1d5db, 0xe5e7eb);

  constructor(private readonly canvas: HTMLCanvasElement) {
    this.gain.connect(this.audio.destination);
    this.analyser.fftSize = this.waveform.length;
    this.analyser.connect(this.gain);
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene.background = new THREE.Color("#f3f4f6");
    this.scene.fog = new THREE.Fog(0xf3f4f6, 8, 25);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x94a3b8, 2.6));
    const light = new THREE.DirectionalLight(0xffffff, 2.2);
    light.position.set(2, 4, 3);
    this.scene.add(light, this.grid, this.inspection.object);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.MeshStandardMaterial({ color: 0xf3f4f6, roughness: 1 }));
    floor.rotation.x = -Math.PI / 2; floor.position.y = -.015; floor.receiveShadow = true;
    this.scene.add(floor);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    light.castShadow = true; light.shadow.mapSize.set(1024, 1024);
    const ceramic = new THREE.MeshStandardMaterial({ color: 0xe1e6ce, side: THREE.DoubleSide });
    const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.06, 0.16, 24, 1, true), ceramic);
    cup.position.set(1, 0.9, 0.4);
    const handle = new THREE.Mesh(new THREE.TorusGeometry(0.045, 0.012, 8, 24), ceramic);
    handle.position.set(0.085, 0, 0);
    cup.add(handle);
    const stand = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.22, 0.82, 24),
      new THREE.MeshStandardMaterial({ color: 0xcbd0d7 }));
    stand.position.set(1, 0.41, 0.4);
    this.scene.add(cup, stand);
    this.camera.position.set(0, 1.4, 3.6);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.set(0, 1, 0);
    this.controls.enableDamping = true;
    this.resize = new ResizeObserver(() => {
      const width = Math.max(1, canvas.clientWidth), height = Math.max(1, canvas.clientHeight);
      this.renderer.setSize(width, height, false);
      this.camera.aspect = width / height;
      this.camera.setViewOffset(width, height, width > 800 ? 100 : 0, width < 640 ? height * .15 : 0, width, height);
      this.camera.updateProjectionMatrix();
      if (this.vrm) this.resetCamera();
    });
    this.resize.observe(canvas);
    this.render();
  }

  async unlockAudio(): Promise<void> { await this.audio.resume(); }

  async togglePause(): Promise<boolean> {
    if (this.audio.state === "running") await this.audio.suspend();
    else await this.audio.resume();
    return this.audio.state === "suspended";
  }

  setVolume(value: number): void { this.gain.gain.value = THREE.MathUtils.clamp(value, 0, 1); }

  setGrid(visible: boolean): void { this.grid.visible = visible; }
  setSkeleton(visible: boolean): void { this.inspection.object.visible = visible; }
  resetCamera(): void {
    const root = this.rootPosition();
    const width = Math.max(this.canvas.clientWidth, 1), height = Math.max(this.canvas.clientHeight, 1);
    const availableHeight = width < 640 ? .55 : .88;
    const availableWidth = width > 800 ? .7 : .9;
    const framing = computeCameraFraming(this.avatarSize.x / availableWidth, this.avatarSize.y / availableHeight,
      this.avatarSize.z, width / height, THREE.MathUtils.degToRad(this.camera.fov));
    this.controls.target.set(root.x, this.hipHeight, root.z);
    this.camera.position.set(root.x, this.hipHeight + framing.distance * .08, root.z + framing.distance);
    this.controls.update();
  }
  motionRecording() { return this.bodyRecording.length ? this.bodyRecording : this.spatial?.export() ?? []; }

  track(value: Session): void {
    const key = `${value.id}:${value.epoch}`;
    if (key !== this.turnKey) { this.turnKey = key; this.tape = new PerformanceRecording(); this.poseMetrics.peak_head_speed_deg_s = 0; }
    if (!this.replaying && value.status === "waiting" && !this.source && !this.bodyRunning
      && (!value.body_program || ["completed", "failed", "interrupted"].includes(value.body_program.status))) this.tape.finish();
  }
  get replayAvailable(): boolean { return this.tape.ready; }
  get recordedAudio(): boolean { return this.tape.audioSeconds > 0; }
  diagnostics() {
    return { clock_seconds: this.audibleTime(), body_owner: this.authority?.owner ?? "hold", preview: this.replaying,
      phase: this.canvas.dataset.motionPhase ?? "", reason: this.canvas.dataset.behaviorReason ?? "",
      body_status: this.canvas.dataset.bodyStatus ?? "idle", body_active: this.bodyRunning,
      retracting: this.authority?.retracting ?? false, body_elapsed: Number(this.canvas.dataset.bodyElapsed ?? 0),
      body_duration: Number(this.canvas.dataset.bodyDuration ?? 0), body_program: this.bodyId,
      speech: { ...this.speechInfo, active: Boolean(this.source) && this.audibleTime() < this.speechInfo.end,
        remaining_seconds: Math.max(0, this.speechInfo.end - this.audibleTime()) },
      motion_ready: this.authority?.speechReady ?? false, ground_clearance: this.authority?.groundClearance,
      synchronization: this.speechClock.observe(this.audibleTime(), Boolean(this.authority?.speechReady)),
      retarget_max_angle: Number(this.canvas.dataset.retargetMaxAngle ?? 0), ...this.poseMetrics,
      peak_head_pose: this.peakHeadPose, recording: this.tape.summary() };
  }

  async replay(kind: "audio" | "motion" | "synchronized", caption: (text: string) => void,
    progress: (value: PlaybackProgress) => void): Promise<void> {
    const tape = this.tape, { windows, face } = tape.assets(this.hipHeight);
    const cues = kind === "motion" ? [] : tape.audioCues();
    const audio = cues.length ? mixRecordedAudio(this.audio, windows[0]!.seconds, cues) : null;
    this.stop(); this.replaying = true;
    const epoch = this.epoch;
    try {
      await this.perform({ id: this.turnKey, epoch: this.epoch, text: "", audio_url: null,
        audio_seconds: audio?.duration ?? 0, actions: [], motion: null, preview: true,
        end_state: "hold", spatial_windows: kind === "audio" ? undefined : windows }, () => {}, value => {
          const cue = tape.speech.find(c => value.elapsed >= c.at && value.elapsed < c.at + c.seconds);
          caption(kind === "motion" ? "" : cue?.text ?? ""); progress(value);
        }, [null, audio, kind === "audio" ? null : face]);
    } finally {
      if (epoch === this.epoch) {
        this.spatial?.stop(); this.replaying = false; caption("");
      }
    }
  }

  private audibleTime(): number {
    const stamp = this.audio.getOutputTimestamp?.();
    return this.audio.state === "running" && stamp?.contextTime && stamp.performanceTime
      ? Math.min(this.audio.currentTime, stamp.contextTime + (performance.now() - stamp.performanceTime) / 1000)
      : this.audio.currentTime;
  }

  private async loadAudio(url: string): Promise<AudioBuffer> {
    if (this.cachedAudio?.url === url) return this.cachedAudio.buffer;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`语音读取失败 (${response.status})`);
    const buffer = await this.audio.decodeAudioData(await response.arrayBuffer());
    this.cachedAudio = { url, buffer };
    return buffer;
  }

  async loadAvatar(file: File): Promise<void> {
    this.stop();
    const epoch = this.epoch;
    const url = URL.createObjectURL(file);
    try {
      const loader = new GLTFLoader();
      loader.register((parser) => new VRMLoaderPlugin(parser));
      const gltf = await loader.loadAsync(url);
      const vrm = gltf.userData.vrm as VRM | undefined;
      if (!vrm || epoch !== this.epoch || this.disposed) {
        VRMUtils.deepDispose(gltf.scene);
        if (!vrm) throw new Error("请选择包含 humanoid 的 VRM 文件");
        return;
      }
      const reference = await fetch("/api/v1/characters/neutral-pose");
      if (!reference.ok) {
        VRMUtils.deepDispose(vrm.scene);
        throw new Error("自然站姿资源未就绪，请运行角色环境初始化。");
      }
      const pose = await reference.json() as { rotations: Record<string, number[]> };
      if (epoch !== this.epoch || this.disposed) { VRMUtils.deepDispose(vrm.scene); return; }
      if (this.vrm) { this.scene.remove(this.vrm.scene); VRMUtils.deepDispose(this.vrm.scene); }
      this.vrm = vrm;
      this.idle = new RelaxedIdle(vrm, pose.rotations);
      this.spatial = new SpatialPlayer(vrm, () => this.audibleTime());
      this.rest = this.poseSample();
      this.authority = new BodyAuthority(vrm);
      this.observations = [];
      this.idle.start(this.rest);
      this.poseHistory.clear();
      VRMUtils.rotateVRM0(vrm);
      ensureVRMLookAtQuaternionProxy(vrm);
      this.scene.add(vrm.scene);
      vrm.scene.traverse(object => { if (object instanceof THREE.Mesh) { object.castShadow = true; object.receiveShadow = true; } });
      this.hipHeight = this.rootPosition().y;
      new THREE.Box3().setFromObject(vrm.scene).getSize(this.avatarSize);
      this.avatarSize.x = Math.max(this.avatarSize.x, this.hipHeight * 2.1);
      const root = this.rootPosition();
      const offset = root.clone().sub(this.cameraRoot); offset.y = 0;
      this.camera.position.add(offset); this.controls.target.add(offset);
      this.cameraRoot.copy(root);
      this.resetCamera();
    } finally { URL.revokeObjectURL(url); }
  }

  state(): BodyState {
    const pose: BodyState["pose"] = {};
    const vrm = this.vrm;
    if (vrm) for (const name of Object.keys(vrm.humanoid.humanBones)) {
      const node = vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      if (node) pose[name] = node.quaternion.toArray();
    }
    const root = this.rootPosition();
    if (vrm?.meta.metaVersion === "0") for (const q of Object.values(pose)) { q[0] *= -1; q[2] *= -1; }
    return { position: { x: root.x, y: vrm?.scene.position.y ?? 0, z: root.z }, pelvis_height: root.y - (vrm?.scene.position.y ?? 0), yaw: (vrm?.scene.rotation.y ?? 0) - (vrm?.meta.metaVersion === "0" ? Math.PI : 0),
      pose, history: this.observations, gaze_target: this.gaze, behavior: this.spatial?.active ? `body:${this.spatial.phase}` : this.source ? "speaking" : "holding_pose" };
  }

  stopSpeech(): BodyState {
    this.epoch++;
    this.replaying = false;
    this.speechClock.reset();
    this.timeline.stop();
    this.authority?.release();
    this.previewSpeech = false;
    this.speechInfo.end = 0;
    if (this.source) { this.source.stop(); this.source.disconnect(); this.source = null; }
    if (this.action) this.action.paused = true;
    for (const name of ["aa", "ih", "ou", "ee", "oh"]) this.vrm?.expressionManager?.setValue(name, 0);
    return this.state();
  }

  stop(): BodyState {
    const body = this.stopSpeech();
    this.bodyGeneration++; this.bodyId = null; this.bodyRecovery = null;
    this.behavior?.stop(); this.activity = null;
    this.canvas.dataset.bodyStatus = "idle";
    this.spatial?.stop(); this.sceneActions = Promise.resolve(); this.idle?.stop();
    return body;
  }

  get bodyRunning(): boolean { return Boolean(this.behavior?.running || this.authority?.retracting); }

  syncBody(program: BodyProgram | null, sessionId: string,
    onProgress: (value: PlaybackProgress) => void, onFinish: (id: string, status: string, message: string) => void): void {
    this.activity = program;
    const id = program?.id ?? null;
    if (id !== this.bodyId) {
      this.bodyId = id;
      this.activityElapsed = program?.elapsed ?? 0;
    }
    if (id && id !== this.recordingId) {
      if (program?.continuation_of !== this.recordingId) this.bodyRecording = [];
      this.recordingId = id;
    }
    const speaking = () => Boolean(this.source) && this.audibleTime() < this.speechInfo.end;
    const speechReady = () => speaking() && Boolean(this.authority?.speechReady);
    const needed = () => speaking() || Boolean(this.activity && ["ready", "playing", "settling"].includes(this.activity.status)
      && (this.activity.completion_mode === "observed" || Boolean(this.activity.ending) || this.activity.recovery_required || this.activityElapsed < this.activity.actions.reduce((sum, a) => sum + (a.duration_seconds ?? 0), 0) - 1e-5));
    if (this.behavior?.running || !needed() || this.disposed) return;
    const player = this.behavior = new BehaviorPlayer({
      state: () => this.state(), hipHeight: () => this.hipHeight, needed,
      canStart: () => true,
      speech: () => this.speechClock.observe(this.audibleTime(), Boolean(this.authority?.speechReady)),
      report: slot => {
        this.canvas.dataset.behaviorSlot = slot.id;
        this.canvas.dataset.behaviorReason = slot.reason;
        this.canvas.dataset.bodyProgram = slot.program_id ?? "";
      },
      play: async ({ slot, windows }, current) => {
        this.tape.driver(this.audibleTime(), slot.owner, slot.reason, slot.id);
        const total = slot.settling ? slot.seconds : this.activity?.completion_mode === "observed"
          ? slot.activity_end : this.activity?.actions.reduce((sum, a) => sum + (a.duration_seconds ?? 0), 0) ?? slot.seconds;
        const progress = (elapsed: number) => {
          this.canvas.dataset.bodyStatus = slot.settling ? "settling" : slot.advances_activity ? "playing" : "idle";
          this.canvas.dataset.bodyElapsed = ((slot.settling ? 0 : slot.activity_start) + (slot.advances_activity || slot.settling ? elapsed : 0)).toFixed(3);
          this.canvas.dataset.bodyDuration = total.toFixed(3);
          if (!this.source && slot.owner === "ardy") onProgress({ elapsed: (slot.settling ? 0 : slot.activity_start) + elapsed, audioDuration: 0, motionDuration: total, paused: this.audio.state !== "running" });
        };
        if (windows) {
          await this.spatial!.run({ id: slot.id, epoch: this.epoch, text: "", audio_url: null, audio_seconds: 0,
            motion: null, actions: [], spatial_windows: windows, temporal: true, end_state: "hold" }, this.state(), this.hipHeight, progress);
          if (current() && slot.program_id === this.recordingId) {
            const offset = this.bodyRecording.reduce((sum, window) => sum + window.seconds, 0);
            const total = offset + windows.reduce((sum, window) => sum + window.seconds, 0);
            for (const window of windows) this.bodyRecording.push({ ...window, sequence: this.bodyRecording.length,
              offset: offset + window.offset, phase_offset: offset + (window.phase_offset ?? 0), total_seconds: total });
            for (const window of this.bodyRecording) window.total_seconds = total;
          }
        } else {
          this.spatial?.stop();
          const start = this.audibleTime();
          while (current() && this.audibleTime() - start < slot.seconds) {
            if (!needed() || !reservationMatches(slot, this.activity)
              || speechReady() !== slot.speech_available
              || slot.waiting_for && cueReached(slot.waiting_for, this.activity?.origin_epoch,
                this.speechClock.observe(this.audibleTime(), Boolean(this.authority?.speechReady)))
              || slot.owner === "sentiavatar" && (this.audibleTime() >= this.speechInfo.end
                || slot.speech_packet_id && slot.speech_packet_id !== this.speechInfo.packet_id)) break;
            progress(this.audibleTime() - start);
            await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
          }
        }
        if (slot.program_id === this.activity?.id) {
          this.activityElapsed = slot.activity_end;
          if (slot.terminal) { this.activity!.status = "completed"; this.authority?.commitRest(); }
        }
      },
    });
    void player.run(sessionId).catch(error => {
      if (!(error instanceof DOMException && error.name === "AbortError")) onFinish(id ?? "", "failed", String(error));
    }).finally(() => {
      if (this.behavior === player) {
        this.spatial?.stop();
        this.canvas.dataset.bodyStatus = this.activity?.status ?? "idle";
      }
    });
  }

  private prepare(packet: Expression) {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
    const checked = async (url: string) => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`表达资源读取失败 (${response.status})`);
      return response;
    };
    return Promise.all([
      packet.motion ? loader.loadAsync(packet.motion.vrma_url) : null,
      packet.audio_url ? this.loadAudio(packet.audio_url) : null,
      packet.motion ? checked(`/api/v1/characters/results/${encodeURIComponent(packet.motion.result_id)}/face`).then(r => r.json() as Promise<FaceTrack>) : null,
    ]);
  }

  private resourceKey(packet: Expression): string {
    return `${packet.id}|${packet.audio_url}|${packet.motion?.result_id}`;
  }

  preload(packet: Expression): ReturnType<CharacterStage["prepare"]> {
    this.expressionUpdates.set(packet.id, packet);
    while (this.expressionUpdates.size > 6) this.expressionUpdates.delete(this.expressionUpdates.keys().next().value!);
    const key = this.resourceKey(packet);
    let value = this.prepared.get(key);
    if (!value) {
      value = this.prepare(packet);
      this.prepared.set(key, value);
      while (this.prepared.size > 6) this.prepared.delete(this.prepared.keys().next().value!);
      const epoch = this.epoch;
      void value.then(([, audio]) => {
        if (epoch === this.epoch && !this.disposed) this.timeline.register(packet, audio);
      }).catch(() => {});
      void value.catch(() => { this.prepared.delete(key); });
    }
    return value;
  }

  async perform(packet: Expression, onStart: () => void,
    onProgress: (value: PlaybackProgress) => void = () => {},
    prepared?: [null, AudioBuffer | null, FaceTrack | null]): Promise<{ audio_seconds: number; motion_seconds: number }> {
    if (!this.vrm || !this.authority) throw new Error("请先载入 VRM");
    const epoch = this.epoch;
    const current = () => epoch === this.epoch && !this.disposed;
    let [gltf, audio, face] = prepared ?? await this.preload(packet).catch(error => {
      if (!packet.independent_speech || !packet.motion) throw error;
      return this.preload({ ...packet, motion: null });
    });
    this.expressionUpdates.set(packet.id, packet);
    if (!current()) throw new DOMException("Interrupted", "AbortError");
    // A missing window must not advertise the previous window's gesture as
    // available. The authority retains the rendered pose for a smooth handoff.
    if (!gltf) this.authority.release();
    this.previewSpeech = Boolean(packet.preview && gltf);
    if (audio && this.audio.state !== "running") throw new Error("音频暂停，请点击继续声音后重试");
    const manager = this.vrm.expressionManager;
    let faceTrack = face;
    let heldFace = new Map<string, number>();
    let duration = audio?.duration ?? 0, motionScale = 1;
    const attach = () => {
      const native = face?.arkit;
      faceTrack = native && native.names.filter(name => manager?.getExpression(name)).length >= 40
        ? { ...face!, names: native.names, values: native.values } : face;
      heldFace = new Map(faceTrack?.names.map(name => [name, manager?.getValue(name) ?? 0]) ?? []);
      if (!gltf) return;
      const animation = gltf.userData.vrmAnimations?.[0];
      if (!animation) throw new Error("动作资源缺少 VRMA 动画");
      const hips = this.vrm!.humanoid.getNormalizedBoneNode("hips")!;
      const clip = anchorClip(createVRMAnimationClip(animation, this.vrm!), hips);
      assertFiniteClip(clip);
      duration = audio?.duration ?? clip.duration;
      motionScale = duration > 0 ? clip.duration / duration : 1;
      this.authority!.beginSpeech();
      this.authority!.capture(() => {
        this.mixer?.stopAllAction(); this.mixer?.uncacheRoot(this.vrm!.scene);
        this.mixer = new THREE.AnimationMixer(this.vrm!.scene);
        this.action = this.mixer.clipAction(clip);
        this.action.setLoop(THREE.LoopOnce, 1); this.action.clampWhenFinished = true; this.action.play();
        sampleClip(this.mixer, this.action, 0);
      });
    };
    attach();
    let attaching = false;
    let start = this.audio.currentTime + .04;
    if (audio && packet.stream_id) {
      const scheduled = this.timeline.begin(packet, audio);
      this.source = scheduled.source; start = scheduled.start;
      this.canvas.dataset.streamUnderruns = String(this.timeline.underruns);
    } else if (audio) {
      this.source = this.audio.createBufferSource(); this.source.buffer = audio;
      this.source.connect(this.analyser); this.source.start(start);
    }
    while (current() && this.audibleTime() < start) await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    if (!current()) throw new DOMException("Interrupted", "AbortError");
    onStart();
    this.speechInfo = { text: packet.caption ?? packet.text, end: start + duration, packet_id: packet.id, stream_id: packet.stream_id ?? null };
    if (!packet.preview) this.speechClock.begin(packet, start, duration);
    if (!packet.preview && audio) this.tape.addSpeech(packet, start, audio.duration, audio);
    // Replay packets may carry a program. Live behavior reservations have their own lifetime.
    const hasBody = Boolean(packet.actions.length || packet.spatial_windows?.length);
    if (hasBody) this.sceneActions = this.executeActions(packet, current, (elapsed, total) => {
      if (!audio) onProgress({ elapsed, audioDuration: 0, motionDuration: total, paused: this.audio.state !== "running" });
    });
    const actions = this.sceneActions; void actions.catch(() => {});
    const release = packet.continues || packet.preview ? 0 : .32;
    const sample = (elapsed: number) => {
      const time = Math.min(elapsed, duration);
      if (gltf && this.mixer && this.action) this.authority!.capture(() => sampleClip(this.mixer!, this.action!, time * motionScale));
      if (faceTrack) {
        this.applyFace(faceTrack, audio ? time * Math.max(0, faceTrack.values.length - 1) / (faceTrack.fps * audio.duration) : time);
        if (elapsed < .1) for (const [name, value] of heldFace)
          manager?.setValue(name, THREE.MathUtils.lerp(value, manager.getValue(name) ?? 0, THREE.MathUtils.smootherstep(elapsed, 0, .1)));
        if (elapsed >= duration && !packet.continues) for (const name of faceTrack.names)
          manager?.setValue(name, (manager.getValue(name) ?? 0) * faceRelease(name, elapsed - duration, release));
      } else if (audio) {
        this.analyser.getFloatTimeDomainData(this.waveform);
        const rms = Math.sqrt(this.waveform.reduce((sum, value) => sum + value * value, 0) / this.waveform.length);
        manager?.setValue("aa", Math.min(1, rms * 5));
      }
    };
    // Sample and present in the same render callback. A separate RAF producer
    // made the visible source one frame old and amplified timing hitches.
    const sampling: { failure: { error: unknown } | null } = { failure: null };
    const present = () => {
      try { if (current()) sample(Math.max(0, this.audibleTime() - start)); }
      catch (error) { sampling.failure = { error }; }
    };
    this.sampleExpression = present;
    try {
      while (current() && this.audibleTime() - start < duration + release) {
        if (sampling.failure) throw sampling.failure.error;
        const elapsed = Math.max(0, this.audibleTime() - start);
        const update = this.expressionUpdates.get(packet.id);
        if (!gltf && update?.motion && !attaching && elapsed < duration) {
          attaching = true;
          void this.preload(update).then(([loaded, , track]) => {
            if (!current() || this.audibleTime() >= start + duration) return;
            gltf = loaded; face = track; attach();
            this.canvas.dataset.motionAttachedAt = String(this.audibleTime() - start);
            // The next sample uses the elapsed audio time, never restarts the gesture.
          }).catch(() => { /* Optional motion failure does not interrupt speech. */ });
        }
        onProgress({ elapsed, audioDuration: audio?.duration ?? 0, motionDuration: duration, paused: this.audio.state !== "running" });
        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      }
      if (current()) sample(duration + release);
      if (hasBody && !packet.continues) await actions;
      if (!current()) throw new DOMException("Interrupted", "AbortError");
      return { audio_seconds: audio?.duration ?? 0, motion_seconds: duration };
    } finally {
      if (this.sampleExpression === present) this.sampleExpression = null;
      if (current()) {
        this.previewSpeech = false;
        if (this.source) { this.source.stop(); this.source.disconnect(); this.source = null; }
        if (this.action) this.action.paused = true;
        if (!packet.continues) {
          this.authority.release();
          if (!packet.preview && (!this.activity || ["completed", "failed", "interrupted"].includes(this.activity.status))) {
            this.authority.retract();
            if (this.authority.retracting) {
              this.canvas.dataset.behaviorReason = "本轮手势完成，回到交流前的稳定支撑姿态";
              this.tape.driver(this.audibleTime(), "retraction", this.canvas.dataset.behaviorReason, packet.id);
            }
          }
        }
        if (!face) for (const name of ["aa", "oh", "ou"]) manager?.setValue(name, 0);
        this.timeline.complete(packet.id);
      }
    }
  }

  dispose(): void {
    this.stop(); this.disposed = true; cancelAnimationFrame(this.frame);
    this.resize.disconnect(); this.controls.dispose();
    this.mixer?.stopAllAction();
    this.cachedAudio = null;
    this.prepared.clear(); this.poseHistory.clear(); this.rest = null;
    VRMUtils.deepDispose(this.scene);
    this.renderer.dispose(); void this.audio.close();
  }

  private rootPosition(): THREE.Vector3 {
    const hips = this.vrm?.humanoid.getNormalizedBoneNode("hips");
    this.vrm?.scene.updateMatrixWorld(true);
    return hips?.getWorldPosition(new THREE.Vector3()) ?? new THREE.Vector3();
  }

  private poseSample(): PoseSample {
    const rotations = new Map<THREE.Object3D, THREE.Quaternion>();
    if (this.vrm) for (const name of Object.keys(this.vrm.humanoid.humanBones)) {
      const bone = this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      if (bone) rotations.set(bone, bone.quaternion.clone());
    }
    return { rotations, position: this.vrm?.humanoid.getNormalizedBoneNode("hips")?.position.clone() ?? new THREE.Vector3() };
  }

  private applyFace(face: FaceTrack, seconds: number): void {
    const cursor = Math.min(face.values.length - 1, Math.max(0, seconds * face.fps));
    const lower = Math.floor(cursor), upper = Math.min(lower + 1, face.values.length - 1);
    face.names.forEach((name, index) => {
      const manager = this.vrm?.expressionManager;
      if (manager?.getExpression(name)) manager.setValue(name,
        THREE.MathUtils.lerp(face.values[lower]?.[index] ?? 0, face.values[upper]?.[index] ?? 0, cursor - lower));
    });
  }

  private async executeActions(packet: Expression, current: () => boolean,
    onProgress: (elapsed: number, duration: number) => void): Promise<void> {
    for (const action of packet.actions) {
      if (!current() || !this.vrm) return;
      if (action.kind === "stop") { this.spatial?.stop(); this.gaze = null; this.gazePoint = null; continue; }
      if (action.kind === "look_at") {
        if (!action.position) throw new Error("场景动作缺少目标位置");
        this.gaze = action.target_id;
        this.gazePoint = sceneDestination(action.position);
      }
    }
    if (packet.spatial_windows?.length || packet.actions.some(action => !["look_at", "stop"].includes(action.kind))) {
      if (!this.vrm || !current()) return;
        this.idle?.stop();
        let duration = 0;
        try {
          await this.spatial!.run(packet, this.state(), this.hipHeight, (elapsed, total) => {
            duration = total; onProgress(elapsed, total);
            this.canvas.dataset.motionPhase = this.spatial!.phase;
            this.canvas.dataset.motionPhaseIndex = String(this.spatial!.phaseIndex);
          });
        } finally {
          this.canvas.dataset.spatialUnderruns = String(this.spatial!.underruns);
          this.canvas.dataset.spatialAction = "program";
          this.canvas.dataset.contactError = String(this.spatial!.contactError ?? "");
          this.canvas.dataset.contactState = JSON.stringify(this.spatial!.contactState);
          if (packet.end_state !== "hold" && this.rest && current()) {
            const pose = this.poseSample();
            const hips = this.vrm.humanoid.getNormalizedBoneNode("hips")!;
            const before = { ...pose, rotations: new Map([...pose.rotations].map(([bone, q]) => {
              const velocity = this.poseHistory.get(bone)?.velocity.clone() ?? new THREE.Vector3();
              const speed = velocity.length();
              const previous = speed > 0 ? new THREE.Quaternion().setFromAxisAngle(velocity.divideScalar(speed), -speed / 60).multiply(q) : q.clone();
              return [bone, previous];
            })) };
            const recovery = new PoseRecovery(hips, before, pose, this.rest, 1 / 60);
            const start = this.audibleTime();
            this.bodyRecovery = () => recovery.apply(this.audibleTime() - start);
            while (current() && this.audibleTime() - start < recovery.duration) {
              onProgress(duration + this.audibleTime() - start, duration + recovery.duration);
              await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
            }
            if (current()) {
              recovery.apply(recovery.duration);
              this.idle?.start(this.poseSample()); this.bodyRecovery = null;
            }
            duration += recovery.duration;
          }
        }
    }
  }

  private render = (): void => {
    if (this.disposed) return;
    const now = performance.now();
    const dt = Math.min((now - this.lastFrame) / 1000, 0.1);
    this.lastFrame = now;
    if (this.vrm) {
      this.sampleExpression?.();
      const owner = this.behavior?.running ? this.behavior.owner : this.spatial?.active ? "ardy" : this.previewSpeech ? "sentiavatar" : "hold";
      this.authority?.render(owner, this.audio.state === "running" ? dt : 0,
        () => this.spatial?.update(false), Boolean(this.spatial?.active));
      this.bodyRecovery?.();
      this.canvas.dataset.bodyOwner = this.authority?.owner ?? "hold";
      this.canvas.dataset.bodyContributors = this.authority?.owner === "hold" ? "0" : "1";
      if (this.audio.state === "running" && this.audibleTime() - this.observationTime >= .05) {
        const { history, gaze_target, behavior, ...observation } = this.state();
        this.observations.push(observation);
        if (this.observations.length > 40) this.observations.shift();
        this.observationTime = Math.max(this.observationTime + .05, this.audibleTime() - .05);
        this.canvas.dataset.bodyPosition = JSON.stringify(observation.position);
        this.canvas.dataset.speechActive = String(Boolean(this.source));
        this.canvas.dataset.mouthValue = String(this.vrm.expressionManager?.getValue("aa") ?? 0);
        this.canvas.dataset.groundClearance = String(this.authority?.groundClearance ?? "");
        this.canvas.dataset.pelvisHeight = String(observation.pelvis_height ?? "");
        if (!this.replaying) this.tape.observe(this.audibleTime(), this.state(), Object.fromEntries(
          Object.keys(this.vrm.expressionManager?.expressionMap ?? {}).map(name => [name, this.vrm!.expressionManager!.getValue(name) ?? 0])), this.authority?.owner ?? "hold");
      }
      let maxSpeed = 0, worstJoint = "";
      const changes: { name: string; angle: number; before: number[]; after: number[] }[] = [];
      if (dt > 0 && this.audio.state === "running") for (const name of Object.keys(this.vrm.humanoid.humanBones)) {
        const bone = this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
        if (!bone) continue;
        const previous = this.poseHistory.get(bone);
        const velocity = previous ? rotationVector(bone.quaternion.clone().multiply(previous.q.clone().invert())).divideScalar(dt) : new THREE.Vector3();
        if (previous) changes.push({ name, angle: THREE.MathUtils.radToDeg(velocity.length() * dt),
          before: previous.q.toArray(), after: bone.quaternion.toArray() });
        if (velocity.length() > maxSpeed) { maxSpeed = velocity.length(); worstJoint = name; }
        this.poseHistory.set(bone, { q: bone.quaternion.clone(), velocity });
      }
      if (this.gazePoint) this.vrm.lookAt?.lookAt(this.gazePoint);
      this.vrm.update(dt);
      this.vrm.scene.updateMatrixWorld(true);
      const head = this.vrm.humanoid.getNormalizedBoneNode("head")?.getWorldQuaternion(new THREE.Quaternion());
      if (head && dt > 0 && this.audio.state === "running") {
        // Matrix decomposition under nonuniform avatar scales is not guaranteed
        // to return a unit quaternion; angleTo assumes both operands are unit.
        const headNorm = head.length(); head.normalize();
        const angle = this.observedHead ? THREE.MathUtils.radToDeg(head.angleTo(this.observedHead)) : 0;
        const speed = angle / dt;
        if (speed > this.poseMetrics.peak_head_speed_deg_s) this.peakHeadPose = {
          before: this.observedHead?.toArray(), after: head.toArray(),
          joints: changes.sort((a, b) => b.angle - a.angle).slice(0, 8),
        };
        this.poseMetrics = { head_speed_deg_s: speed, peak_head_speed_deg_s: Math.max(speed, this.poseMetrics.peak_head_speed_deg_s),
          head_world_norm: headNorm,
          peak_head_delta_deg: speed > this.poseMetrics.peak_head_speed_deg_s ? angle : this.poseMetrics.peak_head_delta_deg,
          peak_head_frame_seconds: speed > this.poseMetrics.peak_head_speed_deg_s ? dt : this.poseMetrics.peak_head_frame_seconds,
          peak_head_at_seconds: speed > this.poseMetrics.peak_head_speed_deg_s ? this.tape.elapsed(this.audibleTime()) : this.poseMetrics.peak_head_at_seconds,
          peak_head_owner: speed > this.poseMetrics.peak_head_speed_deg_s ? this.authority?.owner ?? "hold" : this.poseMetrics.peak_head_owner,
          peak_head_packet: speed > this.poseMetrics.peak_head_speed_deg_s ? this.speechInfo.packet_id ?? "" : this.poseMetrics.peak_head_packet,
          peak_head_joint: speed > this.poseMetrics.peak_head_speed_deg_s ? worstJoint : this.poseMetrics.peak_head_joint,
          max_joint_speed_deg_s: THREE.MathUtils.radToDeg(maxSpeed), worst_joint: worstJoint };
        this.observedHead = head;
        this.canvas.dataset.headSpeed = speed.toFixed(2);
      }
      if (this.spatial?.active) {
        this.canvas.dataset.retargetMaxAngle = this.inspection.update(this.vrm, this.spatial.joints).toFixed(2);
        this.canvas.dataset.motionPhase = this.spatial.phase;
        this.canvas.dataset.motionPhaseIndex = String(this.spatial.phaseIndex);
      }
      const root = this.rootPosition();
      const follow = root.clone().sub(this.cameraRoot); follow.y = 0;
      this.camera.position.add(follow); this.controls.target.add(follow);
      this.cameraRoot.copy(root);
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.canvas.dataset.characterRendering = "true";
    this.frame = requestAnimationFrame(this.render);
  };
}
