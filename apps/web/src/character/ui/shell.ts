const icons: Record<string, string> = {
  panel: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  settings: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
  focus: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/><circle cx="12" cy="12" r="3"/>',
  grid: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/>',
  body: '<circle cx="12" cy="5" r="2"/><path d="m5 10 7 2 7-2m-7 2v5m0 0-4 5m4-5 4 5M12 8v4"/>',
  arrow: '<path d="M12 19V5m-6 6 6-6 6 6"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
};
export const icon = (name: string) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] ?? icons.plus}</svg>`;

export const studioShell = `
  <nav class="rail" aria-label="工作室导航">
    <a class="brand" href="./" aria-label="VIREA 首页">v<span>.</span></a>
    <button id="history-toggle" class="icon-button" aria-label="打开历史记录" aria-expanded="false" title="历史记录">${icon("panel")}</button>
    <button id="trace-toggle" class="icon-button" aria-label="打开执行链" aria-expanded="false" title="执行链与诊断">${icon("body")}</button>
    <button id="new-session" class="icon-button" aria-label="新建会话" title="新建会话">${icon("plus")}</button>
    <button id="settings-toggle" class="icon-button rail-bottom" aria-label="角色与设置" title="角色与设置">${icon("settings")}</button>
  </nav>
  <main class="workspace">
    <header class="topbar"><div><strong>Motion Studio</strong><span class="topbar-divider">/</span><span id="workspace-title">未命名会话</span></div>
      <div class="topbar-actions"><span id="status" role="status">未连接</span><button id="close" class="quiet" disabled>结束会话</button></div>
    </header>
    <section class="stage" aria-label="动作工作室">
      <canvas aria-label="持续角色三维场景"></canvas>
      <div class="stage-heading"><span class="eyebrow">3D WORKSPACE</span><h1>让想法，动起来。</h1><p id="avatar-name">载入角色，开始创作</p></div>
      <div class="viewport-tools" role="group" aria-label="视图工具">
        <button id="reset-camera" class="icon-button" aria-label="重置视角" title="重置视角">${icon("focus")}</button>
        <button id="toggle-grid" class="icon-button" aria-label="显示网格" aria-pressed="true" title="网格">${icon("grid")}</button>
        <button id="toggle-skeleton" class="icon-button" aria-label="显示原生骨架" aria-pressed="false" title="原生骨架对照">${icon("body")}</button>
      </div>
      <div id="subtitle" aria-live="polite"></div>
      <div class="stage-note"><span class="live-dot"></span> LIVE VIEW <span>拖动旋转 · 滚轮缩放</span></div>
      <aside class="chat-dock" aria-label="角色聊天">
        <div class="dock-header"><span class="dock-title">创作对话</span><button id="chat-collapse" class="quiet" aria-label="收起聊天" aria-expanded="true">收起</button></div>
        <div class="chat-content">
          <section class="latest-reply" aria-label="角色回复"><div class="text-heading"><strong id="reply-owner">VIREA</strong><span id="text-state">准备就绪</span></div><p id="response-text">描述一个动作，或和角色聊聊。</p></section>
          <section id="route-card" class="route-card" hidden><span id="route-model"></span><span id="route-reason"></span></section>
          <ol id="motion-plan" class="motion-plan" aria-label="动作序列"></ol>
          <section class="expression-panel" aria-label="语音、动作与文本">
            <p id="current-driver" class="current-driver" role="status">等待行为</p>
            <div class="track timeline"><strong id="active-phase">播放时间轴</strong><span id="timeline-state">等待生成</span><button id="pause" disabled>暂停</button><progress id="timeline-progress" max="1" value="0" aria-label="统一播放进度"></progress></div>
            <details class="playback-tools"><summary>播放与导出</summary><div class="settings-content">
              <div class="track"><strong>语音</strong><span id="audio-state">等待语音</span><progress id="audio-progress" max="1" value="0" aria-label="语音进度"></progress></div>
              <div class="track"><strong>动作</strong><span id="motion-state">自然站姿</span><progress id="motion-progress" max="1" value="0" aria-label="动作进度"></progress></div>
              <label class="volume">音量<input id="volume" type="range" min="0" max="1" step="0.05" value="1"></label>
              <div class="buttons"><button id="replay-audio" disabled>重播语音</button><button id="replay-motion" disabled>重播动作</button><button id="replay-sync" disabled>同步重播</button><button id="export-motion" disabled>导出动作</button><button id="export-video" disabled>导出视频</button></div>
              <p id="playback-note" class="hint">语音、动作与字幕共用时间轴。</p>
            </div></details>
          </section>
        </div>
        <form id="composer"><label class="sr-only" for="message">和角色聊天</label><textarea id="message" rows="2" maxlength="4000" placeholder="和角色聊聊…" required></textarea>
          <div class="composer-actions"><span class="engine-picker" title="先理解对话，再决定如何回应与行动">对话驱动</span>
            <div class="send-actions"><button type="button" id="interrupt" class="quiet" disabled>停止</button><button type="submit" id="send" class="send-button" aria-label="发送" disabled>${icon("arrow")}</button></div></div>
        </form>
        <div id="error" role="alert"></div>
      </aside>
    </section>
  </main>
  <section id="history-drawer" class="history-drawer" aria-label="会话历史" hidden>
    <div class="drawer-heading"><h2>历史记录</h2><button id="history-close" class="icon-button" aria-label="关闭历史记录">${icon("close")}</button></div>
    <input id="history-search" type="search" placeholder="搜索对话或动作" aria-label="搜索历史记录">
    <div id="session-list" class="session-list"></div>
    <div class="history-heading"><strong id="history-title">当前会话</strong><button id="export-history" class="quiet">导出</button></div>
    <div id="conversation" role="log" aria-label="对话与执行记录"></div>
  </section>
  <section id="trace-drawer" class="trace-drawer" aria-label="执行链与诊断" hidden>
    <div class="drawer-heading"><div><span class="eyebrow">EXECUTION TRACE</span><h2>执行链与诊断</h2></div><button id="trace-close" class="icon-button" aria-label="关闭执行链">${icon("close")}</button></div>
    <p class="hint">对话理解 → 行为承诺 → 模型生成 → 实际播放 → 收势。展开条目可检查提示词、来源 ID、时间和失败原因。</p>
    <output id="trace-live" class="trace-live">尚无执行记录</output>
    <button id="trace-export" class="quiet">导出诊断 JSON</button><p id="trace-range" class="hint"></p>
    <div class="trace-scroll">
      <details open><summary>采纳的交互计划 · 顺序与并行</summary><div id="trace-plan"></div></details>
      <details open><summary>实际播放 · 音频时钟</summary><div id="trace-playback"></div></details>
      <details open><summary>身体时段 · 预订与执行</summary><div id="trace-slots"></div></details>
      <details open><summary>执行事件链 · 会话相对时间</summary><div id="trace-events"></div></details>
    </div>
  </section>
  <dialog id="settings-dialog" aria-labelledby="settings-title">
    <div class="dialog-heading"><div><span class="eyebrow">WORKSPACE SETTINGS</span><h2 id="settings-title">角色与设置</h2></div><button id="settings-close" class="icon-button" aria-label="关闭设置">${icon("close")}</button></div>
    <section id="session-tools" class="settings">
      <label class="file"><span class="file-icon">${icon("body")}</span><strong>选择 VRM 角色</strong><span>在本地载入，保留你的角色形象</span><input id="avatar" type="file" accept=".vrm,.glb"></label>
      <label class="mode">播放方式<select id="playback-mode"><option value="synchronized">按计划编排 · 语音与动作独立执行</option></select></label>
      <label class="mode">声线<select id="voice" disabled aria-label="声线"></select></label>
      <div class="voice-preview"><input id="voice-sample" aria-label="试听文本" maxlength="120" value="你好，很高兴见到你。今天有什么想和我聊的吗？"><button id="voice-preview">试听</button></div>
      <audio id="voice-player" controls hidden aria-label="声线试听"></audio>
      <label class="persona-label">角色设定<textarea id="persona" aria-label="角色设定" maxlength="4000"></textarea><small>声线与设定从下一次回复开始生效。</small></label>
      <div class="buttons"><button id="start" class="primary" disabled>开始会话</button><button id="sound">继续声音</button></div>
    </section>
    <details class="diagnostics"><summary>运行状态</summary><output id="metrics">尚无测量</output></details>
    <p id="settings-error" role="alert"></p>
  </dialog>`;
