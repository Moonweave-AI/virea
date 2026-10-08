/** Connection stages are distinct: an HTTP session alone is not a live avatar. */
export function connectionView(state, offline = false) {
  const query = state.feedback?.query;
  const avatar = state.feedback?.values?.avatar_id;
  const live = query?.state === "verified" && query.last_checked_seconds_ago < 3;
  const offlineTesting = query?.online?.connection === "offline_testing";
  const sameRoom = !offline && live && !offlineTesting && query?.online?.same_instance === "matched_in_live_client_logs";
  let title, detail;
  if (offline) {
    title = "控制服务暂时不可用"; detail = "正在自动重试。已保留对话和连接设置。";
  } else if (!state.connected) {
    title = "连接独立 AI 角色"; detail = "连接后自动识别 AI 客户端与已安装的角色参数。";
  } else if (offlineTesting) {
    title = "VRChat 处于离线测试模式";
    detail = "本机 OSC 可用不代表能够联网。请通过修复后的启动脚本或官方 launch.exe 重启此客户端，再核验同房间效果。";
  } else if (state.ready) {
    title = "本机角色控制已连接";
    detail = query?.local_avatar ? "SDK 本地测试角色 · 仅当前客户端可见，跨账号观察需要发布角色。" : "角色输出已就绪，可以开始对话。";
  } else if (avatar && state.config?.avatar_id && avatar !== state.config.avatar_id) {
    title = "角色已切换，输出已暂停"; detail = "当前角色与绑定不一致。停止任务后，在设置里绑定当前角色。";
  } else if (live && query.missing_parameters?.length) {
    title = "已找到角色，缺少控制参数"; detail = "请换上经过 VIREA Unity 工具准备的角色，或在设置中核对后手动绑定。";
  } else if (live && avatar) {
    title = "已识别 AI 角色"; detail = "请在设置里绑定此角色，或启用自动绑定后重新连接。";
  } else {
    title = "正在寻找 AI 客户端"; detail = "自动检测专用端口。请保持 AI 窗口运行，并在该窗口开启 OSC。";
  }
  if (!offline && query?.online?.authentication === "api_auth_error_in_log") {
    detail += " 日志记录了在线接口认证错误（401），不能据此认定账号掉线。同房间连接仍待实测。";
  }
  if (sameRoom) detail += " 两个运行中客户端的同房间记录已匹配；角色外观、动作和声音仍需从观察者视角验收。";
  return {
    title, detail, avatar: avatar?.replace(/^local:sdk_/, "") ?? "尚未识别角色",
    ready: !offline && !!state.ready,
    steps: [
      ["控制服务", !offline], ["本机 OSC", !offline && live],
      ["角色绑定", !offline && !!state.ready],
      [sameRoom ? "同房间记录已匹配" : offlineTesting ? "离线测试模式" : query?.online?.authentication === "api_auth_error_in_log" ? "接口有错误记录" : "同房间未核验", sameRoom],
      [state.config?.audio_enabled ? "语音已配置" : "语音关闭", !offline && !!state.config?.audio_enabled],
    ],
  };
}

export function readConnectionSettings(raw) {
  try {
    const parsed = JSON.parse(raw ?? "null");
    return parsed?.version === 1 && parsed.fields && typeof parsed.fields === "object" ? parsed : null;
  } catch { return null; }
}
