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
            <div class="track timeline"><strong id="active-phase">播放时间轴</strong><span id="timeline-state">等待生成</span><button id="pause" disabled>暂停</button><progress id="timeline-progress" max="1" value="0" aria-label="统一播放进度"></progress></div>
            <details class="playback-tools"><summary>播放与导出</summary><div class="settings-content">
              <div class="track"><strong>语音</strong><span id="audio-state">等待语音</span><progress id="audio-progress" max="1" value="0" aria-label="语音进度"></progress></div>
              <div class="track"><strong>动作</strong><span id="motion-state">自然站姿</span><progress id="motion-progress" max="1" value="0" aria-label="动作进度"></progress></div>
              <label class="volume">音量<input id="volume" type="range" min="0" max="1" step="0.05" value="1"></label>
              <div class="buttons"><button id="replay-audio" disabled>重播语音</button><button id="replay-motion" disabled>重播动作</button><button id="replay-sync" disabled>同步重播</button><button id="export-motion" disabled>导出动作</button></div>
              <p id="playback-note" class="hint">语音、动作与字幕共用时间轴。</p>
            </div></details>
          </section>
        </div>
        <form id="composer"><label class="sr-only" for="message">描述动作或对话</label><textarea id="message" rows="2" maxlength="4000" placeholder="描述动作，或开始对话…" required></textarea>
          <div class="composer-actions"><label class="engine-picker"><span class="sr-only">生成模式</span><select id="engine"><option value="auto">自动选择</option><option value="sentiavatar">对话 · SentiAvatar</option><option value="ardy">动作 · ARDY</option></select></label>
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
  <dialog id="settings-dialog" aria-labelledby="settings-title">
    <div class="dialog-heading"><div><span class="eyebrow">WORKSPACE SETTINGS</span><h2 id="settings-title">角色与设置</h2></div><button id="settings-close" class="icon-button" aria-label="关闭设置">${icon("close")}</button></div>
    <section id="session-tools" class="settings">
      <label class="file"><span class="file-icon">${icon("body")}</span><strong>选择 VRM 角色</strong><span>在本地载入，保留你的角色形象</span><input id="avatar" type="file" accept=".vrm,.glb"></label>
      <label class="mode">播放方式<select id="playback-mode"><option value="synchronized">严格同步 · 统一时间轴</option></select></label>
      <div class="buttons"><button id="start" class="primary" disabled>开始会话</button><button id="sound">继续声音</button></div>
    </section>
    <details class="diagnostics"><summary>运行状态</summary><output id="metrics">尚无测量</output></details>
    <p id="settings-error" role="alert"></p>
  </dialog>`;
