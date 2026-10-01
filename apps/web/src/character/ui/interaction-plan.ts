/** Readable, model-authored commitments beside the independent execution trace. */
type RecordValue = Record<string, unknown>;
const record = (value: unknown): RecordValue => value && typeof value === "object" && !Array.isArray(value)
  ? value as RecordValue : {};
const node = (tag: string, value: unknown) => {
  const element = document.createElement(tag);
  element.textContent = typeof value === "string" ? value : "";
  return element;
};

export function interactionPlan(appraisal: unknown): HTMLElement {
  const root = document.createElement("div");
  const data = record(record(appraisal).interaction_program), score = record(data.score);
  if (!score.program) { root.append(node("p", "尚未采纳新的交互计划。")); return root; }
  root.append(node("p", score.understanding));
  const operations: Record<string, string> = { keep: "延续已有身体状态与进度", replace: "采纳新的身体活动", stop: "结束当前身体任务" };
  root.append(node("p", operations[String(score.body_operation)]));
  const sources = Array.isArray(data.sources) ? data.sources.map(record) : [];
  const render = (value: unknown, path: string, depth = 0): HTMLElement => {
    const task = record(value), row = document.createElement("details");
    row.open = true;
    const source = sources.find(item => item.path === path);
    const labels: Record<string, string> = { sequence: "依次完成", parallel: "并行进行", say: "发言", act: "身体活动" };
    const label = labels[String(task.kind)] ?? "任务";
    const reference = source?.channel === "speech" ? ` · 语音单元 ${Number(source.first) + 1}–${Number(source.last) + 1}`
      : source?.channel === "body" ? ` · 身体目标 ${Number(source.objective) + 1}` : "";
    row.append(node("summary", `${label}${reference}`));
    if (depth > 8) return row;
    if (task.kind === "say") {
      row.append(node("p", task.text), node("p", `伴随表达：${task.motion_intent ?? ""}`));
    } else if (task.kind === "act") {
      const action = record(task.action);
      row.append(node("p", `${task.executor} · ${action.duration_seconds ? `${action.duration_seconds}s` : "持续至完成判断"} · ${task.goal}`),
        node("p", `完成条件：${task.completion}`), node("pre", action.description));
    } else if (Array.isArray(task.children)) {
      task.children.forEach((child, i) => row.append(render(child, `${path}.children[${i}]`, depth + 1)));
    }
    return row;
  };
  root.append(render(score.program, "program"));
  const recovery = record(score.recovery);
  if (recovery.goal) root.append(node("p", `整项活动最后的恢复 · ${recovery.executor}\n${recovery.goal}`));
  root.append(node("p", "粗粒度活动决定模型与输入；执行层结合音频与运动进展判断延续或切换。实际完成以播放回执为准。"));
  return root;
}
