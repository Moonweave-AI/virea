import {getLanguage, subscribe} from "./preferences";
import {english} from "./translations";
import {studioEnglish} from "./translations-studios";
import {runtimeEnglish} from "./translations-runtime";

// UI-only translation: authored labels are translated; conversation content,
// prompts, filenames, model output and diagnostic payloads retain their source.
const excluded = 'script,style,code:not([data-ui-copy]),pre,textarea,option[data-user],.message-content,#conversation p,.session-item,#conversations button:not([data-ui-copy]),#response-text:not([data-ui-copy]),#subtitle,#motion-plan,#workspace-title:not([data-ui-copy]),#reply-owner,[data-ui-owned]';
const copy = {...english, ...studioEnglish, ...runtimeEnglish};
const chineseCopy: Record<string,string> = {
  "VIREA / setup": "VIREA / 部署",
  "API Key": "API 密钥",
  "YOUR OWN AI WORKSPACE": "你的 AI 工作台",
  "打开 Motion Lab ↗": "打开动作实验室 ↗",
  "进入 Character Studio ↗": "打开角色工作室 ↗",
  "打开 VRChat ↗": "打开 VRChat 工作室 ↗",
  "在 Set Up 部署": "在部署页接入",
  "载入 Avatar": "载入角色",
  "载入 Avatar 后即可预览生成动作": "载入角色后即可预览生成动作",
  "CLI、安装验收和 Web 任务共用同一状态": "命令行与工作室共用同一任务状态",
  "没有可播放的源骨架": "原始动作将在这里呈现",
  "完成一次真实模型生成后，这里才会开始播放；空状态不会创建虚拟动画。": "生成动作后，可在这里查看模型输出的原始骨架。",
  "左侧只做坐标归一化用于显示，不进入 VRM 骨骼重定向；右侧是同一结果的最终 VRMA。拖动旋转、右键平移、滚轮或双指缩放；生成期间 Viewer 自动暂停绘制以降低前端 GPU 开销，完成后原位恢复。": "左侧展示原始骨架，右侧展示重定向后的 VRM。拖动旋转、右键平移、滚轮缩放。生成期间预览会暂停绘制，以节省显存。",
};
for (const [original, localized] of Object.entries(chineseCopy)) copy[localized] = copy[original] || original;
const chinese = Object.fromEntries(Object.entries(copy).map(([zh,en])=>[en,zh]));
export function translateLabel(source: string): string {
  const value = source.trim();
  if (value.includes("\n")) return source.replace(value, value.split("\n").map(translateLabel).join("\n"));
  const providerError = value.match(/^(?:模型接口 HTTP (\d+)：|Model API HTTP (\d+): )(.+)$/);
  if (providerError) return source.replace(value, `${getLanguage() === "en" ? "Model API HTTP " : "模型接口 HTTP "}${providerError[1] || providerError[2]}${getLanguage() === "en" ? ": " : "："}${translateLabel(providerError[3]!)}`);
  if (getLanguage() !== "en") {
    const known = chineseCopy[value] || chinese[value];
    if (known) return source.replace(value, known);
    const segments = value.split(/\s+·\s+/);
    if (segments.length > 1) return source.replace(value, segments.map(translateLabel).join(" · "));
    const constraint = value.match(/^(Min|Max|Step) ([\d.-]+)$/);
    if (constraint) return source.replace(value, `${({Min:"最小值",Max:"最大值",Step:"步长"} as Record<string,string>)[constraint[1]!]} ${constraint[2]}`);
    const bilingual = value.match(/^([^·]+[\u4e00-\u9fff].*?)\s*\/\s*[A-Za-z][^\u4e00-\u9fff]*$/);
    return source.replace(value, bilingual?.[1] || value);
  }
  const known = copy[value];
  if (known) return source.replace(value, known);
  const patterns: [RegExp,(...groups:string[])=>string][] = [
    [/^语言流水线 (.+?)s · TTS (.+?)s · 动作 (.+?)s$/, (llm,tts,motion)=>`Language pipeline ${llm}s · TTS ${tts}s · Motion ${motion}s`],
    [/^语音就绪 (.+?)s · 首包就绪 (.+?)s · (动作|生成) RTF (.+)$/, (audio,first,kind,rtf)=>`Speech ready ${audio}s · First chunk ${first}s · ${kind === "动作" ? "Motion" : "Generation"} RTF ${rtf}`],
    [/^我的字幕暂未送达：(.+)$/, detail=>`Your chatbox caption has not arrived: ${detail}`],
    [/^(.+) · 未就绪$/, name=>`${name} · not ready`],
    [/^语音单元 (.+)$/, range=>`Speech units ${range}`],
    [/^身体目标 (.+)$/, number=>`Body objective ${number}`],
    [/^伴随表达：(.+)$/, value=>`Accompanying expression: ${value}`],
    [/^完成条件：(.+)$/, value=>`Completion condition: ${value}`],
    [/^整项活动最后的恢复 · (.+)$/, executor=>`Final activity recovery · ${executor}`],
    [/^最小值 ([\d.-]+)$/, n=>`Min ${n}`],
    [/^最大值 ([\d.-]+)$/, n=>`Max ${n}`],
    [/^步长 ([\d.-]+)$/, n=>`Step ${n}`],
    [/^骨骼格式 (.+)$/, format=>`Representation ${format}`],
    [/^建议至少预留 (\d+) GiB 可用空间。.*$/, n=>`Keep at least ${n} GiB free. Loading and inference progress appear below.`],
    [/^已找到 (\d+) 个模型(?:、(\d+) 个声线)?，已自动选择；可直接启用。$/, (m,v)=>`${m} models${v ? ` and ${v} voices` : ""} found. A recommended option is selected and ready to test.`],
    [/^按设备内存自动选择 · (.+)（推荐）$/, m=>`Choose for this device · ${m} (recommended)`],
    [/^(.+) · 推荐\/当前选择$/, m=>`${m} · recommended / selected`],
    [/^设备检测完成 · (.+) · (\d+) 个本地服务$/, (os,n)=>`Discovery complete · ${os} · ${n} local services`],
    [/^删除连接 (.+)$/, n=>`Delete connection ${n}`],
    [/^当前步骤 (\d+)%$/, n=>`Current step ${n}%`],
    [/^([✓○●·]) (.+)$/, (prefix,label)=>`${prefix} ${translateLabel(label)}`],
    [/^(.+) · 未部署$/, model=>`${model} · not connected`],
    [/^(.+) · (?:本地已安装|已安装)$/, model=>`${model} · installed`],
    [/^创建 (\S+) 隔离环境 · (.+)$/, (model,device)=>`Creating ${model} environment · ${device}`],
    [/^真实动作推理：已生成 (\d+) 帧$/, frames=>`Generation verified · ${frames} motion frames`],
    [/^(.+) · 本地模型(.*)$/, (name,suffix)=>`${name} · local models${suffix}`],
    [/^计算设备：(.+) · 检测已有服务$/, device=>`Compute: ${device} · checking existing service`],
    [/^计算设备：(.+) · 准备本地运行环境$/, device=>`Compute: ${device} · preparing the local runtime`],
    [/^需要至少 ([\d.]+) GiB 总显存和 ([\d.]+) GiB 可用显存。$/, (total,free)=>`At least ${total} GiB total and ${free} GiB available GPU memory are required.`],
    [/^远端 (.+) 服务未就绪：(.+)。请检查该服务后重新连接。$/, (name,url)=>`Remote ${name} worker is not ready: ${url}. Check the worker and reconnect.`],
    [/^安装 (\S+) 与 (.+) 推理依赖$/, (model,device)=>`Installing ${model} and ${device} inference dependencies`],
    [/^最近一条输出在 (\d+) 秒前；后台进程仍在运行。$/, n=>`Last output ${n}s ago. The process is still running.`],
    [/^(.+)启动进度$/, role=>`${translateLabel(role)} launch progress`],
    [/^(.+) · ([\d.]+) 秒参考录音 · 从下一次回复生效$/, (name,seconds)=>`${name} · ${seconds}s reference · applies to the next reply`],
    [/^(.+) · 从下一次回复生效$/, name=>`${name} · applies to the next reply`],
    [/^当前角色：(\d+)% · (\d+)\/(\d+) · (.+)$/, (percent,step,total,label)=>`Current avatar: ${percent}% · ${step}/${total} · ${translateLabel(label)}`],
    [/^已暂停 · (.+)$/, label=>`Paused · ${translateLabel(label)}`],
    [/^(.+) · ([\d.]+) 秒$/, (label,seconds)=>`${translateLabel(label)} · ${seconds}s`],
    [/^简洁模式：只填写下方动作；其余 (\d+) 项使用已通过生产验收的默认值。$/, n=>`Guided mode: describe the action below. The other ${n} fields use verified defaults.`],
  ];
  for (const [pattern, render] of patterns) {const match=value.match(pattern);if(match)return source.replace(value,render(...match.slice(1)));}
  const segments = value.split(/\s+·\s+/);
  if (segments.length > 1) return source.replace(value, segments.map(translateLabel).join(" · "));
  const bilingual = value.match(/^[\s\S]*[\u4e00-\u9fff][\s\S]*?\s*\/\s*([A-Za-z][^\u4e00-\u9fff]*)$/);
  if (bilingual) return source.replace(value, bilingual[1]!);
  const sentences=value.split(/(?<=[。！？])\s*/).filter(Boolean);
  if(sentences.length>1)return source.replace(value,sentences.map(translateLabel).join(" "));
  return source;
}

export function enhanceStudio(root: HTMLElement) {
  const sources = new WeakMap<Node, {source:string; rendered:string}>();
  const attrs = new WeakMap<Element, Map<string,{source:string;rendered:string}>>();
  function text(node: Text) {
    if (node.parentElement?.closest(excluded)) return;
    const current = node.data;
    const previous = sources.get(node);
    const source = previous?.rendered === current ? previous.source : current;
    const rendered = translateLabel(source);
    sources.set(node, {source, rendered});
    if (current !== rendered) node.data = rendered;
  }
  function element(node: Element) {
    if (node.closest(excluded) && !(node.matches("textarea") && !node.parentElement?.closest(excluded))) return;
    if (node.matches("button:not(.button):not(.icon-button):not(.conversation):not(.session-item):not(.nav-item):not(.brand):not(.send-button):not(.quiet)")) {
      node.classList.add("button", node.classList.contains("primary") ? "button--primary" : "button--secondary");
    }
    if(node.matches(".file-action>span,.schema-file-picker>span"))node.classList.add("button","button--secondary");
    const saved = attrs.get(node) ?? new Map(); attrs.set(node, saved);
    for (const key of ["aria-label", "title", "placeholder"]) {
      const current = node.getAttribute(key); if (current === null) continue;
      const previous = saved.get(key); const source = previous?.rendered === current ? previous.source : current;
      const rendered = translateLabel(source); saved.set(key, {source,rendered});
      if (current !== rendered) node.setAttribute(key, rendered);
    }
  }
  function walk(node: Node) {
    if (node instanceof Text) {text(node); return;}
    if (!(node instanceof Element)) return;
    element(node);
    if (node.closest(excluded)) return;
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    while (walker.nextNode()) {
      const child = walker.currentNode;
      if (child instanceof Text) text(child); else if (child instanceof Element) element(child);
    }
  }
  walk(root);
  const observer = new MutationObserver(records => {
    observer.disconnect();
    for (const record of records) {
      if (record.type === "characterData") walk(record.target);
      else if (record.type === "attributes") element(record.target as Element);
      else for (const node of record.addedNodes) walk(node);
    }
    observe();
  });
  const observe = () => observer.observe(root, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:["title","aria-label","placeholder"]});
  observe();
  subscribe(() => {observer.disconnect();walk(root);observe();});
}
