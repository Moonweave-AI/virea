export const LEVEL_ORDER = ["sequence", "action", "part", "context", "metadata"];

export const LEVEL_META = {
  sequence: { label: "Sequence", color: "#2f7d5f" },
  action: { label: "Action", color: "#2f80ed" },
  part: { label: "Body part", color: "#c45a2b" },
  context: { label: "Context", color: "#8e5eb5" },
  metadata: { label: "Metadata", color: "#607d8b" },
};

export const PROVENANCE_META = {
  native: { label: "Native", className: "native" },
  derived: { label: "Derived", className: "derived" },
  fallback: { label: "Fallback", className: "fallback" },
  legacy: { label: "Legacy / unverified", className: "legacy" },
};

export const PART_ORDER = [
  "head",
  "spine",
  "left_arm",
  "right_arm",
  "hands",
  "left_leg",
  "right_leg",
  "trajectory",
];

export const PART_META = {
  sequence_caption: { label: "Sequence", color: "#2f7d5f" },
  action: { label: "Action", color: "#2f80ed" },
  trajectory: { label: "Trajectory", color: "#9b59b6" },
  spine: { label: "Spine", color: "#e0a400" },
  head: { label: "Head", color: "#168aad" },
  left_arm: { label: "Left arm", color: "#d1495b" },
  right_arm: { label: "Right arm", color: "#e07a1f" },
  hands: { label: "Hands", color: "#c45a2b" },
  left_leg: { label: "Left leg", color: "#27864f" },
  right_leg: { label: "Right leg", color: "#56a76d" },
  object: { label: "Object", color: "#9b51b6" },
  dialogue: { label: "Dialogue", color: "#277da1" },
  dataset: { label: "Dataset", color: "#607d8b" },
  source: { label: "Source", color: "#795548" },
  face: { label: "Face", color: "#d94f70" },
  audio: { label: "Audio", color: "#008f83" },
  contact: { label: "Contact", color: "#8d6e63" },
  interaction: { label: "Interaction", color: "#9b51b6" },
  metadata: { label: "Metadata", color: "#828282" },
};

const FINGER_NAMES = ["thumb", "index", "middle", "ring", "little", "pinky"];
const PROVENANCE_VALUES = new Set(["native", "derived", "fallback"]);
const LEVEL_VALUES = new Set(LEVEL_ORDER);
const ACTION_STOPWORDS = new Set([
  "poses",
  "stageii",
  "stageiii",
  "clip",
  "motion",
  "data",
  "human",
  "subset",
  "female",
  "male",
  "subject",
]);
const SECRET_KEY = /(password|passwd|secret|token|credential|api[_-]?key)/i;
const STANDARD_FIELDS = new Set([
  "schema_version",
  "id",
  "level",
  "type",
  "kind",
  "text",
  "caption",
  "proc_label",
  "raw_label",
  "label",
  "value",
  "name",
  "path",
  "bodypart",
  "body_part",
  "bodyPart",
  "part",
  "target",
  "scope",
  "start_sec",
  "start_t",
  "start",
  "begin",
  "start_frame",
  "frame_start",
  "startFrame",
  "end_sec",
  "end_t",
  "end",
  "stop",
  "end_frame",
  "frame_end",
  "endFrame",
  "confidence",
  "score",
  "source",
  "provenance",
  "reasoning",
  "note",
  "original",
  "clipped",
  "extras",
  "annotations",
  "body_parts",
  "sequence_caption",
  "action",
  "duration",
]);

const DEFAULT_PART_ALIASES = {
  seq: "sequence_caption",
  sequence: "sequence_caption",
  sequence_level: "sequence_caption",
  sequence_text: "sequence_caption",
  caption: "sequence_caption",
  global: "sequence_caption",
  global_caption: "sequence_caption",
  body: "action",
  fullbody: "action",
  full_body: "action",
  frame: "action",
  frame_ann: "action",
  gesture: "action",
  gesture_or_semantic: "action",
  semantic: "action",
  text: "sequence_caption",
  dialogue_text: "dialogue",
  speech: "dialogue",
  transcript: "dialogue",
  dataset_name: "dataset",
  source_format: "source",
  source_id: "source",
  object_name: "object",
  object_pose: "object",
  object_translation: "object",
  obj: "object",
  obj_name: "object",
  has_face: "face",
  face_expr: "face",
  face_weights: "face",
  expression_weights: "face",
  expression: "face",
  has_audio: "audio",
  audio_path: "audio",
  audio_waveform: "audio",
  audio_peaks: "audio",
  has_contact: "contact",
  contact_points: "contact",
  contact_map: "contact",
  interaction_context: "interaction",
  torso: "spine",
  chest: "spine",
  upper_body: "spine",
  hips: "spine",
  pelvis: "spine",
  left_hand: "left_arm",
  lefthand: "left_arm",
  lhand: "left_arm",
  l_hand: "left_arm",
  left_wrist: "left_arm",
  lwrist: "left_arm",
  l_wrist: "left_arm",
  larm: "left_arm",
  l_arm: "left_arm",
  right_hand: "right_arm",
  righthand: "right_arm",
  rhand: "right_arm",
  r_hand: "right_arm",
  right_wrist: "right_arm",
  rwrist: "right_arm",
  r_wrist: "right_arm",
  rarm: "right_arm",
  r_arm: "right_arm",
  left_foot: "left_leg",
  leftfoot: "left_leg",
  lfoot: "left_leg",
  l_foot: "left_leg",
  left_knee: "left_leg",
  lknee: "left_leg",
  lleg: "left_leg",
  l_leg: "left_leg",
  right_foot: "right_leg",
  rightfoot: "right_leg",
  rfoot: "right_leg",
  r_foot: "right_leg",
  right_knee: "right_leg",
  rknee: "right_leg",
  rleg: "right_leg",
  r_leg: "right_leg",
};

function cleanText(value) {
  if (value !== null && typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function normalizedName(value) {
  return cleanText(value)
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function aliasSources(payload) {
  return [
    payload?.bodypart_aliases,
    payload?.part_aliases,
    payload?.skeleton?.bodypart_aliases,
    payload?.skeleton?.part_aliases,
    payload?.metadata?.bodypart_aliases,
    payload?.profile?.viewer?.bodypart_aliases,
    payload?.resolved_profile?.viewer?.bodypart_aliases,
  ].filter((value) => value && typeof value === "object" && !Array.isArray(value));
}

export function canonicalPart(value, payload = null) {
  const raw = normalizedName(value);
  if (!raw) return "metadata";
  if (PART_ORDER.includes(raw) || Object.hasOwn(PART_META, raw)) return raw;
  for (const aliases of aliasSources(payload)) {
    const direct = aliases[raw] ?? aliases[value];
    if (typeof direct === "string") {
      const normalizedDirect = normalizedName(direct);
      return DEFAULT_PART_ALIASES[normalizedDirect] || normalizedDirect || "metadata";
    }
    for (const [canonical, candidates] of Object.entries(aliases)) {
      const list = Array.isArray(candidates) ? candidates : [candidates];
      if (list.some((candidate) => typeof candidate === "string" && normalizedName(candidate) === raw)) {
        const normalizedCanonical = normalizedName(canonical);
        return DEFAULT_PART_ALIASES[normalizedCanonical] || normalizedCanonical;
      }
    }
  }
  return DEFAULT_PART_ALIASES[raw] || raw;
}

function directBodypart(annotation) {
  return (
    annotation.bodypart ??
    annotation.body_part ??
    annotation.part ??
    annotation.bodyPart ??
    annotation.target ??
    annotation.scope
  );
}

function bodyPartFromAnnotation(annotation, payload) {
  const direct = directBodypart(annotation);
  if (direct) return canonicalPart(direct, payload);
  const type = canonicalPart(annotation.type ?? annotation.kind ?? annotation.level, payload);
  if (["object", "dialogue", "dataset", "source", "face", "audio", "contact"].includes(type)) return type;
  if (type === "action" || type === "gesture_or_semantic") return "action";
  if (type === "sequence_caption") return "sequence_caption";
  return type || "metadata";
}

function textFromAnnotation(annotation) {
  return cleanText(
    annotation.text ??
      annotation.caption ??
      annotation.proc_label ??
      annotation.raw_label ??
      annotation.label ??
      annotation.value ??
      annotation.name ??
      annotation.path,
  );
}

function readStart(annotation, fps) {
  const seconds = numberOrNull(annotation.start_sec ?? annotation.start_t ?? annotation.start ?? annotation.begin);
  if (seconds !== null) return seconds;
  const frame = numberOrNull(annotation.start_frame ?? annotation.frame_start ?? annotation.startFrame);
  return frame !== null && fps ? frame / fps : null;
}

function readEnd(annotation, fps) {
  const seconds = numberOrNull(annotation.end_sec ?? annotation.end_t ?? annotation.end ?? annotation.stop);
  if (seconds !== null) return seconds;
  const frame = numberOrNull(annotation.end_frame ?? annotation.frame_end ?? annotation.endFrame);
  return frame !== null && fps ? frame / fps : null;
}

function frameFromSeconds(seconds, fps) {
  if (seconds === null || !fps) return null;
  return Math.max(0, Math.ceil(seconds * fps - 1e-9));
}

function flattenAnnotationBlocks(input) {
  if (!input) return [];
  if (Array.isArray(input)) return input.flatMap(flattenAnnotationBlocks);
  if (typeof input !== "object") return [];
  if (Array.isArray(input.items)) return input.items.flatMap(flattenAnnotationBlocks);

  const blocks = [];
  if (input.sequence_caption) {
    blocks.push({
      bodypart: "sequence_caption",
      level: "sequence",
      text: input.sequence_caption,
      confidence: input.confidence,
      reasoning: input.reasoning,
      provenance: input.provenance,
      source: input.source,
    });
  }
  if (input.action) {
    blocks.push({
      bodypart: "action",
      level: "action",
      text: input.action,
      start: input.start,
      end: input.end ?? input.duration,
      confidence: input.confidence,
      reasoning: input.reasoning,
      provenance: input.provenance,
      source: input.source,
    });
  }
  if (input.body_parts && typeof input.body_parts === "object") {
    for (const [bodypart, entries] of Object.entries(input.body_parts)) {
      for (const entry of Array.isArray(entries) ? entries : [entries]) {
        if (entry && typeof entry === "object") blocks.push({ ...entry, bodypart });
        else if (entry !== null && entry !== undefined) blocks.push({ bodypart, text: entry });
      }
    }
  }
  if (Array.isArray(input.annotations)) blocks.push(...input.annotations.flatMap(flattenAnnotationBlocks));

  const text = textFromAnnotation(input);
  if (text || input.bodypart || input.type || input.label || input.schema_version?.startsWith?.("virea.annotation.")) {
    blocks.push(input);
  }
  return blocks;
}

function annotationLevel(bodypart, annotation) {
  const declared = normalizedName(annotation.level);
  if (LEVEL_VALUES.has(declared)) return declared;
  if (bodypart === "sequence_caption") return "sequence";
  if (PART_ORDER.includes(bodypart)) return "part";
  if (bodypart === "action" || annotation.scope === "frame" || annotation.start_sec !== undefined) return "action";
  if (["object", "dialogue", "face", "audio", "contact"].includes(bodypart)) return "context";
  return "metadata";
}

function labelFromSampleId(sampleId) {
  const last = cleanText(String(sampleId || "").split(/[\\/]/).filter(Boolean).at(-1) || "");
  if (!last) return "";
  const withoutExt = last.replace(/\.[a-z0-9]+$/i, "");
  const words = withoutExt
    .replace(/[-_]+/g, " ")
    .replace(/\b\d+\b/g, " ")
    .split(/\s+/)
    .map((word) => word.trim())
    .filter((word) => word && !ACTION_STOPWORDS.has(word.toLowerCase()));
  return words.join(" ").replace(/\s+/g, " ").trim() || withoutExt.replace(/[-_]+/g, " ");
}

function effectiveDuration(payload, fallbackSample, fps) {
  const frameCount = numberOrNull(payload?.frame_count ?? payload?.frames?.positions?.length ?? fallbackSample?.frame_count);
  if (frameCount !== null && fps) return Math.max(0, frameCount / fps);
  return numberOrNull(payload?.duration_sec ?? payload?.time?.duration_sec ?? fallbackSample?.duration_sec);
}

function metadataAnnotations(payload, fallbackSample, hasSemanticAnnotation) {
  const sample = payload?.sample || fallbackSample || {};
  const meta = { ...(fallbackSample?.metadata || {}), ...(payload?.metadata || {}), ...(sample?.metadata || {}) };
  const annotations = [];
  const add = (value) => annotations.push(value);
  const datasetName = meta.dataset_name || sample.dataset || payload?.dataset;
  if (datasetName) add({ level: "metadata", type: "dataset", bodypart: "dataset", text: String(datasetName), source: "sample.dataset", provenance: "native" });
  const sourceFormat = sample.source_format || meta.source_format || payload?.metadata?.source_format;
  if (sourceFormat) add({ level: "metadata", type: "source", bodypart: "source", text: String(sourceFormat), source: "sample.source_format", provenance: "native" });
  if (sample.split) add({ level: "metadata", type: "metadata", bodypart: "metadata", label: "Split", text: String(sample.split), source: "sample.split", provenance: "native" });
  if (meta.object_name) add({ level: "context", type: "object", bodypart: "object", text: String(meta.object_name), source: "metadata.object_name", provenance: "native" });
  if (meta.has_contact !== undefined) add({ level: "context", type: "contact_channel", bodypart: "contact", text: meta.has_contact ? "Contact channel available" : "Contact channel unavailable", source: "metadata.has_contact", provenance: "native" });
  if (meta.has_face !== undefined || meta.face_expr) add({ level: "context", type: "face_channel", bodypart: "face", text: meta.has_face === false ? "Face channel unavailable" : "Face / expression channel available", source: "metadata.face", provenance: "native" });
  if (sample.related_paths?.audio || meta.has_audio !== undefined) add({ level: "context", type: "audio_channel", bodypart: "audio", text: meta.has_audio === false ? "Audio channel unavailable" : "Audio channel available", source: "metadata.audio", provenance: "native" });
  const handBiomechanics = meta.hand_biomechanics;
  if (handBiomechanics?.status === "review_required") {
    const pipViolationCount = Number(
      handBiomechanics.pip_limit_violation_count
        ?? handBiomechanics.violation_count
        ?? 0,
    );
    const bendPlaneViolationCount = Number(
      handBiomechanics.bend_plane_violation_count ?? 0,
    );
    const extensionViolationCount = Number(
      handBiomechanics.extension_limit_violation_count ?? 0,
    );
    const directionUnobservableCount = Number(
      handBiomechanics.direction_unobservable_violation_count ?? 0,
    );
    const hardLimit = Number(handBiomechanics.hard_pip_limit_deg || 0);
    const bendPlaneLimit = Number(handBiomechanics.bend_plane_review_deg || 0);
    const limitEnvelope = (values) => {
      const finite = Object.values(values || {})
        .map(Number)
        .filter((value) => Number.isFinite(value) && value >= 0);
      if (!finite.length) return "";
      const minimum = Math.min(...finite);
      const maximum = Math.max(...finite);
      return Math.abs(maximum - minimum) < 1e-6
        ? `${minimum.toFixed(1)}°`
        : `${minimum.toFixed(1)}–${maximum.toFixed(1)}° per-finger`;
    };
    const flexionEnvelope = limitEnvelope(handBiomechanics.pip_upper_limits_deg);
    const extensionEnvelope = limitEnvelope(
      handBiomechanics.pip_extension_upper_limits_deg,
    );
    const diagnosticParts = [];
    if (hardLimit > 0) {
      diagnosticParts.push(
        `${pipViolationCount} PIP flexion frame-joints exceed ${hardLimit.toFixed(0)}°`,
      );
    } else if (flexionEnvelope) {
      diagnosticParts.push(
        `${pipViolationCount} PIP flexion frame-joints exceed the ${flexionEnvelope} envelope`,
      );
    }
    if (extensionEnvelope) {
      diagnosticParts.push(
        `${extensionViolationCount} PIP extension frame-joints exceed the ${extensionEnvelope} envelope`,
      );
    } else if (extensionViolationCount > 0) {
      diagnosticParts.push(
        `${extensionViolationCount} PIP extension frame-joints exceed their declared limits`,
      );
    }
    if (bendPlaneLimit > 0) {
      diagnosticParts.push(
        `${bendPlaneViolationCount} bend-plane frame-joints exceed ${bendPlaneLimit.toFixed(0)}°`,
      );
    }
    if (directionUnobservableCount > 0) {
      diagnosticParts.push(
        `${directionUnobservableCount} extreme frame-joints have an unobservable bend direction`,
      );
    }
    if (!diagnosticParts.length) {
      diagnosticParts.push(`${Number(handBiomechanics.review_candidate_count || 0)} frame-joints flagged`);
    }
    add({
      level: "part",
      type: "hand_biomechanics_review",
      bodypart: "hands",
      text: `Source hand geometry requires review: ${diagnosticParts.join("; ")}`,
      source: "metadata.hand_biomechanics",
      provenance: "derived",
      reasoning: "Derived source-geometry diagnostic only. Signed PIP angles use a side-oriented convention: positive flexion and negative extension. Thresholds are neither dataset-native labels nor a biomechanical regularizer. The processed motion remains source-faithful, and no hidden clamp or smoothing was applied.",
      extras: { hand_biomechanics: handBiomechanics },
    });
  }

  const sampleId = sample.sample_id || payload?.sample_id;
  const inferred = labelFromSampleId(sampleId);
  if (inferred && !hasSemanticAnnotation) {
    add({ level: "action", type: "inferred_action", bodypart: "action", text: inferred, source: "sample.sample_id", provenance: "derived", reasoning: "Inferred from the source sample identifier; this is not a dataset-native action label." });
  } else if (!hasSemanticAnnotation && !inferred) {
    add({ level: "action", type: "unlabelled_motion", bodypart: "action", text: "Unlabelled motion", source: "viewer.compatibility", provenance: "fallback", reasoning: "No native or derived semantic label is available in this preview payload." });
  }
  return annotations;
}

function normalizeConfidence(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "object" && !Array.isArray(value)) {
    const numeric = numberOrNull(value.value);
    return {
      value: numeric ?? cleanText(value.value),
      min: numberOrNull(value.min),
      max: numberOrNull(value.max),
      unit: cleanText(value.unit) || null,
    };
  }
  const numeric = numberOrNull(value);
  return { value: numeric ?? cleanText(value), min: null, max: null, unit: null };
}

function provenanceFor(annotation) {
  const declared = normalizedName(annotation.provenance);
  if (PROVENANCE_VALUES.has(declared)) return declared;
  const reasoning = cleanText(annotation.reasoning ?? annotation.note ?? annotation.source).toLowerCase();
  if (reasoning.includes("fallback") || reasoning.includes("unlabelled")) return "fallback";
  if (reasoning.includes("infer") || reasoning.includes("deriv") || reasoning.includes("推断")) return "derived";
  return annotation.schema_version?.startsWith?.("virea.annotation.v1") ? "native" : "legacy";
}

function redactedExtra(value, key = "", depth = 0) {
  if (SECRET_KEY.test(key)) return "[redacted]";
  if (depth > 8) return "[maximum depth reached]";
  if (Array.isArray(value)) return value.slice(0, 512).map((item) => redactedExtra(item, "", depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([childKey, child]) => [childKey, redactedExtra(child, childKey, depth + 1)]));
  }
  return value;
}

function extrasFor(annotation) {
  const extras = annotation.extras && typeof annotation.extras === "object" && !Array.isArray(annotation.extras)
    ? { ...redactedExtra(annotation.extras) }
    : {};
  for (const [key, value] of Object.entries(annotation)) {
    if (!STANDARD_FIELDS.has(key)) extras[key] = redactedExtra(value, key);
  }
  return extras;
}

function originalRange(annotation, fps, rawStartSec, rawEndSec, rawStartFrame, rawEndFrame) {
  const original = annotation.original && typeof annotation.original === "object" ? redactedExtra(annotation.original) : {};
  const nativeTime = original.time && typeof original.time === "object" ? original.time : {};
  return {
    ...original,
    start_sec: numberOrNull(original.start_sec ?? original.start ?? nativeTime.start_sec ?? rawStartSec),
    end_sec: numberOrNull(original.end_sec ?? original.end ?? nativeTime.end_sec ?? rawEndSec),
    start_frame: numberOrNull(original.start_frame ?? nativeTime.start_frame ?? rawStartFrame),
    end_frame: numberOrNull(original.end_frame ?? nativeTime.end_frame ?? rawEndFrame),
    fps: numberOrNull(original.fps ?? original.source_fps ?? nativeTime.source_fps ?? annotation.source_fps ?? fps),
  };
}

function isHandSpecific(value) {
  const raw = normalizedName(value);
  return raw === "hands" || /(^|_)(left|right|l|r)?_?(hand|hands|wrist|thumb|index|middle|ring|little|pinky)(_|$)/.test(raw) || /^(l|r)(hand|wrist)/.test(raw);
}

export function normalizeAnnotations(payload, fallbackSample = null) {
  const fps = Number(payload?.fps ?? payload?.time?.effective_fps ?? fallbackSample?.fps ?? 0) || 0;
  const duration = effectiveDuration(payload, fallbackSample, fps);
  const frameCount = numberOrNull(payload?.frame_count ?? payload?.frames?.positions?.length ?? fallbackSample?.frame_count);
  const annotations = flattenAnnotationBlocks(payload?.annotations);
  if (!annotations.length && payload?.metadata?.annotation_record) annotations.push(...flattenAnnotationBlocks(payload.metadata.annotation_record));
  if (!annotations.length && fallbackSample?.metadata?.annotation_record) annotations.push(...flattenAnnotationBlocks(fallbackSample.metadata.annotation_record));
  const fallbackText = cleanText(payload?.sample?.text || fallbackSample?.text);
  if (fallbackText) annotations.unshift({ level: "sequence", type: "caption", bodypart: "sequence_caption", text: fallbackText, source: "sample.text", provenance: "native" });

  const hasSemanticAnnotation = annotations.some((annotation) => {
    const part = bodyPartFromAnnotation(annotation, payload);
    return part === "sequence_caption" || part === "action" || PART_ORDER.includes(part) || ["object", "dialogue"].includes(part);
  });
  annotations.push(...metadataAnnotations(payload, fallbackSample, hasSemanticAnnotation));

  const seen = new Set();
  return annotations
    .map((annotation, index) => {
      const bodypart = bodyPartFromAnnotation(annotation, payload);
      const level = annotationLevel(bodypart, annotation);
      const rawStartSec = readStart(annotation, fps);
      const rawEndSec = readEnd(annotation, fps);
      const rawStartFrame = numberOrNull(annotation.start_frame ?? annotation.frame_start ?? annotation.startFrame);
      const rawEndFrame = numberOrNull(annotation.end_frame ?? annotation.frame_end ?? annotation.endFrame);
      let startSec = rawStartSec;
      let endSec = rawEndSec;
      let startFrame = rawStartFrame ?? frameFromSeconds(startSec, fps);
      let endFrame = rawEndFrame ?? frameFromSeconds(endSec, fps);
      if (startSec !== null && endSec !== null && endSec < startSec) [startSec, endSec] = [endSec, startSec];
      if (startFrame !== null && endFrame !== null && endFrame < startFrame) [startFrame, endFrame] = [endFrame, startFrame];
      let clipped = Boolean(annotation.clipped);
      if (duration !== null) {
        const nextStart = startSec === null ? null : Math.max(0, Math.min(duration, startSec));
        const nextEnd = endSec === null ? null : Math.max(0, Math.min(duration, endSec));
        clipped ||= nextStart !== startSec || nextEnd !== endSec;
        startSec = nextStart;
        endSec = nextEnd;
      }
      if (frameCount !== null) {
        const nextStart = startFrame === null ? null : Math.max(0, Math.min(frameCount, startFrame));
        const nextEnd = endFrame === null ? null : Math.max(0, Math.min(frameCount, endFrame));
        clipped ||= nextStart !== startFrame || nextEnd !== endFrame;
        startFrame = nextStart;
        endFrame = nextEnd;
      }
      const text = textFromAnnotation(annotation);
      const rawLabel = cleanText(annotation.label ?? annotation.proc_label ?? annotation.raw_label);
      const source = cleanText(annotation.source) || (annotation.schema_version ? "annotation" : "legacy annotation object");
      const provenance = provenanceFor(annotation);
      const id = cleanText(annotation.id) || `compat-${bodypart}-${index}`;
      const dedupeKey = cleanText(annotation.id)
        ? `id:${annotation.id}`
        : [bodypart, level, text, rawLabel, startSec ?? "", endSec ?? "", source, provenance].join("|");
      if ((!text && !rawLabel) || seen.has(dedupeKey)) return null;
      seen.add(dedupeKey);
      const levelMeta = LEVEL_META[level] || LEVEL_META.metadata;
      const partMeta = PART_META[bodypart] || PART_META.metadata;
      return {
        schemaVersion: cleanText(annotation.schema_version) || "virea.annotation.compat.v0",
        id,
        bodypart,
        level,
        type: cleanText(annotation.type ?? annotation.kind) || bodypart,
        label: PART_META[bodypart]?.label || rawLabel || bodypart.replace(/_/g, " "),
        text: text || rawLabel,
        rawLabel: rawLabel && rawLabel !== text ? rawLabel : "",
        startSec,
        endSec,
        startFrame,
        endFrame,
        original: originalRange(annotation, fps, rawStartSec, rawEndSec, rawStartFrame, rawEndFrame),
        clipped,
        confidence: normalizeConfidence(annotation.confidence ?? annotation.score),
        reasoning: cleanText(annotation.reasoning ?? annotation.note) || null,
        source,
        provenance,
        sourceType: cleanText(annotation.type ?? annotation.kind ?? annotation.scope),
        color: levelMeta.color,
        anchorColor: partMeta.color,
        extras: extrasFor(annotation),
        requiresHands: isHandSpecific(directBodypart(annotation) ?? annotation.type ?? annotation.kind),
        raw: annotation,
      };
    })
    .filter(Boolean)
    .sort((a, b) => {
      const partA = PART_ORDER.indexOf(a.bodypart);
      const partB = PART_ORDER.indexOf(b.bodypart);
      return (
        LEVEL_ORDER.indexOf(a.level) - LEVEL_ORDER.indexOf(b.level) ||
        (a.startSec ?? 0) - (b.startSec ?? 0) ||
        ((partA < 0 ? 99 : partA) - (partB < 0 ? 99 : partB)) ||
        a.text.localeCompare(b.text)
      );
    });
}

export function mergeAnnotations(...collections) {
  const byId = new Map();
  for (const annotation of collections.flat()) {
    if (!annotation) continue;
    const stableV1Id = annotation.schemaVersion?.startsWith?.("virea.annotation.v1") ? annotation.id : null;
    const key = stableV1Id || [annotation.bodypart, annotation.level, annotation.text, annotation.startSec, annotation.endSec, annotation.source, annotation.provenance].join("|");
    if (!byId.has(key)) byId.set(key, annotation);
  }
  return [...byId.values()].sort((a, b) => LEVEL_ORDER.indexOf(a.level) - LEVEL_ORDER.indexOf(b.level) || (a.startSec ?? 0) - (b.startSec ?? 0));
}

export function activeAnnotations(annotations, frame, fps) {
  const numericFrame = Number.isFinite(Number(frame)) ? Number(frame) : null;
  const time = numericFrame !== null && fps ? numericFrame / fps : null;
  return annotations.filter((annotation) => {
    if (numericFrame !== null && (annotation.startFrame !== null || annotation.endFrame !== null)) {
      const afterStart = annotation.startFrame === null || numericFrame >= annotation.startFrame;
      const beforeEnd = annotation.endFrame === null || numericFrame < annotation.endFrame;
      return afterStart && beforeEnd;
    }
    if (time === null) return true;
    const start = annotation.startSec;
    const end = annotation.endSec;
    if (start === null && end === null) return true;
    return (start === null || time >= start) && (end === null || time < end);
  });
}

export function sequenceText(annotations) {
  return annotations.find((annotation) => annotation.level === "sequence")?.text || "";
}

export function annotationsByLevel(annotations) {
  return Object.fromEntries(LEVEL_ORDER.map((level) => [level, annotations.filter((annotation) => annotation.level === level)]));
}

export function confidenceLabel(confidence) {
  if (!confidence) return "";
  const value = confidence.value ?? "?";
  const range = confidence.min !== null && confidence.max !== null ? ` (${confidence.min}-${confidence.max})` : "";
  const unit = confidence.unit ? ` ${confidence.unit}` : "";
  return `confidence ${value}${range}${unit}`;
}

function formatRange(start, end, unit) {
  if (start === null && end === null) return "whole clip / no native range";
  if (start !== null && end !== null) return `[${Number(start).toFixed(2)}, ${Number(end).toFixed(2)})${unit}`;
  if (start !== null) return `from ${Number(start).toFixed(2)}${unit}`;
  return `until ${Number(end).toFixed(2)}${unit} (exclusive)`;
}

export function timeLabel(annotation) {
  return formatRange(annotation.startSec, annotation.endSec, "s");
}

export function originalTimeLabel(annotation) {
  const original = annotation.original || {};
  if (original.start_sec !== null || original.end_sec !== null) return formatRange(original.start_sec, original.end_sec, "s");
  if (original.start_frame !== null || original.end_frame !== null) return formatRange(original.start_frame, original.end_frame, " frames");
  return "no native range";
}

export function clipText(text, max = 74) {
  const clean = cleanText(text);
  if (clean.length <= max) return clean;
  return `${clean.slice(0, Math.max(0, max - 1)).trim()}...`;
}

export function isHandJointName(name) {
  const normalized = normalizedName(name);
  return FINGER_NAMES.some((finger) => normalized.includes(finger));
}

function hasSide(name, side) {
  const n = normalizedName(name);
  const long = side === "left" ? "left" : "right";
  const short = side === "left" ? "l" : "r";
  return n.includes(long) || new RegExp(`(^|_)${short}(_|$)`).test(n) || new RegExp(`^${short}(arm|hand|wrist|leg|foot|knee|hip|shoulder|toe)`).test(n);
}

function jointMatchesPart(name, bodypart) {
  const n = normalizedName(name);
  if (bodypart === "head") return ["head", "neck", "eye", "jaw", "face"].some((token) => n.includes(token));
  if (bodypart === "spine") return ["spine", "chest", "torso", "pelvis", "hips", "root", "waist"].some((token) => n.includes(token));
  if (bodypart === "left_arm" || bodypart === "right_arm") {
    const side = bodypart.startsWith("left") ? "left" : "right";
    return hasSide(n, side) && ["arm", "shoulder", "elbow", "hand", "wrist", ...FINGER_NAMES].some((token) => n.includes(token));
  }
  if (bodypart === "hands") return ["hand", "wrist", ...FINGER_NAMES].some((token) => n.includes(token));
  if (bodypart === "left_leg" || bodypart === "right_leg") {
    const side = bodypart.startsWith("left") ? "left" : "right";
    return hasSide(n, side) && ["leg", "hip", "knee", "foot", "ankle", "toe"].some((token) => n.includes(token));
  }
  return false;
}

function jointAliasNames(payload, name) {
  const sources = [
    payload?.joint_aliases,
    payload?.skeleton?.joint_aliases,
    payload?.metadata?.joint_aliases,
    payload?.profile?.viewer?.joint_aliases,
    payload?.resolved_profile?.viewer?.joint_aliases,
  ].filter((value) => value && typeof value === "object" && !Array.isArray(value));
  const normalized = normalizedName(name);
  const aliases = [name];
  for (const source of sources) {
    for (const [key, value] of Object.entries(source)) {
      const values = Array.isArray(value) ? value : [value];
      if (normalizedName(key) === normalized) aliases.push(...values.filter((item) => typeof item === "string"));
      if (values.some((item) => typeof item === "string" && normalizedName(item) === normalized)) aliases.push(key);
    }
  }
  return aliases;
}

function explicitPartJointIndices(payload, bodypart) {
  const names = payload?.skeleton?.joint_names || [];
  const matches = new Set();
  for (const aliases of aliasSources(payload)) {
    for (const [key, value] of Object.entries(aliases)) {
      if (canonicalPart(key, payload) !== bodypart) continue;
      const candidates = Array.isArray(value) ? value : [value];
      for (const candidate of candidates) {
        if (Number.isInteger(candidate) && candidate >= 0 && candidate < names.length) matches.add(candidate);
        if (typeof candidate === "string") {
          names.forEach((name, index) => {
            if (normalizedName(name) === normalizedName(candidate)) matches.add(index);
          });
        }
      }
    }
  }
  return [...matches];
}

export function partJointIndices(payload, bodypart, options = {}) {
  const canonical = canonicalPart(bodypart, payload);
  const names = payload?.skeleton?.joint_names || [];
  const explicit = explicitPartJointIndices(payload, canonical);
  const inferred = names
    .map((name, index) => (jointAliasNames(payload, name).some((candidate) => jointMatchesPart(candidate, canonical)) ? index : -1))
    .filter((index) => index >= 0);
  let indices = [...new Set([...explicit, ...inferred])];
  if (canonical === "trajectory" && !indices.length) indices = [0];
  if (options.includeHands === false) indices = indices.filter((index) => !isHandJointName(names[index]));
  return indices;
}

export function groupedPartAnnotations(annotations) {
  const groups = new Map();
  for (const annotation of annotations) {
    if (!PART_ORDER.includes(annotation.bodypart)) continue;
    if (!groups.has(annotation.bodypart)) groups.set(annotation.bodypart, []);
    groups.get(annotation.bodypart).push(annotation);
  }
  return groups;
}

export function buildTimelineRows(annotations, maxRows = 8) {
  const groups = new Map();
  for (const annotation of annotations) {
    const key = annotation.level === "part" || annotation.level === "context" ? annotation.bodypart : annotation.level;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(annotation);
  }
  const rows = [...groups.entries()].map(([key, entries]) => ({
    key,
    label: PART_META[key]?.label || LEVEL_META[key]?.label || key.replace(/_/g, " "),
    level: entries[0]?.level || "metadata",
    color: entries[0]?.anchorColor || entries[0]?.color || LEVEL_META.metadata.color,
    annotations: entries,
    aggregated: false,
    groupCount: 1,
  }));
  rows.sort((a, b) => LEVEL_ORDER.indexOf(a.level) - LEVEL_ORDER.indexOf(b.level) || a.label.localeCompare(b.label));
  const limit = Math.max(1, Number(maxRows) || 1);
  if (rows.length <= limit) return rows;
  const visible = rows.slice(0, Math.max(0, limit - 1));
  const hidden = rows.slice(Math.max(0, limit - 1));
  visible.push({
    key: "__other__",
    label: `Other (+${hidden.length} groups)`,
    level: "metadata",
    color: LEVEL_META.metadata.color,
    annotations: hidden.flatMap((row) => row.annotations),
    aggregated: true,
    groupCount: hidden.length,
  });
  return visible;
}

function channelEntries(payload) {
  const channels = payload?.channels;
  if (Array.isArray(channels)) return channels;
  if (channels && typeof channels === "object") {
    return Object.entries(channels).map(([kind, descriptor]) => ({ kind, ...(descriptor && typeof descriptor === "object" ? descriptor : { preview: descriptor }) }));
  }
  return [];
}

export function normalizeChannels(payload) {
  const result = [];
  for (const [index, channel] of channelEntries(payload).entries()) {
    const kind = canonicalPart(channel.kind ?? channel.type ?? channel.id, payload);
    result.push({
      schemaVersion: cleanText(channel.schema_version) || "virea.channel.compat.v0",
      id: cleanText(channel.id) || `channel-${kind}-${index}`,
      kind,
      availability: cleanText(channel.availability) || (channel.preview !== undefined ? "inline" : "metadata_only"),
      representation: cleanText(channel.representation) || null,
      timebase: cleanText(channel.timebase) || null,
      fps: numberOrNull(channel.fps),
      frameCount: numberOrNull(channel.frame_count),
      shape: Array.isArray(channel.shape) ? channel.shape : null,
      coordinateSystem: cleanText(channel.coordinate_system) || null,
      unit: cleanText(channel.unit) || null,
      source: cleanText(channel.source) || null,
      provenance: provenanceFor(channel),
      reasonUnavailable: cleanText(channel.reason_unavailable) || null,
      preview: channel.preview ?? null,
      dataRef: channel.data_ref ?? null,
      extras: extrasFor(channel),
      raw: channel,
    });
  }
  return result;
}

export function mergeChannels(...collections) {
  const result = new Map();
  for (const channel of collections.flat()) {
    if (!channel) continue;
    const key = channel.id || `${channel.kind}:${channel.source || ""}`;
    if (!result.has(key)) result.set(key, channel);
  }
  return [...result.values()];
}

export function channelVectorAt(channel, frame) {
  const raw = channel?.preview?.translation_m ?? channel?.preview?.positions_m ?? channel?.preview?.points_m ?? channel?.raw?.translation_m ?? channel?.raw?.points_m;
  if (!Array.isArray(raw) || !raw.length) return null;
  if (raw.length >= 3 && raw.slice(0, 3).every(Number.isFinite)) return raw.slice(0, 3);
  const safe = Math.max(0, Math.min(Math.floor(Number(frame) || 0), raw.length - 1));
  const vector = raw[safe];
  if (Array.isArray(vector) && vector.length >= 3 && vector.slice(0, 3).every(Number.isFinite)) return vector.slice(0, 3);
  if (Array.isArray(vector) && vector.length && vector.every((point) => Array.isArray(point) && point.slice(0, 3).every(Number.isFinite))) {
    return vector.reduce((sum, point) => [sum[0] + point[0] / vector.length, sum[1] + point[1] / vector.length, sum[2] + point[2] / vector.length], [0, 0, 0]);
  }
  return null;
}

export function canonicalChannelVectorAt(channels, kind, motionFrame, motionFps) {
  const canonicalCoordinate = (value) => {
    const coordinate = normalizedName(value);
    return coordinate.startsWith("gltf_") || coordinate.startsWith("virea_canonical_") || coordinate === "canonical";
  };
  const canonicalMetricChannels = (channels || []).filter((item) => {
    const unit = normalizedName(item?.unit);
    return item?.kind === kind && canonicalCoordinate(item.coordinateSystem) && (unit === "meter" || unit === "m");
  });
  for (const channel of canonicalMetricChannels) {
    const channelFrame = channel.fps && motionFps ? (motionFrame / motionFps) * channel.fps : motionFrame;
    const vector = channelVectorAt(channel, channelFrame);
    if (Array.isArray(vector) && vector.length >= 3 && vector.slice(0, 3).every(Number.isFinite)) return vector;
  }
  return null;
}

export function verifiedSidecarReference(value) {
  const reference = value?.sidecar && typeof value.sidecar === "object" ? value.sidecar : value;
  if (!reference || typeof reference !== "object") return null;
  const sha256 = cleanText(reference.sha256).toLowerCase();
  const byteLength = numberOrNull(reference.byte_length);
  if (!/^[0-9a-f]{64}$/.test(sha256) || byteLength === null || byteLength < 0) return null;
  const path = cleanText(reference.path);
  if (!path.startsWith(`sidecars/${sha256}`) || path.includes("..") || path.includes("\\")) return null;
  const expectedApi = `/api/artifacts/sidecars/${sha256}`;
  const declaredApi = cleanText(reference.read_api);
  if (declaredApi && declaredApi !== expectedApi) return null;
  return {
    sha256,
    byteLength,
    mediaType: cleanText(reference.media_type) || "application/octet-stream",
    encoding: cleanText(reference.encoding) || "binary",
    path,
    readApi: expectedApi,
  };
}

export function collectSidecarReferences(value, depth = 0, output = new Map()) {
  if (depth > 8 || value === null || value === undefined) return [...output.values()];
  const reference = verifiedSidecarReference(value);
  if (reference) {
    output.set(reference.sha256, reference);
    return [...output.values()];
  }
  if (Array.isArray(value)) {
    for (const child of value.slice(0, 512)) collectSidecarReferences(child, depth + 1, output);
  } else if (typeof value === "object") {
    for (const child of Object.values(value)) collectSidecarReferences(child, depth + 1, output);
  }
  return [...output.values()];
}

export function interpolatePositionFrame(frames, frame) {
  if (!Array.isArray(frames) || !frames.length) return [];
  const value = Math.max(0, Math.min(Number(frame) || 0, frames.length - 1));
  const a = Math.floor(value);
  const b = Math.min(a + 1, frames.length - 1);
  const alpha = value - a;
  if (!alpha || a === b) return frames[a];
  const count = Math.max(frames[a]?.length || 0, frames[b]?.length || 0);
  return Array.from({ length: count }, (_, index) => {
    const p0 = frames[a]?.[index];
    const p1 = frames[b]?.[index];
    if (!Array.isArray(p0)) return p1;
    if (!Array.isArray(p1)) return p0;
    return [
      p0[0] + (p1[0] - p0[0]) * alpha,
      p0[1] + (p1[1] - p0[1]) * alpha,
      p0[2] + (p1[2] - p0[2]) * alpha,
    ];
  });
}
