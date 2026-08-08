import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMHumanBoneList, VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import {
  normalizeQuatArray,
  normalizedLocalPoseRotation,
  vrmSpecWorldAlignment,
} from "./vrm-canonical-alignment.js";
import {
  PART_META,
  activeAnnotations,
  canonicalChannelVectorAt,
  clipText,
  groupedPartAnnotations,
  interpolatePositionFrame,
  partJointIndices,
} from "./annotations.js";

const ROOT_NAMES = ["hips", "pelvis", "root"];
const MAX_RENDER_HZ = 60;

function finitePoint(point) {
  return (
    Array.isArray(point) &&
    point.length >= 3 &&
    Number.isFinite(point[0]) &&
    Number.isFinite(point[1]) &&
    Number.isFinite(point[2])
  );
}

function disposeMaterial(material) {
  if (!material) return;
  if (Array.isArray(material)) {
    material.forEach(disposeMaterial);
    return;
  }
  for (const value of Object.values(material)) {
    if (value?.isTexture) value.dispose();
  }
  material.dispose?.();
}

function disposeObject(object) {
  object.traverse?.((child) => {
    child.geometry?.dispose?.();
    disposeMaterial(child.material);
  });
}

function clearGroup(group) {
  for (const child of [...group.children]) {
    group.remove(child);
    disposeObject(child);
  }
}

function payloadRootIndex(payload) {
  const names = payload?.skeleton?.joint_names || [];
  for (const name of ROOT_NAMES) {
    const index = names.findIndex((item) => String(item).toLowerCase() === name);
    if (index >= 0) return index;
  }
  return 0;
}

function motionBounds(payload) {
  const frames = payload?.frames?.positions || [];
  if (!frames.length) {
    return { center: new THREE.Vector3(0, 0.95, 0), radius: 0.9, source: "canonical-fallback" };
  }
  const box = new THREE.Box3();
  const point = new THREE.Vector3();
  const stride = Math.max(1, Math.floor(frames.length / 80));
  for (let frameIndex = 0; frameIndex < frames.length; frameIndex += stride) {
    for (const raw of frames[frameIndex]) {
      if (!finitePoint(raw)) continue;
      point.set(raw[0], raw[1], raw[2]);
      box.expandByPoint(point);
    }
  }
  if (box.isEmpty()) return { center: new THREE.Vector3(0, 0.95, 0), radius: 0.9, source: "canonical-fallback" };
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  return { center, radius: Math.max(size.x, size.y, size.z, 1.6) / 2, source: "canonical-motion" };
}

function objectBounds(object, source) {
  if (!object) return null;
  object.updateWorldMatrix?.(true, true);
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return null;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const extent = Math.max(size.x, size.y, size.z);
  if (!Number.isFinite(extent) || extent <= 1e-5) return null;
  return { center, radius: Math.max(extent / 2, 0.25), source };
}

function fitStaticScene(scene) {
  const box = new THREE.Box3().setFromObject(scene);
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const scale = 1.75 / Math.max(size.x, size.y, size.z, 1e-4);
  scene.position.sub(center);
  scene.scale.setScalar(scale);
}

function resolveVrmBodyOffset(vrm) {
  const rawHips = vrm?.humanoid?.getRawBoneNode?.("hips");
  if (!rawHips || !vrm?.scene) return new THREE.Vector3(0, 0, 0);
  vrm.scene.updateMatrixWorld(true);
  const hipsInLoadFrame = rawHips.getWorldPosition(new THREE.Vector3());
  // loadModel calls this before attaching gltf.scene, so both values are in
  // the same parent/load frame. Preserve any scene rotation/scale and move the
  // complete hierarchy until its actual hips world point is at the origin.
  return vrm.scene.position.clone().sub(hipsInLoadFrame);
}

export function createVrmViewer({ canvas, statusEl, fileInput, resetButton }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xfbf7ed);

  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 120);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.target.set(0, 0.9, 0);

  scene.add(new THREE.HemisphereLight(0xfff7e2, 0x20343c, 1.7));
  const key = new THREE.DirectionalLight(0xfff0cf, 2.0);
  key.position.set(3.5, 5.0, 4.0);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xbfe6ff, 1.0);
  rim.position.set(-4.0, 2.5, -3.0);
  scene.add(rim);

  const grid = new THREE.GridHelper(12, 24, 0x8aa19a, 0xd4cabc);
  grid.material.transparent = true;
  grid.material.opacity = 0.45;
  scene.add(grid);

  const motionRoot = new THREE.Group();
  scene.add(motionRoot);

  const canonicalRoot = new THREE.Group();
  motionRoot.add(canonicalRoot);

  const staticRoot = new THREE.Group();
  scene.add(staticRoot);

  const annotationRoot = new THREE.Group();
  scene.add(annotationRoot);

  const annotationMarkerGeometry = new THREE.SphereGeometry(0.035, 14, 10);

  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));

  const state = {
    payload: null,
    motion: null,
    annotations: [],
    channels: [],
    showHands: false,
    markerPool: [],
    markerSignature: "",
    markerSpecs: [],
    textureCreateCount: 0,
    frame: 0,
    vrm: null,
    vrmWorldAlignment: null,
    staticScene: null,
    currentFileName: "",
    theme: "light",
    diagnosticsSignature: "",
    viewBounds: null,
    modelLoadGeneration: 0,
  };
  let resizeDirty = true;
  let renderWidth = 0;
  let renderHeight = 0;
  let nextRenderMs = Number.NEGATIVE_INFINITY;

  function setStatus(message) {
    if (statusEl) statusEl.textContent = message || "";
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.floor(rect.width));
    const height = Math.max(1, Math.floor(rect.height));
    resizeDirty = false;
    if (width === renderWidth && height === renderHeight) return;
    renderWidth = width;
    renderHeight = height;
    renderer.setSize(width, height, false);
    camera.aspect = width / Math.max(height, 1);
    camera.updateProjectionMatrix();
  }

  function resetView() {
    const bounds =
      objectBounds(state.vrm?.scene, "vrm-scene") ||
      objectBounds(state.staticScene, "static-scene") ||
      motionBounds(state.payload);
    const { center, radius } = bounds;
    state.viewBounds = {
      source: bounds.source,
      center: [center.x, center.y, center.z],
      radius,
    };
    controls.target.copy(center);
    camera.position.set(center.x - radius * 0.75, center.y + radius * 0.35, center.z + radius * 2.7);
    camera.near = Math.max(0.005, radius / 120);
    camera.far = Math.max(40, radius * 30);
    camera.updateProjectionMatrix();
    controls.update();
  }

  function clearCurrentModel() {
    // clearGroup owns disposal for attached scenes; disposing them before the
    // traversal would release the same GPU resources twice.
    clearGroup(canonicalRoot);
    clearGroup(staticRoot);
    state.markerSignature = "";
    for (const entry of state.markerPool) entry.group.visible = false;
    motionRoot.position.set(0, 0, 0);
    motionRoot.quaternion.identity();
    canonicalRoot.position.set(0, 0, 0);
    canonicalRoot.quaternion.identity();
    state.vrm = null;
    state.vrmWorldAlignment = null;
    state.staticScene = null;
    state.currentFileName = "";
  }

  function createMarkerEntry() {
    const group = new THREE.Group();
    group.visible = false;
    group.renderOrder = 20;

    const markerMaterial = new THREE.MeshBasicMaterial({
      color: 0x2f80ed,
      depthTest: false,
      transparent: true,
      opacity: 0.92,
    });
    const marker = new THREE.Mesh(annotationMarkerGeometry, markerMaterial);
    marker.renderOrder = 21;
    group.add(marker);

    const canvasEl = document.createElement("canvas");
    canvasEl.width = 1024;
    canvasEl.height = 256;
    const texture = new THREE.CanvasTexture(canvasEl);
    state.textureCreateCount += 1;
    texture.colorSpace = THREE.SRGBColorSpace;
    const spriteMaterial = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
    const sprite = new THREE.Sprite(spriteMaterial);
    sprite.scale.set(0.82, 0.2, 1);
    sprite.renderOrder = 22;
    group.add(sprite);

    const connectorPositions = new Float32Array(6);
    const connectorGeometry = new THREE.BufferGeometry();
    connectorGeometry.setAttribute("position", new THREE.BufferAttribute(connectorPositions, 3));
    const connectorMaterial = new THREE.LineBasicMaterial({ color: 0x2f80ed, transparent: true, opacity: 0.78, depthTest: false });
    const connector = new THREE.Line(connectorGeometry, connectorMaterial);
    // Connector vertices are written in scene/world coordinates. Avoid an
    // expensive bounding-sphere rebuild for every active label on every frame.
    connector.frustumCulled = false;
    connector.renderOrder = 20;
    group.add(connector);

    annotationRoot.add(group);
    const entry = { group, marker, markerMaterial, canvasEl, texture, sprite, connector, connectorGeometry, connectorMaterial, labelKey: "" };
    state.markerPool.push(entry);
    return entry;
  }

  function updateMarkerLabel(entry, text, color) {
    const label = clipText(text, 58);
    const labelKey = `${label}|${color}|${state.theme}`;
    if (entry.labelKey === labelKey) return;
    entry.labelKey = labelKey;
    const ctx = entry.canvasEl.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, entry.canvasEl.width, entry.canvasEl.height);
    ctx.scale(2, 2);
    ctx.font = "700 22px Aptos, Segoe UI, sans-serif";
    ctx.textBaseline = "middle";
    ctx.fillStyle = state.theme === "dark" ? "rgba(15, 22, 30, 0.9)" : "rgba(255, 252, 244, 0.94)";
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.roundRect(8, 24, 496, 62, 14);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(34, 55, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = state.theme === "dark" ? "#e8edf0" : "#182026";
    ctx.fillText(label, 52, 56, 428);
    entry.texture.needsUpdate = true;
    entry.markerMaterial.color.set(color);
    entry.connectorMaterial.color.set(color);
  }

  function humanoidBonesFor(spec) {
    const bodypart = spec.bodypart;
    if (bodypart === "head" || ["dialogue", "face", "audio"].includes(bodypart)) return ["head", "neck"];
    if (bodypart === "spine") return ["upperChest", "chest", "spine"];
    if (bodypart === "left_arm") return spec.requiresHands ? ["leftHand"] : ["leftLowerArm", "leftUpperArm"];
    if (bodypart === "right_arm") return spec.requiresHands ? ["rightHand"] : ["rightLowerArm", "rightUpperArm"];
    if (bodypart === "hands") return ["leftHand", "rightHand"];
    if (bodypart === "left_leg") return ["leftFoot", "leftLowerLeg"];
    if (bodypart === "right_leg") return ["rightFoot", "rightLowerLeg"];
    if (bodypart === "object" || bodypart === "contact" || bodypart === "interaction") {
      if (spec.side === "left") return ["leftHand"];
      if (spec.side === "right") return ["rightHand"];
      return ["leftHand", "rightHand"];
    }
    return ["hips", "spine"];
  }

  function humanoidWorldPositionCache(specs) {
    const positions = new Map();
    if (!state.vrm?.humanoid || !specs.length) return positions;
    // Updating a complex avatar traverses its complete scene. Do this once per
    // annotation update, then reuse the bone positions for every marker.
    state.vrm.scene.updateMatrixWorld(true);
    const requiredBones = new Set(specs.flatMap((spec) => humanoidBonesFor(spec)));
    for (const boneName of requiredBones) {
      const node = state.vrm.humanoid.getRawBoneNode?.(boneName);
      if (!node) continue;
      positions.set(boneName, node.getWorldPosition(new THREE.Vector3()));
    }
    return positions;
  }

  function averageHumanoidWorldPosition(boneNames, worldPositions) {
    if (!worldPositions?.size) return null;
    const points = [];
    for (const boneName of boneNames) {
      const point = worldPositions.get(boneName);
      if (point) points.push(point);
    }
    if (!points.length) return null;
    return points.reduce((sum, point) => sum.add(point), new THREE.Vector3()).multiplyScalar(1 / points.length);
  }

  function channelAnchor(bodypart, frame) {
    if (!["object", "contact"].includes(bodypart)) return null;
    const fps = Number(state.payload?.fps || state.motion?.fps || 30) || 30;
    const vector = canonicalChannelVectorAt(state.channels, bodypart, frame, fps);
    if (finitePoint(vector)) return new THREE.Vector3(vector[0], vector[1], vector[2]);
    return null;
  }

  function canonicalAnnotationAnchor(spec, frame) {
    const rawFrames = state.payload?.frames?.positions || [];
    const positions = interpolatePositionFrame(rawFrames, frame);
    if (!positions?.length) return null;
    const names = state.payload?.skeleton?.joint_names || [];
    const byNames = (patterns) => names
      .map((name, index) => ({ name: String(name || "").toLowerCase(), index }))
      .filter(({ name }) => patterns.some((pattern) => name.includes(pattern)))
      .map(({ index }) => index);
    let indices = partJointIndices(state.payload, spec.bodypart, { includeHands: state.showHands });
    if (!indices.length && ["object", "contact", "interaction"].includes(spec.bodypart)) indices = byNames(["hand", "wrist"]).slice(0, 4);
    if (!indices.length && ["dialogue", "face", "audio"].includes(spec.bodypart)) indices = byNames(["head", "neck", "jaw"]);
    if (!indices.length) indices = [payloadRootIndex(state.payload)];
    const points = indices.filter((index) => finitePoint(positions[index])).map((index) => positions[index]);
    if (!points.length) return null;
    return points.reduce((sum, point) => sum.add(new THREE.Vector3(point[0], point[1], point[2])), new THREE.Vector3()).multiplyScalar(1 / points.length);
  }

  function annotationAnchor(spec, frame, humanoidWorldPositions) {
    const fromChannel = channelAnchor(spec.bodypart, frame);
    if (fromChannel) {
      spec.anchorMode = "channel";
      return fromChannel;
    }
    const fromHumanoid = averageHumanoidWorldPosition(humanoidBonesFor(spec), humanoidWorldPositions);
    if (fromHumanoid) {
      spec.anchorMode = "humanoid";
      return fromHumanoid;
    }
    spec.anchorMode = state.staticScene ? "canonical-static-glb-fallback" : "canonical-fallback";
    return canonicalAnnotationAnchor(spec, frame);
  }

  function annotationSpecs(active) {
    const groups = groupedPartAnnotations(active.filter((annotation) => state.showHands || !annotation.requiresHands));
    for (const annotation of active.filter((item) => ["action", "dialogue", "object", "contact", "interaction", "face", "audio"].includes(item.bodypart))) {
      if (!groups.has(annotation.bodypart)) groups.set(annotation.bodypart, []);
      groups.get(annotation.bodypart).push(annotation);
    }
    return [...groups.entries()].slice(0, 10).map(([bodypart, annotations]) => {
      const first = annotations[0];
      const rawPart = String(first.raw?.bodypart ?? first.raw?.body_part ?? "").toLowerCase();
      const side = rawPart.includes("left") || /(^|_)l(hand|arm|wrist)/.test(rawPart) ? "left" : rawPart.includes("right") || /(^|_)r(hand|arm|wrist)/.test(rawPart) ? "right" : null;
      const summary = annotations.slice(0, 3).map((annotation) => clipText(annotation.text, 34)).join(" | ");
      return {
        key: `${bodypart}:${annotations.map((annotation) => annotation.id).join(",")}`,
        bodypart,
        side,
        requiresHands: annotations.some((annotation) => annotation.requiresHands),
        color: first.anchorColor || PART_META[bodypart]?.color || first.color || "#2f80ed",
        text: `${first.label}: ${summary}${annotations.length > 3 ? ` +${annotations.length - 3}` : ""}`,
      };
    });
  }

  function reconcileMarkerPool(specs) {
    const signature = `${state.theme}|${state.vrm ? "vrm" : state.staticScene ? "static" : "canonical"}|${specs.map((spec) => `${spec.key}:${spec.text}:${spec.color}`).join("|")}`;
    if (signature !== state.markerSignature) {
      state.markerSignature = signature;
      state.markerSpecs = specs;
      specs.forEach((spec, index) => {
        const entry = state.markerPool[index] || createMarkerEntry();
        entry.group.visible = true;
        updateMarkerLabel(entry, spec.text, spec.color);
      });
      for (let index = specs.length; index < state.markerPool.length; index += 1) state.markerPool[index].group.visible = false;
    } else {
      state.markerSpecs = specs;
    }
  }

  function updateAnnotationMarkers() {
    if (!state.annotations.length) {
      reconcileMarkerPool([]);
      publishDiagnostics();
      return;
    }
    const fps = Number(state.payload?.fps || state.motion?.fps || 30) || 30;
    const active = activeAnnotations(state.annotations, state.frame, fps);
    const specs = annotationSpecs(active);
    reconcileMarkerPool(specs);
    const humanoidWorldPositions = humanoidWorldPositionCache(specs);
    specs.forEach((spec, index) => {
      const entry = state.markerPool[index];
      const anchor = annotationAnchor(spec, state.frame, humanoidWorldPositions);
      entry.group.visible = Boolean(anchor);
      if (!anchor) return;
      const xOffset = 0.14 + (index % 2) * 0.08;
      const yOffset = 0.16 + (index % 5) * 0.055;
      entry.marker.position.copy(anchor);
      entry.sprite.position.copy(anchor).add(new THREE.Vector3(xOffset, yOffset, 0));
      const attribute = entry.connectorGeometry.getAttribute("position");
      attribute.setXYZ(0, anchor.x, anchor.y, anchor.z);
      attribute.setXYZ(1, entry.sprite.position.x, entry.sprite.position.y, entry.sprite.position.z);
      attribute.needsUpdate = true;
    });
    publishDiagnostics();
  }

  function frameBlend(frame, frameCount) {
    const count = Math.max(1, Number(frameCount) || 1);
    const value = Math.max(0, Math.min(Number(frame) || 0, count - 1));
    const a = Math.floor(value);
    const b = Math.min(a + 1, count - 1);
    return { a, b, alpha: value - a };
  }

  function slerpQuatArrays(a, b, alpha) {
    const qa = normalizeQuatArray(a || [0, 0, 0, 1]);
    const qb = normalizeQuatArray(b || qa);
    const start = new THREE.Quaternion(qa[0], qa[1], qa[2], qa[3]).normalize();
    const end = new THREE.Quaternion(qb[0], qb[1], qb[2], qb[3]).normalize();
    if (start.dot(end) < 0) end.set(-end.x, -end.y, -end.z, -end.w);
    start.slerp(end, alpha).normalize();
    return [start.x, start.y, start.z, start.w];
  }

  function lerpVectorArrays(a, b, alpha) {
    const start = finitePoint(a) ? a : [0, 0, 0];
    const end = finitePoint(b) ? b : start;
    return [
      start[0] + (end[0] - start[0]) * alpha,
      start[1] + (end[1] - start[1]) * alpha,
      start[2] + (end[2] - start[2]) * alpha,
    ];
  }

  function applyVrmCanonicalWorldAlignment(vrm = state.vrm) {
    if (!vrm) return null;
    canonicalRoot.quaternion.identity();
    const alignment = vrmSpecWorldAlignment(vrm.meta?.metaVersion);
    if (!alignment?.alignment_quaternion) {
      state.vrmWorldAlignment = null;
      return null;
    }
    const q = alignment.alignment_quaternion;
    canonicalRoot.quaternion.set(q[0], q[1], q[2], q[3]).normalize();
    motionRoot.updateMatrixWorld(true);
    state.vrmWorldAlignment = alignment;
    return alignment;
  }

  function poseObjectFromFrame(frame) {
    const motion = state.motion;
    if (!motion) return {};
    const blend = frameBlend(frame, motion.frame_count);
    const pose = {};
    const canonicalToVrm = motion.canonical_to_vrm || {};
    (motion.core_bones || []).forEach((boneName, boneIndex) => {
      const rotation0 = motion.core_quaternions?.[blend.a]?.[boneIndex];
      const rotation1 = motion.core_quaternions?.[blend.b]?.[boneIndex] || rotation0;
      const rotation = rotation0 ? slerpQuatArrays(rotation0, rotation1, blend.alpha) : null;
      if (!rotation) return;
      const vrmBoneName = canonicalToVrm[boneName] || boneName;
      pose[vrmBoneName] = {
        rotation: normalizedLocalPoseRotation(
          rotation,
          state.vrmWorldAlignment?.alignment_quaternion || null,
        ),
      };
    });
    (motion.hand_bones || []).forEach((boneName, boneIndex) => {
      const rotation0 = motion.hand_quaternions?.[blend.a]?.[boneIndex];
      const rotation1 = motion.hand_quaternions?.[blend.b]?.[boneIndex] || rotation0;
      const rotation = rotation0 ? slerpQuatArrays(rotation0, rotation1, blend.alpha) : null;
      if (!rotation) return;
      const vrmBoneName = canonicalToVrm[boneName] || boneName;
      pose[vrmBoneName] = {
        rotation: normalizedLocalPoseRotation(
          rotation,
          state.vrmWorldAlignment?.alignment_quaternion || null,
        ),
      };
    });
    return pose;
  }

  function applyVrmFrame(frame) {
    if (!state.vrm || !state.motion) return;
    const motion = state.motion;
    const blend = frameBlend(frame, motion.frame_count);
    const translation = lerpVectorArrays(motion.root_translation?.[blend.a], motion.root_translation?.[blend.b], blend.alpha);
    const rotation = slerpQuatArrays(motion.root_rotation?.[blend.a], motion.root_rotation?.[blend.b], blend.alpha);
    motionRoot.position.set(translation[0], translation[1], translation[2]);
    motionRoot.quaternion.set(rotation[0], rotation[1], rotation[2], rotation[3]).normalize();
    const pose = poseObjectFromFrame(frame);
    if (typeof state.vrm.humanoid.setNormalizedPose === "function") {
      state.vrm.humanoid.resetNormalizedPose?.();
      state.vrm.humanoid.setNormalizedPose(pose);
    }
    if (typeof state.vrm.update === "function") state.vrm.update(0);
    else state.vrm.humanoid.update?.();
  }

  function applyFrame() {
    applyVrmFrame(state.frame);
    updateAnnotationMarkers();
  }

  async function loadModel(file) {
    const loadGeneration = ++state.modelLoadGeneration;
    clearCurrentModel();
    if (!file) {
      setStatus("No model loaded. Load a .vrm to preview the processed motion on the avatar.");
      return;
    }
    state.currentFileName = file.name;
    setStatus(`Loading ${file.name} ...`);
    const url = URL.createObjectURL(file);
    try {
      const gltf = await loader.loadAsync(url);
      if (loadGeneration !== state.modelLoadGeneration) {
        disposeObject(gltf.scene);
        return;
      }
      const vrm = gltf.userData.vrm || null;
      if (vrm) {
        if (typeof vrm.humanoid?.setNormalizedPose !== "function") {
          throw new Error("This VRM runtime does not expose normalized humanoid pose application");
        }
        if (!vrmSpecWorldAlignment(vrm.meta?.metaVersion)) {
          throw new Error(`Unsupported or missing VRM meta version: ${vrm.meta?.metaVersion ?? "unknown"}`);
        }
        VRMUtils.removeUnnecessaryVertices(gltf.scene);
        VRMUtils.combineSkeletons?.(gltf.scene);
        // Keep the load-time VRM frame unchanged. canonicalRoot computes the
        // complete avatar-to-canonical alignment, and local pose conjugation
        // uses that same transform. Applying rotateVRM0 here would introduce a
        // second outer frame that must otherwise be included in the conjugate.
        vrm.scene.position.copy(resolveVrmBodyOffset(vrm));
        canonicalRoot.add(vrm.scene);
        state.vrm = vrm;
        applyVrmCanonicalWorldAlignment(vrm);
        applyFrame();
        const boneCount = VRMHumanBoneList.filter((boneName) => vrm.humanoid?.getRawBoneNode?.(boneName)).length;
        const aligned = state.vrmWorldAlignment ? "aligned to processed VRM rest" : "loaded without rest alignment";
        setStatus(`${file.name} loaded as VRM. Humanoid bones: ${boneCount}; ${aligned}. Annotation markers follow raw humanoid bone world nodes. Drag to orbit; wheel to zoom.`);
      } else {
        fitStaticScene(gltf.scene);
        staticRoot.add(gltf.scene);
        state.staticScene = gltf.scene;
        applyFrame();
        setStatus(`${file.name} loaded as static GLB/GLTF. It has no VRM humanoid: motion retargeting is not applied, and any 3D annotation marker uses the canonical preview skeleton as an explicit fallback.`);
      }
      resetView();
    } catch (error) {
      if (loadGeneration !== state.modelLoadGeneration) return;
      clearCurrentModel();
      setStatus(`Failed to load ${file.name}: ${error?.message || error}`);
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function setMotionPayload(payload) {
    state.payload = payload || null;
    state.motion = payload?.motion || null;
    state.frame = 0;
    applyVrmCanonicalWorldAlignment(state.vrm);
    applyFrame();
    resetView();
    if (!state.motion) {
      setStatus("Processed preview loaded, but no VRM motion payload is available.");
    }
  }

  function setFrame(frame) {
    state.frame = Math.max(0, Number(frame) || 0);
    applyFrame();
  }

  function setAnnotations(annotations) {
    state.annotations = Array.isArray(annotations) ? annotations : [];
    state.markerSignature = "";
    updateAnnotationMarkers();
  }

  function setChannels(channels) {
    state.channels = Array.isArray(channels) ? channels : [];
    updateAnnotationMarkers();
  }

  function setShowHands(showHands) {
    state.showHands = Boolean(showHands);
    state.markerSignature = "";
    updateAnnotationMarkers();
  }

  function getDiagnostics() {
    return {
      markerPoolSize: state.markerPool.length,
      visibleMarkerCount: state.markerPool.filter((entry) => entry.group.visible).length,
      textureCreateCount: state.textureCreateCount,
      anchorModes: [...new Set(state.markerSpecs.map((spec) => spec.anchorMode).filter(Boolean))],
      hasVrmHumanoid: Boolean(state.vrm?.humanoid),
      hasStaticGlbFallback: Boolean(state.staticScene),
      frame: state.frame,
      viewBounds: state.viewBounds,
    };
  }

  function publishDiagnostics() {
    const diagnostics = getDiagnostics();
    const signature = [
      diagnostics.markerPoolSize,
      diagnostics.visibleMarkerCount,
      diagnostics.textureCreateCount,
      diagnostics.anchorModes.join(","),
      diagnostics.hasVrmHumanoid,
    ].join("|");
    if (signature === state.diagnosticsSignature) return;
    state.diagnosticsSignature = signature;
    canvas.dataset.markerPoolSize = String(diagnostics.markerPoolSize);
    canvas.dataset.visibleMarkerCount = String(diagnostics.visibleMarkerCount);
    canvas.dataset.textureCreateCount = String(diagnostics.textureCreateCount);
    canvas.dataset.anchorModes = diagnostics.anchorModes.join(",");
    canvas.dataset.hasVrmHumanoid = String(diagnostics.hasVrmHumanoid);
  }

  function setTheme(theme) {
    state.theme = theme === "dark" ? "dark" : "light";
    scene.background = new THREE.Color(state.theme === "dark" ? 0x111820 : 0xfbf7ed);
    grid.material.opacity = state.theme === "dark" ? 0.32 : 0.45;
    state.markerSignature = "";
    updateAnnotationMarkers();
  }

  function render(now) {
    window.requestAnimationFrame(render);
    const renderIntervalMs = 1000 / MAX_RENDER_HZ;
    if (now < nextRenderMs - 1) return;
    const scheduledNext = Number.isFinite(nextRenderMs)
      ? nextRenderMs + renderIntervalMs
      : now + renderIntervalMs;
    nextRenderMs = scheduledNext <= now ? now + renderIntervalMs : scheduledNext;
    if (resizeDirty) resize();
    controls.update();
    renderer.render(scene, camera);
  }

  fileInput?.addEventListener("change", async (event) => {
    await loadModel(event.target.files?.[0] || null);
  });
  resetButton?.addEventListener("click", resetView);
  window.addEventListener("resize", () => {
    resizeDirty = true;
  });
  const resizeObserver = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => {
        resizeDirty = true;
      })
    : null;
  resizeObserver?.observe(canvas);

  setStatus("three-vrm viewer ready. Load a .vrm to drive it with the processed motion.");
  resetView();
  window.requestAnimationFrame(render);

  return { loadModel, resetView, setMotionPayload, setFrame, setTheme, setAnnotations, setChannels, setShowHands, getDiagnostics };
}
