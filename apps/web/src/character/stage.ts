import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM, type VRMHumanBoneName } from "@pixiv/three-vrm";
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from "@pixiv/three-vrm-animation";
import { assertFiniteClip, ensureVRMLookAtQuaternionProxy } from "../viewer-compat";
import { anchorClip, sceneDestination, sampleClip } from "./motion";
import { RotationBridge, rotationVector } from "./continuity";
import { PoseRecovery, faceRelease, type PoseSample } from "./recovery";
import type { BodyState, Expression, FaceTrack, SceneAction, PlaybackProgress } from "./contracts";

export class CharacterStage {
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(35, 1, 0.05, 100);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly resize: ResizeObserver;
  private readonly audio = new AudioContext();
  private readonly gain = this.audio.createGain();
  private readonly analyser = this.audio.createAnalyser();
  private readonly waveform = new Float32Array(256);
  private prepared = new Map<string, ReturnType<CharacterStage["prepare"]>>();
  private poseHistory = new Map<THREE.Object3D, { q: THREE.Quaternion; velocity: THREE.Vector3 }>();
  private rest: PoseSample | null = null;
  private cachedAudio: { url: string; buffer: AudioBuffer } | null = null;
  private vrm: VRM | null = null;
  private mixer: THREE.AnimationMixer | null = null;
  private action: THREE.AnimationAction | null = null;
  private source: AudioBufferSourceNode | null = null;
  private frame = 0;
  private epoch = 0;
  private disposed = false;
  private gaze: string | null = null;
  private gazePoint: THREE.Vector3 | null = null;
  private lastFrame = performance.now();

  constructor(private readonly canvas: HTMLCanvasElement) {
    this.gain.connect(this.audio.destination);
    this.analyser.fftSize = this.waveform.length;
    this.analyser.connect(this.gain);
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene.background = new THREE.Color("#13221f");
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x455e57, 2.6));
    const light = new THREE.DirectionalLight(0xffffff, 2.2);
    light.position.set(2, 4, 3);
    this.scene.add(light, new THREE.GridHelper(16, 32, 0x476e61, 0x263e35));
    const ceramic = new THREE.MeshStandardMaterial({ color: 0xe1e6ce, side: THREE.DoubleSide });
    const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.06, 0.16, 24, 1, true), ceramic);
    cup.position.set(1, 0.9, 0.4);
    const handle = new THREE.Mesh(new THREE.TorusGeometry(0.045, 0.012, 8, 24), ceramic);
    handle.position.set(0.085, 0, 0);
    cup.add(handle);
    const stand = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.22, 0.82, 24),
      new THREE.MeshStandardMaterial({ color: 0x455e57 }));
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
      this.camera.updateProjectionMatrix();
    });
    this.resize.observe(canvas);
    this.render();
  }

  async unlockAudio(): Promise<void> { await this.audio.resume(); }

  async togglePause(): Promise<void> {
    if (this.audio.state === "running") await this.audio.suspend();
    else await this.audio.resume();
  }

  setVolume(value: number): void { this.gain.gain.value = THREE.MathUtils.clamp(value, 0, 1); }

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
      if (this.vrm) { this.scene.remove(this.vrm.scene); VRMUtils.deepDispose(this.vrm.scene); }
      this.vrm = vrm;
      // Establish a relaxed initial pose once; later responses retain executed bones.
      for (const [name, angle] of [["leftUpperArm", -1.35], ["rightUpperArm", 1.35]] as const) {
        vrm.humanoid.getNormalizedBoneNode(name)?.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), angle);
      }
      for (const [name, angle] of [["leftLowerArm", -0.12], ["rightLowerArm", 0.12]] as const) {
        vrm.humanoid.getNormalizedBoneNode(name)?.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), angle);
      }
      this.rest = this.poseSample();
      // Retain the model's hand shape instead of straightening every finger on release.
      for (const name of Object.keys(vrm.humanoid.humanBones)) {
        if (/(Thumb|Index|Middle|Ring|Little)/.test(name)) {
          const bone = vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
          if (bone) this.rest.rotations.delete(bone);
        }
      }
      this.poseHistory.clear();
      VRMUtils.rotateVRM0(vrm);
      ensureVRMLookAtQuaternionProxy(vrm);
      this.scene.add(vrm.scene);
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
    return { position: { x: root.x, y: 0, z: root.z }, yaw: vrm?.scene.rotation.y ?? 0,
      pose, gaze_target: this.gaze, behavior: this.source ? "speaking" : "holding_pose" };
  }

  stop(): BodyState {
    this.epoch++;
    if (this.source) { this.source.stop(); this.source.disconnect(); this.source = null; }
    if (this.action) this.action.paused = true;
    return this.state();
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

  preload(packet: Expression): Promise<unknown> {
    const key = this.resourceKey(packet);
    let value = this.prepared.get(key);
    if (!value) {
      value = this.prepare(packet);
      this.prepared.set(key, value);
      while (this.prepared.size > 3) this.prepared.delete(this.prepared.keys().next().value!);
      void value.catch(() => { this.prepared.delete(key); });
    }
    return value;
  }

  async perform(packet: Expression, onStart: () => void,
    onProgress: (value: PlaybackProgress) => void = () => {}): Promise<{ audio_seconds: number; motion_seconds: number }> {
    if (!this.vrm) throw new Error("请先载入 VRM");
    const epoch = this.epoch;
    const current = () => epoch === this.epoch && !this.disposed;
    const [gltf, audio, face] = await (this.prepared.get(this.resourceKey(packet)) ?? this.prepare(packet));
    if (!current()) throw new DOMException("Interrupted", "AbortError");
    if (audio && this.audio.state !== "running") throw new Error("音频暂停，请点击继续声音后重试");
    let duration = 0;
    let motionScale = 1;
    let held: Map<THREE.Object3D, THREE.Quaternion> = new Map();
    let heldHips: THREE.Vector3 | null = null;
    const bridges = new Map<THREE.Object3D, RotationBridge>();
    let recovery: PoseRecovery | null = null;
    if (gltf) {
      const animation = gltf.userData.vrmAnimations?.[0];
      if (!animation) throw new Error("动作资源缺少 VRMA 动画");
      const hips = this.vrm.humanoid.getNormalizedBoneNode("hips");
      if (!hips) throw new Error("VRM 缺少 hips");
      let clip = createVRMAnimationClip(animation, this.vrm);
      assertFiniteClip(clip);
      clip = anchorClip(clip, hips);
      duration = audio?.duration ?? clip.duration;
      motionScale = duration > 0 ? clip.duration / duration : 1;
      for (const name of Object.keys(this.vrm.humanoid.humanBones)) {
        const bone = this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
        if (bone) held.set(bone, bone.quaternion.clone());
      }
      const position = hips.position.clone();
      heldHips = position.clone();
      this.mixer?.stopAllAction();
      this.mixer?.uncacheRoot(this.vrm.scene);
      for (const [bone, quaternion] of held) bone.quaternion.copy(quaternion);
      hips.position.copy(position);
      this.mixer = new THREE.AnimationMixer(this.vrm.scene);
      this.action = this.mixer.clipAction(clip);
      this.action.setLoop(THREE.LoopOnce, 1);
      this.action.clampWhenFinished = true;
      this.action.play();
      sampleClip(this.mixer, this.action, 0);
      const first = new Map([...held.keys()].map(bone => [bone, bone.quaternion.clone()]));
      sampleClip(this.mixer, this.action, motionScale / 120);
      for (const [bone, q] of held) {
        const incoming = first.get(bone)!;
        const velocity = rotationVector(bone.quaternion.clone().multiply(incoming.clone().invert())).multiplyScalar(120);
        bridges.set(bone, new RotationBridge(q, incoming, this.poseHistory.get(bone)?.velocity, velocity));
        bone.quaternion.copy(q);
      }
      hips.position.copy(position);
    }
    const sampleMotion = (elapsed: number) => {
      if (!gltf || !this.mixer || !this.action) return;
      sampleClip(this.mixer, this.action, elapsed * motionScale);
      for (const [bone, bridge] of bridges) bridge.apply(bone.quaternion, elapsed);
      const hips = this.vrm!.humanoid.getNormalizedBoneNode("hips");
      if (hips && heldHips) hips.position.lerpVectors(heldHips, hips.position.clone(), THREE.MathUtils.smoothstep(elapsed, 0, 0.2));
    };
    if (gltf && this.rest && duration > 0) {
      const dt = Math.min(1 / 120, duration);
      sampleMotion(duration - dt);
      const before = this.poseSample();
      sampleMotion(duration);
      recovery = new PoseRecovery(this.vrm.humanoid.getNormalizedBoneNode("hips")!, before, this.poseSample(), this.rest, dt);
      // Endpoint sampling is planning, not an executed jump before audio starts.
      for (const [bone, q] of held) bone.quaternion.copy(q);
      if (heldHips) this.vrm.humanoid.getNormalizedBoneNode("hips")?.position.copy(heldHips);
    }
    const start = this.audio.currentTime + 0.04;
    if (audio) {
      this.source = this.audio.createBufferSource();
      this.source.buffer = audio;
      this.source.connect(this.analyser);
      this.source.start(start);
    }
    while (current() && this.audibleTime() < start) await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    if (!current()) throw new DOMException("Interrupted", "AbortError");
    onStart();
    const actions = this.executeActions(packet.actions, current);
    const motionDuration = duration + (recovery?.duration ?? 0);
    const end = Math.max(motionDuration, audio?.duration ?? 0);
    const sample = (elapsed: number) => {
      const tail = Math.max(0, elapsed - duration);
      const hips = this.vrm!.humanoid.getNormalizedBoneNode("hips");
      if (recovery && hips && elapsed >= duration) recovery.apply(tail);
      else sampleMotion(Math.min(elapsed, duration));
      if (face) {
        const time = Math.min(elapsed, duration);
        this.applyFace(face, audio ? time * Math.max(0, face.values.length - 1) / (face.fps * audio.duration) : time);
        if (recovery && elapsed >= duration) for (const name of face.names) {
          const manager = this.vrm!.expressionManager;
          manager?.setValue(name, (manager.getValue(name) ?? 0) * faceRelease(name, tail, recovery.duration));
        }
      } else if (audio && this.audio.state === "running") {
        this.analyser.getFloatTimeDomainData(this.waveform);
        const rms = Math.sqrt(this.waveform.reduce((sum, value) => sum + value * value, 0) / this.waveform.length);
        const manager = this.vrm!.expressionManager;
        const previous = manager?.getValue("aa") ?? 0;
        manager?.setValue("aa", THREE.MathUtils.lerp(previous, Math.min(1, rms * 5), 0.4));
      }
    };
    try {
      while (current() && this.audibleTime() - start < end) {
        const elapsed = Math.max(0, this.audibleTime() - start);
        sample(elapsed);
        onProgress({ elapsed, audioDuration: audio?.duration ?? 0, motionDuration, paused: this.audio.state !== "running" });
        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      }
      if (current()) sample(end);
      await actions;
      if (!current()) throw new DOMException("Interrupted", "AbortError");
      onProgress({ elapsed: end, audioDuration: audio?.duration ?? 0, motionDuration, paused: false });
      return { audio_seconds: audio?.duration ?? 0, motion_seconds: motionDuration };
    } finally {
      if (current()) {
        if (this.source) { this.source.stop(); this.source.disconnect(); this.source = null; }
        if (this.action) this.action.paused = true;
        if (!face) for (const name of ["aa", "oh", "ou"]) this.vrm?.expressionManager?.setValue(name, 0);
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
    face.names.forEach((name, index) => this.vrm?.expressionManager?.setValue(name,
      THREE.MathUtils.lerp(face.values[lower]?.[index] ?? 0, face.values[upper]?.[index] ?? 0, cursor - lower)));
  }

  private async executeActions(actions: SceneAction[], current: () => boolean): Promise<void> {
    for (const action of actions) {
      if (!current() || !this.vrm) return;
      if (action.kind === "stop") { this.gaze = null; this.gazePoint = null; continue; }
      if (!action.position) throw new Error("场景动作缺少目标位置");
      const target = sceneDestination(action.position);
      if (action.kind === "look_at") {
        this.gaze = action.target_id;
        this.gazePoint = target;
      } else {
        // Engine translation is deliberately exposed as movement, not synthesized walking.
        let previous = this.audibleTime();
        while (current()) {
          if (this.audio.state !== "running") {
            previous = this.audibleTime();
            await new Promise<void>(resolve => setTimeout(resolve, 16));
            continue;
          }
          const root = this.rootPosition();
          const delta = new THREE.Vector3(target.x - root.x, 0, target.z - root.z);
          if (delta.length() < 0.01) break;
          const now = this.audibleTime();
          delta.clampLength(0, Math.min(Math.max(0, now - previous), 0.1) * 0.7);
          this.vrm.scene.position.add(delta);
          previous = now;
          await new Promise<void>(resolve => setTimeout(resolve, 16));
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
      if (dt > 0 && this.audio.state === "running") for (const name of Object.keys(this.vrm.humanoid.humanBones)) {
        const bone = this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
        if (!bone) continue;
        const previous = this.poseHistory.get(bone);
        const velocity = previous ? rotationVector(bone.quaternion.clone().multiply(previous.q.clone().invert())).divideScalar(dt) : new THREE.Vector3();
        this.poseHistory.set(bone, { q: bone.quaternion.clone(), velocity });
      }
      if (this.gazePoint) this.vrm.lookAt?.lookAt(this.gazePoint);
      this.vrm.update(dt);
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.canvas.dataset.characterRendering = "true";
    this.frame = requestAnimationFrame(this.render);
  };
}
