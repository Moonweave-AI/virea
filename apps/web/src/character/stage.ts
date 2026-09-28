import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM, type VRMHumanBoneName } from "@pixiv/three-vrm";
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from "@pixiv/three-vrm-animation";
import { assertFiniteClip, computeCameraFraming, ensureVRMLookAtQuaternionProxy } from "../viewer-compat";
import { anchorClip, sceneDestination, sampleClip } from "./motion";
import { RotationBridge, rotationVector } from "./continuity";
import { PoseRecovery, faceRelease, type PoseSample } from "./recovery";
import { RelaxedIdle } from "./idle";
import { ExpressionTimeline } from "./timeline";
import { SpatialPlayer } from "./spatial";
import { MotionInspection } from "./inspection";
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
  private readonly timeline = new ExpressionTimeline(this.audio, this.analyser);
  private idle: RelaxedIdle | null = null;
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
  motionRecording() { return this.spatial?.export() ?? []; }

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
      this.spatial = new SpatialPlayer(vrm, () => this.audibleTime());
      this.idle = new RelaxedIdle(vrm, pose.rotations);
      this.rest = this.poseSample();
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
      pose, gaze_target: this.gaze, behavior: this.source ? "speaking" : "holding_pose" };
  }

  stop(): BodyState {
    this.epoch++;
    this.timeline.stop();
    this.spatial?.stop();
    this.sceneActions = Promise.resolve();
    this.idle?.stop();
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

  preload(packet: Expression): ReturnType<CharacterStage["prepare"]> {
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
    onProgress: (value: PlaybackProgress) => void = () => {}): Promise<{ audio_seconds: number; motion_seconds: number }> {
    if (!this.vrm) throw new Error("请先载入 VRM");
    const epoch = this.epoch;
    const current = () => epoch === this.epoch && !this.disposed;
    const [gltf, audio, face] = await this.preload(packet);
    if (!current()) throw new DOMException("Interrupted", "AbortError");
    if (audio && this.audio.state !== "running") throw new Error("音频暂停，请点击继续声音后重试");
    this.idle?.stop();
    const manager = this.vrm.expressionManager;
    const native = face?.arkit;
    const faceTrack = native && native.names.filter(name => manager?.getExpression(name)).length >= 40
      ? { ...face!, names: native.names, values: native.values } : face;
    const heldFace = new Map(faceTrack?.names.map(name => [name, manager?.getValue(name) ?? 0]) ?? []);
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
    if (gltf && this.rest && duration > 0 && !packet.continues) {
      const dt = Math.min(1 / 120, duration);
      sampleMotion(duration - dt);
      const before = this.poseSample();
      sampleMotion(duration);
      recovery = new PoseRecovery(this.vrm.humanoid.getNormalizedBoneNode("hips")!, before, this.poseSample(), this.rest, dt);
      // Endpoint sampling is planning, not an executed jump before audio starts.
      for (const [bone, q] of held) bone.quaternion.copy(q);
      if (heldHips) this.vrm.humanoid.getNormalizedBoneNode("hips")?.position.copy(heldHips);
    }
    let start = this.audio.currentTime + 0.04;
    if (audio && packet.stream_id) {
      const scheduled = this.timeline.begin(packet, audio);
      this.source = scheduled.source;
      start = scheduled.start;
      this.canvas.dataset.streamUnderruns = String(this.timeline.underruns);
    } else if (audio) {
      this.source = this.audio.createBufferSource();
      this.source.buffer = audio;
      this.source.connect(this.analyser);
      this.source.start(start);
    }
    while (current() && this.audibleTime() < start) await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    if (!current()) throw new DOMException("Interrupted", "AbortError");
    onStart();
    let spatialDuration = 0;
    if (packet.actions.length) this.sceneActions = this.executeActions(packet, current, (elapsed, total) => {
      if (audio) return;
      spatialDuration = total;
      onProgress({ elapsed, audioDuration: 0, motionDuration: total, paused: this.audio.state !== "running" });
    });
    const actions = this.sceneActions;
    void actions.catch(() => {}); // Terminal feedback owns errors; internal windows keep advancing.
    const motionDuration = duration + (recovery?.duration ?? 0);
    const end = Math.max(motionDuration, audio?.duration ?? 0);
    const sample = (elapsed: number) => {
      const tail = Math.max(0, elapsed - duration);
      const hips = this.vrm!.humanoid.getNormalizedBoneNode("hips");
      if (recovery && hips && elapsed >= duration) recovery.apply(tail);
      else sampleMotion(Math.min(elapsed, duration));
      if (faceTrack) {
        const time = Math.min(elapsed, duration);
        this.applyFace(faceTrack, audio ? time * Math.max(0, faceTrack.values.length - 1) / (faceTrack.fps * audio.duration) : time);
        if (elapsed < 0.1) for (const [name, value] of heldFace) {
          if (manager?.getExpression(name)) manager.setValue(name,
            THREE.MathUtils.lerp(value, manager.getValue(name) ?? 0, THREE.MathUtils.smootherstep(elapsed, 0, 0.1)));
        }
        if (recovery && elapsed >= duration) for (const name of faceTrack.names) {
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
      if (!packet.continues) await actions;
      if (!current()) throw new DOMException("Interrupted", "AbortError");
      const finalDuration = Math.max(motionDuration, spatialDuration);
      onProgress({ elapsed: Math.max(end, spatialDuration), audioDuration: audio?.duration ?? 0, motionDuration: finalDuration, paused: false });
      return { audio_seconds: audio?.duration ?? 0, motion_seconds: finalDuration };
    } finally {
      if (current()) {
        if (this.source) { this.source.stop(); this.source.disconnect(); this.source = null; }
        if (this.action) this.action.paused = true;
        if (!face) for (const name of ["aa", "oh", "ou"]) this.vrm?.expressionManager?.setValue(name, 0);
        this.timeline.complete(packet.id);
        if (recovery) this.idle?.start(this.poseSample());
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
    if (packet.actions.some(action => !["look_at", "stop"].includes(action.kind))) {
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
          if (packet.end_state !== "hold" && !this.source && this.rest && current()) {
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
            while (current() && this.audibleTime() - start < recovery.duration) {
              recovery.apply(this.audibleTime() - start);
              onProgress(duration + this.audibleTime() - start, duration + recovery.duration);
              await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
            }
            if (current()) { recovery.apply(recovery.duration); this.idle?.start(this.poseSample()); }
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
      if (!this.spatial?.active) this.idle?.update(dt);
      this.spatial?.update(Boolean(this.source));
      if (dt > 0 && this.audio.state === "running") for (const name of Object.keys(this.vrm.humanoid.humanBones)) {
        const bone = this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
        if (!bone) continue;
        const previous = this.poseHistory.get(bone);
        const velocity = previous ? rotationVector(bone.quaternion.clone().multiply(previous.q.clone().invert())).divideScalar(dt) : new THREE.Vector3();
        this.poseHistory.set(bone, { q: bone.quaternion.clone(), velocity });
      }
      if (this.gazePoint) this.vrm.lookAt?.lookAt(this.gazePoint);
      this.vrm.update(dt);
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
