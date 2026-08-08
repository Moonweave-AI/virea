import {
  LEVEL_META,
  LEVEL_ORDER,
  PART_META,
  PART_ORDER,
  PROVENANCE_META,
  activeAnnotations,
  annotationsByLevel,
  buildTimelineRows,
  collectSidecarReferences,
  confidenceLabel,
  clipText,
  groupedPartAnnotations,
  interpolatePositionFrame,
  isHandJointName,
  mergeAnnotations,
  mergeChannels,
  normalizeAnnotations,
  normalizeChannels,
  originalTimeLabel,
  partJointIndices,
  sequenceText,
  timeLabel,
} from "./annotations.js";

const state = {
  dataSources: {},
  datasets: [],
  samples: [],
  selected: null,
  raw: null,
  processed: null,
  annotations: [],
  channels: [],
  annotationLevels: new Set(LEVEL_ORDER),
  frame: 0,
  playing: false,
  playbackTimer: null,
  playbackStartMs: 0,
  playbackStartTimeSec: 0,
  playbackNextRenderMs: Number.NEGATIVE_INFINITY,
  showHands: false,
  showTrails: true,
  viewYaw: 0,
  viewPitch: 0.08,
  viewZoom: 1,
  viewDragging: false,
  viewPointer: [0, 0],
  sampleListRequest: 0,
  previewRequest: 0,
  annotationRevision: 0,
};

const $ = (id) => document.getElementById(id);
const FINGER_PATTERNS = ["thumb", "index", "middle", "ring", "little"];
const ROOT_NAMES = ["hips", "pelvis", "root"];
const CURRENT_TRAIL = 48;
const MAX_PLAYBACK_RENDER_HZ = 60;
const THEME_KEY = "virea-theme";

let vrmViewer = null;
let sharedBoundsCache = null;
const normalizedFramesCache = new WeakMap();
const skeletonCanvasVisibility = new WeakMap();
const cssVariableCache = new Map();
let projectionTrigCache = { yaw: Number.NaN, pitch: Number.NaN, cy: 1, sy: 0, cp: 1, sp: 0 };
let filteredAnnotationCache = { key: "", value: [] };
let activeAnnotationCache = { key: "", value: [] };

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.text();
    let detail = body;
    try {
      detail = JSON.parse(body)?.detail || body;
    } catch {
      // Preserve a non-JSON server/proxy response as plain text.
    }
    throw new Error(`${response.status} ${detail}`);
  }
  return response.json();
}

function formatErrorTable(quality) {
  if (!quality) return "";
  const lines = [];
  lines.push(`Frames: ${quality.frame_count} | Joints: ${quality.joint_count}`);
  if (quality.retarget_direction_error) {
    const re = quality.retarget_direction_error;
    lines.push(`Direction Error: mean=${re.overall_mean_deg?.toFixed(4)}° max=${re.overall_max_deg?.toFixed(4)}° (${re.max_as_pct_of_full_rotation?.toFixed(4)}%)`);
  }
  return lines.join("\n");
}

function renderQualityPanel(quality) {
  const panel = $("qualityPanel");
  if (panel.dataset.qualityInitialized === "true" && panel.__vireaQuality === quality) return;
  panel.dataset.qualityInitialized = "true";
  panel.__vireaQuality = quality;
  if (!quality || (!quality.retarget_direction_error && !quality.ground_contact)) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "";

  const rde = quality.retarget_direction_error;
  const heroEl = $("qualityHeroValue");
  const heroSub = $("qualityHeroSub");

  if (rde) {
    const maxDeg = rde.overall_max_deg ?? 0;
    const pct = rde.max_as_pct_of_full_rotation ?? 0;
    heroEl.textContent = `${maxDeg.toFixed(4)}°`;
    heroEl.className = "quality-hero-value" + (pct > 1 ? " bad" : pct > 0.1 ? " warn" : "");
    heroSub.textContent = `Mean: ${(rde.overall_mean_deg ?? 0).toFixed(4)}° | ${pct.toFixed(4)}% of full rotation | ${rde.bones_evaluated ?? 0} bones`;
  } else {
    heroEl.textContent = "N/A";
    heroEl.className = "quality-hero-value";
    heroSub.textContent = "";
  }

  const gcBody = $("qualityGcBody");
  if (quality.ground_contact) {
    const gc = quality.ground_contact;
    gcBody.innerHTML = `
      <div class="stat-row"><span class="stat-label">Floating</span><span class="stat-value">${(gc.floating_ratio * 100).toFixed(1)}%</span></div>
      <div class="stat-row"><span class="stat-label">Penetrating</span><span class="stat-value">${(gc.penetrating_ratio * 100).toFixed(1)}%</span></div>
      <div class="stat-row"><span class="stat-label">Foot range</span><span class="stat-value">${gc.min_foot_height_m?.toFixed(3)}m ~ ${gc.max_foot_height_m?.toFixed(3)}m</span></div>
    `;
  } else {
    gcBody.textContent = "--";
  }

  const velBody = $("qualityVelBody");
  if (quality.velocity) {
    const v = quality.velocity;
    velBody.innerHTML = `
      <div class="stat-row"><span class="stat-label">Mean speed</span><span class="stat-value">${v.mean_speed_m_s?.toFixed(3)} m/s</span></div>
      <div class="stat-row"><span class="stat-label">Max speed</span><span class="stat-value">${v.max_speed_m_s?.toFixed(3)} m/s</span></div>
      <div class="stat-row"><span class="stat-label">Jittery joints</span><span class="stat-value">${v.jittery_joints ?? 0}</span></div>
    `;
  } else {
    velBody.textContent = "--";
  }

  const symBody = $("qualitySymBody");
  if (quality.symmetry) {
    const s = quality.symmetry;
    const pairs = (s.details || []).map((d) => `<div class="stat-row"><span class="stat-label">${escapeHtml(String(d.pair || "").replace(" / ", "/"))}</span><span class="stat-value">${(d.asymmetry_ratio * 100).toFixed(1)}%</span></div>`);
    symBody.innerHTML = `
      <div class="stat-row"><span class="stat-label">Max asymmetry</span><span class="stat-value">${(s.max_asymmetry * 100).toFixed(1)}%</span></div>
      ${pairs.join("")}
    `;
  } else {
    symBody.textContent = "--";
  }

  const bones = quality.per_bone_direction_errors || [];
  const chartEl = $("qualityBoneChart");
  const tableBody = $("qualityBoneTableBody");

  if (bones.length > 0) {
    const maxVal = Math.max(...bones.map((b) => b.max_deg || 0), 0.001);
    chartEl.innerHTML = bones
      .map((b) => {
        const pct = Math.max(((b.max_deg || 0) / maxVal) * 100, 2);
        return `<div class="quality-bone-bar" style="height:${pct}%" data-tooltip="${escapeHtml(b.bone)}: ${b.max_deg?.toFixed(4)}°"></div>`;
      })
      .join("");

    tableBody.innerHTML = bones
      .map((b) => {
        const barW = Math.max(((b.max_deg || 0) / maxVal) * 60, 0);
        return `<tr>
          <td>${escapeHtml(b.bone)}</td>
          <td><span class="cell-bar" style="width:${barW}px"></span>${b.mean_deg?.toFixed(4)}</td>
          <td><span class="cell-bar" style="width:${barW}px"></span>${b.max_deg?.toFixed(4)}</td>
          <td>${b.std_rad?.toFixed(6)}</td>
          <td>${b.worst_frame}</td>
        </tr>`;
      })
      .join("");
  } else {
    chartEl.innerHTML = '<span style="color:var(--muted);font-size:0.8rem">No bone direction data</span>';
    tableBody.innerHTML = "";
  }
}

function metaSummary(payload) {
  if (!payload) return "";
  const q = payload.quality;
  if (q && (q.per_joint_errors || q.retarget_error || q.ground_contact)) {
    return formatErrorTable(q);
  }
  return JSON.stringify(
    {
      fps: payload.fps,
      frames: payload.frame_count,
      joints: payload.skeleton?.joint_names?.length,
      quality: q,
    },
    null,
    2,
  );
}

function applyTheme(theme) {
  const resolved = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = resolved;
  cssVariableCache.clear();
  localStorage.setItem(THEME_KEY, resolved);
  $("themeToggle").textContent = resolved === "dark" ? "Light Theme" : "Dark Theme";
  vrmViewer?.setTheme?.(resolved);
}

function cssVar(name, fallback) {
  const key = `${document.documentElement.dataset.theme || "light"}:${name}`;
  if (cssVariableCache.has(key)) return cssVariableCache.get(key);
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const resolved = value || fallback;
  cssVariableCache.set(key, resolved);
  return resolved;
}

function isDarkTheme() {
  return document.documentElement.dataset.theme === "dark";
}

function sampleText(sample) {
  return sample?.text || sample?.metadata?.object_name || sample?.metadata?.name || "";
}

function fpsForAnnotations() {
  return Number(state.processed?.fps || state.raw?.fps || state.selected?.fps || 0) || 0;
}

function playbackFrameCount() {
  return Number(state.processed?.frame_count || state.raw?.frame_count || 0) || 0;
}

function playbackDuration() {
  const count = playbackFrameCount();
  const fps = playbackFps();
  return count && fps ? count / fps : 0;
}

function currentTimeSec() {
  const fps = playbackFps();
  return fps ? state.frame / fps : 0;
}

function frameForPayload(payload) {
  const fps = Number(payload?.fps || playbackFps()) || playbackFps();
  const count = Number(payload?.frame_count || payload?.frames?.positions?.length || 0) || 0;
  return Math.max(0, Math.min(currentTimeSec() * fps, Math.max(0, count - 1)));
}

function filteredAnnotations() {
  const levels = LEVEL_ORDER.map((level) => state.annotationLevels.has(level) ? "1" : "0").join("");
  const key = `${state.annotationRevision}:${levels}`;
  if (filteredAnnotationCache.key !== key) {
    filteredAnnotationCache = {
      key,
      value: (state.annotations || []).filter((annotation) => state.annotationLevels.has(annotation.level)),
    };
  }
  return filteredAnnotationCache.value;
}

function currentActiveAnnotations() {
  const visible = filteredAnnotations();
  const fps = fpsForAnnotations();
  const key = `${filteredAnnotationCache.key}:${Math.floor(Math.max(0, state.frame) + 1e-9)}:${fps}`;
  if (activeAnnotationCache.key !== key) {
    activeAnnotationCache = { key, value: activeAnnotations(visible, state.frame, fps) };
  }
  return activeAnnotationCache.value;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function replaceOptions(select, entries) {
  select.replaceChildren();
  for (const { value, label } of entries) {
    const option = document.createElement("option");
    option.value = String(value ?? "");
    option.textContent = String(label ?? "");
    select.appendChild(option);
  }
}

function annotationTooltip(annotation) {
  const lines = [
    `${annotation.label}: ${annotation.text}`,
    `effective ${timeLabel(annotation)}`,
    annotation.clipped ? `original ${originalTimeLabel(annotation)} (clipped)` : "",
    confidenceLabel(annotation.confidence),
    `${PROVENANCE_META[annotation.provenance]?.label || annotation.provenance}: ${annotation.source}`,
    annotation.reasoning || "",
  ].filter(Boolean);
  return escapeHtml(lines.join("\n"));
}

function provenanceBadgeHtml(annotation) {
  const provenance = PROVENANCE_META[annotation.provenance] || PROVENANCE_META.legacy;
  return `<span class="annotation-provenance ${provenance.className}">${escapeHtml(provenance.label)}</span>`;
}

function extrasHtml(annotation) {
  const extras = annotation.extras || {};
  if (!Object.keys(extras).length) return "";
  return `
    <details class="annotation-extras">
      <summary>Unknown / extension fields (${Object.keys(extras).length})</summary>
      <pre>${escapeHtml(JSON.stringify(extras, null, 2))}</pre>
    </details>
  `;
}

function originalHtml(annotation) {
  const original = annotation.original && typeof annotation.original === "object" ? annotation.original : {};
  if (!Object.keys(original).length) return "";
  return `
    <details class="annotation-extras annotation-original">
      <summary>Native / original record (${Object.keys(original).length} fields)</summary>
      <pre>${escapeHtml(JSON.stringify(original, null, 2))}</pre>
    </details>
  `;
}

function contractHtml(annotation) {
  const fields = [
    `schema=${annotation.schemaVersion || "unknown"}`,
    `id=${annotation.id || "unknown"}`,
    `level=${annotation.level || "unknown"}`,
    `type=${annotation.type || "unknown"}`,
    `bodypart=${annotation.bodypart || "none"}`,
  ];
  return `<small class="annotation-contract">${escapeHtml(fields.join(" · "))}</small>`;
}

function annotationGroupText(annotations, maxItems = 3) {
  const text = annotations
    .slice(0, maxItems)
    .map((annotation) => clipText(annotation.text, 42))
    .join(" | ");
  const extra = annotations.length > maxItems ? ` +${annotations.length - maxItems}` : "";
  return `${text}${extra}`;
}

function annotationAnchorIndices(payload, bodypart) {
  const names = payload?.skeleton?.joint_names || [];
  const byNames = (patterns) =>
    names
      .map((name, index) => ({ name: String(name || "").toLowerCase(), index }))
      .filter(({ name }) => patterns.some((pattern) => name.includes(pattern)) && (state.showHands || !isHandJointName(name)))
      .map(({ index }) => index);
  if (PART_ORDER.includes(bodypart)) return partJointIndices(payload, bodypart, { includeHands: state.showHands });
  if (bodypart === "object" || bodypart === "contact" || bodypart === "interaction") {
    return byNames(["hand", "wrist", "thumb", "index"]).slice(0, 8);
  }
  if (bodypart === "dialogue" || bodypart === "face") {
    return byNames(["head", "neck", "jaw"]);
  }
  if (bodypart === "action") {
    return [rootIndex(payload), ...byNames(["spine", "chest", "hips"]).slice(0, 4)];
  }
  return [rootIndex(payload)];
}

function timelineHtml(annotations, timeSec, duration, maxRows = 6) {
  if (!annotations.length || !duration) return "";
  const rows = buildTimelineRows(annotations, maxRows);
  const pct = Math.min(100, Math.max(0, (timeSec / duration) * 100));
  return `
    <div class="annotation-mini-timeline">
      <div class="annotation-mini-cursor" style="left:${pct}%"></div>
      ${rows
        .map((row) => {
          const bars = row.annotations
            .map((annotation) => {
              const start = Math.max(0, annotation.startSec ?? 0);
              const end = Math.min(duration, annotation.endSec ?? duration);
              const left = (start / duration) * 100;
              const width = Math.max(1, ((end - start) / duration) * 100);
              const untimed = annotation.startSec === null && annotation.endSec === null ? " untimed" : "";
              return `<span class="${untimed}" title="${annotationTooltip(annotation)}" style="--part-color:${annotation.color};left:${left}%;width:${width}%"></span>`;
            })
            .join("");
          return `<div class="annotation-mini-row"><strong>${escapeHtml(row.label)}</strong><div>${bars}</div></div>`;
        })
        .join("")}
    </div>
  `;
}

function levelFiltersHtml() {
  return LEVEL_ORDER.map((level) => {
    const meta = LEVEL_META[level];
    const active = state.annotationLevels.has(level);
    return `<button type="button" class="annotation-filter ${active ? "active" : ""}" data-annotation-level="${level}" aria-pressed="${active}" style="--part-color:${meta.color}">${escapeHtml(meta.label)}</button>`;
  }).join("");
}

function attachFilterControls(container) {
  for (const button of container?.querySelectorAll?.("[data-annotation-level]") || []) {
    button.addEventListener("click", () => {
      const level = button.dataset.annotationLevel;
      if (state.annotationLevels.has(level)) state.annotationLevels.delete(level);
      else state.annotationLevels.add(level);
      vrmViewer?.setAnnotations?.(filteredAnnotations());
      renderPreview();
    });
  }
}

function renderTimelineInto(element, annotations) {
  if (!element) return;
  const duration = playbackDuration();
  if (!annotations.length || !duration) {
    element.innerHTML = '<span class="annotation-empty">No annotation timeline is available.</span>';
    return;
  }
  const rows = buildTimelineRows(annotations, 8);
  const signature = `${rows.map((row) => `${row.key}:${row.annotations.map((item) => item.id).join(",")}`).join("|")}:${duration}`;
  if (element.dataset.signature !== signature) {
    element.dataset.signature = signature;
    element.innerHTML = `
      <div class="annotation-dom-cursor" data-annotation-cursor></div>
      ${rows.map((row) => `
        <div class="annotation-timeline-row">
          <strong title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</strong>
          <div class="annotation-timeline-track">
            ${row.annotations.map((annotation) => {
              const start = Math.max(0, annotation.startSec ?? 0);
              const end = Math.min(duration, annotation.endSec ?? duration);
              const startFrame = annotation.startFrame ?? Math.ceil(start * playbackFps() - 1e-9);
              const untimed = annotation.startSec === null && annotation.endSec === null ? " untimed" : "";
              return `<button type="button" class="annotation-timeline-bar${untimed}" data-annotation-jump="${startFrame}" title="${annotationTooltip(annotation)}" aria-label="Jump to ${escapeHtml(annotation.label)}" style="--part-color:${annotation.color};left:${(start / duration) * 100}%;width:${Math.max(1, ((end - start) / duration) * 100)}%"></button>`;
            }).join("")}
          </div>
        </div>
      `).join("")}
    `;
    for (const button of element.querySelectorAll("[data-annotation-jump]")) {
      button.addEventListener("click", () => {
        stopPlayback();
        state.frame = Math.max(0, Math.min(Number(button.dataset.annotationJump) || 0, Math.max(0, playbackFrameCount() - 1)));
        renderPreview();
      });
    }
  }
  const cursor = element.querySelector("[data-annotation-cursor]");
  if (cursor) {
    const progress = Math.min(1, Math.max(0, currentTimeSec() / duration));
    cursor.style.left = `calc(102px + (100% - 110px) * ${progress})`;
  }
}

function previewBars(values) {
  const flattened = Array.isArray(values) ? values.flat(2).filter((value) => Number.isFinite(Number(value))).slice(0, 48) : [];
  if (!flattened.length) return "";
  const max = Math.max(...flattened.map((value) => Math.abs(Number(value))), 1e-6);
  return `<span class="channel-spark" aria-label="Inline preview with ${flattened.length} values">${flattened.map((value) => `<i style="height:${Math.max(8, Math.min(100, Math.abs(Number(value)) / max * 100))}%"></i>`).join("")}</span>`;
}

function sidecarUrl(reference) {
  const url = new URL(reference.readApi, window.location.origin);
  const source = $("dataSourceSelect")?.value;
  if (source) url.searchParams.set("data_source", source);
  return `${url.pathname}${url.search}`;
}

function attachSidecarControls(container, values) {
  if (!container) return;
  const references = collectSidecarReferences(values);
  if (!references.length) return;
  const group = document.createElement("div");
  group.className = "sidecar-controls";
  for (const reference of references) {
    const row = document.createElement("div");
    row.className = "sidecar-control";
    const summary = document.createElement("small");
    summary.textContent = `${reference.mediaType} | ${reference.byteLength.toLocaleString()} bytes | sha256 ${reference.sha256.slice(0, 12)}…`;
    row.appendChild(summary);
    const canInlineJson = reference.mediaType === "application/json" && reference.byteLength <= 2 * 1024 * 1024;
    if (canInlineJson) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "sidecar-action";
      button.textContent = "Load verified native record";
      const content = document.createElement("pre");
      content.hidden = true;
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const response = await fetch(sidecarUrl(reference), { headers: { Accept: "application/json" } });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const text = await response.text();
          if (text.length > 2 * 1024 * 1024) throw new Error("sidecar exceeds the safe inline limit");
          try {
            content.textContent = JSON.stringify(JSON.parse(text), null, 2);
          } catch {
            content.textContent = text;
          }
          content.hidden = false;
          button.textContent = "Verified native record loaded";
        } catch (error) {
          content.textContent = `Unable to load verified sidecar: ${error?.message || error}`;
          content.hidden = false;
          button.disabled = false;
        }
      });
      row.append(button, content);
    } else {
      const link = document.createElement("a");
      link.className = "sidecar-action";
      link.href = sidecarUrl(reference);
      link.download = reference.path.split("/").at(-1) || reference.sha256;
      link.textContent = "Download verified native channel";
      row.appendChild(link);
    }
    group.appendChild(row);
  }
  container.appendChild(group);
}

function renderChannelsInto(element) {
  if (!element) return;
  const channels = state.channels.filter((channel) => ["face", "audio", "object", "contact"].includes(channel.kind));
  const fallbackKinds = [...new Set(state.annotations.filter((annotation) => ["face", "audio", "object", "contact"].includes(annotation.bodypart)).map((annotation) => annotation.bodypart))];
  if (!channels.length && !fallbackKinds.length) {
    element.innerHTML = "";
    element.dataset.signature = "";
    element.style.display = "none";
    return;
  }
  const signature = channels.length
    ? channels.map((channel) => `${channel.id}:${channel.kind}:${channel.availability}:${channel.representation}:${channel.frameCount}:${channel.provenance}:${channel.dataRef?.sha256 || ""}`).join("|")
    : `fallback:${fallbackKinds.join("|")}`;
  if (element.dataset.signature === signature) return;
  element.dataset.signature = signature;
  element.style.display = "";
  element.innerHTML = channels.length
    ? channels.map((channel, index) => {
        const shape = channel.shape?.length ? ` · ${channel.shape.join("×")}` : "";
        const detail = [channel.representation, channel.frameCount ? `${channel.frameCount} frames` : "", channel.unit].filter(Boolean).join(" · ");
        const preview = channel.preview?.peaks ?? channel.preview?.weights ?? channel.preview?.values ?? null;
        return `<article class="channel-card" data-channel-index="${index}" style="--part-color:${PART_META[channel.kind]?.color || LEVEL_META.context.color}">
          <header><strong>${escapeHtml(PART_META[channel.kind]?.label || channel.kind)}</strong>${provenanceBadgeHtml(channel)}</header>
          <span>${escapeHtml(channel.availability || "unknown")}${escapeHtml(shape)}</span>
          <small>${escapeHtml(detail || channel.reasonUnavailable || "Descriptor metadata only; no per-frame visual data is claimed.")}</small>
          ${previewBars(preview)}
        </article>`;
      }).join("")
    : fallbackKinds.map((kind) => `<article class="channel-card availability-only" style="--part-color:${PART_META[kind]?.color || LEVEL_META.context.color}"><header><strong>${escapeHtml(PART_META[kind]?.label || kind)}</strong></header><span>Annotation / availability information only</span><small>No v1 per-frame channel descriptor is present.</small></article>`).join("");
  for (const card of element.querySelectorAll("[data-channel-index]")) {
    const channel = channels[Number(card.dataset.channelIndex)];
    attachSidecarControls(card, [channel?.dataRef, channel?.extras]);
  }
}

function renderAnnotationPanelInto(ids) {
  const panel = $(ids.panel);
  if (!panel) return;
  const annotations = state.annotations || [];
  if (!annotations.length) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "";
  const fps = fpsForAnnotations();
  const visible = filteredAnnotations();
  const active = currentActiveAnnotations();
  const grouped = annotationsByLevel(annotations);
  const sequence = sequenceText(annotations) || sampleText(state.selected);
  const sequenceValue = sequence || "No sequence-level text";
  if ($(ids.sequence).textContent !== sequenceValue) $(ids.sequence).textContent = sequenceValue;
  if (ids.summary) {
    const summaryValue = `${annotations.length} labels | ${active.length} active | sequence ${grouped.sequence.length} | action ${grouped.action.length} | part ${grouped.part.length} | context ${grouped.context.length} | metadata ${grouped.metadata.length}`;
    if ($(ids.summary).textContent !== summaryValue) $(ids.summary).textContent = summaryValue;
  }

  const filters = $(ids.filters);
  const filterSignature = LEVEL_ORDER.map((level) => state.annotationLevels.has(level) ? "1" : "0").join("");
  if (filters && filters.dataset.signature !== filterSignature) {
    filters.dataset.signature = filterSignature;
    filters.innerHTML = levelFiltersHtml();
    attachFilterControls(filters);
  }

  const chips = $(ids.chips);
  const activeSignature = active.map((annotation) => annotation.id).join("|");
  if (chips.dataset.signature !== activeSignature) {
    chips.dataset.signature = activeSignature;
    chips.innerHTML = active
      .slice(0, 18)
      .map((annotation) => `
          <span class="annotation-chip" style="--part-color:${annotation.color}" title="${annotationTooltip(annotation)}">
            <span>${escapeHtml(annotation.label)}</span>
            ${provenanceBadgeHtml(annotation)}
            ${escapeHtml(clipText(annotation.text, 46))}
          </span>
        `)
      .join("");
    if (!chips.innerHTML) chips.innerHTML = '<span class="annotation-empty">No visible annotation is active at this frame.</span>';
  }

  const detail = $(ids.detail);
  const detailSignature = `${state.annotationRevision}:${filterSignature}`;
  if (detail.dataset.signature !== detailSignature) {
    detail.dataset.signature = detailSignature;
    detail.innerHTML = LEVEL_ORDER
      .filter((level) => grouped[level].length)
      .map((level) => `
        <div class="annotation-level-title">${escapeHtml(LEVEL_META[level]?.label || level)} (${grouped[level].length})</div>
        ${grouped[level].map((annotation) => {
          const confidence = confidenceLabel(annotation.confidence);
          const timing = annotation.clipped ? `effective ${timeLabel(annotation)} · original ${originalTimeLabel(annotation)} · clipped` : timeLabel(annotation);
          return `<article data-annotation-id="${escapeHtml(annotation.id)}" class="annotation-detail ${state.annotationLevels.has(level) ? "" : "filtered-out"}" style="--part-color:${annotation.color}">
            <header><strong>${escapeHtml(annotation.label)}</strong>${provenanceBadgeHtml(annotation)}</header>
            <span>${escapeHtml(annotation.text)}</span>
            <small>${escapeHtml(timing)}${confidence ? ` · ${escapeHtml(confidence)}` : ""}</small>
            <small>source: ${escapeHtml(annotation.source)}${annotation.reasoning ? ` · ${escapeHtml(annotation.reasoning)}` : ""}</small>
            ${contractHtml(annotation)}
            ${originalHtml(annotation)}
            ${extrasHtml(annotation)}
          </article>`;
        }).join("")}
      `)
      .join("");
    const byId = new Map(annotations.map((annotation) => [annotation.id, annotation]));
    for (const card of detail.querySelectorAll("[data-annotation-id]")) {
      const annotation = byId.get(card.dataset.annotationId);
      attachSidecarControls(card, [annotation?.original, annotation?.extras]);
    }
  }
  const activeIds = new Set(active.map((annotation) => annotation.id));
  if (detail.dataset.activeSignature !== activeSignature) {
    detail.dataset.activeSignature = activeSignature;
    for (const card of detail.querySelectorAll("[data-annotation-id]")) card.classList.toggle("active", activeIds.has(card.dataset.annotationId));
  }
  renderTimelineInto($(ids.timeline), visible);
  renderChannelsInto($(ids.channels));
}

function renderAnnotationPanels() {
  renderAnnotationPanelInto({
    panel: "annotationPanel",
    sequence: "annotationSequenceText",
    summary: "annotationSummary",
    filters: "annotationLevelFilters",
    chips: "annotationActiveChips",
    detail: "annotationDetailList",
    timeline: "annotationTimeline",
    channels: "annotationChannelSummary",
  });
  renderAnnotationPanelInto({
    panel: "modelAnnotationPanel",
    sequence: "modelAnnotationSequenceText",
    summary: "modelAnnotationSummary",
    filters: "modelAnnotationLevelFilters",
    chips: "modelAnnotationActiveChips",
    detail: "modelAnnotationDetailList",
    timeline: "modelAnnotationTimeline",
    channels: "modelAnnotationChannelSummary",
  });
}

function renderModelAnnotationOverlay() {
  const overlay = $("modelAnnotationOverlay");
  if (!overlay) return;
  const annotations = filteredAnnotations();
  if (!annotations.length) {
    overlay.innerHTML = "";
    overlay.dataset.signature = "";
    overlay.style.display = "none";
    return;
  }
  const duration = playbackDuration();
  const active = currentActiveAnnotations();
  const visible = active.filter((annotation) => !["metadata", "dataset", "source"].includes(annotation.bodypart)).slice(0, 10);
  overlay.style.display = "";
  const signature = `${annotations.map((annotation) => annotation.id).join("|")}:${visible.map((annotation) => annotation.id).join("|")}:${duration}`;
  if (overlay.dataset.signature !== signature) {
    overlay.dataset.signature = signature;
    overlay.innerHTML = `
      <div class="model-annotation-overlay-head">
        <strong>${escapeHtml(sequenceText(annotations) || sampleText(state.selected) || "Current motion")}</strong>
        <span>${annotations.length} labels</span>
      </div>
      <div class="model-annotation-overlay-chips">
        ${
          visible.length
            ? visible
                .map(
                  (annotation) => `
                    <span class="annotation-chip" style="--part-color:${annotation.color}" title="${annotationTooltip(annotation)}">
                      <span>${escapeHtml(annotation.label)}</span>${provenanceBadgeHtml(annotation)}${escapeHtml(clipText(annotation.text, 38))}
                    </span>
                  `,
                )
                .join("")
            : '<span class="annotation-empty">No semantic label active at this frame</span>'
        }
      </div>
      ${timelineHtml(annotations, 0, duration)}
    `;
  }
  const cursor = overlay.querySelector(".annotation-mini-cursor");
  if (cursor) cursor.style.left = `${Math.min(100, Math.max(0, currentTimeSec() / Math.max(duration, 1e-9) * 100))}%`;
}

function hasFingerName(name) {
  return isHandJointName(name) || FINGER_PATTERNS.some((pattern) => String(name || "").toLowerCase().includes(pattern));
}

function rootIndex(payload) {
  const names = payload?.skeleton?.joint_names || [];
  for (const name of ROOT_NAMES) {
    const index = names.findIndex((item) => String(item).toLowerCase() === name);
    if (index >= 0) return index;
  }
  return 0;
}

function visibleJointIndices(payload, showHands) {
  const names = payload?.skeleton?.joint_names || [];
  return names
    .map((name, index) => ({ name, index }))
    .filter(({ name, index }) => index >= 0 && (showHands || !hasFingerName(name)))
    .map(({ index }) => index);
}

function isFinitePoint(point) {
  return (
    Array.isArray(point) &&
    point.length >= 3 &&
    Number.isFinite(point[0]) &&
    Number.isFinite(point[1]) &&
    Number.isFinite(point[2])
  );
}

function normalizeFrames(payload, anchorFrameIndex = null) {
  const frames = payload?.frames?.positions || [];
  if (!frames.length) return [];
  const anchorIndex = rootIndex(payload);
  const frameIndex = Math.min(
    Math.max(anchorFrameIndex ?? state.frame, 0),
    Math.max(frames.length - 1, 0),
  );
  const anchorFrame = interpolatePositionFrame(frames, frameIndex);
  const anchor = anchorFrame?.[anchorIndex] || frames[0]?.[anchorIndex] || [0, 0, 0];
  let cache = normalizedFramesCache.get(payload);
  if (!cache || cache.source !== frames) {
    cache = {
      source: frames,
      anchor: [Number.NaN, Number.NaN, Number.NaN],
      frames: frames.map((frame) => frame.map(() => [0, 0, 0])),
    };
    normalizedFramesCache.set(payload, cache);
  }
  if (cache.anchor[0] === anchor[0] && cache.anchor[1] === anchor[1] && cache.anchor[2] === anchor[2]) {
    return cache.frames;
  }
  cache.anchor[0] = anchor[0];
  cache.anchor[1] = anchor[1];
  cache.anchor[2] = anchor[2];
  for (let frameIndexValue = 0; frameIndexValue < frames.length; frameIndexValue += 1) {
    const sourceFrame = frames[frameIndexValue];
    const targetFrame = cache.frames[frameIndexValue];
    for (let pointIndex = 0; pointIndex < sourceFrame.length; pointIndex += 1) {
      const point = sourceFrame[pointIndex];
      const target = targetFrame[pointIndex];
      target[0] = point[0] - anchor[0];
      target[1] = point[1] - anchor[1];
      target[2] = point[2] - anchor[2];
    }
  }
  return cache.frames;
}

function rotatePoint(point) {
  const yaw = state.viewYaw;
  const pitch = state.viewPitch;
  if (projectionTrigCache.yaw !== yaw || projectionTrigCache.pitch !== pitch) {
    projectionTrigCache = {
      yaw,
      pitch,
      cy: Math.cos(yaw),
      sy: Math.sin(yaw),
      cp: Math.cos(pitch),
      sp: Math.sin(pitch),
    };
  }
  const { cy, sy, cp, sp } = projectionTrigCache;
  const x = point[0] * cy - point[2] * sy;
  const z = point[0] * sy + point[2] * cy;
  const y = point[1] * cp - z * sp;
  const rz = point[1] * sp + z * cp;
  return [x, y, rz];
}

function boundsFor(payloads, canvas) {
  const cacheKey = {
    first: payloads[0] || null,
    second: payloads[1] || null,
    width: canvas.width,
    height: canvas.height,
    showHands: state.showHands,
    yaw: state.viewYaw,
    pitch: state.viewPitch,
    zoom: state.viewZoom,
  };
  if (
    sharedBoundsCache &&
    sharedBoundsCache.first === cacheKey.first &&
    sharedBoundsCache.second === cacheKey.second &&
    sharedBoundsCache.width === cacheKey.width &&
    sharedBoundsCache.height === cacheKey.height &&
    sharedBoundsCache.showHands === cacheKey.showHands &&
    sharedBoundsCache.yaw === cacheKey.yaw &&
    sharedBoundsCache.pitch === cacheKey.pitch &&
    sharedBoundsCache.zoom === cacheKey.zoom
  ) return sharedBoundsCache.value;
  const points = [];
  for (const payload of payloads) {
    const frames = payload?.frames?.positions || [];
    if (!frames.length) continue;
    const visible = new Set(visibleJointIndices(payload, state.showHands));
    const root = rootIndex(payload);
    const stride = Math.max(1, Math.floor(frames.length / 96));
    for (let frameIndex = 0; frameIndex < frames.length; frameIndex += stride) {
      const frame = frames[frameIndex];
      const anchor = frame?.[root] || [0, 0, 0];
      for (const index of visible) {
        if (!isFinitePoint(frame?.[index])) continue;
        const point = frame[index];
        points.push(rotatePoint([point[0] - anchor[0], point[1] - anchor[1], point[2] - anchor[2]]));
      }
    }
  }
  if (!points.length) {
    const value = { cx: 0, cy: 0.8, scale: 180, zoom: state.viewZoom };
    sharedBoundsCache = { ...cacheKey, value };
    return value;
  }
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const width = Math.max(maxX - minX, 0.6);
  const height = Math.max(maxY - minY, 1.2);
  const usableWidth = Math.max(canvas.width * 0.70, 1);
  const usableHeight = Math.max(canvas.height * 0.76, 1);
  const value = {
    cx: (minX + maxX) / 2,
    cy: (minY + maxY) / 2,
    scale: Math.min(usableWidth / width, usableHeight / height) * state.viewZoom,
  };
  sharedBoundsCache = { ...cacheKey, value };
  return value;
}

function projectPoint(point, bounds, canvas) {
  const rotated = rotatePoint(point);
  const x = canvas.width / 2 + (rotated[0] - bounds.cx) * bounds.scale;
  const y = canvas.height * 0.56 - (rotated[1] - bounds.cy) * bounds.scale;
  return [x, y, rotated[2] || 0];
}

function drawBackground(ctx, width, height) {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = cssVar("--canvas", "#fff8ec");
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = cssVar("--grid", "rgba(20, 59, 76, 0.12)");
  ctx.lineWidth = 1;
  for (let x = 0; x < width; x += 32) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = 0; y < height; y += 32) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
}

function drawSkeletonFrame(ctx, canvas, payload, frames, frame, bounds, alpha = 1, showHands = false) {
  const jointNames = payload?.skeleton?.joint_names || [];
  const visible = new Set(visibleJointIndices(payload, showHands));
  const edges = (payload?.skeleton?.edges || []).filter(([a, b]) => visible.has(a) && visible.has(b));
  const skeletonRgb = isDarkTheme() ? "190, 218, 220" : "20, 59, 76";
  const rootRgb = isDarkTheme() ? "226, 118, 66" : "200, 95, 47";
  const payloadRoot = rootIndex(payload);

  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (const [a, b] of edges) {
    if (!isFinitePoint(frame[a]) || !isFinitePoint(frame[b])) continue;
    const pa = projectPoint(frame[a], bounds, canvas);
    const pb = projectPoint(frame[b], bounds, canvas);
    const depth = Math.max(-1, Math.min(1, (pa[2] + pb[2]) / 2));
    ctx.strokeStyle = `rgba(${skeletonRgb}, ${Math.max(0.03, Math.min(0.9, alpha * (0.38 + depth * 0.10)))})`;
    ctx.lineWidth = alpha < 1 ? 2.4 : 4;
    ctx.beginPath();
    ctx.moveTo(pa[0], pa[1]);
    ctx.lineTo(pb[0], pb[1]);
    ctx.stroke();
  }

  frame.forEach((point, index) => {
    if (!visible.has(index)) return;
    if (!isFinitePoint(point)) return;
    const [x, y] = projectPoint(point, bounds, canvas);
    const isRoot = index === payloadRoot;
    ctx.fillStyle = isRoot ? `rgba(${rootRgb}, ${alpha})` : `rgba(${skeletonRgb}, ${alpha})`;
    ctx.beginPath();
    ctx.arc(x, y, isRoot ? 5.5 : 3.0, 0, Math.PI * 2);
    ctx.fill();
  });

  if (jointNames.length && state.showTrails) {
    const root = payloadRoot;
    const trail = [];
    const trailEnd = Math.min(Math.floor(frameForPayload(payload)), frames.length - 1);
    for (let i = Math.max(0, trailEnd - CURRENT_TRAIL); i <= trailEnd; i += 1) {
      if (isFinitePoint(frames[i]?.[root])) trail.push(projectPoint(frames[i][root], bounds, canvas));
    }
    if (trail.length > 1) {
      ctx.save();
      ctx.setLineDash([8, 8]);
      ctx.strokeStyle = isDarkTheme() ? "rgba(226, 118, 66, 0.48)" : "rgba(200, 95, 47, 0.35)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(trail[0][0], trail[0][1]);
      for (const point of trail.slice(1)) {
        ctx.lineTo(point[0], point[1]);
      }
      ctx.stroke();
      ctx.restore();
    }
  }
}

function averageProjectedPoint(indices, frame, bounds, canvas) {
  const points = indices.filter((index) => isFinitePoint(frame?.[index])).map((index) => projectPoint(frame[index], bounds, canvas));
  if (!points.length) return null;
  return points.reduce((acc, point) => [acc[0] + point[0] / points.length, acc[1] + point[1] / points.length, acc[2] + point[2] / points.length], [0, 0, 0]);
}

function wrapCanvasText(ctx, text, maxWidth, maxLines = 3) {
  const words = String(text || "").split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width <= maxWidth || !line) {
      line = next;
      continue;
    }
    lines.push(line);
    line = word;
    if (lines.length >= maxLines - 1) break;
  }
  if (line && lines.length < maxLines) lines.push(line);
  if (words.join(" ").length > lines.join(" ").length && lines.length) {
    lines[lines.length - 1] = clipText(lines[lines.length - 1], Math.max(12, lines[lines.length - 1].length - 2));
  }
  return lines;
}

function drawLabel(ctx, canvas, anchor, annotation, offsetIndex) {
  const side = anchor[0] > canvas.width * 0.52 ? -1 : 1;
  const x = Math.max(12, Math.min(canvas.width - 210, anchor[0] + side * 22));
  const y = Math.max(46, Math.min(canvas.height - 118, anchor[1] - 34 + offsetIndex * 24));
  const width = 190;
  ctx.save();
  ctx.font = "700 12px Aptos, Segoe UI, sans-serif";
  const lines = wrapCanvasText(ctx, annotation.text, width - 18, 3);
  const height = Math.max(42, 24 + lines.length * 15);
  ctx.strokeStyle = annotation.color;
  ctx.fillStyle = isDarkTheme() ? "rgba(17, 24, 32, 0.88)" : "rgba(255, 252, 244, 0.92)";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(anchor[0], anchor[1]);
  ctx.lineTo(side > 0 ? x : x + width, y + 16);
  ctx.stroke();
  ctx.beginPath();
  ctx.roundRect(x, y, width, height, 8);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = annotation.color;
  ctx.fillText(annotation.label, x + 10, y + 15);
  ctx.font = "600 12px Aptos, Segoe UI, sans-serif";
  ctx.fillStyle = cssVar("--ink", "#182026");
  lines.forEach((line, index) => ctx.fillText(line, x + 10, y + 32 + index * 15));
  ctx.restore();
}

function drawAnnotationHighlights(ctx, canvas, payload, frames, frame, bounds, payloadFrame) {
  const active = currentActiveAnnotations()
    .filter((annotation) => state.showHands || !annotation.requiresHands);
  const groups = groupedPartAnnotations(active);
  const visible = new Set(visibleJointIndices(payload, state.showHands));
  let labelIndex = 0;
  for (const [bodypart, annotations] of [...groups.entries()].slice(0, 5)) {
    const color = annotations[0]?.anchorColor || PART_META[bodypart]?.color || annotations[0]?.color || "#2f80ed";
    const indices = new Set(partJointIndices(payload, bodypart, { includeHands: state.showHands }).filter((index) => visible.has(index)));
    if (!indices.size) continue;
    if (bodypart === "trajectory") {
      const root = rootIndex(payload);
      const start = Math.max(0, Math.floor(payloadFrame) - CURRENT_TRAIL * 2);
      const end = Math.min(Math.floor(payloadFrame), frames.length - 1);
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 4;
      ctx.globalAlpha = 0.78;
      ctx.beginPath();
      for (let i = start; i <= end; i += 1) {
        if (!isFinitePoint(frames[i]?.[root])) continue;
        const point = projectPoint(frames[i][root], bounds, canvas);
        if (i === start) ctx.moveTo(point[0], point[1]);
        else ctx.lineTo(point[0], point[1]);
      }
      ctx.stroke();
      ctx.restore();
    } else {
      ctx.save();
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.globalAlpha = 0.88;
      for (const [a, b] of payload?.skeleton?.edges || []) {
        if (!indices.has(a) && !indices.has(b)) continue;
        if (!visible.has(a) || !visible.has(b)) continue;
        if (!isFinitePoint(frame[a]) || !isFinitePoint(frame[b])) continue;
        const pa = projectPoint(frame[a], bounds, canvas);
        const pb = projectPoint(frame[b], bounds, canvas);
        ctx.lineWidth = 7;
        ctx.beginPath();
        ctx.moveTo(pa[0], pa[1]);
        ctx.lineTo(pb[0], pb[1]);
        ctx.stroke();
      }
      for (const index of indices) {
        if (!isFinitePoint(frame[index])) continue;
        const [x, y] = projectPoint(frame[index], bounds, canvas);
        ctx.beginPath();
        ctx.arc(x, y, 5.2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }
    const anchor = averageProjectedPoint([...indices], frame, bounds, canvas);
    if (anchor) {
      drawLabel(ctx, canvas, anchor, { ...annotations[0], color, text: annotationGroupText(annotations) }, labelIndex);
      labelIndex += 1;
    }
  }
  const contextGroups = new Map();
  for (const annotation of active) {
    if (PART_ORDER.includes(annotation.bodypart)) continue;
    if (["sequence_caption", "dataset", "source", "metadata"].includes(annotation.bodypart)) continue;
    if (!contextGroups.has(annotation.bodypart)) contextGroups.set(annotation.bodypart, []);
    contextGroups.get(annotation.bodypart).push(annotation);
  }
  for (const [bodypart, annotations] of [...contextGroups.entries()].slice(0, Math.max(0, 6 - labelIndex))) {
    const color = annotations[0]?.anchorColor || PART_META[bodypart]?.color || annotations[0]?.color || "#2f80ed";
    const indices = annotationAnchorIndices(payload, bodypart);
    const anchor = averageProjectedPoint(indices, frame, bounds, canvas);
    if (!anchor) continue;
    if (bodypart === "object" || bodypart === "contact" || bodypart === "interaction") {
      ctx.save();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.9;
      for (const index of indices) {
        if (!isFinitePoint(frame[index])) continue;
        const [x, y] = projectPoint(frame[index], bounds, canvas);
        ctx.beginPath();
        ctx.arc(x, y, 6.2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }
    drawLabel(ctx, canvas, anchor, { ...annotations[0], color, text: annotationGroupText(annotations) }, labelIndex);
    labelIndex += 1;
  }
}

function drawCanvasTimeline(ctx, canvas, annotations, fps) {
  const timed = annotations.filter((annotation) => annotation.startSec !== null || annotation.endSec !== null);
  if (!timed.length || !fps) return;
  const duration = Math.max(state.raw?.duration_sec || 0, state.processed?.duration_sec || 0, state.selected?.duration_sec || 0, 0.001);
  let rows = ["sequence_caption", "action", ...PART_ORDER, "object", "dialogue", "contact", "face", "audio"].filter((part) => timed.some((annotation) => annotation.bodypart === part || (part === "action" && annotation.level === "action")));
  if (!rows.length) return;
  const width = Math.min(canvas.width - 32, 620);
  const x = 16;
  const rowHeight = 14;
  const maxRows = Math.max(3, Math.floor((canvas.height * 0.42 - 24) / rowHeight));
  rows = rows.slice(0, maxRows);
  const panelHeight = 24 + rows.length * rowHeight;
  const y = canvas.height - panelHeight;
  ctx.save();
  ctx.fillStyle = isDarkTheme() ? "rgba(12, 17, 23, 0.76)" : "rgba(255, 252, 244, 0.84)";
  ctx.strokeStyle = cssVar("--line", "rgba(35, 51, 61, 0.16)");
  ctx.beginPath();
  ctx.roundRect(x - 6, y - 18, width + 12, rows.length * rowHeight + 28, 8);
  ctx.fill();
  ctx.stroke();
  ctx.font = "700 10px Aptos, Segoe UI, sans-serif";
  ctx.fillStyle = cssVar("--muted", "#62707a");
  ctx.fillText("Annotations", x, y - 6);
  rows.forEach((row, rowIndex) => {
    const rowY = y + rowIndex * rowHeight;
    ctx.fillStyle = cssVar("--muted", "#62707a");
    ctx.fillText(PART_META[row]?.label || row, x, rowY + 9);
    ctx.fillStyle = isDarkTheme() ? "rgba(255,255,255,0.12)" : "rgba(24,32,38,0.10)";
    ctx.fillRect(x + 84, rowY + 2, width - 94, 8);
    for (const annotation of timed) {
      if (!(annotation.bodypart === row || (row === "action" && annotation.level === "action"))) continue;
      const start = Math.max(0, annotation.startSec ?? 0);
      const end = Math.min(duration, annotation.endSec ?? duration);
      const sx = x + 84 + (start / duration) * (width - 94);
      const ex = x + 84 + (end / duration) * (width - 94);
      ctx.fillStyle = annotation.color;
      ctx.fillRect(sx, rowY + 2, Math.max(3, ex - sx), 8);
    }
  });
  const currentX = x + 84 + Math.min(1, Math.max(0, state.frame / Math.max(1, duration * fps))) * (width - 94);
  ctx.strokeStyle = cssVar("--accent-dark", "#8c3b21");
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(currentX, y - 14);
  ctx.lineTo(currentX, y + rows.length * rowHeight);
  ctx.stroke();
  ctx.restore();
}

function drawSkeleton(canvas, payload, sharedBounds) {
  if (skeletonCanvasVisibility.get(canvas) === false) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  drawBackground(ctx, width, height);

  if (!payload?.frames?.positions?.length) return;
  const payloadFrame = frameForPayload(payload);
  const frames = normalizeFrames(payload, payloadFrame);
  const frame = interpolatePositionFrame(frames, payloadFrame);
  drawSkeletonFrame(ctx, canvas, payload, frames, frame, sharedBounds, 1, state.showHands);
  drawAnnotationHighlights(ctx, canvas, payload, frames, frame, sharedBounds, payloadFrame);
}

function renderPreview() {
  const maxFrames = playbackFrameCount();
  const maxFrame = Math.max(maxFrames - 1, 0);
  const frameValue = Math.min(Math.floor(state.frame), maxFrame);
  $("frameSlider").max = maxFrame;
  $("frameSlider").value = frameValue;
  $("frameLabel").textContent = `${frameValue}/${maxFrame}`;
  $("modelFrameSlider").max = maxFrame;
  $("modelFrameSlider").value = frameValue;
  $("modelFrameLabel").textContent = `${frameValue}/${maxFrame}`;
  const rawMeta = metaSummary(state.raw);
  const processedMeta = metaSummary(state.processed);
  if ($("rawMeta").textContent !== rawMeta) $("rawMeta").textContent = rawMeta;
  if ($("processedMeta").textContent !== processedMeta) $("processedMeta").textContent = processedMeta;
  const rawCanvas = $("rawCanvas");
  const processedCanvas = $("processedCanvas");
  const skeletonVisible = skeletonCanvasVisibility.get(rawCanvas) !== false || skeletonCanvasVisibility.get(processedCanvas) !== false;
  const shared = skeletonVisible ? boundsFor([state.raw, state.processed], rawCanvas) : null;
  if (shared) {
    drawSkeleton(rawCanvas, state.raw, shared);
    drawSkeleton(processedCanvas, state.processed, shared);
  }
  vrmViewer?.setFrame?.(state.frame);
  renderQualityPanel(state.processed?.quality);
  renderAnnotationPanels();
  renderModelAnnotationOverlay();
}

function previewParams(sample, fromArtifacts = true) {
  const params = new URLSearchParams({
    data_source: $("dataSourceSelect").value,
    dataset: $("datasetSelect").value,
    sample_id: sample.sample_id,
    from_artifacts: fromArtifacts ? "true" : "false",
  });
  const maxFrames = $("maxFramesInput").value.trim();
  if (maxFrames) params.set("max_frames", maxFrames);
  return params;
}

async function loadPreview(sample, persist = false, requestId = ++state.previewRequest) {
  const sampleId = sample.sample_id;
  if (persist) {
    const maxFrames = $("maxFramesInput").value.trim();
    await api("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        data_source: $("dataSourceSelect").value,
        dataset: $("datasetSelect").value,
        sample_id: sample.sample_id,
        max_frames: maxFrames ? Number(maxFrames) : null,
        persist: true,
        skip_existing: false,
      }),
    });
  }

  const params = previewParams(sample, true);
  const [raw, processed] = await Promise.all([
    api(`/api/preview/source?${params.toString()}`),
    api(`/api/preview/processed?${params.toString()}`),
  ]);
  let motionPayload = processed;
  if (!processed?.motion) {
    try {
      const motion = await api(`/api/preview/motion?${params.toString()}`);
      motionPayload = { ...processed, motion };
    } catch {
      motionPayload = processed;
    }
  }
  if (requestId !== state.previewRequest || state.selected?.sample_id !== sampleId) return false;

  state.raw = raw;
  state.processed = processed;
  const rawAnnotations = normalizeAnnotations(raw || {}, sample);
  const processedAnnotations = normalizeAnnotations(processed || {}, sample);
  state.annotations = mergeAnnotations(processedAnnotations, rawAnnotations);
  state.channels = mergeChannels(normalizeChannels(processed || {}), normalizeChannels(raw || {}));
  state.annotationRevision += 1;
  state.frame = 0;
  if (motionPayload?.motion) {
    vrmViewer?.setMotionPayload?.(motionPayload);
  } else {
    vrmViewer?.setMotionPayload?.(processed);
  }
  vrmViewer?.setAnnotations?.(filteredAnnotations());
  vrmViewer?.setChannels?.(state.channels);
  renderPreview();
  return true;
}

async function selectSample(sample, persist) {
  const requestId = ++state.previewRequest;
  stopPlayback();
  state.selected = sample;
  state.annotations = normalizeAnnotations({ annotations: sample?.annotations || [], sample }, sample);
  state.channels = [];
  state.annotationRevision += 1;
  vrmViewer?.setAnnotations?.([]);
  vrmViewer?.setChannels?.([]);
  $("sampleTitle").textContent = sample.sample_id;
  $("sampleText").textContent = sampleText(sample);
  renderSamples();
  $("rawMeta").textContent = "Loading raw preview...";
  $("processedMeta").textContent = "Loading processed preview...";
  try {
    await loadPreview(sample, persist, requestId);
  } catch (error) {
    if (requestId === state.previewRequest && state.selected?.sample_id === sample.sample_id) {
      $("processedMeta").textContent = String(error);
    }
  }
}

async function loadSamples() {
  const requestId = ++state.sampleListRequest;
  ++state.previewRequest;
  stopPlayback();
  const dataset = $("datasetSelect").value;
  const params = new URLSearchParams({
    data_source: $("dataSourceSelect").value,
    dataset,
    q: $("queryInput").value || "",
    limit: "80",
  });
  const payload = await api(`/api/samples?${params.toString()}`);
  if (requestId !== state.sampleListRequest) return;
  state.samples = payload.items || [];
  state.selected = null;
  state.raw = null;
  state.processed = null;
  state.annotations = [];
  state.channels = [];
  state.annotationRevision += 1;
  vrmViewer?.setAnnotations?.([]);
  vrmViewer?.setChannels?.([]);
  renderSamples();
  renderPreview();
  if (state.samples.length) {
    await selectSample(state.samples[0], false);
  }
}

function stopPlayback() {
  if (state.playbackTimer) {
    cancelAnimationFrame(state.playbackTimer);
    state.playbackTimer = null;
  }
  state.playing = false;
  $("playButton").textContent = "Play";
  $("modelPlayButton").textContent = "Play";
}

function playbackFps() {
  const candidates = [state.processed?.fps, state.raw?.fps]
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value > 0);
  return candidates[0] || 30;
}

function startPlayback() {
  if (state.playbackTimer) return;
  state.playing = true;
  $("playButton").textContent = "Pause";
  $("modelPlayButton").textContent = "Pause";
  state.playbackStartMs = performance.now();
  state.playbackStartTimeSec = currentTimeSec();
  state.playbackNextRenderMs = Number.NEGATIVE_INFINITY;
  const tick = (now) => {
    const duration = playbackDuration();
    const renderIntervalMs = 1000 / MAX_PLAYBACK_RENDER_HZ;
    if (duration > 0 && now >= state.playbackNextRenderMs - 1) {
      const elapsedSec = Math.max(0, (now - state.playbackStartMs) / 1000);
      const timeSec = (state.playbackStartTimeSec + elapsedSec) % duration;
      state.frame = timeSec * playbackFps();
      const scheduledNext = Number.isFinite(state.playbackNextRenderMs)
        ? state.playbackNextRenderMs + renderIntervalMs
        : now + renderIntervalMs;
      state.playbackNextRenderMs = scheduledNext <= now
        ? now + renderIntervalMs
        : scheduledNext;
      renderPreview();
    }
    state.playbackTimer = requestAnimationFrame(tick);
  };
  state.playbackTimer = requestAnimationFrame(tick);
}

function togglePlayback() {
  if (state.playing) {
    stopPlayback();
    return;
  }
  startPlayback();
}

function renderSamples() {
  const list = $("sampleList");
  list.replaceChildren();
  for (const sample of state.samples) {
    const item = document.createElement("button");
    item.className = `sample-item ${state.selected?.sample_id === sample.sample_id ? "active" : ""}`;
    const id = document.createElement("strong");
    id.textContent = String(sample.sample_id || "");
    const format = document.createElement("small");
    format.textContent = `${sample.source_format || ""}${sample.frame_count ? ` | ${sample.frame_count} frames` : ""}`;
    const description = document.createElement("small");
    description.textContent = String(sampleText(sample)).slice(0, 140);
    item.append(id, format, description);
    item.addEventListener("click", () => selectSample(sample, false));
    list.appendChild(item);
  }
}

function resetPreviewView() {
  state.viewYaw = 0;
  state.viewPitch = 0.08;
  state.viewZoom = 1;
  renderPreview();
}

function attachPreviewViewControls(canvas) {
  canvas.addEventListener("pointerdown", (event) => {
    state.viewDragging = true;
    state.viewPointer = [event.clientX, event.clientY];
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!state.viewDragging) return;
    const dx = event.clientX - state.viewPointer[0];
    const dy = event.clientY - state.viewPointer[1];
    state.viewPointer = [event.clientX, event.clientY];
    state.viewYaw += dx * 0.01;
    state.viewPitch = Math.max(-1.35, Math.min(1.35, state.viewPitch + dy * 0.01));
    renderPreview();
  });
  canvas.addEventListener("pointerup", (event) => {
    state.viewDragging = false;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointercancel", () => {
    state.viewDragging = false;
  });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    state.viewZoom = Math.max(0.45, Math.min(3.0, state.viewZoom * Math.exp(-event.deltaY * 0.001)));
    renderPreview();
  }, { passive: false });
  canvas.addEventListener("dblclick", resetPreviewView);
}

async function init() {
  const health = await api("/api/health");
  $("persistButton").disabled = !health.write_api_enabled;
  if (!health.write_api_enabled) {
    $("persistButton").title = "Write API is disabled for this viewer session. Set VIREA_ENABLE_WRITE_API=1 only in a trusted local session.";
  }
  state.dataSources = health.available_data_sources || {};
  replaceOptions($("dataSourceSelect"), Object.entries(state.dataSources).map(([key, value]) => {
    const mark = value.exists ? "available" : "missing";
    const location = value.location || (value.exists ? "configured" : "missing");
    return { value: key, label: `${mark} | ${key} | ${value.label || key} [${location}]` };
  }));
  const defaultSource = health.default_data_source;
  const firstExistingSource = Object.keys(state.dataSources).find((key) => state.dataSources[key].exists);
  $("dataSourceSelect").value =
    (defaultSource && state.dataSources[defaultSource]?.exists && defaultSource) || firstExistingSource || "full";
  const activeSource = state.dataSources[$("dataSourceSelect").value];
  $("health").textContent = `${$("dataSourceSelect").value}: ${activeSource?.location || "unknown"}`;
  const datasets = await api(`/api/datasets?data_source=${encodeURIComponent($("dataSourceSelect").value)}`);
  state.datasets = datasets.datasets || [];
  replaceOptions($("datasetSelect"), state.datasets.map((dataset) => ({ value: dataset.key, label: dataset.name })));
  $("datasetSelect").value = state.datasets.find((d) => d.key === "susuinteracts")?.key || state.datasets[0]?.key;
  try {
    const { createVrmViewer } = await import("./vrm-viewer.js");
    vrmViewer = createVrmViewer({
      canvas: $("modelCanvas"),
      statusEl: $("modelStatus"),
      fileInput: $("modelFileInput"),
      resetButton: $("resetModelButton"),
    });
  } catch (error) {
    const message = `Avatar viewer unavailable: Three.js / three-vrm modules could not be loaded. Install the Node dependencies and restart the service. (${error?.message || error})`;
    $("modelStatus").textContent = message;
    $("modelFileInput").disabled = true;
    $("resetModelButton").disabled = true;
    $("modelCanvas").setAttribute("aria-label", message);
    document.body.dataset.vrmUnavailable = "true";
  }
  applyTheme(localStorage.getItem(THEME_KEY) || "light");
  attachPreviewViewControls($("rawCanvas"));
  attachPreviewViewControls($("processedCanvas"));
  if (typeof IntersectionObserver === "function") {
    const skeletonObserver = new IntersectionObserver((entries) => {
      let redraw = false;
      for (const entry of entries) {
        const wasVisible = skeletonCanvasVisibility.get(entry.target) !== false;
        const isVisible = entry.isIntersecting && entry.intersectionRatio > 0;
        skeletonCanvasVisibility.set(entry.target, isVisible);
        if (isVisible && !wasVisible) redraw = true;
      }
      if (redraw && !state.playing) requestAnimationFrame(renderPreview);
    });
    skeletonObserver.observe($("rawCanvas"));
    skeletonObserver.observe($("processedCanvas"));
  }
  window.__vireaShowcase = {
    async loadSample({ dataSource = "demo", dataset, sampleId, maxFrames = "" }) {
      ++state.sampleListRequest;
      const requestId = ++state.previewRequest;
      stopPlayback();
      if (dataSource && $("dataSourceSelect").value !== dataSource) {
        $("dataSourceSelect").value = dataSource;
        const info = state.dataSources[dataSource];
        $("health").textContent = `${dataSource}: ${info?.location || "unknown"}`;
        const datasets = await api(`/api/datasets?data_source=${encodeURIComponent(dataSource)}`);
        state.datasets = datasets.datasets || [];
        replaceOptions($("datasetSelect"), state.datasets.map((item) => ({ value: item.key, label: item.name })));
      }
      if (dataset) $("datasetSelect").value = dataset;
      $("maxFramesInput").value = maxFrames ? String(maxFrames) : "";
      state.selected = { sample_id: sampleId };
      state.samples = [state.selected];
      $("sampleTitle").textContent = sampleId;
      $("sampleText").textContent = "";
      renderSamples();
      await loadPreview(state.selected, false, requestId);
      return {
        dataset: $("datasetSelect").value,
        sampleId,
        frames: Math.max(state.raw?.frame_count || 0, state.processed?.frame_count || 0),
      };
    },
    setFrame(frame) {
      stopPlayback();
      state.frame = Math.max(0, Number(frame) || 0);
      renderPreview();
    },
    vrmDiagnostics() {
      return vrmViewer?.getDiagnostics?.() || { unavailable: true };
    },
    setAnnotationFixture(annotations) {
      state.annotations = normalizeAnnotations(
        {
          fps: playbackFps(),
          frame_count: playbackFrameCount(),
          annotations: Array.isArray(annotations) ? annotations : [],
        },
        state.selected,
      );
      state.annotationRevision += 1;
      vrmViewer?.setAnnotations?.(filteredAnnotations());
      renderPreview();
      return {
        annotationCount: state.annotations.length,
        activeCount: currentActiveAnnotations().length,
        diagnostics: vrmViewer?.getDiagnostics?.() || {},
      };
    },
  };
  await loadSamples();
}

$("searchButton").addEventListener("click", loadSamples);
$("datasetSelect").addEventListener("change", loadSamples);
$("dataSourceSelect").addEventListener("change", async () => {
  const src = $("dataSourceSelect").value;
  const info = state.dataSources[src];
  $("health").textContent = `${src}: ${info?.location || "unknown"}`;
  stopPlayback();
  await loadSamples();
});
$("queryInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadSamples();
});
$("frameSlider").addEventListener("input", (event) => {
  stopPlayback();
  state.frame = Number(event.target.value);
  renderPreview();
});
$("playButton").addEventListener("click", togglePlayback);
$("modelPlayButton").addEventListener("click", togglePlayback);
$("modelFrameSlider").addEventListener("input", (event) => {
  stopPlayback();
  state.frame = Number(event.target.value);
  renderPreview();
});
$("themeToggle").addEventListener("click", () => {
  const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  applyTheme(current === "dark" ? "light" : "dark");
  renderPreview();
});
$("persistButton").addEventListener("click", () => {
  if (state.selected) selectSample(state.selected, true);
});
$("showTrailsToggle").addEventListener("change", (event) => {
  state.showTrails = event.target.checked;
  renderPreview();
});
$("showHandsToggle").addEventListener("change", (event) => {
  state.showHands = event.target.checked;
  vrmViewer?.setShowHands?.(state.showHands);
  renderPreview();
});

init().catch((error) => {
  $("health").textContent = String(error);
});
