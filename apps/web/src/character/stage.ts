import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM, type VRMHumanBoneName } from "@pixiv/three-vrm";
import { VRMAnimationLoaderPlugin, createVRMAnimationClip } from "@pixiv/three-vrm-animation";
import { assertFiniteClip, ensureVRMLookAtQuaternionProxy } from "../viewer-compat";
import { anchorClip, sceneDestination } from "./motion";
import type { BodyState, Expression, FaceTrack, SceneAction } from "./contracts";

export class CharacterStage {
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(35, 1, 0.05, 100);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly resize: ResizeObserver;
  private readonly audio = new AudioContext();
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

  async perform(packet: Expression, onStart: () => void): Promise<{ audio_seconds: number; motion_seconds: number }> {
    if (!this.vrm) throw new Error("请先载入 VRM");
    const epoch = this.epoch;
    const current = () => epoch === this.epoch && !this.disposed;
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
    const checked = async (url: string) => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`表达资源读取失败 (${response.status})`);
      return response;
    };
    const [gltf, audio, face] = await Promise.all([
      packet.motion ? loader.loadAsync(packet.motion.vrma_url) : null,
      packet.audio_url ? checked(packet.audio_url).then(r => r.arrayBuffer()).then(b => this.audio.decodeAudioData(b)) : null,
      packet.motion ? checked(`/api/v1/characters/results/${encodeURIComponent(packet.motion.result_id)}/face`).then(r => r.json() as Promise<FaceTrack>) : null,
    ]);
    if (!current()) throw new DOMException("Interrupted", "AbortError");
    if (audio && this.audio.state !== "running") throw new Error("音频暂停，请点击继续声音后重试");
    let duration = 0;
    let held: Map<THREE.Object3D, THREE.Quaternion> = new Map();
    let heldHips: THREE.Vector3 | null = null;
    if (gltf) {
      const animation = gltf.userData.vrmAnimations?.[0];
      if (!animation) throw new Error("动作资源缺少 VRMA 动画");
      const hips = this.vrm.humanoid.getNormalizedBoneNode("hips");
      if (!hips) throw new Error("VRM 缺少 hips");
      let clip = createVRMAnimationClip(animation, this.vrm);
      assertFiniteClip(clip);
      clip = anchorClip(clip, hips);
      duration = clip.duration;
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
    }
    const start = this.audio.currentTime + 0.04;
    if (audio) {
      this.source = this.audio.createBufferSource();
      this.source.buffer = audio;
      this.source.connect(this.audio.destination);
      this.source.start(start);
    }
    onStart();
    const actions = this.executeActions(packet.actions, current);
    const end = Math.max(duration, audio?.duration ?? 0);
    try {
      while (current() && this.audio.currentTime - start < end) {
        if (audio && this.audio.state !== "running") throw new Error("音频设备暂停，表达已中断");
        const elapsed = Math.max(0, this.audio.currentTime - start);
        if (gltf && this.mixer) {
          this.mixer.setTime(Math.min(elapsed, duration));
          const blend = THREE.MathUtils.smoothstep(elapsed, 0, 0.2);
          for (const [bone, quaternion] of held) bone.quaternion.slerpQuaternions(quaternion, bone.quaternion.clone(), blend);
          const hips = this.vrm.humanoid.getNormalizedBoneNode("hips");
          if (hips && heldHips) hips.position.lerpVectors(heldHips, hips.position.clone(), blend);
        }
        if (face) this.applyFace(face, elapsed);
        await new Promise<void>(resolve => setTimeout(resolve, 16));
      }
      if (current() && gltf && this.mixer) this.mixer.setTime(duration);
      await actions;
      if (!current()) throw new DOMException("Interrupted", "AbortError");
      return { audio_seconds: audio?.duration ?? 0, motion_seconds: duration };
    } finally {
      if (current()) {
        if (this.source) { this.source.stop(); this.source.disconnect(); this.source = null; }
        if (this.action) this.action.paused = true;
        for (const name of ["aa", "oh", "ou"]) this.vrm?.expressionManager?.setValue(name, 0);
      }
    }
  }

  dispose(): void {
    this.stop(); this.disposed = true; cancelAnimationFrame(this.frame);
    this.resize.disconnect(); this.controls.dispose();
    this.mixer?.stopAllAction();
    VRMUtils.deepDispose(this.scene);
    this.renderer.dispose(); void this.audio.close();
  }

  private rootPosition(): THREE.Vector3 {
    const hips = this.vrm?.humanoid.getNormalizedBoneNode("hips");
    this.vrm?.scene.updateMatrixWorld(true);
    return hips?.getWorldPosition(new THREE.Vector3()) ?? new THREE.Vector3();
  }

  private applyFace(face: FaceTrack, seconds: number): void {
    const values = face.values[Math.min(face.values.length - 1, Math.floor(seconds * face.fps))];
    face.names.forEach((name, index) => this.vrm?.expressionManager?.setValue(name, values?.[index] ?? 0));
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
        let previous = performance.now();
        while (current()) {
          const root = this.rootPosition();
          const delta = new THREE.Vector3(target.x - root.x, 0, target.z - root.z);
          if (delta.length() < 0.01) break;
          const now = performance.now();
          delta.clampLength(0, Math.min((now - previous) / 1000, 0.1) * 0.7);
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
      if (this.gazePoint) this.vrm.lookAt?.lookAt(this.gazePoint);
      this.vrm.update(dt);
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.canvas.dataset.characterRendering = "true";
    this.frame = requestAnimationFrame(this.render);
  };
}
