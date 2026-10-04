/** Capture an actual replay, including its audio clock, without another inference. */
export async function captureVideo(canvas: HTMLCanvasElement, context: AudioContext, output: AudioNode,
  playback: () => Promise<void>, overlay: () => { caption: string; label: string }): Promise<Blob> {
  if (typeof MediaRecorder === "undefined") throw new Error("当前浏览器不支持视频录制");
  const mimeType = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"]
    .find(type => MediaRecorder.isTypeSupported(type));
  if (!mimeType) throw new Error("当前浏览器不支持 WebM 视频导出");
  const frame = document.createElement("canvas");
  frame.width = canvas.width; frame.height = canvas.height;
  const paint = frame.getContext("2d")!;
  const video = frame.captureStream(30), audio = context.createMediaStreamDestination();
  const stream = new MediaStream([...video.getVideoTracks(), ...audio.stream.getAudioTracks()]);
  let raf = 0;
  const chunks: Blob[] = [];
  const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 4_000_000 });
  const stopped = new Promise<{ blob: Blob; error?: Error }>(resolve => {
    let error: Error | undefined;
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.onerror = () => { error = new Error("视频编码失败，请重新录制"); };
    recorder.onstop = () => resolve({ blob: new Blob(chunks, { type: mimeType }), error });
  });
  const draw = () => {
    const { width, height } = frame, font = Math.max(18, Math.round(width / 55));
    paint.drawImage(canvas, 0, 0, width, height);
    const { caption, label } = overlay();
    paint.font = `500 ${font}px system-ui, sans-serif`;
    paint.fillStyle = "#202938"; paint.fillText(`VIREA  /  ${label}`, font, font * 2);
    if (caption) {
      const lines: string[] = []; let line = "";
      for (const char of caption) {
        if (paint.measureText(line + char).width > width * .82) { lines.push(line); line = ""; }
        line += char;
      }
      if (line) lines.push(line);
      const lineHeight = font * 1.5, y = height - font * 2 - lines.length * lineHeight;
      paint.fillStyle = "rgba(22,29,41,.86)"; paint.fillRect(width * .06, y, width * .88, (lines.length + 1) * lineHeight);
      paint.fillStyle = "white"; paint.textAlign = "center";
      lines.forEach((text, i) => paint.fillText(text, width / 2, y + (i + 1) * lineHeight));
      paint.textAlign = "left";
    }
    raf = requestAnimationFrame(draw);
  };
  try {
    output.connect(audio); draw(); recorder.start(1000);
    await playback();
  } finally {
    cancelAnimationFrame(raf);
    if (recorder.state !== "inactive") recorder.stop();
    output.disconnect(audio);
    stream.getTracks().forEach(track => track.stop());
  }
  const result = await stopped;
  if (result.error) throw result.error;
  if (!result.blob.size) throw new Error("视频为空，请保持页面可见后重试");
  return result.blob;
}

export async function downloadVideo(blob: Blob, sessionId?: string): Promise<void> {
  let url: string;
  if (sessionId) {
    const response = await fetch(`/api/v1/characters/${sessionId}/recording`, {
      method: "PUT", headers: { "Content-Type": "video/webm" }, body: blob,
    });
    if (!response.ok) throw new Error(`视频保存失败 (${response.status})`);
    url = (await response.json()).url;
  } else url = URL.createObjectURL(blob);
  const dialog = document.createElement("dialog");
  const title = document.createElement("h2"), link = document.createElement("a"), close = document.createElement("button");
  dialog.setAttribute("aria-label", "导出视频"); title.textContent = "视频已录制";
  link.href = url; link.download = "virea-performance.webm";
  link.textContent = `保存视频（${(blob.size / 1024 / 1024).toFixed(1)} MB）`;
  close.textContent = "关闭"; close.onclick = () => dialog.close();
  const actions = document.createElement("div"); actions.className = "export-actions"; actions.append(link, close);
  dialog.append(title, actions);
  dialog.onclose = () => { dialog.remove(); URL.revokeObjectURL(url); };
  document.body.append(dialog); dialog.showModal();
}
