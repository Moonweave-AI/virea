"""Wire descriptions for model outputs; personality lives in session preferences."""

DECISION_RULES = """当前任务是把本轮回应计划表达成一轮完整的口头回复。
角色设定描述说话者，历史记录描述已经发生的对话，Current state 提供当前可用能力。
reply_plan 的 goal 和 outline 是本轮内容计划；beats 是连续回应的语义段落，长度随内容变化。
每个 beat 的 text 是将被朗读的正文，motion_intent 是同期身体手势的中文运动描述。
SPEAK 表示发言，WAIT 表示用户此时希望保持安静；actions 是实际可执行的场景操作。
JSON 按 schema 序列化，控制字段在 beats 之前，以便正文完成前开始流式播放。
"""
